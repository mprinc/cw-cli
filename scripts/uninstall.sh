#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# CW Uninstall Script — safely removes Contextual-Walker.
#
# What this script does:
#   1. Runs a backup FIRST (safety net before any deletion)
#   2. Removes the daemon from iTerm2 AutoLaunch
#   3. Removes man pages
#   4. Removes shell completion from shell config
#   5. Optionally removes ~/.contextual-walker/ (asks first)
#   6. Optionally removes the virtual environment
#
# The backup is ALWAYS created before anything is deleted.
#
# Usage:
#   bash scripts/uninstall.sh
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
CW_HOME="$HOME/.contextual-walker"
ITERM_AUTOLAUNCH="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch"
DAEMON_WRAPPER="$ITERM_AUTOLAUNCH/cw_daemon.py"
LOCAL_MAN="/usr/local/share/man/man1"

echo "╔══════════════════════════════════════════════════╗"
echo "║       Contextual-Walker — Uninstall              ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ─── Step 1: Backup FIRST ─────────────────────────────────────────
echo "→ Step 1/5: Creating backup before uninstall ..."
if [ -f "$CW_HOME/cw.sqlite" ]; then
    # Try using CW's own backup command
    if [ -f "$VENV_DIR/bin/cw" ]; then
        source "$VENV_DIR/bin/activate" 2>/dev/null || true
        BACKUP_DIR="${CW_HOME}/backups/pre-uninstall_$(date +%Y-%m-%d_%H-%M-%S)"
        cw backup --target "$BACKUP_DIR" 2>/dev/null && {
            echo "  ✓ Backup created at: $BACKUP_DIR"
        } || {
            # Fallback: manual copy
            mkdir -p "$BACKUP_DIR"
            cp "$CW_HOME/cw.sqlite" "$BACKUP_DIR/"
            [ -f "$CW_HOME/config.json" ] && cp "$CW_HOME/config.json" "$BACKUP_DIR/"
            [ -f "$CW_HOME/daemon.log" ] && cp "$CW_HOME/daemon.log" "$BACKUP_DIR/"
            echo "  ✓ Backup created at: $BACKUP_DIR (manual copy)"
        }
    else
        # No venv — manual copy
        BACKUP_DIR="${CW_HOME}/backups/pre-uninstall_$(date +%Y-%m-%d_%H-%M-%S)"
        mkdir -p "$BACKUP_DIR"
        cp "$CW_HOME/cw.sqlite" "$BACKUP_DIR/"
        [ -f "$CW_HOME/config.json" ] && cp "$CW_HOME/config.json" "$BACKUP_DIR/"
        [ -f "$CW_HOME/daemon.log" ] && cp "$CW_HOME/daemon.log" "$BACKUP_DIR/"
        echo "  ✓ Backup created at: $BACKUP_DIR (manual copy)"
    fi
else
    echo "  — No database found, skipping backup"
fi

# ─── Step 2: Remove `cw` from PATH ───────────────────────────────
echo ""
echo "→ Step 2/6: Removing 'cw' from PATH ..."
CW_SYMLINK="/usr/local/bin/cw"
if [ -L "$CW_SYMLINK" ]; then
    rm "$CW_SYMLINK" 2>/dev/null || sudo rm "$CW_SYMLINK" 2>/dev/null || true
    echo "  ✓ Removed symlink: $CW_SYMLINK"
else
    echo "  — No symlink found"
fi

# Remove PATH line from shell config if present
for RC_FILE in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile"; do
    if [ -f "$RC_FILE" ] && grep -q "# CW (Contextual-Walker)" "$RC_FILE" 2>/dev/null; then
        sed -i '' '/# CW (Contextual-Walker)/d' "$RC_FILE" 2>/dev/null || true
        echo "  ✓ Removed PATH entry from $RC_FILE"
    fi
done

# ─── Step 3: Remove daemon from iTerm2 ────────────────────────────
echo ""
echo "→ Step 3/6: Removing daemon from iTerm2 ..."
if [ -f "$DAEMON_WRAPPER" ]; then
    rm "$DAEMON_WRAPPER"
    echo "  ✓ Removed: $DAEMON_WRAPPER"
else
    echo "  — Daemon not found (already removed)"
fi

# ─── Step 3: Remove man pages ─────────────────────────────────────
echo ""
echo "→ Step 4/6: Removing man pages ..."
MAN_REMOVED=false
for manfile in "$LOCAL_MAN"/cw*.1 "$PROJECT_DIR"/man/cw*.1; do
    if [ -f "$manfile" ]; then
        rm "$manfile" 2>/dev/null || sudo rm "$manfile" 2>/dev/null || true
        MAN_REMOVED=true
    fi
done
if [ "$MAN_REMOVED" = true ]; then
    echo "  ✓ Man pages removed"
else
    echo "  — No man pages found"
fi

# ─── Step 4: Remove shell completion ──────────────────────────────
echo ""
echo "→ Step 5/6: Removing shell completion ..."
COMPLETION_REMOVED=false

# Remove from .zshrc
if [ -f "$HOME/.zshrc" ] && grep -q "# CW zsh completion" "$HOME/.zshrc" 2>/dev/null; then
    # Remove the comment line and the eval line after it
    sed -i '' '/# CW zsh completion/,+1d' "$HOME/.zshrc" 2>/dev/null || true
    COMPLETION_REMOVED=true
    echo "  ✓ Removed from ~/.zshrc"
fi

# Remove from .bashrc
if [ -f "$HOME/.bashrc" ] && grep -q "# CW bash completion" "$HOME/.bashrc" 2>/dev/null; then
    sed -i '' '/# CW bash completion/,+1d' "$HOME/.bashrc" 2>/dev/null || true
    COMPLETION_REMOVED=true
    echo "  ✓ Removed from ~/.bashrc"
fi

# Remove fish completion
FISH_COMPLETION="$HOME/.config/fish/completions/cw.fish"
if [ -f "$FISH_COMPLETION" ]; then
    rm "$FISH_COMPLETION"
    COMPLETION_REMOVED=true
    echo "  ✓ Removed fish completion"
fi

if [ "$COMPLETION_REMOVED" = false ]; then
    echo "  — No shell completions found"
fi

# ─── Step 5: Remove CW data and socket ────────────────────────────
echo ""
echo "→ Step 6/6: CW data directory ..."

# Remove socket (always safe)
[ -S "$CW_HOME/cw.sock" ] && rm "$CW_HOME/cw.sock"

echo ""
echo "  The CW data directory contains your database and backups:"
echo "    $CW_HOME"
echo ""
read -p "  Delete it? Your backup is safe at: $BACKUP_DIR [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Move backups out first, then delete, then put backups back
    if [ -d "$CW_HOME/backups" ]; then
        TEMP_BACKUP="/tmp/cw-backups-$$"
        mv "$CW_HOME/backups" "$TEMP_BACKUP"
        rm -rf "$CW_HOME"
        mkdir -p "$CW_HOME"
        mv "$TEMP_BACKUP" "$CW_HOME/backups"
        echo "  ✓ Data deleted (backups preserved at $CW_HOME/backups/)"
    else
        rm -rf "$CW_HOME"
        echo "  ✓ Data deleted"
    fi
else
    echo "  — Kept: $CW_HOME"
fi

# ─── Optional: Remove venv ────────────────────────────────────────
echo ""
if [ -d "$VENV_DIR" ]; then
    read -p "  Remove virtual environment ($VENV_DIR)? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_DIR"
        echo "  ✓ Virtual environment removed"
    else
        echo "  — Kept: $VENV_DIR"
    fi
fi

# ─── Summary ──────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║             Uninstall complete                    ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "What was removed:"
echo "  ✓ iTerm2 daemon"
echo "  ✓ Man pages"
echo "  ✓ Shell completions"
echo ""
if [ -d "$CW_HOME/backups" ]; then
    echo "Your backups are preserved at:"
    echo "  $CW_HOME/backups/"
    echo ""
fi
echo "Restart iTerm2 to complete the removal."
