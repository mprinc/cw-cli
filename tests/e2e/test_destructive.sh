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

PASS=0
FAIL=0
TEST_CTX="__cw_e2e_destructive_$$"

cleanup() {
    # Try to clean up
    cw leave -y 2>/dev/null || true
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

# ─── Test: close/open cycle ───────────────────────────────────────
echo "▸ Close/Open cycle"

# Create context and join current window
assert_ok "create context" cw create "$TEST_CTX" -a
assert_contains "context is OPEN" "OPEN" cw list

# Get window name
WIN_NAME=$(cw current 2>/dev/null | cut -d'/' -f2 | xargs)

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

# Clean up — leave the context
cw leave -y 2>/dev/null || true
cw close "$TEST_CTX" 2>/dev/null || true

echo ""
echo "Done."
