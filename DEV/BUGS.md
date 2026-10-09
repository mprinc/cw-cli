Synced with commit: 8ae6d0c

# Known Bugs & Fixes

States: `NEW` → `UNDERSTOOD` → `IN-PROGRESS` → `SOLVED`

---

## BUG-001: LayoutChangeMonitor never fires

**Status:** SOLVED  
**Discovered:** 2026-10-09  
**Severity:** Critical — state loss on crash  
**Fixed in:** `db8aa18`, `ea0fed4`, `c9e2559`, `16debe2`, `cb047ac`

**Reproduction:** Split a pane, wait 30+ seconds, run `cw windows -vv` — new pane not shown. Check `daemon.log` — no `layout change` entries ever.

**Problem:** `iterm2.LayoutChangeMonitor` class (async context manager with `async_get()`) never fires in AutoLaunch scripts. The monitor starts but blocks forever.

**Root cause:** iTerm2 Python API `LayoutChangeMonitor` uses async context manager pattern that doesn't receive notifications in `run_forever` AutoLaunch context. The callback subscription API (`async_subscribe_to_layout_change_notification`) uses the same underlying notification type but a different invocation mechanism that works.

**Fix (multi-layered defense):**
1. **Callback subscription** (`db8aa18`): `async_subscribe_to_layout_change_notification()` — works
2. **FocusMonitor** (`ea0fed4`): syncs on every tab/pane/window focus change
3. **Unconditional checkpoint** (`c9e2559`): always syncs, not only on `_changes_pending`
4. **5-second interval** (`16debe2`): max 5s data loss on crash
5. **Smart dedup** (`cb047ac`): skips checkpoint if monitor synced recently

**Verification:** `tail -f ~/.contextual-walker/daemon.log | grep layout` shows `Layout change detected (callback)` on every split/close/tab create.

---

## BUG-002: `cw windows -vv` shows stale DB data

**Status:** SOLVED  
**Discovered:** 2026-10-09  
**Severity:** Medium — misleading display  
**Fixed in:** `f585898`

**Reproduction:** Split a pane, immediately run `cw windows -vv` — shows old pane count.

**Problem:** CLI read from SQLite which lags behind live state (especially before BUG-001 fix).

**Fix:** `cw windows` now reads live iTerm state via daemon (`windows_live` command). Side effect: persists to DB, keeping it fresh.

---

## BUG-003: Tab titles not read correctly

**Status:** SOLVED  
**Discovered:** 2026-10-09  
**Severity:** Low — cosmetic  
**Fixed in:** `3d1789f`

**Reproduction:** Tab has a visible name in iTerm (from session name), but `cw windows -vv` shows `(tab 0)`.

**Problem:** Code read `titleOverride` which is only set on manual rename. Auto-generated tab titles use different variables.

**Fix:** Fallback chain: `titleOverride` → `title` → first session `autoName`.

---

## BUG-004: `cw move` to existing window crashes

**Status:** SOLVED  
**Discovered:** 2026-10-09  
**Severity:** High — command fails  
**Fixed in:** `b9afeec`

**Reproduction:** `cw move Context/ExistingWindow` — error about `iterm2.move_tab_to_window` function signature.

**Problem:** Used `Tab.async_invoke_function('iterm2.move_tab_to_window(window_id: ...)')` which doesn't exist as a scripting function.

**Fix:** Use `Window.async_set_tabs()` to append current tab to target window's tab list. This API supports cross-window tab moves.

---

## BUG-005: `cw move` to new window doesn't move tab

**Status:** SOLVED  
**Discovered:** 2026-10-09  
**Severity:** High — command fails  
**Fixed in:** `b86d445`, `4c63256`

**Reproduction:** `cw move Context/NewWindow` — creates empty new window, tab stays in original.

**Problem:** `Tab.async_move_to_window()` takes NO arguments (creates new window from tab). Code was passing target window as argument.

**Fix:** Call `async_move_to_window()` without arguments for new window case. Handle single-tab windows by re-registering instead of moving.

---

## BUG-006: Window title not set after `cw move`

**Status:** SOLVED  
**Discovered:** 2026-10-09  
**Severity:** Low — cosmetic  
**Fixed in:** `26cca63`

**Reproduction:** After `cw move`, new window shows tab name instead of `Context / Window`.

**Problem:** `async_set_title()` called too early — iTerm overwrites it with its own title during window creation.

**Fix:** Add 0.5s delay, refresh app reference, then set title.

---

## Open

(none currently)
