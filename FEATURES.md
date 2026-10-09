Synced with commit: 3d1789f

# CW Features

## Context Management

- **Create** empty Contexts or with current window (`cw create`, `-a`)
- **Join** windows by current focus, ref number, iTerm title, or `Context/WindowName` (`cw join`)
- **Leave** — remove window from Context by name, ref, or title (`cw leave`)
- **Move** — move current tab to a Context/Window, creates if needed (`cw move`)
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
  - Detail levels: `-v` (tabs with numbers), `-vv` (+ panes with numbers + CWDs)
  - Color coded: yellow bold window names, blue tabs, bold pane numbers
  - Markers: `▶` for current window (yellow), selected tab (blue), active pane (green)
  - Auto-detects current Context when no name given
- **Current** — show which Context the current window belongs to (`cw current`)
- **Go** — jump to window by Context, ref number, or iTerm title (`cw go`)
  - Remembers last-used window per Context
  - `cw go -` toggles between two Contexts (like `cd -`)
- **Refresh** — re-apply badges and user variables to all tracked windows (`cw refresh`)

## Save & Restore

- **Close** — save-before-close principle; aborts if save fails (`cw close`)
  - Without arguments closes current window (with confirmation)
- **Open** — restores window position, tabs, panes, CWDs, tab titles, session names (`cw open`)
- **Save** — explicit snapshot (`cw save`)
- **History** — view snapshots with full timestamps (`cw history`)

## Shell Completion (bash / zsh / fish)

- All commands and subcommands
- Context names with `/` suffix for window drill-down
- iTerm window titles for `go`, `join`, `leave`
- Case-insensitive matching
- Latin → Cyrillic transliteration (e.g. `Dr` → `ДРУЖБА`)

## iTerm Integration

- Badge display: `\(user.cw_context_name) / \(user.cw_window_name)`
- Window titles set to `Context / Window` format
- Tab titles read with fallbacks: titleOverride → title → session autoName
- User variables on sessions for reconciliation
- AutoLaunch daemon — starts with iTerm

## Daemon

- Hot-reload (`cw reload`) — no iTerm restart for code changes
- Detects new modules that require restart
- All handlers in try/except — never affects iTerm stability
- Smart checkpoint: skips if a monitor already synced recently

## Backup & Config

- Timestamped backups with SQLite backup API (`cw backup`)
- Configurable backup directory (`cw config --backup-dir`)
- Uninstall always creates backup first

## Installation

- One-command install (`bash scripts/install.sh`)
- Auto-detects Python, creates venv, installs daemon, man pages, completion
- Configurable backup dir at install time (`--backup-dir`)
- Idempotent — safe to re-run
