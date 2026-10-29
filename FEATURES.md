Synced with commit: 17d5a03

# CW Features

## Context Management

- **Create** empty Contexts or with current window (`cw create`, `-a`)
- **Join** windows by current focus, ref number, iTerm title, or `Context/WindowName` (`cw join`)
- **Leave** — remove window from Context by name, ref, or title; safe even if iTerm window no longer exists (`cw leave`)
- **Move** — move current tab to a Context/Window, creates if needed; auto-cleans source window if last tab moved out (`cw move`)
- **Rename** Contexts and Windows (`cw rename`)
- **Delete** Contexts with soft-delete (recoverable)

## Window Tracking

- Continuous state persistence via daemon (layout, geometry, CWD, titles)
- Window close = `is_open=false`, membership preserved — never loses data
- Active pane tracked per tab (`is_active` in DB)
- Multiple sync mechanisms:
  - Layout change callback (immediate)
  - Focus change monitor (on every tab/pane/window switch)
  - Session creation/termination monitors
  - Periodic checkpoint every 5 seconds (safety net)
- Reconciliation on daemon startup (catches missed changes)

## Browsing & Navigation

- **List** all Contexts with live DB ↔ iTerm comparison (`cw list`)
- **Windows** — view by Context, all, or untracked only (`cw windows`)
  - Reads live iTerm state (not stale DB)
  - Detail levels: `-v` (tabs), `-vv` (+ panes + CWDs), `-vvv` (+ pane UUID + history file path)
  - Color coded: yellow bold window names, blue tabs, bold pane numbers
  - Markers: `▶` for last-used window (yellow), selected tab (blue), active pane (green)
  - Auto-detects current Context when no name given
- **History-pane** — per-pane command history (`cw history-pane`)
  - `--file` shows history file path, `--cat` shows raw contents
- **Current** — show which Context the current window belongs to (`cw current`)
- **Go** — jump to window by Context, ref number, or iTerm title (`cw go`)
  - Remembers last-used window per Context
  - `cw go -` toggles between two Contexts (like `cd -`)
- **Refresh** — re-apply badges and user variables to all tracked windows (`cw refresh`)

## Save & Restore

- **Close** — save-before-close principle; aborts if save fails (`cw close`)
  - Without arguments closes current window (with confirmation)
- **Open** — restores window position, tabs, panes, CWDs, tab titles, session names, **font size** (`cw open`)
  - Already-open window → focuses it instead of error
  - Per-pane history preserved across close/open (stable UUID)
  - Session-level font size restored (even if different from profile default)
- **Save** — explicit snapshot (`cw save`)
- **History** — view snapshots with full timestamps (`cw history`)

## Shell Completion (bash / zsh / fish)

- All commands and subcommands
- Context names with `/` suffix for window drill-down
- iTerm window titles for `go`, `join`, `leave`
- Case-insensitive matching
- **Bidirectional** Latin ↔ Cyrillic transliteration with fuzzy digraph matching (`S` matches `Школа`, `Лит` matches `LitTerra`)
- Baby latinica support (`sh`→ш, `ch`→ч, `dzh`→џ, `cj`→ћ)

## iTerm Integration

- Badge display: `\(user.cw_context_name) / \(user.cw_window_name)`
- Window titles set to `Context / Window` format
- Tab titles read with fallbacks: titleOverride → title → session autoName
- User variables on sessions for reconciliation
- AutoLaunch daemon — starts with iTerm

## Per-pane Shell History

- Every pane gets its own HISTFILE (`~/.contextual-walker/history/<UUID>.history.txt`)
- ↑ arrow shows only commands from that specific pane
- ALL sessions get HISTFILE at daemon start (tracked and untracked)
- History flushed to disk after every command (`PROMPT_COMMAND`)
- UUID preserved across close/open cycles (stable pane identity)
- Configurable max commands per pane (`cw config --history-max`)

## Daemon

- Hot-reload (`cw reload`) — no iTerm restart for command handler changes
- `database.__class__` updated on reload (fixes stale DB method references)
- Runs pending DB migrations on reload (new columns available immediately)
- Detects new modules that require restart
- All handlers in try/except — never affects iTerm stability
- Smart checkpoint: skips if a monitor already synced recently

## Backup & Config

- ZIP-compressed timestamped backups with SQLite backup API (`cw backup`, ~3x smaller)
- Backup includes DB, config, per-pane history files (not daemon.log)
- Configurable backup directory (`cw config --backup-dir`)
- **Restore from backup** (`cw restore-backup`) — restore Context/Window from `.zip`, folder, or `.sqlite`
  - Also restores per-pane history files for restored panes
- Uninstall always creates backup first
- Daemon log rotation: `RotatingFileHandler`, 50MB max, 2 backups

## Installation

- One-command install (`bash scripts/install.sh`)
- Auto-detects Python, creates venv, installs daemon, man pages, completion
- Configurable backup dir at install time (`--backup-dir`)
- Idempotent — safe to re-run

## Testing

- 74 unit tests (DB, models, CLI, completion, config, migration, daemon commands)
- Mock iTerm2 API for daemon command testing without live iTerm
- 19 safe e2e tests (no window disruption)
- 18 destructive e2e tests (creates/closes windows)
- 11 restart e2e tests (restarts iTerm, user confirmation required)
- UUID stability tests: checkpoint, close/open cycle, pre-mapping
