"""
CW global constants — file paths, defaults, and configuration values.

All CW data lives under ~/.contextual-walker/ to keep the home directory clean.
"""

from pathlib import Path

# ─── Base directory ─────────────────────────────────────────────────
CW_HOME = Path.home() / ".contextual-walker"

# ─── SQLite database ───────────────────────────────────────────────
DB_PATH = CW_HOME / "cw.sqlite"

# ─── Unix socket for CLI ↔ daemon communication ───────────────────
SOCKET_PATH = CW_HOME / "cw.sock"

# ─── Daemon log file ──────────────────────────────────────────────
DAEMON_LOG_PATH = CW_HOME / "daemon.log"

# ─── iTerm2 AutoLaunch directory for daemon installation ──────────
ITERM_SCRIPTS_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "iTerm2"
    / "Scripts"
    / "AutoLaunch"
)

# ─── iTerm2 user variable prefixes ────────────────────────────────
# These are set on iTerm objects so CW can re-identify them after restart.
ITERM_VAR_CONTEXT_ID = "user.cw_context_id"
ITERM_VAR_WINDOW_ID = "user.cw_window_id"
ITERM_VAR_TAB_ID = "user.cw_tab_id"
ITERM_VAR_SESSION_ID = "user.cw_session_id"

# ─── Periodic checkpoint interval (seconds) ───────────────────────
CHECKPOINT_INTERVAL_SECONDS = 30

# ─── Socket protocol ──────────────────────────────────────────────
SOCKET_BUFFER_SIZE = 65536
SOCKET_TIMEOUT_SECONDS = 10

# ─── Backup ───────────────────────────────────────────────────────
# Default backup directory. Can be overridden by config file.
DEFAULT_BACKUP_DIR = CW_HOME / "backups"

# Config file that stores user preferences (e.g. custom backup dir)
CONFIG_PATH = CW_HOME / "config.json"
