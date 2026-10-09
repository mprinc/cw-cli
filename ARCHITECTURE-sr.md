Synced with commit: f6054b7

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
        │ LayoutChangeMonitor │
        │ SessionTermination  │
        │ NewSessionMonitor   │
        │ Periodic checkpoint │
        └──────────┬──────────┘
                   │
        ┌──────────┴──────────┐
        │     SQLite DB       │
        │  ~/.contextual-     │
        │   walker/cw.sqlite  │
        └─────────────────────┘
```

## Три главне компоненте

### 1. CW Daemon (`src/cw/daemon.py`)

Дуготрајни Python процес који ради као iTerm2 AutoLaunch скрипта. Покреће се аутоматски са iTerm-ом.

Одговорности:
- Прати промјене layout-а (LayoutChangeMonitor)
- Прати затварање сесија (SessionTerminationMonitor)
- Прати нове сесије (NewSessionMonitor)
- Ради периодичне checkpoint-е (сваких 30 сек)
- Reconciliation при покретању (усаглашавање DB ↔ iTerm)
- Unix socket сервер за CLI команде
- Прати задњи фокусирани прозор по контексту
- Hot-reload модула (`cw reload`) без рестартовања iTerm-а

**Безбједност:** Сваки event handler је у `try/except`. Ако daemon падне, iTerm наставља нормално.

### 2. CLI (`src/cw/cli.py`)

Click-based CLI који комуницира са daemon-ом преко Unix socket-а. За read-only операције (history) чита директно из SQLite.

Команде: `list`, `create`, `join`, `leave`, `rename`, `open`, `close`, `save`, `history`, `windows`, `go`, `reload`, `status`, `backup`, `config`, `completion`

### 3. SQLite база (`src/cw/db.py`)

Canonical source of truth. WAL mode за конкурентан приступ (daemon пише, CLI чита).

## SQLite шема

6 табела:

| Табела | Сврха |
|--------|-------|
| `contexts` | Именоване групе прозора (id, name, description, is_deleted) |
| `windows` | Прозори у контексту (is_member, is_open, геометрија) |
| `tabs` | Табови у прозору (title, order, is_selected) |
| `panes` | Панели у табу (CWD, hostname, profile, split tree) |
| `id_mappings` | CW UUID ↔ iTerm runtime ID |
| `state_log` | Историјски snapshot-ови (JSON) |

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

## Reconciliation

При покретању daemon-а (или reconnect-у):
1. Прочитај све iTerm прозоре и њихове `user.cw_*` варијабле
2. Упореди са DB стањем
3. Прозори у iTerm-у а не у DB → означи (untracked)
4. Прозори у DB а не у iTerm-у → `is_open = false`
5. Прозори у оба → ажурирај layout/геометрију
6. Атомски сачувај све промјене

## Фајлови на диску

```
~/.contextual-walker/
├── cw.sqlite          # SQLite база (WAL mode)
├── cw.sock            # Unix socket (daemon ↔ CLI)
├── config.json        # Конфигурација (backup dir, итд.)
├── daemon.log         # Логови daemon-а
└── backups/           # Бекапови (timestamped подфолдери)
    └── 2026-10-08_09-00-15/
        ├── cw.sqlite
        ├── config.json
        └── daemon.log
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
│   ├── db.py                # SQLite шема + CRUD + трансакције
│   ├── daemon.py            # iTerm2 event loop + socket сервер
│   ├── reconciler.py        # State diffing (DB ↔ iTerm)
│   ├── cli.py               # Click CLI
│   └── completion.py        # Shell completion (bash/zsh/fish)
├── scripts/
│   ├── install.sh           # Пуна инсталација (venv, DB, daemon, man, completion)
│   └── uninstall.sh         # Деинсталација (бекап прво!)
├── tests/
│   └── test_db.py           # Тестови за DB слој
└── man/                     # Генерисане man странице
```

## iTerm2 интеграција

### User variables
На сваку сесију daemon поставља:
- `user.cw_context_id` / `user.cw_context_name`
- `user.cw_window_id` / `user.cw_window_name`

Служе за: reconciliation (поновна идентификација прозора) и приказ у iTerm badge-у.

### AutoLaunch
Daemon wrapper се инсталира у:
`~/Library/Application Support/iTerm2/Scripts/AutoLaunch/cw_daemon.py`

### Monitors
- `LayoutChangeMonitor` — промјене у структури (split, close, resize)
- `SessionTerminationMonitor` — затварање сесије
- `NewSessionMonitor` — нова сесија
