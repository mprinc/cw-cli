Synced with commit: f6054b7

# CW Features

## Context Management

- **Create** empty Contexts or with current window (`cw create`, `-a`)
- **Join** windows by current focus, ref number, or iTerm title (`cw join`)
- **Leave** — remove window from Context by name, ref, or title (`cw leave`)
- **Rename** Contexts and Windows (`cw rename`)
- **Delete** Contexts with soft-delete (recoverable)

## Window Tracking

- Continuous state persistence via daemon (layout, geometry, CWD, titles)
- Window close = `is_open=false`, membership preserved — never loses data
- Periodic checkpoints every 30 seconds
- Reconciliation on daemon startup (catches missed changes)

## Browsing & Navigation

- **List** all Contexts with live DB ↔ iTerm comparison (`cw list`)
- **Windows** — view by Context, all, or untracked only (`cw windows`)
  - Detail levels: `-v` (tabs), `-vv` (tabs + panes + CWDs)
  - Auto-detects current Context when no name given
- **Go** — jump to window by Context, ref number, or iTerm title (`cw go`)
  - Remembers last-used window per Context
  - `cw go -` toggles between two Contexts (like `cd -`)

## Save & Restore

- **Close** — save-before-close principle; aborts if save fails (`cw close`)
  - Without arguments closes current window (with confirmation)
- **Open** — restores window position, tabs, panes, CWDs, titles (`cw open`)
- **Save** — explicit snapshot (`cw save`)
- **History** — view snapshots (`cw history`)

## Shell Completion (bash / zsh / fish)

- All commands and subcommands
- Context names with `/` suffix for window drill-down
- iTerm window titles for `go`, `join`, `leave`
- Case-insensitive matching
- Latin → Cyrillic transliteration (e.g. `Dr` → `ДРУЖБА`)

## iTerm Integration

- Badge display: `\(user.cw_context_name) / \(user.cw_window_name)`
- User variables on sessions for reconciliation
- AutoLaunch daemon — starts with iTerm

## Daemon

- Hot-reload (`cw reload`) — no iTerm restart for code changes
- Detects new modules that require restart
- All handlers in try/except — never affects iTerm stability

## Backup & Config

- Timestamped backups with SQLite backup API (`cw backup`)
- Configurable backup directory (`cw config --backup-dir`)
- Uninstall always creates backup first

## Installation

- One-command install (`bash scripts/install.sh`)
- Auto-detects Python, creates venv, installs daemon, man pages, completion
- Configurable backup dir at install time (`--backup-dir`)
- Idempotent — safe to re-run
