Synced with commit: f6054b7

# Contextual-Walker

Систем за трајно чување и враћање радних контекста у iTerm2. Групише терминалске прозоре по пројекту, континуирано прати њихово стање и враћа их на захтјев.

## Шта

**Contextual-Walker (CW)** додаје слој „Context" изнад iTerm2. Context је именована група прозора који припадају једном пројекту или активности. CW памти који прозори припадају ком Context-у, какав им је layout (табови, панели, радни директоријуми, геометрија) и може их вратити након затварања.

## Зашто

Када радиш на више пројеката, имаш много iTerm прозора, табова и панела. Затварањем губиш layout. Поновно отварање значи ручно реконструисање свега. CW рјешава то — затвори прозоре пројекта, пребаци се на други, и касније врати први тачно какав је био.

## Како

- **Daemon** ради унутар iTerm2 (AutoLaunch скрипта), прати промјене layout-а преко iTerm2 Python API-ја
- Стање се чува у **SQLite** (`~/.contextual-walker/cw.sqlite`) са атомским трансакцијама
- **CLI** (`cw`) омогућава управљање Context-има из било ког терминала
- Затварање прозора означава га као `open=false` — остаје у Context-у и може се вратити
- Ако CW падне, iTerm наставља нормално — daemon ради у засебном процесу са свим грешкама ухваћеним

## Инсталација

```bash
# Уђи у пројекат
cd Contextual-Walker

# Једна команда ради СВЕ:
#   venv, pip install, база, daemon, man странице, completion
bash scripts/install.sh

# Активирај у тренутном shell-у (или отвори нови таб)
source ~/.bashrc   # или ~/.zshrc зависно од shell-а

# Рестартуј iTerm2 (daemon се аутоматски покреће)
```

## Брзи почетак

```bash
cw create МојПројекат           # Празан Context
cw create МојПројекат -a        # Креирај + додај тренутни прозор
cw join МојПројекат             # Додај тренутни прозор
cw join МојПројекат/Dev         # Додај тренутни, именуј "Dev"
cw join МојПројекат 3           # Додај по реф броју
cw join МојПројекат IoT         # Додај по iTerm наслову
cw leave                        # Уклони тренутни прозор из контекста
cw rename Старо Ново            # Преименуј Context или Context/Window
cw list                         # Сви Context-и са живим статусом
cw windows                      # Прозори тренутног Context-а
cw windows -vv                  # Са табовима + панелима + CWD
cw windows --all                # СВИ iTerm прозори
cw go МојПројекат               # Скочи на задњи кориштени прозор
cw go 3                         # Скочи по реф броју
cw go IoT                       # Скочи по iTerm наслову
cw go -                         # Врати се на претходни Context
cw close                        # Затвори тренутни прозор (потврда)
cw close МојПројекат            # Сачувај и затвори
cw open МојПројекат             # Врати све назад
cw save                         # Форсирај snapshot
cw history МојПројекат          # Прикажи историју
cw backup                       # Бекап базе
cw reload                       # Reload daemon кода (без рестарта iTerm-а)
```

## Инсталација са прилагођеним бекап фолдером

```bash
bash scripts/install.sh --backup-dir ~/Documents/CW-Backups
```

## Деинсталација

```bash
bash scripts/uninstall.sh
```

Скрипта **увијек прво направи бекап**, па тек онда уклања daemon, man странице, completion и опционо податке. Бекапови се чувају.

## Приказ имена Context-а у iTerm панелима

CW поставља корисничке варијабле на сваку сесију. За приказ:

```
iTerm → Settings → Profiles → General → Badge:
\(user.cw_context_name) / \(user.cw_window_name)
```

Сваки панел ће тада приказивати нпр. `МојПројекат / Development` као позадински badge.

## Документација

- [FEATURES.md](FEATURES.md) — преглед функционалности
- [COMMANDS-sr.md](COMMANDS-sr.md) — детаљна референца команди (српски)
- [COMMANDS.md](COMMANDS.md) — command reference (English)
- [ARCHITECTURE-sr.md](ARCHITECTURE-sr.md) — преглед архитектуре
- [DEV/ARCHITECTURE-DISCUSSION.md](DEV/ARCHITECTURE-DISCUSSION.md) — детаљна архитектонска дискусија
- [README.md](README.md) — овај фајл на енглеском

## Лиценца

MIT
