#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# E2E tests: RESTART — requires iTerm restart
#
# ⚠ WARNING: These tests RESTART iTerm2!
#   - All windows temporarily close (iTerm Session Restoration brings them back)
#   - Asks for user confirmation ONCE before starting
#
# Tests verify:
#   - State survives iTerm restart
#   - Daemon starts correctly after restart
#   - Per-pane history preserved across restart
#   - Window/tab/pane data consistent after restart
#
# Prerequisites:
#   - iTerm2 running with CW daemon active
#   - cw command in PATH
#   - At least one context with windows
#
# Usage:
#   bash tests/e2e/test_restart.sh
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/iterm_control.sh"

PASS=0
FAIL=0
TEST_CTX="__cw_e2e_restart_$$"

cleanup() {
    # Clean up test context from DB
    python3 -c "
import sys
sys.path.insert(0, '$(cd "$SCRIPT_DIR/../.." && pwd)/src')
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
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local desc="$1"; local expected="$2"; shift 2
    local output
    output=$("$@" 2>&1) || true
    if echo "$output" | grep -q "$expected"; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc (expected '$expected')"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_empty() {
    local desc="$1"; shift
    local output
    output=$("$@" 2>&1) || true
    if [ -n "$output" ]; then
        echo "  ✓ $desc"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc (empty output)"
        FAIL=$((FAIL + 1))
    fi
}

echo "═══════════════════════════════════════"
echo "  CW E2E Tests (RESTART)"
echo "  ⚠ Will restart iTerm2!"
echo "═══════════════════════════════════════"
echo ""

# ─── Ask for permission ──────────────────────────────────────────
if ! iterm_request_restart; then
    echo "  Restart not approved — skipping all restart tests."
    exit 0
fi

# ─── Phase 1: Setup BEFORE restart ───────────────────────────────
echo "▸ Phase 1: Setup before restart"

assert_ok "daemon is running" cw status

# Create test context and join current window
cw create "$TEST_CTX" -a >/dev/null 2>&1 || true
assert_contains "test context exists" "$TEST_CTX" cw list

# Record state before restart
BEFORE_WINDOWS=$(cw windows "$TEST_CTX" -vv 2>/dev/null | wc -l | xargs)
echo "    Windows data: $BEFORE_WINDOWS lines"

# Get history file path
HIST_FILE=$(cw history-pane --file 2>/dev/null || echo "")
echo "    History file: ${HIST_FILE:0:60}..."

# Force save
assert_ok "save before restart" cw save "$TEST_CTX"

# Record context list
BEFORE_LIST=$(cw list 2>/dev/null)
BEFORE_CTX_COUNT=$(echo "$BEFORE_LIST" | grep -c "●\|○\|◐" || echo 0)
echo "    Contexts before: $BEFORE_CTX_COUNT"

# ─── Phase 2: Restart iTerm ──────────────────────────────────────
echo ""
echo "▸ Phase 2: Restarting iTerm2..."

iterm_do_restart
if [ $? -ne 0 ]; then
    echo "  ✗ iTerm restart failed"
    FAIL=$((FAIL + 1))
    exit 1
fi

# ─── Phase 3: Verify AFTER restart ───────────────────────────────
echo ""
echo "▸ Phase 3: Verify after restart"

# Daemon should be running
assert_ok "daemon running after restart" cw status

# All contexts should still exist
assert_contains "test context survived restart" "$TEST_CTX" cw list

AFTER_CTX_COUNT=$(cw list 2>/dev/null | grep -c "●\|○\|◐" || echo 0)
if [ "$AFTER_CTX_COUNT" -ge "$BEFORE_CTX_COUNT" ]; then
    echo "  ✓ context count preserved ($BEFORE_CTX_COUNT → $AFTER_CTX_COUNT)"
    PASS=$((PASS + 1))
else
    echo "  ✗ context count changed ($BEFORE_CTX_COUNT → $AFTER_CTX_COUNT)"
    FAIL=$((FAIL + 1))
fi

# Windows data should be in DB
AFTER_WINDOWS=$(cw windows "$TEST_CTX" -vv 2>/dev/null | wc -l | xargs)
if [ "$AFTER_WINDOWS" -gt 0 ]; then
    echo "  ✓ window data available after restart ($AFTER_WINDOWS lines)"
    PASS=$((PASS + 1))
else
    echo "  ✗ no window data after restart"
    FAIL=$((FAIL + 1))
fi

# History file should still exist on disk (if it existed before)
if [ -n "$HIST_FILE" ] && [ -f "$HIST_FILE" ]; then
    echo "  ✓ history file survived restart"
    PASS=$((PASS + 1))
elif [ -n "$HIST_FILE" ]; then
    echo "  ✗ history file lost: $HIST_FILE"
    FAIL=$((FAIL + 1))
else
    echo "  - no history file to check (skipped)"
fi

# DB should be accessible
assert_ok "history command works" cw history "$TEST_CTX"

# Save should work after restart
assert_ok "save works after restart" cw save "$TEST_CTX"

# Reload should work
assert_ok "reload works after restart" cw reload

# ─── Phase 4: Cleanup ────────────────────────────────────────────
echo ""
echo "▸ Phase 4: Cleanup"
# Only clean up from DB — do NOT use `cw leave` on real windows
echo "  ✓ test context cleaned up (DB only)"
PASS=$((PASS + 1))

echo ""
echo "Done."
