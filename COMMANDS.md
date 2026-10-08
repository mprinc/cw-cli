Synced with commit: 05a75c6

# CW Command Reference

All commands support `-h` / `--help` for inline help.

## `cw list`

Show all Contexts with their current status. Contacts the daemon to compare the database state with live iTerm state. If they don't match, discrepancies are reported.

```bash
cw list
```

Output example:
```
CONTEXT              STATUS       WINDOWS      UPDATED
────────────────────────────────────────────────────────────
EcoColabo            ● OPEN       2/3          18:14
Contextual-Walker    ● OPEN       1/1          18:12
HZZ                  ○ CLOSED     0/1          Oct 06
PlayFormers          ◐ PARTIAL    1/3          Oct 04

✓ DB and iTerm state match.
```

Status icons:
- `●` OPEN — all member windows are open
- `◐` PARTIAL — some windows open, some closed
- `○` CLOSED — no windows open

If daemon is not running, falls back to database-only view with a warning.

---

## `cw create <name>`

Create a new Context. The currently focused iTerm window becomes its first member.

```bash
cw create MyProject
cw create MyProject -d "Frontend and backend development"
```

Options:
- `-d`, `--description TEXT` — optional description

---

## `cw join <name>`

Add a window to an existing Context. By default adds the current (focused) window. Use `--ref` to add a specific window by its reference number from `cw windows --all`.

```bash
cw join MyProject                    # Add current window
cw join MyProject --ref 3            # Add window #3 from `cw windows --all`
cw join MyProject -r 3 -w "Dev"      # Add window #3 and name it "Dev"
```

Options:
- `-w`, `--window-name TEXT` — name for this window within the Context (default: auto-generated)
- `-r`, `--ref INT` — window ref number from `cw windows --all`

---

## `cw open <name>[/<window>]`

Restore closed windows of a Context. Recreates windows with saved layout: tabs, panes, working directories, and geometry.

```bash
cw open MyProject                    # Restore all closed windows
cw open MyProject/Infrastructure     # Restore one specific window
```

What gets restored:
- Window position and size
- Tab structure
- Pane splits
- Working directories (via `cd`)

What does NOT auto-run:
- Previous commands (for safety). The last CWD is restored so you can restart manually.

---

## `cw close <name>[/<window>]`

Save the current state, then close windows in iTerm. Follows the **save-before-close** principle — if the save fails, the close is aborted and no windows are lost.

```bash
cw close MyProject                   # Save and close all windows
cw close MyProject/Infrastructure    # Close one specific window
```

The closed windows remain members of the Context (`is_member=true`, `is_open=false`) and can be restored with `cw open`.

---

## `cw save [<name>]`

Force an explicit snapshot of a Context's current state. Useful before major changes.

```bash
cw save MyProject     # Snapshot one Context
cw save               # Snapshot all Contexts
```

The daemon also saves state automatically on every layout change and periodically (every 30 seconds).

---

## `cw history <name>`

Show the state snapshot history for a Context. Reads directly from the database — daemon not required.

```bash
cw history MyProject
cw history MyProject -n 50      # Show more entries
```

Options:
- `-n`, `--limit INT` — number of entries to show (default: 20)

Output example:
```
History for 'MyProject' (newest first):

  TIMESTAMP                EVENT
  ──────────────────────────────────────────────────
  18:17:31                 manual_save
  18:14:02                 before_close
  18:07:12                 layout_change
  18:00:00                 context_created
```

---

## `cw windows [<name>]`

Show windows belonging to a Context, or browse all iTerm windows.

If no name is given, auto-detects the Context from the current window.

```bash
cw windows                           # Current Context (auto-detected)
cw windows MyProject                 # Specific Context
cw windows MyProject -v              # With tabs
cw windows MyProject -vv             # With tabs + panes + CWDs
cw windows --all                     # ALL iTerm windows (tracked + untracked)
cw windows --untracked               # Only windows NOT in any Context
```

Options:
- `-v`, `--verbose` — detail level: `-v` tabs, `-vv` tabs+panes+CWDs (stackable)
- `--all` — show ALL iTerm windows with Context membership info
- `--untracked` — show only windows not belonging to any Context

Output example (context mode):
```
MyProject

  ● Development          2 tab(s), 4 pane(s)
      ├── frontend ←
      │   ├── dev-server  [/home/user/frontend]
      │   └── git  [/home/user/frontend]
      ├── backend
      │   └── api  [/home/user/backend]
  ○ Production           1 tab(s), 1 pane(s)
```

Output example (`--all`):
```
REF   CONTEXT            WINDOW             ITERM TITLE               TABS  PANES
────────────────────────────────────────────────────────────────────────────────────
#1    ● MyProject        Development        dev-server                   3      5
#2    ● MyProject        Infrastructure     ssh                          1      2
#3    ○ —                —                  random-terminal              1      1
```

The ref numbers (#1, #2, ...) can be used with `cw join --ref` to add untracked windows to a Context.

---

## `cw focus <name>`

Jump to a Context window (bring it to front).

When only a Context name is given (no `/WindowName`), focuses the **last used window** in that context — not the first one. This is tracked automatically as you switch between windows.

```bash
cw focus MyProject                   # Last used window in MyProject
cw focus MyProject/Development       # Specific window
cw focus -                           # Jump back to previous Context
```

Use `cw focus -` to toggle between two Contexts (like `cd -` in the shell).

---

## `cw reload`

Reload the daemon's Python modules so code changes take effect without restarting iTerm2.

```bash
cw reload
```

If new source files were added (not just modified), the reload will warn that an iTerm restart is needed for those specific modules.

```
✓ Daemon reloaded (5 modules)
⚠ New modules detected (cw.export) — these require iTerm restart to load
```

---

## `cw status`

Check if the CW daemon is running.

```bash
cw status
```

Output when running:
```
✓ CW daemon is running.
  Database: /Users/you/.contextual-walker/cw.sqlite
  Socket:   /Users/you/.contextual-walker/cw.sock
```

---

## `cw backup`

Backup the CW database to a timestamped subfolder. Uses the SQLite backup API for a consistent copy (safe even while daemon is writing).

```bash
cw backup                                  # Use configured backup dir
cw backup --target ~/Documents/CW-Backups  # Override destination
```

Options:
- `-t`, `--target PATH` — backup directory (default: configured dir or `~/.contextual-walker/backups/`)

Each backup creates a timestamped folder:
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

The uninstall script calls `cw backup` automatically before removing anything.

---

## `cw config`

View or update CW configuration.

```bash
cw config --show                           # Show current config
cw config --backup-dir ~/Documents/Backups # Set backup directory
```

Options:
- `--show` — display current configuration
- `--backup-dir PATH` — set the default backup directory

Configuration is stored in `~/.contextual-walker/config.json`.

You can also set the backup directory during installation:
```bash
bash scripts/install.sh --backup-dir ~/Documents/CW-Backups
```

---

## `cw completion <shell>`

Output a shell completion script. Supports dynamic completion of Context and Window names.

```bash
cw completion bash >> ~/.bashrc
cw completion zsh  >> ~/.zshrc
cw completion fish > ~/.config/fish/completions/cw.fish
```

After sourcing, tab-completion works hierarchically:
```
cw <TAB>                        → list, create, open, close, ...
cw open <TAB>                   → MyProject, EcoColabo, ...
cw open MyProject/<TAB>         → Development, Infrastructure, ...
```

---

## `cw --version`

Show the installed version.

```bash
cw --version
```

---

## Man page

Man pages are automatically generated during `bash scripts/install.sh` (requires `help2man` — install with `brew install help2man`).

After installation: `man cw`, `man cw-list`, `man cw-open`, etc.

To regenerate manually:

```bash
help2man --no-info cw > man/cw.1
help2man --no-info "cw list" > man/cw-list.1
# etc.
cp man/cw*.1 ~/.local/share/man/man1/
```

---

## Uninstall

```bash
bash scripts/uninstall.sh
```

The uninstall script:
1. **Creates a backup first** (always, before any deletion)
2. Removes daemon from iTerm2 AutoLaunch
3. Removes man pages
4. Removes shell completion entries from shell config
5. Asks whether to delete `~/.contextual-walker/` (backups are preserved even if you say yes)
6. Asks whether to remove the `.venv` virtual environment
