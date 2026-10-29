Synced with commit: 17d5a03

# CW Архитектура

Преглед архитектуре Contextual-Walker система. За детаљну дискусију о свим одлукама види [DEV/ARCHITECTURE-DISCUSSION.md](DEV/ARCHITECTURE-DISCUSSION.md).

## Компоненте

```
┌───────────────────────────────────────┐
│                USER                   │
│  cw create / join / open / close ...  │
└──────────────────┬────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
   CLI (cw)              iTerm2
   click-based           terminal
        │                     │
        │ Unix socket         │ Python API
        │                     │
        └──────────┬──────────┘
                   │
        ┌──────────┴──────────┐
        │    CW DAEMON        │
        │                     │
        │ Layout callback     │
        │ FocusMonitor        │
        │ SessionTermination  │
        │ NewSessionMonitor   │
        │ Checkpoint (5с)     │
        └──────────┬──────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
   SQLite DB    History    Config
   cw.sqlite    *.history  config.json
                  .txt
```

## Три главне компоненте

### 1. CW Daemon (`src/cw/daemon.py`)

Дуготрајни Python процес који ради као iTerm2 AutoLaunch скрипта. Покреће се аутоматски са iTerm-ом.

Одговорности:
- Прати промјене layout-а (callback subscription — `async_subscribe_to_layout_change_notification`)
- Прати промјене фокуса (`FocusMonitor` — синхронизује стање при сваком пребацивању)
- Прати нове сесије (`NewSessionMonitor` — одмах додјељује UUID и HISTFILE)
- Прати затварање сесија (`SessionTerminationMonitor`)
- Периодични checkpoint (сваких 5с — safety net, прескаче ако је монитор већ синковао)
- Reconciliation при покретању (усаглашавање DB ↔ iTerm)
- HISTFILE setup за СВЕ сесије при покретању (tracked и untracked)
- Unix socket сервер за CLI команде
- Прати задњи фокусирани прозор по контексту (за `cw go`)
- Hot-reload модула (`cw reload`) са `database.__class__` ажурирањем + DB миграције при reload-у

**Безбједност:** Сваки event handler је у `try/except`. Ако daemon падне, iTerm наставља нормално.

### 2. CLI (`src/cw/cli.py`)

Click-based CLI који комуницира са daemon-ом преко Unix socket-а. За read-only операције (history) чита директно из SQLite.

Команде: `list`, `create`, `join`, `leave`, `move`, `rename`, `open`, `close`, `save`, `history`, `history-pane`, `windows`, `go`, `current`, `refresh`, `reload`, `status`, `backup`, `config`, `completion`

### 3. SQLite база (`src/cw/db.py`)

Canonical source of truth за контексте, прозоре, табове, панеле. WAL mode за конкурентан приступ (daemon пише, CLI чита).

## SQLite шема

6 табела:

| Табела | Сврха |
|--------|-------|
| `contexts` | Именоване групе прозора (id, name, description, is_deleted) |
| `windows` | Прозори у контексту (is_member, is_open, геометрија) |
| `tabs` | Табови у прозору (title, order, is_selected) |
| `panes` | Панели у табу (CWD, hostname, profile, font, split tree, is_active) |
| `id_mappings` | CW UUID ↔ iTerm runtime ID (двосмјерно деактивирање) |
| `state_log` | Историјски snapshot-ови (JSON) |

## ID Mapping систем

Кључна компонента — повезује стабилне CW UUID-ове са привремним iTerm ID-овима.

```
CW UUID (стабилан)          iTerm ID (привремен)
────────────────            ────────────────────
8b13e840 (pane)      ↔      953B70DC-EF63... (session)
ca44f991 (window)    ↔      pty-F79F98F8... (window)
```

**Правила:**
- За сваки `iterm_id` постоји ТАЧНО ЈЕДАН активан mapping
- `set_mapping` деактивира и по `cw_id` И по `iterm_id` (спречава дупликате)
- Pane UUID-еви су СТАБИЛНИ — исти UUID преко close/open циклуса (за историју)
- Tab UUID-еви се генеришу нови при sync-у, осим ако mapping постоји
- Конфликт resolution: UUID из затвореног прозора → cleanup; из отвореног → нови UUID

### Зашто стабилност UUID-а

Per-pane shell history фајлови носе UUID у имену (`8b13e840.history.txt`). Ако се UUID промијени при restore-у, историја се губи. Зато:

1. `cw close` — снима стање, деактивира mapping-е, history фајл остаје
2. `cw open` — ПРИЈЕ sync-а, креира mapping `СТАРИ_UUID ↔ НОВИ_SESSION_ID`
3. `sync_window_layout` — налази постојећи mapping → задржава стари UUID
4. `_set_pane_histfile` — поставља HISTFILE на стари UUID → иста историја

### NewSessionMonitor race condition

`NewSessionMonitor` одмах генерише UUID за нову сесију. Ако `_cmd_open` касније позове `set_mapping(OLD_UUID, session)`, постоје ДВА активна mapping-а за исти `iterm_id`. Ријешено тако да `set_mapping` деактивира и по `iterm_id`, не само по `cw_id`.

## Per-pane Shell History

```
~/.contextual-walker/history/
├── 8b13e840-da97-41d2-8e16-21836a2cd41f.history.txt
├── ca44f991-c176-49d7-94a1-5c5ec35a16f7.history.txt
└── ...
```

**Flow:**

1. **Daemon старт:** `_ensure_all_sessions_have_histfile` — поставља HISTFILE на СВЕ сесије (tracked и untracked)
2. **Нова сесија:** `NewSessionMonitor` → генерише UUID, mapping, `export HISTFILE=...`
3. **Свака команда:** `PROMPT_COMMAND="history -a"` флашује на диск одмах
4. **`cw close`:** history фајл остаје на диску
5. **`cw open`:** pre-create mapping → sync задржава UUID → HISTFILE показује на исти фајл
6. **`cw history-pane`:** чита фајл по UUID-у тренутне сесије

**HISTFILE команда шаље shell-у:**
```bash
export HISTFILE='/path/UUID.history.txt'; export HISTSIZE=100;
export HISTFILESIZE=100; history -c; history -r;
export PROMPT_COMMAND="history -a;$PROMPT_COMMAND"; clear
```

- `history -c` — чисти глобалну историју из меморије
- `history -r` — учитава per-pane историју
- `PROMPT_COMMAND="history -a"` — флашује након СВАКЕ команде
- `clear` — сакрива `export` команду од корисника
- Водећи размак — спречава да сама команда уђе у историју

## Кључне семантике

### Window: persistent member
Затварање прозора **не** уклања га из Context-а:
```
is_member = true    (и даље део Context-а)
is_open = false     (тренутно не постоји у iTerm-у)
```

### Tab/Pane: mutable layout
Затварање таба/панела **јесте** промјена layout-а — при restore-у се не враћају.

### CLOSE ≠ DELETE
```
CLOSE   → is_open = false
REMOVE  → is_member = false
DELETE  → is_deleted = true (soft delete)
PURGE   → физичко брисање (V2)
```

## Sync механизми (5 слојева)

| # | Механизам | Окида | Шта ради |
|---|-----------|-------|----------|
| 1 | Layout change callback | split/close pane, нови таб, resize | Читај стање, упиши у DB |
| 2 | FocusMonitor | свако пребацивање | Синк фокусираног прозора + прати задњи фокус по контексту |
| 3 | NewSessionMonitor | нова сесија | Генериши UUID, mapping, постави HISTFILE |
| 4 | SessionTerminationMonitor | затварање сесије | Деактивирај mapping |
| 5 | Checkpoint (5с) | тајмер | Синк свих tracked прозора, прескаче ако монитор већ синковао |

**Smart dedup:** Checkpoint прескаче ако је монитор синковао у задњих 4с (`_seconds_since_last_sync`).

## Reconciliation

При покретању daemon-а:
1. Прочитај све iTerm прозоре и њихове `user.cw_*` варијабле
2. Упореди са DB стањем
3. Прозори у iTerm-у а не у DB → означи (untracked)
4. Прозори у DB а не у iTerm-у → `is_open = false`
5. Прозори у оба → ажурирај layout/геометрију
6. Атомски сачувај све промјене
7. Постави HISTFILE на СВЕ сесије (tracked и untracked)

## `cw open` flow (restore)

Критичан flow — мора сачувати UUID стабилност:

```
1. Прочитај стање из DB (табови, панели, CWD-ови)
2. Креирај нови iTerm прозор
3. За сваки таб: креирај таб, постави наслов
4. За сваки панел: креирај сесију, cd у CWD, постави име, врати font
5. Pre-create mapping: СТАРИ_PANE_UUID → НОВИ_SESSION_ID
   (ПРИЈЕ sync-а! Иначе NewSessionMonitor може украсти UUID)
6. sync_window_layout — налази mapping → задржава стари UUID
7. Постави HISTFILE на сваку сесију (стари UUID)
8. Постави window title: "Context / Window"
```

## `cw reload` механизам

`importlib.reload` ажурира модуле, али:
- `database.__class__` мора бити ручно ажуриран (инстанца задржава стару класу)
- `_run_migrations()` се позива при reload-у (нове колоне одмах доступне)
- `_dispatch_command` се тражи динамички: `getattr(_self_module, '_dispatch_command')`
- Покренуте coroutine-е (монитори, checkpoint) НЕ могу бити ажуриране — захтијевају рестарт iTerm-а
- Module-level state (`_last_focused_context`, `_last_sync_time`) се ресетује при reload-у

## Фајлови на диску

```
~/.contextual-walker/
├── cw.sqlite                  # SQLite база (WAL mode)
├── cw.sock                    # Unix socket (daemon ↔ CLI)
├── config.json                # Конфигурација (backup dir, history max)
├── daemon.log                 # Логови daemon-а (RotatingFileHandler, макс 50MB, 2 бекапа)
├── daemon.log.1               # Ротирани лог
├── daemon.log.2               # Ротирани лог
├── history/                   # Per-pane shell history фајлови
│   ├── 8b13e840-..-.history.txt
│   └── ...
└── backups/                   # Бекапови (ZIP архиве, ~3x мањи)
    └── 2026-10-08_09-00-15.zip  # садржи: cw.sqlite, config.json, history/
```

## Пројектна структура

```
contextual-walker/
├── pyproject.toml           # Пројектна конфигурација, `cw` entry point
├── setup.cfg                # Setuptools компатибилност
├── src/cw/
│   ├── __init__.py          # Верзија
│   ├── constants.py         # Путање, интервали, варијабле
│   ├── models.py            # Dataclass-ови: Context, Window, Tab, Pane
│   ├── db.py                # SQLite шема + CRUD + трансакције + mapping
│   ├── daemon.py            # iTerm2 event loop + socket сервер + monitors
│   ├── reconciler.py        # State diffing (DB ↔ iTerm)
│   ├── cli.py               # Click CLI + display formatting
│   └── completion.py        # Shell completion (bash/zsh/fish) + transliteration
├── scripts/
│   ├── install.sh           # Пуна инсталација (venv, DB, daemon, man, completion)
│   └── uninstall.sh         # Деинсталација (бекап прво!)
├── tests/
│   ├── mocks/
│   │   └── iterm2_fake.py   # Mock iTerm2 API за unit тестове
│   ├── e2e/
│   │   ├── iterm_control.sh # iTerm restart модул са user confirmation
│   │   ├── test_safe.sh     # Безбједни тестови (не утичу на остале прозоре)
│   │   ├── test_destructive.sh  # Тестови који стварају/затварају прозоре
│   │   └── test_restart.sh  # Тестови који рестартују iTerm
│   ├── test_db.py           # DB CRUD + UUID stability тестови
│   ├── test_models.py       # Dataclass логика
│   ├── test_cli_helpers.py  # CLI помоћне функције + display тестови
│   ├── test_completion.py   # Shell completion генерисање
│   ├── test_config.py       # Конфигурација
│   ├── test_db_migration.py # DB миграције
│   └── test_daemon_commands.py  # Daemon команде (mock iTerm2)
├── man/                     # Генерисане man странице
└── DEV/
    ├── BUGS.md              # Познати багови и фиксеви
    └── ARCHITECTURE-DISCUSSION.md  # Детаљна архитектонска дискусија
```

## iTerm2 интеграција

### User variables
На сваку сесију daemon поставља:
- `user.cw_context_id` / `user.cw_context_name`
- `user.cw_window_id` / `user.cw_window_name`

Служе за: reconciliation (поновна идентификација прозора) и приказ у iTerm badge-у.

### Window/Tab titles
- Window title: `Context / Window` (постављен при join, open, refresh)
- Tab title: читан fallback chain `titleOverride → title → session autoName`

### AutoLaunch
Daemon wrapper се инсталира у:
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/cw_daemon.py`

### Monitors
- **Layout change callback** (`async_subscribe_to_layout_change_notification`) — промјене у структури. `LayoutChangeMonitor` класа НЕ ради у AutoLaunch контексту (BUG-001).
- **`FocusMonitor`** — промјене фокуса (таб, пане, прозор). Синхронизује стање при сваком пребацивању.
- **`SessionTerminationMonitor`** — затварање сесије
- **`NewSessionMonitor`** — нова сесија: одмах UUID + HISTFILE за SVE сесије
- **Checkpoint (5с)** — safety net, прескаче ако је монитор синковао

## UUID Lifecycle — детаљан ток кроз отварање и затварање

### Два свијета UUID-ова

| | CW UUID | iTerm ID |
|---|---|---|
| **Природа** | Стабилан — генерише се једном, преживљава рестарте | Привремен — мијења се при сваком рестарту iTerm-а |
| **Гдје живи** | `id_mappings.cw_id`, `panes.id`, `tabs.id` | `id_mappings.iterm_id` |
| **Примјер** | `8b13e840-da97-41d2-8e16-21836a2cd41f` | `953B70DC-EF63-4DE7-9E6C-06D114699B84` |
| **За шта служи** | History фајл (`UUID.history.txt`), DB идентитет | API позиви (`app.get_session_by_id()`) |

### Сценарио: Прво отварање (cw join)

```
Корисник: cw create MyProject && cw join MyProject

1. CLI → daemon socket → _cmd_join
2. daemon чита app.current_terminal_window → iTerm window "win-ABC"
3. daemon чита read_iterm_window_state:
   - tab "tab-11" са session "sess-XYZ"
4. database.create_window → генерише CW window UUID: W1
5. database.set_mapping(W1, "win-ABC", "window")
6. database.sync_window_layout:
   а. За tab "tab-11":
      - Нема mapping → генерише CW tab UUID: T1
      - INSERT INTO tabs (id=T1, window_id=W1)
   б. За session "sess-XYZ":
      - NewSessionMonitor ВЕЋ направио mapping N1 ↔ "sess-XYZ"
      - sync тражи: SELECT cw_id WHERE iterm_id="sess-XYZ" → налази N1
      - INSERT INTO panes (id=N1, tab_id=T1)
7. _set_pane_histfile(session, N1):
   - shell добија: export HISTFILE=~/.../history/N1.history.txt
   - PROMPT_COMMAND="history -a" (flush после сваке команде)

Стање:
  DB: pane N1 → tab T1 → window W1 → context MyProject
  Mapping: N1 ↔ sess-XYZ (активан)
  Фајл: ~/.contextual-walker/history/N1.history.txt (shell пише)
```

### Сценарио: Checkpoint (сваких 5с)

Daemon периодично освјежава стање свих tracked прозора. Циљ: DB увијек одражава тренутно стање iTerm-а.

```
1. Daemon чита живо стање из iTerm-а (табови, панели, CWD, наслови)
2. Брише старе табове/панеле за овај прозор из DB
3. За сваки таб:
   - Тражи: "да ли овај iTerm таб ИМА постојећи CW UUID?" (из mapping-а)
   - Ако да → задржава стари UUID
   - Ако не → генерише нови
4. За сваки панел (сесију):
   - Исто: тражи постојећи UUID из mapping-а
   - Ако да → задржава стари UUID (КРИТИЧНО — history фајл остаје исти!)
   - Ако не → генерише нови
5. Уписује свјеже податке (CWD, наслов, геометрију) у DB

Резултат: UUID-ови НЕПРОМИЈЕЊЕНИ. History фајл исти.
Ажурирани су само подаци (CWD, наслов, итд).
```

### Сценарио: Затварање (cw close MyProject)

```
1. CLI → daemon → _cmd_close
2. daemon чита ЖИВО стање из iTerm (save-before-close)
3. sync_window_layout(W1, live_state) — задњи пут ажурира DB
4. database.save_snapshot(context, "before_close") — JSON snapshot
5. iTerm прозор затворен: await iterm_window.async_close(force=True)
6. database.update_window_state(W1, is_open=False)
7. database.deactivate_mappings_for_cw_id(W1)
   - Mapping W1 ↔ "win-ABC" → is_active=0
   - (pane mapping-и ОСТАЈУ активни! — нема разлога да их деактивирамо)

Стање:
  DB: pane N1 → tab T1 → window W1 (is_open=False, is_member=True)
  Mapping W1 ↔ win-ABC: ДЕАКТИВИРАН
  Mapping N1 ↔ sess-XYZ: ДЕАКТИВИРАН (сесија не постоји)
  Фајл: N1.history.txt ОСТАЈЕ на диску (нетакнут)
```

### Сценарио: Отварање (cw open MyProject)

```
1. CLI → daemon → _cmd_open
2. daemon чита стање из DB: window W1 са tab T1, pane N1
3. Провјера: iterm_id за W1 → None (деактивиран) → прозор НИЈЕ у iTerm-у
4. _restore_window:
   а. Креирај нови iTerm прозор → "win-NEW"
   б. Креирај сесију → "sess-NEW" (НОВИ iTerm session ID!)
   в. cd /path/to/cwd
   г. Постави session name
5. ⚡ КРИТИЧАН КОРАК: Pre-create mapping ПРИЈЕ sync-а:
   database.set_mapping(N1, "sess-NEW", "session")
   - Деактивира све активне mapping-е за cw_id=N1 (ако их има)
   - Деактивира све активне mapping-е за iterm_id="sess-NEW"
     (укључујући mapping од NewSessionMonitor-а!)
   - INSERT (N1, "sess-NEW") → активан
6. sync_window_layout(W1, new_state):
   - За session "sess-NEW":
     SELECT cw_id WHERE iterm_id="sess-NEW" → N1 ← СТАРИ UUID!
     INSERT INTO panes (id=N1) ← ИСТИ UUID
7. _set_pane_histfile(session, N1):
   - HISTFILE=N1.history.txt ← ИСТИ ФАЈЛ!
   - Shell учитава старе команде ← ↑ стрелица ради!

Стање:
  DB: pane N1 → tab T2 (нов) → window W1 (is_open=True)
  Mapping: N1 ↔ sess-NEW (активан)
  Фајл: N1.history.txt — ИСТИ фајл, старе команде + нове
```

### Сценарио: iTerm рестарт

```
1. Све iTerm сесије добијају НОВЕ ID-ове
2. daemon покреће reconciliation:
   - Тражи прозоре по user.cw_* варијаблама
   - Ремапира: W1 ↔ "win-RESTART"
3. _ensure_all_sessions_have_histfile:
   - За "sess-RESTART": нема mapping → НОВИ UUID R1
   - HISTFILE=R1.history.txt (НОВИ фајл)

Резултат: Историја из N1.history.txt је ORPHANED.
Стари фајл постоји на диску, али нова сесија га не користи.
Ово је прихватљиво за V1 — рестарт = нова shell сесија = нова историја.
```

## Тестирање

| Категорија | Број | Покреће се |
|-----------|------|-----------|
| Unit (pytest) | 74 | Сваки комит, CI |
| E2E safe | 19 | Сваки комит, из било ког терминала |
| E2E destructive | 18 | Прије release-а, из iTerm или Terminal.app |
| E2E restart | 11 | Прије release-а, из Terminal.app (рестартује iTerm) |
| **Укупно** | **122** | |
