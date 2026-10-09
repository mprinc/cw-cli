Synced with commit: 62cd0be

# Known Bugs & Fixes

## Fixed

### BUG-001: LayoutChangeMonitor never fires (CRITICAL)

**Discovered:** 2026-10-09  
**Fixed in:** `db8aa18`, `ea0fed4`, `c9e2559`, `16debe2`  
**Severity:** Critical — state loss on crash

**Symptom:** Database never captured layout changes (split pane, new tab, close pane). `cw windows -vv` showed stale data. If iTerm crashed, all changes since last explicit `cw save` were lost.

**Root cause:** `iterm2.LayoutChangeMonitor` class (async context manager style) never fires `async_get()` in AutoLaunch scripts. The monitor starts but `await monitor.async_get()` blocks forever without returning.

**Investigation:** Daemon log showed `LayoutChangeMonitor started` but zero `layout change` entries, ever. SessionTerminationMonitor and NewSessionMonitor worked fine. The periodic checkpoint relied on `_changes_pending` flag which was only set by monitors — so checkpoint also never ran.

**Fix (multi-layered):**
1. **Callback subscription** (`db8aa18`): Replaced `LayoutChangeMonitor` class with `async_subscribe_to_layout_change_notification()` callback style — same iTerm2 API but different invocation mechanism. This **works**.
2. **FocusMonitor** (`ea0fed4`): Added `iterm2.FocusMonitor` which fires on every tab/pane/window focus change. Syncs the focused window's state immediately.
3. **Unconditional checkpoint** (`c9e2559`): Checkpoint now always syncs every interval, not only when `_changes_pending` is set. Safety net if all monitors fail.
4. **5-second interval** (`16debe2`): Reduced checkpoint from 30s to 5s. Async + WAL mode makes this cheap.
5. **Smart dedup** (`cb047ac`): Checkpoint skips if a monitor already synced within the last 4 seconds, avoiding duplicate work.

**Verification:** After iTerm restart, daemon log shows:
- `Layout change detected (callback)` — on every split/close/tab create
- `FocusMonitor started` — active
- `Checkpoint: synced N window(s)` — every 5s when no monitor synced recently

**Lesson:** Never rely on a single event mechanism. Multiple independent sync paths (callback + focus + checkpoint) provide defense in depth.

---

### BUG-002: `cw windows -vv` shows stale DB data

**Discovered:** 2026-10-09  
**Fixed in:** `f585898`  
**Severity:** Medium — misleading display

**Symptom:** `cw windows -vv` showed fewer panes than actually exist, missing newly split panes.

**Root cause:** CLI read from SQLite database, which could be seconds behind live iTerm state (especially before BUG-001 was fixed).

**Fix:** `cw windows` now reads live iTerm state via daemon (`windows_live` command) instead of DB. As a side effect, the live state is also persisted to DB, keeping it fresh.

---

### BUG-003: Tab titles not read correctly

**Discovered:** 2026-10-09  
**Fixed in:** `3d1789f`  
**Severity:** Low — cosmetic

**Symptom:** Tab titles showed as `(tab 0)`, `(tab 1)` even when tabs had visible names in iTerm.

**Root cause:** Code read `titleOverride` variable which is only set when user manually renames a tab. Most tabs use auto-generated titles from session names.

**Fix:** Read tab title with fallback chain: `titleOverride` → `title` → first session's `autoName`.

---

## Open

(none currently)
