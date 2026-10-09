Synced with commit: 8ae6d0c

# Contextual-Walker

Persistent context manager for iTerm2. Groups terminal windows by project, tracks their state continuously, and restores them on demand.

## What

**Contextual-Walker (CW)** adds a "Context" layer on top of iTerm2. A Context is a named set of windows that belong to one project or activity. CW remembers which windows belong to which Context, what their layout looks like (tabs, panes, working directories, geometry), and can bring them back after you close them.

## Why

When working on multiple projects you end up with many iTerm windows, tabs, and panes. Closing them loses your layout. Reopening means manually recreating everything. CW solves this — close a project's windows, switch to another, and restore the first one later exactly as it was.

## How

- A **daemon** runs inside iTerm2 (AutoLaunch script), watching layout changes via the iTerm2 Python API
- State is persisted to **SQLite** (`~/.contextual-walker/cw.sqlite`) with atomic transactions
- A **CLI** (`cw`) lets you manage Contexts from any terminal pane
- Closing a window marks it as `open=false` — it stays in the Context and can be restored
- If CW crashes, iTerm is unaffected — the daemon runs in a separate process with all errors caught

## Install

```bash
# Clone and enter the project
cd Contextual-Walker

# One command does everything:
#   venv, pip install, database init, daemon install,
#   man pages, shell completion
bash scripts/install.sh

# Activate in current shell (or open a new tab)
source ~/.bashrc   # or ~/.zshrc depending on your shell

# Restart iTerm2 (daemon auto-starts)
```

## Quick start

```bash
cw create MyProject           # Create empty Context
cw create MyProject -a        # Create + add current window
cw join MyProject             # Add current window to Context
cw join MyProject/Dev         # Add current window, name it "Dev"
cw join MyProject 3           # Add window by ref number
cw join MyProject IoT         # Add window by iTerm title
cw leave                      # Remove current window from its Context
cw move MyProject/Dev         # Move current tab to Context/Window
cw rename Old New             # Rename Context or Context/Window
cw current                    # Show current Context
cw list                       # All Contexts with live status
cw windows                    # Windows in current Context
cw windows -vv                # With tabs + panes + CWDs
cw windows --all              # ALL iTerm windows (tracked + untracked)
cw go MyProject               # Jump to last used window in Context
cw go 3                       # Jump by ref number
cw go IoT                     # Jump by iTerm title
cw go -                       # Jump back to previous Context
cw close                      # Close current window (confirm)
cw close MyProject            # Save state and close all windows
cw open MyProject             # Restore everything
cw save                       # Force a snapshot
cw history MyProject          # View snapshots
cw backup                     # Backup database
cw refresh                    # Re-apply badges and window titles
cw reload                     # Reload daemon code (no iTerm restart)
```

## Install with custom backup directory

```bash
bash scripts/install.sh --backup-dir ~/Documents/CW-Backups
```

## Uninstall

```bash
bash scripts/uninstall.sh
```

The uninstall script **always creates a backup first**, then removes the daemon, man pages, shell completion, and optionally the data directory. Backups are preserved.

## Tests

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

47 tests covering: DB CRUD, models, CLI helpers, shell completion, config, DB migration.

## Show Context name in iTerm panes

CW sets user variables on every session. To display them:

```
iTerm → Settings → Profiles → General → Badge:
\(user.cw_context_name) / \(user.cw_window_name)
```

Each pane will then show e.g. `MyProject / Development` as a background badge.

## Documentation

- [FEATURES.md](FEATURES.md) — feature overview
- [COMMANDS.md](COMMANDS.md) — full command reference
- [COMMANDS-sr.md](COMMANDS-sr.md) — command reference in Serbian
- [ARCHITECTURE-sr.md](ARCHITECTURE-sr.md) — architecture overview (Serbian)
- [DEV/ARCHITECTURE-DISCUSSION.md](DEV/ARCHITECTURE-DISCUSSION.md) — detailed architecture discussion (Serbian)
- [README-sr.md](README-sr.md) — this file in Serbian

## License

MIT
