Synced with commit: 91087a5

# CW Референца команди

Све команде подржавају `-h` / `--help` за помоћ у терминалу.

## `cw list`

Приказује све Context-е са тренутним статусом. Контактира daemon да упореди стање базе са живим iTerm стањем. Ако се не поклапају, пријављује разлике.

```bash
cw list
```

Примјер излаза:
```
CONTEXT              STATUS       WINDOWS      UPDATED
────────────────────────────────────────────────────────────
EcoColabo            ● OPEN       2/3          18:14
Contextual-Walker    ● OPEN       1/1          18:12
HZZ                  ○ CLOSED     0/1          Oct 06
PlayFormers          ◐ PARTIAL    1/3          Oct 04

✓ DB and iTerm state match.
```

Иконе статуса:
- `●` OPEN — сви прозори отворени
- `◐` PARTIAL — неки отворени, неки затворени
- `○` CLOSED — ниједан прозор отворен

Ако daemon не ради, приказује само стање из базе уз упозорење.

---

## `cw create <име>`

Креира нови Context. Тренутно фокусирани iTerm прозор постаје први члан.

```bash
cw create МојПројекат
cw create МојПројекат -d "Frontend и backend развој"
```

Опције:
- `-d`, `--description TEXT` — опциони опис

---

## `cw join <име>`

Додаје прозор у постојећи Context. Подразумевано додаје тренутни (фокусирани) прозор. Са `--ref` додаје прозор по референтном броју из `cw windows --all`.

```bash
cw join МојПројекат                       # Додај тренутни прозор
cw join МојПројекат --ref 3               # Додај прозор #3 из `cw windows --all`
cw join МојПројекат -r 3 -w "Dev"         # Додај прозор #3 и именуј га "Dev"
```

Опције:
- `-w`, `--window-name TEXT` — име прозора унутар Context-а (подразумевано: аутоматски генерисано)
- `-r`, `--ref INT` — референтни број прозора из `cw windows --all`

---

## `cw open <име>[/<прозор>]`

Враћа затворене прозоре Context-а. Реконструише прозоре са сачуваним layout-ом: табови, панели, радни директоријуми и геометрија.

```bash
cw open МојПројекат                       # Врати све затворене прозоре
cw open МојПројекат/Инфраструктура        # Врати само један прозор
```

Шта се враћа:
- Позиција и величина прозора
- Структура табова
- Подјела панела
- Радни директоријуми (преко `cd`)

Шта се НЕ покреће аутоматски:
- Претходне команде (из безбједносних разлога). Враћа се задњи CWD тако да можеш ручно покренути.

---

## `cw close <име>[/<прозор>]`

Сачува тренутно стање, па затвори прозоре у iTerm-у. Слиједи принцип **save-before-close** — ако save не успије, close се прекида и ниједан прозор се не губи.

```bash
cw close МојПројекат                      # Сачувај и затвори све прозоре
cw close МојПројекат/Инфраструктура       # Затвори само један прозор
```

Затворени прозори остају чланови Context-а (`is_member=true`, `is_open=false`) и могу се вратити командом `cw open`.

---

## `cw save [<име>]`

Форсира експлицитан snapshot тренутног стања Context-а.

```bash
cw save МојПројекат    # Snapshot једног Context-а
cw save                # Snapshot свих Context-а
```

Daemon такође аутоматски чува стање на сваку промјену layout-а и периодично (сваких 30 секунди).

---

## `cw history <име>`

Приказује историју снимака стања Context-а. Чита директно из базе — daemon није потребан.

```bash
cw history МојПројекат
cw history МојПројекат -n 50      # Прикажи више уноса
```

Опције:
- `-n`, `--limit INT` — број уноса (подразумевано: 20)

Примјер излаза:
```
History for 'МојПројекат' (newest first):

  TIMESTAMP                EVENT
  ──────────────────────────────────────────────────
  18:17:31                 manual_save
  18:14:02                 before_close
  18:07:12                 layout_change
  18:00:00                 context_created
```

---

## `cw windows [<име>]`

Приказује прозоре Context-а, или прегледа све iTerm прозоре.

Ако се не наведе име, ауто-детектује Context тренутног прозора.

```bash
cw windows                                # Тренутни Context (ауто-детекција)
cw windows МојПројекат                     # Специфичан Context
cw windows МојПројекат -v                  # Са табовима
cw windows МојПројекат -vv                 # Са табовима + панелима + CWD
cw windows --all                           # СВИ iTerm прозори (tracked + untracked)
cw windows --untracked                     # Само прозори НЕ у ниједном Context-у
```

Опције:
- `-v`, `--verbose` — ниво детаља: `-v` табови, `-vv` табови+панели+CWD (кумулативно)
- `--all` — прикажи СВЕ iTerm прозоре са информацијом о Context-у
- `--untracked` — само прозори који не припадају ниједном Context-у

Примјер излаза (`--all`):
```
REF   CONTEXT            WINDOW             ITERM TITLE               TABS  PANES
────────────────────────────────────────────────────────────────────────────────────
#1    ● МојПројекат      Development        dev-server                   3      5
#2    ● МојПројекат      Инфраструктура     ssh                          1      2
#3    ○ —                —                  random-terminal              1      1
```

Референтни бројеви (#1, #2, ...) се могу користити са `cw join --ref` за додавање неуправљаних прозора у Context.

---

## `cw focus <име>`

Скочи на прозор Context-а (донеси га у фокус).

Када се наведе само име Context-а (без `/ИмеПрозора`), фокусира **задњи кориштени прозор** у том контексту — не први. Ово се аутоматски прати док се пребацујеш између прозора.

```bash
cw focus МојПројекат                       # Задњи кориштени прозор
cw focus МојПројекат/Development            # Специфичан прозор
cw focus -                                  # Врати се на претходни Context
```

Користи `cw focus -` за брзо пребацивање између два Context-а (као `cd -` у shell-у).

---

## `cw status`

Провјерава да ли CW daemon ради.

```bash
cw status
```

Излаз када ради:
```
✓ CW daemon is running.
  Database: /Users/ti/.contextual-walker/cw.sqlite
  Socket:   /Users/ti/.contextual-walker/cw.sock
```

---

## `cw backup`

Бекап CW базе у фолдер са временским печатом. Користи SQLite backup API за конзистентну копију (безбједно и док daemon пише).

```bash
cw backup                                       # Користи конфигурисани фолдер
cw backup --target ~/Documents/CW-Backups       # Експлицитна дестинација
```

Опције:
- `-t`, `--target PATH` — бекап фолдер (подразумевано: конфигурисани или `~/.contextual-walker/backups/`)

Сваки бекап прави фолдер са временским печатом:
```
~/.contextual-walker/backups/
  2026-10-07_18-14-32/
    cw.sqlite
    config.json
    daemon.log
  2026-10-08_09-00-15/
    cw.sqlite
    config.json
    daemon.log
```

Деинсталациона скрипта аутоматски позива `cw backup` прије уклањања.

---

## `cw config`

Прегледај или ажурирај CW конфигурацију.

```bash
cw config --show                                  # Прикажи конфигурацију
cw config --backup-dir ~/Documents/Backups        # Постави бекап фолдер
```

Опције:
- `--show` — прикажи тренутну конфигурацију
- `--backup-dir PATH` — постави подразумевани бекап фолдер

Конфигурација се чува у `~/.contextual-walker/config.json`.

Бекап фолдер се може задати и приликом инсталације:
```bash
bash scripts/install.sh --backup-dir ~/Documents/CW-Backups
```

---

## `cw completion <shell>`

Генерише скрипту за shell completion. Подржава динамско допуњавање имена Context-а и Window-а.

```bash
cw completion bash >> ~/.bashrc
cw completion zsh  >> ~/.zshrc
cw completion fish > ~/.config/fish/completions/cw.fish
```

Након учитавања, tab-completion ради хијерархијски:
```
cw <TAB>                           → list, create, open, close, ...
cw open <TAB>                      → МојПројекат, EcoColabo, ...
cw open МојПројекат/<TAB>          → Development, Инфраструктура, ...
```

---

## `cw --version`

Приказује инсталирану верзију.

---

## Man страница

Man странице се аутоматски генеришу током `bash scripts/install.sh` (потребан `help2man` — инсталирај са `brew install help2man`).

Након инсталације: `man cw`, `man cw-list`, `man cw-open` итд.

За ручно регенерисање:

```bash
help2man --no-info cw > man/cw.1
help2man --no-info "cw list" > man/cw-list.1
# итд.
cp man/cw*.1 ~/.local/share/man/man1/
```

---

## Деинсталација

```bash
bash scripts/uninstall.sh
```

Скрипта за деинсталацију:
1. **Прво прави бекап** (увијек, прије било каквог брисања)
2. Уклања daemon из iTerm2 AutoLaunch
3. Уклања man странице
4. Уклања shell completion из конфигурације shell-а
5. Пита да ли обрисати `~/.contextual-walker/` (бекапови се чувају чак и ако кажеш да)
6. Пита да ли уклонити `.venv` виртуелно окружење
