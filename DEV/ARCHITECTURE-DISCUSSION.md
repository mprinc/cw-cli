дискусија са LLM

# iTerm Contextual-Walker — поуздано чување и враћање радних контекста

## 1. Основна идеја

**Contextual-Walker (CW)** треба да уведе концепт **Context-а** изнад iTerm2-а.

Један Context представља **један или више iTerm прозора** који логички припадају истом послу, пројекту или активности.

На примјер:

```text
Context: EcoColabo
│
├── Window: Development
│   ├── Tab: frontend
│   │   ├── Pane: dev-server
│   │   └── Pane: git
│   │
│   └── Tab: backend
│       ├── Pane: API
│       └── Pane: tests
│
└── Window: Infrastructure
    ├── Tab: server
    └── Tab: logs


Context: Contextual-Walker
│
└── Window: Development
    ├── Tab: iTerm API
    ├── Tab: daemon
    └── Tab: tests


Context: HZZ
│
└── Window: research
```

Истовремено може бити отворено више Context-а.

На примјер:

```text
OPEN:
    EcoColabo
    Contextual-Walker

CLOSED:
    HZZ
    PlayFormers
    Vibye
```

**Затворен Context није обрисан Context.**

То је једна од најважнијих архитектонских одлука цијелог система.

---

# 2. Најважнији принцип: Definition ≠ Runtime State

За сваки објекат морамо раздвојити:

1. **да ли припада Context-у**
2. **да ли тренутно постоји у iTerm-у**

На примјер:

```text
EcoColabo
│
├── Development       member=yes    open=yes
├── Infrastructure    member=yes    open=no
└── Logs              member=yes    open=no
```

Ако ручно затворим `Infrastructure` прозор:

```text
member=yes
open=yes
```

постаје:

```text
member=yes
open=no
```

НЕ:

```text
member=no
```

Другим ријечима:

> **затварање никада не значи брисање.**

Исто важи и на нижим нивоима, али уз једну важну разлику коју ћемо касније дефинисати за pane/tab структуру.

---

# 3. Шта желимо да памтимо

За сваки Context желимо трајно чувати:

```text
CONTEXT
│
├── metadata
│   ├── id
│   ├── name
│   ├── created_at
│   ├── updated_at
│   ├── description
│   └── tags
│
├── windows[]
│   │
│   ├── persistent CW id
│   ├── semantic name
│   ├── iTerm title
│   ├── open / closed
│   ├── position
│   ├── size
│   ├── monitor
│   ├── fullscreen
│   │
│   └── tabs[]
│       │
│       ├── persistent CW id
│       ├── semantic name
│       ├── title
│       ├── order
│       ├── selected
│       │
│       └── panes[]
│           │
│           ├── persistent CW id
│           ├── name
│           ├── profile
│           ├── split hierarchy
│           ├── split orientation
│           ├── relative size
│           ├── CWD
│           ├── hostname
│           ├── username
│           ├── shell
│           ├── last command
│           ├── command history
│           ├── scrollback/archive
│           ├── running process
│           │
│           └── context
│               ├── git repository
│               ├── git branch
│               ├── git HEAD
│               ├── git dirty status
│               ├── selected environment info
│               └── SSH target
│
└── runtime
    ├── open windows
    ├── focused window
    ├── selected tabs
    └── focused panes
```

---

# 4. Ко је за шта одговоран

Не треба покушавати да CW замијени iTerm.

Треба искористити оно што iTerm већ добро ради и направити **persistent semantic layer** преко њега.

Архитектура би била:

```text
┌───────────────────────────────────────┐
│                USER                   │
│                                       │
│  Cmd-W   split pane   resize   cd     │
│  cw open   cw close   cw save         │
└──────────────────┬────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────┐
│                iTerm2                 │
│                                       │
│ windows / tabs / sessions / panes     │
│ layouts / geometry / profiles         │
│ shell integration                     │
│ session archives                      │
│ session restoration                   │
└──────────────────┬────────────────────┘
                   │
             Python API
             notifications
             monitors
                   │
                   ▼
┌───────────────────────────────────────┐
│          CW WATCHER / DAEMON          │
│                                       │
│ observes iTerm                        │
│ maps iTerm IDs → CW persistent IDs    │
│ detects changes                       │
│ persists state                        │
│ writes transactionally                │
└──────────────────┬────────────────────┘
                   │
                   ▼
┌───────────────────────────────────────┐
│           CW PERSISTENT STORE         │
│                                       │
│ contexts                              │
│ session metadata                      │
│ archives                              │
│ backups                               │
└───────────────────────────────────────┘
```

---

# 5. iTerm је runtime, CW је source of persistent context

Ово је фундаментално.

iTerm зна:

> „Тренутно постоје ова 3 прозора, ових 9 tab-ова и ових 17 sessions.“

CW зна:

> „Ова два прозора припадају EcoColabo Context-у, овај затворени прозор такође припада EcoColabo-у, овако је изгледао када је затворен и ово је његово посљедње познато стање.“

Зато:

```text
iTerm state
    =
what exists NOW
```

док је:

```text
CW state
    =
what belongs to the Context
+
last known state
+
what is currently open
+
history/recovery information
```

---

# 6. Не бих користио macOS hooks ако нам нису потребни

Ово је важна поједностављујућа ствар.

Ако корисник у iTerm-у притисне:

```text
Cmd-W
```

не морамо пресретати macOS keyboard event.

iTerm2 Python API већ има:

```text
LayoutChangeMonitor
```

који прати промјене у композицији:

```text
sessions
tabs
windows
```

Постоји и:

```text
SessionTerminationMonitor
```

за завршетак session-а.

iTerm2 документација експлицитно каже да `LayoutChangeMonitor` прати промјене композиције sessions, tabs и windows.

Такође `App` објекат сам одржава актуелно стање користећи notifications када се sessions, tabs или windows промијене.

Референце:

- [iTerm2 Notifications API](https://iterm2.com/python-api/notifications.html)
- [iTerm2 Life Cycle API](https://iterm2.com/python-api/lifecycle.html)
- [iTerm2 App API](https://iterm2.com/python-api/app.html)

То значи да CW може бити **event-driven**, а не да сваке секунде наслијепо испитује iTerm.

---

# 7. Шта се дешава када ручно затворим PANE

Претпоставимо:

```text
Tab: backend

┌─────────────────────┬─────────────────┐
│ API                 │ tests           │
│                     │                 │
│ npm run dev         │ pytest          │
└─────────────────────┴─────────────────┘
```

Корисник ручно затвори `tests`.

iTerm промијени layout:

```text
┌───────────────────────────────────────┐
│ API                                   │
│                                       │
│ npm run dev                           │
└───────────────────────────────────────┘
```

iTerm шаље layout-change notification. ([iterm2.com](https://iterm2.com/python-api/notifications.html?utm_source=chatgpt.com))

CW watcher тада:

```text
1. прими notification

2. прочита нови iTerm layout

3. упореди:
      previous state
          vs
      current state

4. установи:
      pane "tests" disappeared

5. прије коначног commit-а чува све што о њему већ зна

6. нови layout постаје current desired layout

7. atomic commit у CW storage
```

Овдје је битна семантика:

**Pane који си намјерно затворио јесте промјена layout-а Context-а.**

Дакле, ако си имао:

```text
API | tests
```

па затвориш `tests`, сачувано стање Context-а постаје:

```text
API
```

Када сутра отвориш Context, `tests` се неће магично вратити.

То је оно што си тражио:

> „када затворим панел, да се то упамти у контексту као промјена“

---

# 8. Али WINDOW има другачију семантику

Ово је јако важно.

Ако затвориш:

```text
EcoColabo / Infrastructure
```

то **не значи**:

```text
remove Infrastructure from EcoColabo
```

него:

```text
Infrastructure:
    member = true
    open = false
```

CW прије/током затварања има његово посљедње познато стање:

```text
window:
    cw_id: ecocolabo-infrastructure

    member: true
    open: false

    tabs:
        server
        logs
        docker

    geometry:
        ...

    sessions:
        ...
```

Зато га можемо касније вратити:

```bash
cw open EcoColabo/Infrastructure
```

---

# 9. Уклањање Window-а из Context-а мора бити експлицитно

Само команда типа:

```bash
cw remove-window EcoColabo/Infrastructure
```

смије значити:

```text
member = false
```

И чак бих ту тражио потврду:

```text
Remove window "Infrastructure" from Context "EcoColabo"?

Its recovery snapshots will be retained.

[y/N]
```

Чак ни тада не бих одмах физички брисао његове snapshot-е.

---

# 10. DELETE не смије бити исто што и CLOSE

Требају нам најмање четири различита концепта:

```text
CLOSE
    престани приказивати/runtime session

REMOVE
    више није дио Context definition-а

DELETE
    логички обриши објекат

PURGE
    стварно избриши recovery data
```

Тако:

```bash
cw close EcoColabo
```

је безбједно.

А:

```bash
cw delete EcoColabo
```

може ставити Context у trash/recovery.

Тек:

```bash
cw purge EcoColabo
```

стварно уклања податке.

---

# 11. Најважнији захтјев: НЕ СМИЈЕМО зависити од једног save-а

Ако желимо стварно поуздан систем, модел:

```text
cw save
```

није довољан.

Корисник ће прије или касније:

- заборавити save;
- затворити прозор;
- убити iTerm;
- имати crash;
- рестартовати машину;
- направити грешку;
- затворити погрешан pane.

Зато CW треба бити **continuous persistence system**.

---

# 12. Continuous persistence

CW daemon прати промјене у iTerm-у.

На сваку релевантну промјену:

```text
iTerm event
    ↓
CW observes
    ↓
CW reads actual state
    ↓
CW validates
    ↓
CW persists
```

То је примарни механизам.

> **Додатна идеја за каснију верзију:** event journal (append-only лог свих промјена) и immutable snapshots (периодични замрзнути пресјеци стања) могу додатно побољшати recovery могућности, али нису потребни за V1.

---

# 14. Atomic writes су обавезни

Никада:

```text
open context.json
truncate
write...
```

јер crash усред write-а може оставити пола JSON-а.

Умјесто тога:

```text
write context.json.tmp
        ↓
flush
        ↓
fsync
        ↓
validate
        ↓
atomic rename
        ↓
context.json
```

---

# 15. Ја бих користио SQLite као canonical store

Умјесто да JSON буде једини извор истине:

```text
~/.contextual-walker/
│
├── cw.sqlite
│
├── archives/
│
├── exports/
│
└── logs/
```

SQLite нам даје:

```text
transactions
atomic commits
constraints
indexes
WAL
crash recovery
```

а Context можемо по жељи export-овати у читљив:

```text
context.json
```

или:

```text
context.yaml
```

за backup/Git.

---

# 16. iTerm Session Archives као независни safety net

Ово је јако корисно.

iTerm2 има **Session Archives**.

Archive садржи scrollback једне session и може се касније поново отворити.

Још важније, iTerm има:

```text
Settings
→ Profiles
→ Session
→ Archive sessions on closure
```

Када је то укључено, iTerm аутоматски прави archive када се session затвори. ([iterm2.com](https://iterm2.com/documentation-session-archives.html?utm_source=chatgpt.com))

То значи:

```text
USER CLOSES PANE
       │
       ├───────────────► iTerm archive
       │
       └───────────────► CW persistent state
```

Два независна механизма.

То је управо врста redundancy-а коју желимо.

Документација:

[iTerm2 Session Archives](https://iterm2.com/documentation-session-archives.html)

---

# 17. Undo Close нам даје још један safety layer

iTerm2 већ има:

```text
Shell → Undo Close
```

за недавно затворен:

```text
session
tab
window
```

у временском периоду подешеном у Session preferences. ([stage.iterm2.com](https://stage.iterm2.com/documentation-one-page.html?utm_source=chatgpt.com))

Тако имамо:

```text
Level 0   iTerm Undo Close

Level 1   iTerm Session Archive

Level 2   CW live persistent state

Level 3   external backup
```

То већ постаје озбиљно robust.

---

# 18. Session Restoration је друга врста заштите

iTerm2 има и **Session Restoration**.

Он може држати jobs у дуготрајним server processes тако да crash/update iTerm-а не мора убити процес.

При поновном старту iTerm покушава поново повезати restored terminal са постојећим process-ом. ([iterm2.com](https://iterm2.com/documentation-restoration.html?utm_source=chatgpt.com))

То је важно за:

```text
npm run dev
python server.py
ssh ...
tail -f ...
```

Али не треба га помијешати са CW persistence-ом.

Session Restoration штити:

```text
LIVE PROCESS
```

CW штити:

```text
CONTEXT
```

То су комплементарни механизми.

---

# 19. CW daemon треба бити дуготрајан процес

Архитектонски бих имао:

```text
cw
    CLI

cw-daemon
    long-running watcher
```

`cw-daemon` одржава Python API connection са iTerm-ом.

Он слуша:

```text
LayoutChangeMonitor
SessionTerminationMonitor
NewSession notifications
Variable changes
```

и друге потребне iTerm events.

iTerm API је намијењен управо оваквом async раду. ([iterm2.com](https://iterm2.com/python-api/notifications.html?utm_source=chatgpt.com))

---

# 20. macOS LaunchAgent

Daemon не треба зависити од тога да си ручно укуцао:

```bash
cw daemon
```

На macOS-у бих га регистровао као:

```text
LaunchAgent
```

отприлике:

```text
macOS login
     ↓
launchd
     ↓
CW daemon
     ↓
wait for iTerm
     ↓
connect iTerm Python API
     ↓
reconcile state
     ↓
monitor continuously
```

Дакле, **launchd је системски дио**.

Али он не прати iTerm прозоре.

Само обезбјеђује да CW daemon живи.

---

# 21. Који дио је macOS, који iTerm, који CW?

```text
macOS
────────────────────────────────────

launchd
    └── покреће/рестартује CW daemon

filesystem
    └── CW database
    └── backups
    └── archives

optional:
    Time Machine
    filesystem backup


iTerm2
────────────────────────────────────

windows
tabs
panes/sessions
geometry
profiles
shell integration
session archives
session restoration

Python API:
    LayoutChangeMonitor
    SessionTerminationMonitor
    notifications
    Window/Tab/Session APIs


CW
────────────────────────────────────

Context concept
persistent IDs
membership
open/closed state
semantic names

mapping:
    iTerm object
        ↔
    CW object

SQLite persistence
reconciliation
restore logic
backup/export

CLI:
    cw list
    cw open
    cw close
    cw save
    cw history
    ...
```

---

# 22. Persistent ID је неопходан

iTerm ID није наш трајни идентитет.

Рецимо:

```text
CW Window:
    cw_id = 53c1...
```

тренутно може бити:

```text
iTerm window_id = w0t17
```

Затворимо га.

`w0t17` више не постоји.

Касније:

```bash
cw open EcoColabo/Infrastructure
```

iTerm направи:

```text
window_id = w0t93
```

Али CW зна:

```text
w0t17   ─┐
         ├──► cw_id 53c1...
w0t93   ─┘
```

То је исти **логички Window**, само друга runtime инстанца.

---

# 23. Како iTerm објекат зна којем CW Context-у припада?

iTerm API подржава user-defined variables на својим објектима; на примјер Tab API има `async_set_variable`, а user variable мора почети са `user.`. ([iterm2.com](https://iterm2.com/python-api/tab.html?utm_source=chatgpt.com))

Зато можемо означавати runtime објекте, нпр.:

```text
user.cw_context_id
user.cw_window_id
user.cw_tab_id
user.cw_session_id
```

Тако CW може много лакше поново успоставити mapping.

Не бих, међутим, само то користио као једини извор истине.

Canonical mapping је у CW бази.

iTerm metadata је **маркер који помаже reconciliation-у**.

Поред ID-ева, CW поставља и human-readable варијабле:

```text
user.cw_context_name
user.cw_window_name
```

Ово омогућава кориснику да **види име Context-а и Window-а директно у iTerm-у**.

Подешавање:

```text
iTerm → Settings → Profiles → General → Badge
```

У Badge поље ставити:

```text
\(user.cw_context_name) / \(user.cw_window_name)
```

Тада ће сваки pane у доњем десном углу приказивати нпр.:

```text
EcoColabo / Development
```

Ово је потпуно опционо — ако корисник не жели badge, све функционише исто без њега.

---

# 24. Reconciliation је пресудан за поузданост

Шта ако CW daemon падне?

Рецимо:

```text
18:00 daemon crashes

18:01 user closes pane
18:02 user creates tab
18:03 user moves pane

18:04 daemon restarts
```

Не можемо очекивати events од 18:01–18:03.

Зато при сваком reconnect-у CW ради:

```text
RECONCILIATION
```

односно:

```text
read complete current iTerm state
           │
           ▼
compare with CW last-known runtime state
           │
           ▼
identify differences
           │
           ▼
reconstruct safe changes where possible
           │
           ▼
persist reconciled state
```

То је много поузданије него ослањање искључиво на event stream.

---

# 25. Треба нам и периодични checkpoint

Иако имамо events, ја бих ипак сваких, рецимо:

```text
30–60 seconds
```

радио јефтин reconciliation/checkpoint ако је било промјена.

Не зато што не вјерујемо iTerm API-ју, него због принципа:

> events дају брзину; reconciliation даје сигурност.

---

# 26. CWD

iTerm Shell Integration већ прати:

```text
current working directory
hostname
command history
...
```

чак и у подржаним SSH сценаријима. ([iterm2.com](https://iterm2.com/documentation-shell-integration.html?utm_source=chatgpt.com))

Зато CW не мора да хакује shell prompt да би добио CWD.

Референца:

[iTerm2 Shell Integration](https://iterm2.com/documentation-shell-integration.html)

---

# 27. Command history

Имамо два нивоа.

Shell има своју:

```text
~/.zsh_history
```

или еквивалент.

iTerm Shell Integration такође зна command history.

CW може чувати свој **per-session semantic history**:

```text
Context
    Window
        Tab
            Pane
                command #1
                command #2
                command #3
```

То је корисније него глобална shell history.

---

# 28. Last command

За сваки pane можемо чувати:

```text
last_command
last_command_started
last_command_finished
exit_status
```

На примјер:

```json
{
  "command": "npm run dev",
  "cwd": "/development/ecocolabo/frontend",
  "started_at": "...",
  "exit_status": null
}
```

Али при restore-у **не треба аутоматски извршавати произвољну посљедњу команду**.

То би било опасно.

Можемо:

```text
restore CWD
restore context

Last command:
npm run dev

[Run]
```

или command ставити у prompt без Enter-а.

---

# 29. Running processes су посебна категорија

Не треба претпоставити:

```text
last command == running process
```

На примјер:

```text
npm run dev
```

може и даље радити.

За crash/restart iTerm-а Session Restoration може помоћи да job настави. ([iterm2.com](https://iterm2.com/documentation-restoration.html?utm_source=chatgpt.com))

Али након reboot-а OS-а process више не постоји.

Тада CW може знати:

```text
previously_running:
    npm run dev
```

и понудити:

```text
Restart previous process?
```

---

# 30. Scrollback / terminal text

Ово бих чувао двоструко.

## iTerm archive

Native iTerm Session Archive. ([iterm2.com](https://iterm2.com/documentation-session-archives.html?utm_source=chatgpt.com))

## CW metadata

CW база памти:

```text
archive path
session ID
timestamp
context
window
tab
pane
```

Тако:

```text
archive-92837
```

није само случајни terminal dump него:

```text
EcoColabo
→ Development
→ backend
→ tests
→ closed 2026-10-07 18:07
```

---

# 31. Window geometry

iTerm Window API омогућава читање/постављање frame-а, а Window Arrangements могу чувати/враћати window arrangement. ([iterm2.com](https://iterm2.com/python-api/window.html?utm_source=chatgpt.com))

Зато чувамо:

```text
x
y
width
height
fullscreen
screen/monitor
```

Али restore мора бити паметан.

Ако је оригинално било:

```text
Monitor 2
```

а сада имаш само laptop screen, не смијемо направити невидљив прозор ван екрана.

Fallback:

```text
desired monitor unavailable
        ↓
place safely on current monitor
```

---

# 32. Pane layout

iTerm има структуру sessions/tabs/windows и API за layout manipulation.

Постоји и:

```text
App.async_apply_layout()
```

који може reshaping tabs, премјештање sessions између tabs/windows и мијењање split tree-а. ([iterm2.com](https://iterm2.com/python-api/app.html?utm_source=chatgpt.com))

Важна напомена из документације: структурна валидација се ради прије мутације, али не треба претпоставити савршен rollback ако неочекивана грешка настане усред примјене. ([iterm2.com](https://iterm2.com/python-api/app.html?utm_source=chatgpt.com))

Зато CW restore мора имати сопствену recovery логику.

---

# 33. Restore мора бити transactional колико можемо

Не:

```text
delete current
then try restore
```

него:

```text
load snapshot
     ↓
validate snapshot
     ↓
validate profiles/directories
     ↓
prepare restore plan
     ↓
create new runtime objects
     ↓
apply layout
     ↓
verify
     ↓
mark restore successful
```

Ако нешто не успије:

```text
DO NOT MODIFY SAVED SNAPSHOT
```

То је још један фундаменталан принцип:

> **Неуспјешан restore никада не смије уништити оно из чега restore-ујемо.**

---

# 34. `cw close` мора бити save-before-close

Ако корисник каже:

```bash
cw close EcoColabo
```

CW ради:

```text
freeze logical operation
        ↓
read complete current state
        ↓
persist snapshot
        ↓
fsync/commit
        ↓
verify
        ↓
request iTerm close
        ↓
observe resulting events
        ↓
mark windows open=false
```

Ако persistence не успије:

```text
ABORT CLOSE
```

и:

```text
ERROR:
Could not safely snapshot EcoColabo.

No windows were closed.
```

---

# 35. Али шта ако корисник притисне црвено дугме или Cmd-W?

Ту не можемо радити `save-before-close`, јер је корисник већ наредио iTerm-у да затвори објекат.

Зато су нам потребни:

```text
continuous state
+
events
+
archives
```

CW је већ прије клика имао скоро комплетно стање.

iTerm затвори window.

CW добије layout change.

Он каже:

```text
Window 53c1 disappeared.

It belonged to EcoColabo.

DO NOT remove it.

Set:
    open=false

Preserve:
    last known layout
    tabs
    panes
    CWDs
    commands
    metadata
    archives
```

То директно испуњава твој захтјев.

---

# 36. Шта ако затворим цијели iTerm?

Опет:

```text
iTerm disappears
```

не значи:

```text
all Context windows deleted
```

CW само означава runtime као unavailable:

```text
EcoColabo
    Development       closed
    Infrastructure    closed

Contextual-Walker
    Development       closed
```

Context definitions остају.

---

# 37. Шта ако се рачунар сруши?

У најгорем случају имамо:

```text
SQLite last committed state
+
WAL
+
iTerm archives
+
shell history
```

Губитак би требао бити ограничен на евентуално врло мали неперзистирани runtime интервал.

А са event-driven commit-има, тај прозор може бити практично минималан.

---

# 38. Backup

„Не могу изгубити Context“ захтијева још нешто:

**локална база није backup.**

Треба омогућити:

```bash
cw backup
```

или аутоматски backup у:

```text
~/Documents/Contextual-Walker-Backup/
```

или други filesystem/cloud/Time Machine destination.

Добар модел:

```text
LIVE DB
    +
LOCAL SNAPSHOTS
    +
EXTERNAL BACKUP
```

Тек тада можемо озбиљно причати о високој поузданости.

---

# 39. Не чувати secrets

Никада аутоматски dump:

```bash
env
```

јер може садржати:

```text
OPENAI_API_KEY
AWS_SECRET_ACCESS_KEY
DATABASE_URL
GITHUB_TOKEN
...
```

Чувамо само allowlisted environment metadata:

```text
VIRTUAL_ENV
CONDA_DEFAULT_ENV
NODE_ENV
PYENV_VERSION
...
```

и чак то треба бити configurable.

---

# 40. Git context

За Contextual-Walker је врло корисно чувати:

```text
repo root
branch
HEAD commit
dirty status
```

На примјер:

```text
saved:

branch:
    feature/contextual-walker

HEAD:
    a81cf34

dirty:
    yes
```

При restore-у CW може упозорити:

```text
Workspace was saved at:

feature/contextual-walker @ a81cf34

Repository is currently:

main @ 91bb293
```

али не треба сам радити `checkout` без експлицитне дозволе.

---

# 41. CLI

Основни интерфејс:

```bash
cw list
```

на примјер:

```text
CONTEXT             STATUS       WINDOWS     SAVED
────────────────────────────────────────────────────
EcoColabo           ● OPEN       2/3         18:14
Contextual-Walker   ● OPEN       1/1         18:12
HZZ                 ○ CLOSED     0/1         Oct 06
PlayFormers         ◐ PARTIAL    1/3         Oct 04
```

Три стања су кориснија него два:

```text
OPEN
PARTIAL
CLOSED
```

---

# 42. Window list

```bash
cw windows EcoColabo
```

```text
EcoColabo

● Development
● Infrastructure
○ Production
```

---

# 43. Отварање цијелог Context-а

```bash
cw open EcoColabo
```

отвара све његове затворене windows.

А:

```bash
cw open EcoColabo/Production
```

само један.

---

# 44. Затварање

```bash
cw close EcoColabo
```

ради:

```text
SAVE
VERIFY
CLOSE
```

А:

```bash
cw close EcoColabo/Infrastructure
```

затвара само тај window.

И даље:

```text
member=true
open=false
```

---

# 45. `cw save`

Иако имамо continuous persistence, `save` је и даље користан.

```bash
cw save EcoColabo
```

значи:

> направи именован/експлицитан recovery checkpoint сада.

Може бити:

```text
Snapshot created:
EcoColabo @ 2026-10-07 18:17:31
```

---

# 46. `cw history`

```bash
cw history EcoColabo
```

```text
18:17:31   manual checkpoint
18:14:02   before window close
18:07:12   pane layout changed
18:00:00   automatic snapshot
17:45:00   automatic snapshot
```

---

# 47. Restore старог стања

```bash
cw restore EcoColabo --snapshot 18:07:12
```

Али бих прије restore-а аутоматски направио:

```text
pre-restore snapshot
```

Тако је и restore undoable.

---

# 48. Context creation / membership

На примјер:

```bash
cw create EcoColabo
```

тренутни window постаје први window Context-а.

Из другог window-а:

```bash
cw join EcoColabo
```

додаје га.

А:

```bash
cw leave
```

је **експлицитна membership промјена**.

Само затварање прозора никада није `leave`.

---

# 49. Shell auto-complete

CW CLI мора подржавати tab-completion за bash/zsh/fish.

На примјер:

```bash
cw open EcoCo<TAB>
```

допуњава у:

```bash
cw open EcoColabo
```

А даље:

```bash
cw open EcoColabo/<TAB>
```

нуди:

```text
Development
Infrastructure
Production
```

Completion ради хијерархијски:

```text
cw <TAB>              → list, open, close, save, create, join, leave, history, restore, ...
cw open <TAB>         → EcoColabo, Contextual-Walker, HZZ, PlayFormers, ...
cw open EcoColabo/<TAB>  → Development, Infrastructure, Production
cw close <TAB>        → EcoColabo, Contextual-Walker  (само отворени)
cw restore <TAB>      → EcoColabo, ...
```

Имплементација: CW CLI генерише completion script:

```bash
cw completion bash >> ~/.bashrc
cw completion zsh  >> ~/.zshrc
cw completion fish > ~/.config/fish/completions/cw.fish
```

Completion функција чита листу Context-а и Window-а из CW базе (SQLite), тако да је увијек ажурна.

---

# 50. Потенцијални GUI

Касније можемо имати мали Contextual-Walker manager:

```text
┌──────────────────────────────────────────────┐
│ Contextual Walker                            │
├──────────────────────────────────────────────┤
│                                              │
│ ▼ EcoColabo                    ● OPEN         │
│     ● Development                            │
│     ● Infrastructure                         │
│     ○ Production                             │
│                                              │
│ ▶ Contextual-Walker             ● OPEN        │
│                                              │
│ ▶ HZZ                           ○ CLOSED      │
│                                              │
│ ▶ PlayFormers                   ◐ PARTIAL     │
│                                              │
└──────────────────────────────────────────────┘
```

и:

```text
Open
Close
Save snapshot
History
Restore
Rename
Remove
```

---

# 50. Шта бих сматрао SOURCE OF TRUTH

Не бих направио iTerm Arrangement јединим source of truth.

Arrangement је одличан native механизам и можемо га користити као:

```text
additional snapshot
restore helper
fallback
```

али CW мора имати свој semantic model.

Зашто?

Јер iTerm не зна нашу семантику:

```text
Context
membership
closed-but-still-member window
persistent CW identity
history
git context
backup policy
```

Зато:

```text
             ┌─────────────────────┐
             │ CW SQLite database  │
             │  SOURCE OF TRUTH    │
             └──────────┬──────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
      iTerm API                  archives
       runtime                  scrollback
```

---

# 51. Али за LIVE layout је iTerm ауторитет

Постоји суптилна али важна разлика.

За питање:

> „Како Context треба да изгледа?“

CW је authority.

За питање:

> „Шта је управо сада отворено у iTerm-у?“

iTerm је authority.

CW их непрестано усаглашава.

---

# 52. Дакле имамо двије врсте state-а

```text
DESIRED / PERSISTENT STATE

EcoColabo
├── Development
├── Infrastructure
└── Production
```

и:

```text
OBSERVED RUNTIME STATE

Development       open
Infrastructure    open
Production        closed
```

То је врло слично начину на који озбиљни orchestration systems раздвајају desired и observed state.

---

# 53. Pane close vs Window close — коначна семантика

Ово вриједи експлицитно записати.

### Pane close

Корисник затвори pane:

```text
layout changed
```

CW прихвата то као нову верзију layout-а.

Pane више није дио активног layout-а.

Његова history/archive остаје у recovery history.

### Tab close

Исто:

```text
layout changed
```

Tab не треба поново да се појави при нормалном restore-у.

Али остаје у history/snapshot-има.

### Window close

Другачије:

```text
window remains Context member
open=false
```

Његова комплетна посљедња структура остаје.

### Context close

```text
all windows:
    member=true
    open=false
```

### Remove window

Само експлицитно:

```bash
cw leave
```

или:

```bash
cw remove-window ...
```

мијења membership.

---

# 54. Зашто Window има другачију семантику?

Зато што си управо дефинисао Context као:

> **скуп једног или више прозора који представљају један радни контекст.**

Зато је Window дио **идентитета Context-а**.

Pane и Tab су његов mutable layout.

То је добра и чиста граница:

```text
CONTEXT MEMBERSHIP
    ↓
WINDOWS

WINDOW CONTENT/LAYOUT
    ↓
TABS
    ↓
PANES
```

---

# 55. Можемо касније омогућити persistent tabs/panes

Ако се покаже корисним, можемо имати:

```text
pinned tab
pinned pane
```

гдје затварање значи:

```text
open=false
```

умјесто remove-from-layout.

Али то не бих стављао у прву верзију.

За почетак:

```text
Window = persistent Context member

Tab/Pane = mutable Window layout
```

је врло чист модел.

---

# 56. Цијели lifecycle

```text
                   CREATE
                     │
                     ▼
              ┌──────────────┐
              │   CONTEXT    │
              │              │
              │ persistent   │
              └──────┬───────┘
                     │
                   OPEN
                     │
                     ▼
          ┌─────────────────────┐
          │      iTerm LIVE     │
          │                     │
          │ windows             │
          │ tabs                │
          │ panes               │
          └──────────┬──────────┘
                     │
             continuous events
                     │
                     ▼
          ┌─────────────────────┐
          │     CW DAEMON       │
          │                     │
          │ observe             │
          │ reconcile           │
          │ persist             │
          └──────────┬──────────┘
                     │
          ┌──────────┼───────────┐
          │          │           │
          ▼          ▼           ▼
       SQLite              backup
          │
          ▼
       RESTORE
          │
          ▼
        iTerm
```

---

# 57. Минимална robust имплементација

За **V1** бих направио:

```text
1. Python CW daemon
2. iTerm Python API connection
3. LayoutChangeMonitor
4. SessionTerminationMonitor
5. SQLite database
6. persistent Context/Window IDs
7. iTerm ↔ CW ID mapping
8. continuous layout persistence
9. Window open/closed semantics
10. CWD capture
11. titles
12. geometry
13. split hierarchy
14. automatic Session Archives
15. CLI:
       cw list
       cw create
       cw join
       cw open
       cw close
       cw save
       cw history
16. reconciliation after reconnect
17. LaunchAgent
18. automatic backups
```

---

# 58. V2

Онда:

```text
command history
last command
exit codes
git context
SSH context
running-process metadata
better snapshot browser
partial restore
window-level restore
tab/pane history
GUI
```

---

# 59. V3 — Contextual Walker у правом смислу

Тада можемо ићи много даље:

```text
Context:
    EcoColabo

Terminal:
    2 windows
    7 tabs
    14 panes

Git:
    3 repositories

Browser:
    relevant tabs

VS Code:
    workspace

Documents:
    relevant files

ChatGPT:
    relevant project/conversation

Notes:
    ...
```

Тада Context више није:

> „iTerm workspace“

него:

> **snapshot радног контекста корисника преко више апликација.**

iTerm Contextual-Walker је онда први, добро ограничен модул тог система.

---

# 60. Коначна архитектонска препорука

Ја бих систем засновао на ових **9 правила**:

1. **Context је persistent entity.**
2. **Window membership је persistent и независан од open/closed стања.**
3. **Затварање Window-а никада га не уклања из Context-а.**
4. **Tab/Pane close је нормална измјена layout-а, али стари state остаје у history-ју.**
5. **CW daemon непрестано слуша iTerm events.**
6. **Events нису довољни — након reconnect-а увијек радимо reconciliation.**
7. **SQLite + transactions је canonical persistence.**
8. **`cw close` увијек ради save → verify → close.**
9. **Delete никада није исто што и Close; destructive purge мора бити посебна операција.**

Са тим моделом добијамо управо оно што желимо:

```text
                 Contextual-Walker
                        │
             ┌──────────┴──────────┐
             │                     │
        PERSISTENT              RUNTIME
         CONTEXT                 iTerm
             │                     │
        Context ID             Windows
             │                  Tabs
        Window IDs              Panes
             │                     │
             └──────────┬──────────┘
                        │
                     DAEMON
                        │
             observe + reconcile
                        │
       ┌────────────────┼────────────────┐
       │                                │
     SQLite                          Backup
       │
       └───────────────┬─────────────────┘
                       │
                    RESTORE
                       │
                       ▼
                     iTerm
```

**То значи да iTerm остаје одговоран за terminal runtime, macOS/launchd за живот CW daemon-а, а Contextual-Walker постаје поуздани persistent „мозак“ који зна шта је Context, шта му припада, шта је тренутно отворено, како је изгледало, шта се промијенило и како све то поново реконструисати.**

## Референце

- [iTerm2 Python API](https://iterm2.com/python-api/)
- [iTerm2 Notifications API](https://iterm2.com/python-api/notifications.html)
- [iTerm2 Life Cycle / LayoutChangeMonitor](https://iterm2.com/python-api/lifecycle.html)
- [iTerm2 App API / `async_apply_layout`](https://iterm2.com/python-api/app.html)
- [iTerm2 Window API](https://iterm2.com/python-api/window.html)
- [iTerm2 Tab API](https://iterm2.com/python-api/tab.html)
- [iTerm2 Session API](https://iterm2.com/python-api/session.html)
- [iTerm2 Session Archives](https://iterm2.com/documentation-session-archives.html)
- [iTerm2 Session Restoration](https://iterm2.com/documentation-restoration.html)
- [iTerm2 Shell Integration](https://iterm2.com/documentation-shell-integration.html)

Ово бих узео као **основни архитектонски документ V1**. Сљедећи логичан корак је да из њега изведемо конкретан **SQLite data model + event model + state machine**, прије него што пишемо daemon.