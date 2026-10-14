Synced with commit: dbf35d5

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

### BUG-007: UNIQUE constraint failed: tabs.id on join/save

**Status:** SOLVED  
**Discovered:** 2026-10-13  
**Severity:** High — blocks join and save for already-tracked windows

**Reproduction:** `cw join OtherContext` when current window is already in a context, or `cw save` on some contexts. Error: `UNIQUE constraint failed: tabs.id`

**Problem:** `sync_window_layout` reuses existing tab UUIDs (from id_mappings) to preserve history file stability. But the same tab UUID can exist in the `tabs` table for a DIFFERENT window (from a previous sync of another context's window). `DELETE FROM tabs WHERE window_id = ?` only deletes tabs for the current window — the duplicate UUID in another window survives, causing INSERT to fail.

**Root cause analysis in progress:**
- `INSERT OR REPLACE` was added but daemon may not have picked it up via `cw reload`
- `cw reload` reloads Python modules but existing `CwDatabase` instance methods should update (methods are on class, not instance) — needs verification
- The fundamental issue: tab/pane UUID reuse across different CW windows when the same iTerm tab is mapped in multiple contexts

**Potential fixes:**
1. `INSERT OR REPLACE INTO tabs` — replaces existing row (may orphan panes in old window via CASCADE)
2. Delete tab from ALL windows before inserting (not just current window_id)
3. Don't reuse tab UUIDs — only reuse pane (session) UUIDs which are what matters for history files

---

### BUG-008: `cw reload` doesn't update all daemon code paths

**Status:** IN-PROGRESS  
**Discovered:** 2026-10-09 — 2026-10-13 (recurring)  
**Severity:** Medium — requires iTerm restart for some changes

**Reproduction:** Change daemon code, run `cw reload`, new code not active for some operations.

**Problem:** `importlib.reload` updates module-level function definitions, but:

1. **Socket handler closure** (fixed in `b89ab57`): `_handle_client` was a closure in `_socket_server` coroutine. After reload, the running coroutine still referenced old functions. Fixed by using `getattr(_self_module, '_dispatch_command')` for dynamic lookup.

4. **Database instance class** (fix pending): `importlib.reload` creates a NEW class object. Existing `database` instance keeps the OLD class — its methods are NOT updated. Fix: `database.__class__ = cw.db.CwDatabase` after reload. This was the root cause of `cw reload` not picking up db.py changes (e.g. INSERT OR REPLACE).

2. **Running coroutines**: Monitor coroutines (`_monitor_layout_changes`, `_periodic_checkpoint`, `_monitor_focus_changes`) are started at daemon startup via `asyncio.gather`. Reload changes the function definition but the RUNNING coroutine continues with old code. New sessions monitor behavior, checkpoint intervals, etc. require iTerm restart.

3. **Module-level state**: `_last_focused_context`, `_last_focused_window_per_context`, `_last_sync_time` are reset on reload, losing focus tracking state.

**Lesson:** `cw reload` is useful for command handler changes (join, open, close, etc.) but NOT for changes to:
- Monitor coroutines (layout, focus, session, checkpoint)
- Module-level state
- Database schema or `init_schema`
- `_set_pane_histfile` or `_ensure_all_sessions_have_histfile` (startup-only)

For these, iTerm restart is required.

---

### BUG-009: Per-pane HISTFILE UUID instability

**Status:** SOLVED  
**Discovered:** 2026-10-13  
**Severity:** High — history lost across close/open cycles

**Reproduction:** 
1. `cw join` assigns UUID `A` to pane, sets `HISTFILE=A.history.txt`
2. User types commands → saved in `A.history.txt`
3. `cw close` → saves state
4. `cw open` → creates new iTerm session with new ID
5. Problem: `sync_window_layout` generated NEW UUID `B` → `HISTFILE=B.history.txt` → old history in `A` orphaned

**Root cause:** `sync_window_layout` deleted all tabs/panes and recreated with new UUIDs every time. Fixed in `9956a66` to reuse existing UUIDs by checking `id_mappings` first.

**Additional fix needed:** Pre-create mappings (OLD_UUID → NEW_SESSION_ID) in `_cmd_open` BEFORE calling `sync_window_layout`, so sync finds existing mapping and reuses old UUID. Fixed in `7ff4d66`.

**Final fix:** `set_mapping` now deactivates by BOTH `cw_id` AND `iterm_id` (`57b7709`). This prevents NewSessionMonitor from stealing the UUID during restore. E2e test `test_destructive.sh` verifies marker command preserved across close/open.

**Verification:** Unit tests `test_sync_preserves_existing_pane_uuids` and `test_sync_preserves_uuid_after_pre_mapping` pass.
