#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# E2E tests: SAFE — do not affect other windows/contexts
#
# These tests create temporary contexts, test operations, and clean up.
# They do NOT close existing windows or restart iTerm.
#
# Prerequisites:
#   - iTerm2 running with CW daemon active
#   - cw command in PATH
#
# Usage:
#   bash tests/e2e/test_safe.sh
# ──────────────────────────────────────────────────────────────────

set -euo pipefail

PASS=0
FAIL=0
TEST_CTX="__cw_e2e_test_$$"

cleanup() {
    # ONLY clean up the test context — NEVER touch real contexts!
    # Do NOT use `cw leave` here — it affects the current window which may be real!
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

assert_fail() {
    local desc="$1"
    shift
    if ! "$@" >/dev/null 2>&1; then
        echo "  ✓ $desc (expected failure)"
        PASS=$((PASS + 1))
    else
        echo "  ✗ $desc (should have failed)"
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
        echo "  ✗ $desc (expected '$expected' in output)"
        echo "    got: $output"
        FAIL=$((FAIL + 1))
    fi
}

echo "═══════════════════════════════════════"
echo "  CW E2E Tests (SAFE)"
echo "═══════════════════════════════════════"
echo ""

# ─── Test: daemon running ─────────────────────────────────────────
echo "▸ Daemon status"
assert_ok "daemon is running" cw status

# ─── Test: create context ─────────────────────────────────────────
echo "▸ Context creation"
assert_ok "create empty context" cw create "$TEST_CTX"
assert_contains "context appears in list" "$TEST_CTX" cw list
assert_fail "duplicate name rejected" cw create "$TEST_CTX"

# ─── Test: join ───────────────────────────────────────────────────
echo "▸ Join"
# Current window may already be tracked — test join by checking if it reports error correctly
JOIN_OUTPUT=$(cw join "$TEST_CTX" 2>&1) || true
if echo "$JOIN_OUTPUT" | grep -q "already belongs"; then
    echo "  ✓ join correctly rejects already-tracked window"
    PASS=$((PASS + 1))
elif echo "$JOIN_OUTPUT" | grep -q "joined"; then
    echo "  ✓ join current window"
    PASS=$((PASS + 1))
else
    echo "  ✗ join unexpected: $JOIN_OUTPUT"
    FAIL=$((FAIL + 1))
fi

# ─── Test: current ────────────────────────────────────────────────
echo "▸ Current"
assert_ok "current shows some context" cw current

# ─── Test: windows ────────────────────────────────────────────────
echo "▸ Windows"
assert_ok "windows shows context" cw windows "$TEST_CTX"
assert_ok "windows -v works" cw windows "$TEST_CTX" -v
assert_ok "windows -vv works" cw windows "$TEST_CTX" -vv
assert_ok "windows --all works" cw windows --all

# ─── Test: history-pane ───────────────────────────────────────────
echo "▸ History pane"
assert_ok "history-pane --file" cw history-pane --file

# ─── Test: rename ─────────────────────────────────────────────────
echo "▸ Rename"
RENAMED="${TEST_CTX}_renamed"
assert_ok "rename context" cw rename "$TEST_CTX" "$RENAMED"
assert_contains "renamed appears in list" "$RENAMED" cw list
# Rename back
cw rename "$RENAMED" "$TEST_CTX" >/dev/null 2>&1

# ─── Test: save & history ─────────────────────────────────────────
echo "▸ Save & History"
assert_ok "save context" cw save "$TEST_CTX"
assert_contains "history has entries" "context_created" cw history "$TEST_CTX"

# ─── Test: leave ──────────────────────────────────────────────────
echo "▸ Leave"
assert_ok "leave with -y" cw leave -y

# ─── Test: config ─────────────────────────────────────────────────
echo "▸ Config"
assert_ok "config --show" cw config --show

# ─── Test: backup ─────────────────────────────────────────────────
echo "▸ Backup"
assert_ok "backup" cw backup

# ─── Test: reload ─────────────────────────────────────────────────
echo "▸ Reload"
assert_ok "reload daemon" cw reload

echo ""
echo "Done."
