#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────
# iTerm2 control module for e2e tests.
#
# Provides functions to restart iTerm safely with user confirmation.
# Asks ONCE per test suite run, not per individual test.
#
# Usage:
#   source tests/e2e/iterm_control.sh
#   iterm_request_restart   # asks user, remembers answer
#   iterm_do_restart        # actually restarts (only if approved)
#   iterm_wait_ready        # waits until daemon is responsive
# ──────────────────────────────────────────────────────────────────

# State: has the user approved iTerm restart for this session?
_ITERM_RESTART_APPROVED=""

iterm_request_restart() {
    # Only ask once per suite run
    if [ -n "$_ITERM_RESTART_APPROVED" ]; then
        return 0
    fi

    echo ""
    echo "╔══════════════════════════════════════════════════════════╗"
    echo "║  ⚠  iTerm2 RESTART required for next tests             ║"
    echo "║                                                         ║"
    echo "║  This will:                                             ║"
    echo "║    - Quit iTerm2                                        ║"
    echo "║    - Wait 3 seconds                                     ║"
    echo "║    - Reopen iTerm2                                      ║"
    echo "║    - Wait for CW daemon to start                       ║"
    echo "║                                                         ║"
    echo "║  All your windows will be restored by iTerm2's          ║"
    echo "║  Session Restoration.                                   ║"
    echo "╚══════════════════════════════════════════════════════════╝"
    echo ""
    read -p "  Proceed with iTerm restart? [y/N] " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        _ITERM_RESTART_APPROVED="yes"
        return 0
    else
        _ITERM_RESTART_APPROVED="no"
        return 1
    fi
}

iterm_is_approved() {
    [ "$_ITERM_RESTART_APPROVED" = "yes" ]
}

iterm_do_restart() {
    if ! iterm_is_approved; then
        echo "  ⚠ iTerm restart not approved — skipping"
        return 1
    fi

    echo "  → Quitting iTerm2..."
    osascript -e 'tell application "iTerm2" to quit' 2>/dev/null || true

    echo "  → Waiting 3 seconds..."
    sleep 3

    echo "  → Opening iTerm2..."
    open -a iTerm

    echo "  → Waiting for iTerm2 to start..."
    sleep 5

    # Wait for daemon socket to appear
    iterm_wait_ready
}

iterm_wait_ready() {
    echo "  → Waiting for CW daemon..."
    local attempts=0
    local max_attempts=20
    while [ $attempts -lt $max_attempts ]; do
        if cw status >/dev/null 2>&1; then
            echo "  ✓ CW daemon is ready"
            return 0
        fi
        sleep 1
        attempts=$((attempts + 1))
    done
    echo "  ✗ CW daemon not ready after ${max_attempts}s"
    return 1
}
