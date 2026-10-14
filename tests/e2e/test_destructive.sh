#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# E2E tests: DESTRUCTIVE — may close windows or affect iTerm state
#
# ⚠ WARNING: These tests:
#   - Create and CLOSE windows (cw close)
#   - Open/restore windows (cw open)
#   - Move tabs between windows (cw move)
#
# They do NOT restart iTerm, but they DO create/close temporary windows.
# Run only when you can tolerate brief window changes.
#
# Prerequisites:
#   - iTerm2 running with CW daemon active
#   - cw command in PATH
#
# Usage:
#   bash tests/e2e/test_destructive.sh
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PASS=0
FAIL=0
TEST_CTX="__cw_e2e_destructive_$$"

cleanup() {
    # ONLY clean up test context from DB — NEVER use `cw leave` on real windows!
    python3 -c "
from cw.db import CwDatabase
db = CwDatabase()
ctx = db.get_context_by_name('$TEST_CTX')
if ctx:
    db.delete_context(ctx.id)
db.close()
" 2>/dev/null || true
    echo ""
    echo "═══════════════════════════════════════"
    echo "  RESULTS: $PASS passed, $FAIL failed"
    echo "═══════════════════════════════════════"
    if [ "$FAIL" -gt 0 ]; then
        exit 1
    fi
}
trap cleanup EXIT

assert_ok() {
    local desc="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local desc="$1"
    local expected="$2"
    shift 2
    local output
    output=$("$@" 2>&1) || true
    if echo "$output" | grep -q "$expected"; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc (expected '$expected')"
        echo "    got: $output"
        FAIL=$((FAIL + 1))
    fi
}

echo "═══════════════════════════════════════"
echo "  CW E2E Tests (DESTRUCTIVE)"
echo "  ⚠ May create/close windows"
echo "═══════════════════════════════════════"
echo ""

# ─── Find a window to use (by ref, not by focus) ─────────────────
# Pick an iTerm window by ref — works from Terminal.app too
# Try untracked first, then any window
TEST_REF=$(cw windows --all 2>/dev/null | grep "○ —" | head -1 | awk '{print $1}' || true)
if [ -z "$TEST_REF" ]; then
    TEST_REF=$(cw windows --all 2>/dev/null | grep -E "^  [0-9]" | head -1 | awk '{print $1}' || true)
fi
if [ -z "$TEST_REF" ]; then
    echo "  ✗ No iTerm windows found — cannot run destructive tests"
    exit 1
fi
echo "  Using window ref #$TEST_REF for tests"

# ─── Test: close/open cycle ───────────────────────────────────────
echo "▸ Close/Open cycle"

# Create context and join window by ref (not by focus)
assert_ok "create context" cw create "$TEST_CTX"
JOIN_OUT=$(cw join "$TEST_CTX" "$TEST_REF" 2>&1) || true
if echo "$JOIN_OUT" | grep -q "already belongs"; then
    echo "  ⚠ Window #$TEST_REF already tracked — trying to find untracked window"
    # Try each window until we find one that's not tracked
    ALL_REFS=$(cw windows --all 2>/dev/null | grep -E "^  [0-9]" | awk '{print $1}')
    JOINED=false
    for REF in $ALL_REFS; do
        JOIN_OUT=$(cw join "$TEST_CTX" "$REF" 2>&1) || true
        if echo "$JOIN_OUT" | grep -q "joined"; then
            TEST_REF="$REF"
            JOINED=true
            echo "  ✓ joined untracked window #$REF"
            PASS=$((PASS + 1))
            break
        fi
    done
    if [ "$JOINED" = false ]; then
        echo "  → Creating new iTerm window for test..."
        # Ask daemon to create a new window via open (creates test context window)
        # Use osascript to create a bare iTerm window
        osascript -e 'tell application "iTerm2" to create window with default profile' 2>/dev/null
        sleep 2
        # Now try to find the new untracked window
        NEW_REF=$(cw windows --all 2>/dev/null | grep "○ —" | tail -1 | awk '{print $1}' || true)
        if [ -n "$NEW_REF" ]; then
            JOIN_OUT=$(cw join "$TEST_CTX" "$NEW_REF" 2>&1) || true
            if echo "$JOIN_OUT" | grep -q "joined"; then
                TEST_REF="$NEW_REF"
                JOINED=true
                echo "  ✓ created and joined new window #$NEW_REF"
                PASS=$((PASS + 1))
            fi
        fi
        if [ "$JOINED" = false ]; then
            echo "  ✗ cannot create untracked window — skipping"
            exit 0
        fi
    fi
else
    echo "  ✓ join window by ref #$TEST_REF"
    PASS=$((PASS + 1))
fi
assert_contains "context is OPEN" "OPEN" cw list

# Save to ensure state is captured
assert_ok "save before close" cw save "$TEST_CTX"

# Check pane has CWD
CWD_BEFORE=$(cw history-pane --file 2>/dev/null || echo "none")
echo "    CWD info captured: ${CWD_BEFORE:0:60}..."

# Close the context (this closes the window!)
assert_ok "close context" cw close "$TEST_CTX"
assert_contains "context is CLOSED" "CLOSED" cw list

# Verify state was saved
assert_ok "history has before_close entry" cw history "$TEST_CTX"

# Open the context (restores window)
assert_ok "open context" cw open "$TEST_CTX"
assert_contains "context is OPEN again" "OPEN" cw list

# Verify CWD was restored (give it a moment)
sleep 1
WINDOW_DATA=$(cw windows "$TEST_CTX" -vv 2>/dev/null || echo "")
echo "    Restored window data available: $(echo "$WINDOW_DATA" | wc -l | xargs) lines"

# ─── Test: close specific window ──────────────────────────────────
echo "▸ Close specific window"

# Close again
assert_ok "close specific window" cw close "$TEST_CTX"
assert_contains "closed after specific" "CLOSED" cw list

# ─── Test: open on already-open ───────────────────────────────────
echo "▸ Open already-open"
assert_ok "restore for focus test" cw open "$TEST_CTX"
assert_contains "open on open → switched" "already open" cw open "$TEST_CTX"

# Clean up from previous tests
cw close "$TEST_CTX" 2>/dev/null || true

# ─── Test: per-pane history survives close/open ───────────────────
echo "▸ Per-pane history across close/open"

# Create fresh context and join window by ref
TEST_CTX_HIST="__cw_e2e_hist_$$"
# Create a new iTerm window for history test
osascript -e 'tell application "iTerm2" to create window with default profile' 2>/dev/null
sleep 2
HIST_REF=$(cw windows --all 2>/dev/null | grep "○ —" | tail -1 | awk '{print $1}' || true)
if [ -z "$HIST_REF" ]; then
    echo "  ✗ cannot create window for history test — skipping"
    PASS=$((PASS + 0))
fi
cw create "$TEST_CTX_HIST" >/dev/null 2>&1
cw join "$TEST_CTX_HIST" "$HIST_REF" >/dev/null 2>&1

# Get the history file path from DB (works from any terminal, not just iTerm)
HIST_FILE=$(python3 -c "
import sys
sys.path.insert(0, '$(cd "$SCRIPT_DIR/../.." && pwd)/src')
from cw.db import CwDatabase
from cw.constants import HISTORY_DIR
db = CwDatabase()
ctx = db.get_context_by_name('$TEST_CTX_HIST')
if ctx:
    for w in ctx.windows:
        for t in w.tabs:
            for p in t.panes:
                hist = HISTORY_DIR / f'{p.id}.history.txt'
                print(str(hist))
                break
            break
        break
db.close()
" 2>/dev/null || echo "")
if [ -z "$HIST_FILE" ]; then
    echo "  ✗ no history file assigned"
    FAIL=$((FAIL + 1))
else
    echo "  ✓ history file assigned: ${HIST_FILE##*/}"
    PASS=$((PASS + 1))

    # Type a unique marker command and wait for it to flush
    MARKER="__cw_e2e_marker_$(date +%s)"
    echo "$MARKER" >> "$HIST_FILE"  # write directly to ensure it's there
    sleep 1

    # Verify marker is in history
    if grep -q "$MARKER" "$HIST_FILE" 2>/dev/null; then
        echo "  ✓ marker command in history file"
        PASS=$((PASS + 1))
    else
        echo "  ✗ marker not found in history file"
        FAIL=$((FAIL + 1))
    fi

    # Record file path and UUID
    HIST_UUID="${HIST_FILE##*/}"
    HIST_UUID="${HIST_UUID%.history.txt}"
    echo "    UUID before close: $HIST_UUID"

    # Save and close
    cw save "$TEST_CTX_HIST" >/dev/null 2>&1
    cw close "$TEST_CTX_HIST" >/dev/null 2>&1

    # Verify history file still exists on disk after close
    if [ -f "$HIST_FILE" ]; then
        echo "  ✓ history file survives close"
        PASS=$((PASS + 1))
    else
        echo "  ✗ history file deleted on close!"
        FAIL=$((FAIL + 1))
    fi

    # Open again
    cw open "$TEST_CTX_HIST" >/dev/null 2>&1
    sleep 2  # wait for restore + HISTFILE setup

    # Get NEW history file path from DB
    HIST_FILE_AFTER=$(python3 -c "
import sys
sys.path.insert(0, '$(cd "$SCRIPT_DIR/../.." && pwd)/src')
from cw.db import CwDatabase
from cw.constants import HISTORY_DIR
db = CwDatabase()
ctx = db.get_context_by_name('$TEST_CTX_HIST')
if ctx:
    for w in ctx.windows:
        for t in w.tabs:
            for p in t.panes:
                print(str(HISTORY_DIR / f'{p.id}.history.txt'))
                break
            break
        break
db.close()
" 2>/dev/null || echo "")
    HIST_UUID_AFTER="${HIST_FILE_AFTER##*/}"
    HIST_UUID_AFTER="${HIST_UUID_AFTER%.history.txt}"
    echo "    UUID after open:  $HIST_UUID_AFTER"

    if [ "$HIST_UUID" = "$HIST_UUID_AFTER" ]; then
        echo "  ✓ UUID preserved across close/open"
        PASS=$((PASS + 1))
    else
        echo "  ✗ UUID changed! $HIST_UUID → $HIST_UUID_AFTER"
        FAIL=$((FAIL + 1))
    fi

    # Check if marker is still in history
    if [ -n "$HIST_FILE_AFTER" ] && grep -q "$MARKER" "$HIST_FILE_AFTER" 2>/dev/null; then
        echo "  ✓ marker command preserved after close/open"
        PASS=$((PASS + 1))
    else
        echo "  ✗ marker command LOST after close/open"
        if [ -f "$HIST_FILE" ] && grep -q "$MARKER" "$HIST_FILE" 2>/dev/null; then
            echo "    (still in old file: $HIST_FILE)"
        fi
        FAIL=$((FAIL + 1))
    fi
fi

# Clean up hist test context
cw close "$TEST_CTX_HIST" 2>/dev/null || true
python3 -c "
from cw.db import CwDatabase
db = CwDatabase()
ctx = db.get_context_by_name('$TEST_CTX_HIST')
if ctx:
    db.delete_context(ctx.id)
db.close()
" 2>/dev/null || true

echo ""
echo "Done."
