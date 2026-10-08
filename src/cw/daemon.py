"""
CW Daemon — long-running iTerm2 script that continuously watches
terminal state and persists it to SQLite.

This script is designed to run as an iTerm2 AutoLaunch script:
    ~/Library/Application Support/iTerm2/Scripts/AutoLaunch/cw_daemon.py

Architecture:
    1. Connects to iTerm2 via Python API
    2. Runs initial reconciliation (catch up on missed changes)
    3. Starts three concurrent monitors (layout, session termination, new session)
    4. Runs a Unix socket server for CLI commands
    5. Runs periodic checkpoints

CRITICAL SAFETY RULE:
    Every event handler is wrapped in try/except. If CW crashes,
    iTerm must continue working normally. CW is a parasite that
    observes — it must never break the host.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import iterm2

from cw.constants import (
    CHECKPOINT_INTERVAL_SECONDS,
    CW_HOME,
    DAEMON_LOG_PATH,
    ITERM_VAR_CONTEXT_ID,
    ITERM_VAR_WINDOW_ID,
    SOCKET_BUFFER_SIZE,
    SOCKET_PATH,
)
from cw.db import CwDatabase
from cw.reconciler import (
    get_live_status,
    read_iterm_window_state,
    reconcile,
)

# ─── Logging setup ─────────────────────────────────────────────────

CW_HOME.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=str(DAEMON_LOG_PATH),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cw.daemon")


# ─── Global state ──────────────────────────────────────────────────

# Flag to trigger checkpoint on next interval (set by event handlers)
_changes_pending = False


def _mark_dirty():
    """Signal that a change happened and checkpoint should save state."""
    global _changes_pending
    _changes_pending = True


# ─── Main entry point ─────────────────────────────────────────────

async def main(connection: iterm2.Connection) -> None:
    """
    Main daemon coroutine. Called by iterm2.run_forever().

    Sets up the database, runs reconciliation, then starts all
    monitors and the socket server concurrently.

    @param connection: iTerm2 API connection object.
    """
    logger.info("CW daemon starting")

    # Initialize database
    database = CwDatabase()
    database.init_schema()
    logger.info("Database ready at %s", database.db_path)

    # Get the iTerm App singleton
    app = await iterm2.async_get_app(connection)

    # Run initial reconciliation to catch up on anything missed
    try:
        result = await reconcile(app, database)
        logger.info("Initial reconciliation: %s", result)
    except Exception:
        logger.exception("Initial reconciliation failed — continuing anyway")

    # Start all concurrent tasks
    await asyncio.gather(
        _monitor_layout_changes(connection, app, database),
        _monitor_session_termination(connection, app, database),
        _monitor_new_sessions(connection, app, database),
        _periodic_checkpoint(app, database),
        _socket_server(app, database),
    )


# ─── Layout change monitor ────────────────────────────────────────

async def _monitor_layout_changes(
    connection: iterm2.Connection,
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Watch for layout changes (tabs moved, panes split/closed, windows resized).

    On each change, re-read the affected window's state and persist it.
    """
    try:
        async with iterm2.LayoutChangeMonitor(connection) as monitor:
            logger.info("LayoutChangeMonitor started")
            while True:
                await monitor.async_get()
                try:
                    await _handle_layout_change(app, database)
                except Exception:
                    logger.exception("Error handling layout change")
    except Exception:
        logger.exception("LayoutChangeMonitor crashed — will not restart")


async def _handle_layout_change(
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Called when iTerm layout changes. Re-reads all tracked windows
    and updates their layout in the database.

    @param app: iTerm2 App singleton.
    @param database: CW database instance.
    """
    # Track which window is currently focused (for "cw focus" last-used logic)
    current_iterm_window = app.current_terminal_window
    if current_iterm_window:
        current_cw_id = database.get_cw_id_for_iterm(current_iterm_window.window_id)
        if current_cw_id:
            cw_win = database.get_window_by_id(current_cw_id)
            if cw_win:
                ctx = database.get_context_by_id(cw_win.context_id)
                if ctx:
                    _last_focused_window_per_context[ctx.name] = current_cw_id

    active_mappings = database.get_all_active_mappings("window")
    live_window_ids = {w.window_id for w in app.terminal_windows}

    for mapping in active_mappings:
        if mapping.iterm_id in live_window_ids:
            # Window still exists — update its layout
            iterm_window = app.get_window_by_id(mapping.iterm_id)
            if iterm_window:
                window_state = await read_iterm_window_state(iterm_window)
                database.update_window_state(
                    mapping.cw_id,
                    frame_x=window_state["frame_x"],
                    frame_y=window_state["frame_y"],
                    frame_width=window_state["frame_width"],
                    frame_height=window_state["frame_height"],
                    fullscreen=window_state["fullscreen"],
                )
                database.sync_window_layout(mapping.cw_id, window_state["tabs"])
        else:
            # Window disappeared — mark as closed
            cw_window = database.get_window_by_id(mapping.cw_id)
            if cw_window and cw_window.is_open:
                # Save snapshot BEFORE marking closed
                database.save_snapshot(cw_window.context_id, "window_close")
                database.update_window_state(mapping.cw_id, is_open=False)
                database.deactivate_mappings_for_cw_id(mapping.cw_id)
                logger.info("Window '%s' closed (detected by layout change)", cw_window.name)

    _mark_dirty()


# ─── Session termination monitor ──────────────────────────────────

async def _monitor_session_termination(
    connection: iterm2.Connection,
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Watch for session (pane) termination events.

    When a session ends, we update the parent tab/window layout.
    """
    try:
        async with iterm2.SessionTerminationMonitor(connection) as monitor:
            logger.info("SessionTerminationMonitor started")
            while True:
                session_id = await monitor.async_get()
                try:
                    cw_id = database.get_cw_id_for_iterm(session_id)
                    if cw_id:
                        database.deactivate_mappings_for_cw_id(cw_id)
                        logger.info("Session %s terminated (CW pane %s)", session_id, cw_id)
                    _mark_dirty()
                except Exception:
                    logger.exception("Error handling session termination %s", session_id)
    except Exception:
        logger.exception("SessionTerminationMonitor crashed — will not restart")


# ─── New session monitor ──────────────────────────────────────────

async def _monitor_new_sessions(
    connection: iterm2.Connection,
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Watch for new sessions being created.

    If a new session appears in a tracked window, update the layout.
    """
    try:
        async with iterm2.NewSessionMonitor(connection) as monitor:
            logger.info("NewSessionMonitor started")
            while True:
                session_id = await monitor.async_get()
                try:
                    _mark_dirty()
                    logger.debug("New session created: %s", session_id)
                except Exception:
                    logger.exception("Error handling new session %s", session_id)
    except Exception:
        logger.exception("NewSessionMonitor crashed — will not restart")


# ─── Periodic checkpoint ──────────────────────────────────────────

async def _periodic_checkpoint(
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Every CHECKPOINT_INTERVAL_SECONDS, if changes have occurred,
    re-read full state of all tracked windows and persist.

    This is the safety net — even if an event was missed, the
    checkpoint will catch the drift.
    """
    while True:
        try:
            await asyncio.sleep(CHECKPOINT_INTERVAL_SECONDS)
            global _changes_pending
            if _changes_pending:
                _changes_pending = False
                await _do_checkpoint(app, database)
        except Exception:
            logger.exception("Checkpoint error")


async def _do_checkpoint(
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Perform a full checkpoint: re-read all tracked windows from iTerm.

    @param app: iTerm2 App singleton.
    @param database: CW database instance.
    """
    active_mappings = database.get_all_active_mappings("window")
    for mapping in active_mappings:
        iterm_window = app.get_window_by_id(mapping.iterm_id)
        if iterm_window:
            window_state = await read_iterm_window_state(iterm_window)
            database.update_window_state(
                mapping.cw_id,
                frame_x=window_state["frame_x"],
                frame_y=window_state["frame_y"],
                frame_width=window_state["frame_width"],
                frame_height=window_state["frame_height"],
                fullscreen=window_state["fullscreen"],
            )
            database.sync_window_layout(mapping.cw_id, window_state["tabs"])
    logger.debug("Checkpoint complete")


# ─── Unix socket server for CLI communication ─────────────────────

async def _socket_server(
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Listen for CLI commands on a Unix domain socket.

    Protocol: client sends JSON line, server responds with JSON line.
    Each request: {"cmd": "...", "args": {...}}
    Each response: {"ok": true, "data": ...} or {"ok": false, "error": "..."}
    """
    # Remove stale socket file
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()

    server = await asyncio.start_unix_server(
        lambda r, w: _handle_client(r, w, app, database),
        path=str(SOCKET_PATH),
    )
    # Make socket accessible
    os.chmod(str(SOCKET_PATH), 0o600)
    logger.info("Socket server listening at %s", SOCKET_PATH)

    async with server:
        await server.serve_forever()


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    app: iterm2.App,
    database: CwDatabase,
) -> None:
    """
    Handle a single CLI client connection.

    Reads one JSON command, executes it, sends back one JSON response.
    """
    try:
        data = await asyncio.wait_for(
            reader.read(SOCKET_BUFFER_SIZE),
            timeout=10,
        )
        if not data:
            return

        request = json.loads(data.decode("utf-8"))
        command = request.get("cmd", "")
        args = request.get("args", {})

        response = await _dispatch_command(command, args, app, database)
        writer.write(json.dumps(response, ensure_ascii=False).encode("utf-8"))
        await writer.drain()
    except Exception as exc:
        logger.exception("Error handling client request")
        try:
            error_response = {"ok": False, "error": str(exc)}
            writer.write(json.dumps(error_response).encode("utf-8"))
            await writer.drain()
        except Exception:
            pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _dispatch_command(
    command: str,
    args: dict,
    app: iterm2.App,
    database: CwDatabase,
) -> dict:
    """
    Route a CLI command to the appropriate handler.

    @param command: Command name (e.g. "create", "join", "list", "close").
    @param args: Command arguments dict.
    @param app: iTerm2 App singleton.
    @param database: CW database instance.
    @returns: Response dict with "ok" and optional "data"/"error".
    """
    # "reload" is handled here directly — it reloads all CW modules
    # so code changes take effect without restarting iTerm2
    if command == "reload":
        return await _cmd_reload(args, app, database)

    # Dispatch to handler — uses dynamic import so reload takes effect
    handler = _get_handler(command)
    if not handler:
        return {"ok": False, "error": f"Unknown command: {command}"}
    return await handler(args, app, database)


def _get_handler(command: str):
    """
    Look up a command handler by name.

    This is a function (not a dict literal) so that after _cmd_reload()
    reloads the module, new/changed handlers are picked up.
    """
    handlers = {
        "create": _cmd_create,
        "join": _cmd_join,
        "open": _cmd_open,
        "close": _cmd_close,
        "save": _cmd_save,
        "list": _cmd_list,
        "status": _cmd_status,
        "current": _cmd_current,
        "all_windows": _cmd_all_windows,
        "focus": _cmd_focus,
        "focus_ref": _cmd_focus_ref,
        "focus_title": _cmd_focus_title,
        "leave": _cmd_leave,
        "rename": _cmd_rename,
        "_complete_iterm_titles": _cmd_complete_iterm_titles,
    }
    return handlers.get(command)


async def _cmd_reload(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Reload all CW Python modules so code changes take effect
    without restarting iTerm2.

    Also detects new .py files that weren't loaded at daemon start —
    those require a full iTerm restart since importlib.reload can only
    reload already-imported modules.

    Usage from CLI: `cw reload`
    """
    import importlib
    import sys as _sys

    # Modules the daemon actually uses (not CLI-only ones like cli.py, completion.py)
    DAEMON_MODULES = {"cw.constants", "cw.models", "cw.db", "cw.reconciler", "cw.daemon"}

    # Discover all .py files in src/cw/ that could be daemon modules
    cw_package_dir = Path(__file__).parent
    files_on_disk = {
        f"cw.{p.stem}"
        for p in cw_package_dir.glob("*.py")
        if p.stem != "__pycache__" and not p.stem.startswith("_")
    }
    # Only consider files that look like daemon modules (not cli, completion, etc.)
    # A "new daemon module" is one that exists on disk, is NOT in our known set,
    # and is also NOT already loaded (i.e. truly new)
    loaded_cw_modules = {
        name for name in _sys.modules if name.startswith("cw.") and not name.startswith("cw.__")
    }

    # CLI-only modules that the daemon never imports — ignore these
    cli_only_modules = files_on_disk - DAEMON_MODULES - loaded_cw_modules

    # New daemon-relevant files on disk that aren't loaded
    new_modules = (files_on_disk - loaded_cw_modules - cli_only_modules)
    # Daemon modules that were loaded but no longer exist on disk
    removed_modules = (DAEMON_MODULES & loaded_cw_modules) - files_on_disk

    # Reload all currently loaded cw.* modules
    modules_reloaded = []
    reload_errors = []
    for module_name in sorted(loaded_cw_modules):
        module = _sys.modules.get(module_name)
        if module:
            try:
                importlib.reload(module)
                modules_reloaded.append(module_name)
            except Exception as exc:
                logger.exception("Failed to reload %s", module_name)
                reload_errors.append(f"{module_name}: {exc}")

    if reload_errors:
        return {"ok": False, "error": f"Reload failed: {'; '.join(reload_errors)}"}

    # Build warnings for user
    warnings = []
    if new_modules:
        names = ", ".join(sorted(new_modules))
        warnings.append(
            f"New modules detected ({names}) — these require iTerm restart to load"
        )
    if removed_modules:
        names = ", ".join(sorted(removed_modules))
        warnings.append(
            f"Removed modules still in memory ({names}) — iTerm restart recommended"
        )

    logger.info("Reloaded %d modules, warnings: %s", len(modules_reloaded), warnings)
    return {
        "ok": True,
        "data": {
            "reloaded": modules_reloaded,
            "warnings": warnings,
        },
    }


# ─── Command handlers ─────────────────────────────────────────────

async def _cmd_create(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Create a new empty Context.

    Does NOT automatically add the current window — use `cw join` for that.

    @param args: {"name": "MyProject", "description": "..."}
    """
    name = args.get("name", "").strip()
    if not name:
        return {"ok": False, "error": "Context name is required"}

    existing = database.get_context_by_name(name)
    if existing:
        return {"ok": False, "error": f"Context '{name}' already exists"}

    context = database.create_context(name, args.get("description", ""))
    database.save_snapshot(context.id, "context_created")

    logger.info("Created context '%s'", name)
    return {"ok": True, "data": {"context_id": context.id}}


async def _cmd_join(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Add the currently focused window to an existing Context.

    @param args: {"name": "MyProject", "window_name": "optional window name"}
    """
    name = args.get("name", "").strip()
    if not name:
        return {"ok": False, "error": "Context name is required"}

    context = database.get_context_by_name(name)
    if not context:
        return {"ok": False, "error": f"Context '{name}' not found"}

    # Determine target window: ref number, iTerm title, or current focused window
    ref = args.get("ref")
    iterm_title_query = args.get("iterm_title")

    if ref is not None:
        # Find window by ref number (1-based index into app.terminal_windows)
        try:
            ref_index = int(ref) - 1
            windows_list = list(app.terminal_windows)
            if ref_index < 0 or ref_index >= len(windows_list):
                return {"ok": False, "error": f"Invalid ref {ref} — use `cw windows --all` to see refs"}
            iterm_window = windows_list[ref_index]
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Invalid ref: {ref}"}
    elif iterm_title_query:
        # Find window by iTerm title (case-insensitive substring match)
        iterm_window = None
        query_lower = iterm_title_query.lower()
        for w in app.terminal_windows:
            try:
                title = await w.async_get_variable("titleOverride") or ""
            except Exception:
                title = ""
            if title.lower() == query_lower or query_lower in title.lower():
                iterm_window = w
                break
        if not iterm_window:
            return {"ok": False, "error": f"No iTerm window with title matching '{iterm_title_query}'"}
    else:
        iterm_window = app.current_terminal_window
        if not iterm_window:
            return {"ok": False, "error": "No focused iTerm window found"}

    # Check if this window is already tracked
    existing_cw_id = database.get_cw_id_for_iterm(iterm_window.window_id)
    if existing_cw_id:
        return {"ok": False, "error": "This window already belongs to a Context"}

    window_state = await read_iterm_window_state(iterm_window)
    # Default window name: use iTerm window title, fall back to context name
    iterm_title = ""
    try:
        iterm_title = await iterm_window.async_get_variable("titleOverride") or ""
    except Exception:
        pass
    window_name = args.get("window_name", "").strip() or iterm_title or name

    cw_window = database.create_window(
        context_id=context.id,
        name=window_name,
        frame_x=window_state["frame_x"],
        frame_y=window_state["frame_y"],
        frame_width=window_state["frame_width"],
        frame_height=window_state["frame_height"],
        fullscreen=window_state["fullscreen"],
    )
    database.set_mapping(cw_window.id, iterm_window.window_id, "window")
    database.sync_window_layout(cw_window.id, window_state["tabs"])
    await _set_window_cw_vars(iterm_window, context.id, cw_window.id, context.name, window_name)
    # Set window title to "Context / Window"
    try:
        title = f"{context.name} / {window_name}" if window_name != context.name else context.name
        await iterm_window.async_set_title(title)
    except Exception:
        pass
    database.save_snapshot(context.id, "window_joined")

    logger.info("Window '%s' joined context '%s'", window_name, name)
    return {"ok": True, "data": {"window_id": cw_window.id}}


async def _cmd_leave(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Remove the current window from its Context (explicit membership change).

    The window stays open in iTerm but CW stops tracking it.
    Requires confirmation unless args["confirm"] is True.

    @param args: {"confirm": bool}
    """
    iterm_window = app.current_terminal_window
    if not iterm_window:
        return {"ok": False, "error": "No focused iTerm window found"}

    cw_id = database.get_cw_id_for_iterm(iterm_window.window_id)
    if not cw_id:
        return {"ok": False, "error": "Current window is not tracked by any Context"}

    cw_window = database.get_window_by_id(cw_id)
    if not cw_window:
        return {"ok": False, "error": "Window not found in database"}

    context = database.get_context_by_id(cw_window.context_id)
    context_name = context.name if context else "?"

    # Ask for confirmation if not already confirmed
    if not args.get("confirm"):
        return {
            "ok": False,
            "error": "confirm",
            "data": {
                "context_name": context_name,
                "window_name": cw_window.name,
            },
        }

    # Save snapshot before removing
    if context:
        database.save_snapshot(context.id, "before_leave")

    # Remove membership
    database.update_window_state(cw_id, is_member=False, is_open=False)
    database.deactivate_mappings_for_cw_id(cw_id)

    # Clear CW user variables from all sessions in this window
    for tab in iterm_window.tabs:
        for session in tab.sessions:
            try:
                await session.async_set_variable(ITERM_VAR_CONTEXT_ID, "")
                await session.async_set_variable(ITERM_VAR_WINDOW_ID, "")
                await session.async_set_variable("user.cw_context_name", "")
                await session.async_set_variable("user.cw_window_name", "")
                # Clear badge
                profile = await session.async_get_profile()
                await profile.async_set_badge_text("")
            except Exception:
                pass

    logger.info("Window '%s' left context '%s'", cw_window.name, context_name)
    return {"ok": True, "data": {"context_name": context_name, "window_name": cw_window.name}}


async def _cmd_rename(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Rename a Context or a Window within a Context.

    @param args: {"target": "OldName" or "Context/Window", "new_name": "NewName"}
    """
    target = args.get("target", "").strip()
    new_name = args.get("new_name", "").strip()
    if not target or not new_name:
        return {"ok": False, "error": "Both target and new_name are required"}

    context_name, _, window_name = target.partition("/")
    window_name = window_name.strip()

    context = database.get_context_by_name(context_name)
    if not context:
        return {"ok": False, "error": f"Context '{context_name}' not found"}

    if window_name:
        # Rename a window within the context
        target_window = None
        for w in context.windows:
            if w.name == window_name and w.is_member:
                target_window = w
                break
        if not target_window:
            return {"ok": False, "error": f"Window '{window_name}' not found in '{context_name}'"}

        database.update_window_state(target_window.id, name=new_name)

        # Update user variables on live iTerm window if it's open
        iterm_id = database.get_iterm_id_for_cw(target_window.id)
        if iterm_id:
            iterm_window = app.get_window_by_id(iterm_id)
            if iterm_window:
                await _set_window_cw_vars(
                    iterm_window, context.id, target_window.id,
                    context.name, new_name,
                )
                title = f"{context.name} / {new_name}" if new_name != context.name else context.name
                await iterm_window.async_set_title(title)

        logger.info("Renamed window '%s' → '%s' in context '%s'", window_name, new_name, context_name)
    else:
        # Rename the context itself
        existing = database.get_context_by_name(new_name)
        if existing:
            return {"ok": False, "error": f"Context '{new_name}' already exists"}

        with database.transaction() as cursor:
            cursor.execute(
                "UPDATE contexts SET name = ?, updated_at = ? WHERE id = ?",
                (new_name, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), context.id),
            )

        # Update user variables on all live windows
        for w in context.windows:
            if not w.is_open:
                continue
            iterm_id = database.get_iterm_id_for_cw(w.id)
            if iterm_id:
                iterm_window = app.get_window_by_id(iterm_id)
                if iterm_window:
                    await _set_window_cw_vars(
                        iterm_window, context.id, w.id, new_name, w.name,
                    )
                    title = f"{new_name} / {w.name}" if w.name != new_name else new_name
                    await iterm_window.async_set_title(title)

        logger.info("Renamed context '%s' → '%s'", context_name, new_name)

    return {"ok": True}


async def _cmd_complete_iterm_titles(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Return iTerm window titles for shell completion.

    Used internally by completion scripts. Returns titles of
    untracked windows (for `cw join`) or all windows.

    @param args: {"filter": "untracked" | "all"}
    """
    filter_mode = args.get("filter", "all")
    titles = []
    for iterm_window in app.terminal_windows:
        try:
            title = await iterm_window.async_get_variable("titleOverride") or ""
        except Exception:
            title = ""
        if not title:
            continue

        if filter_mode == "untracked":
            cw_id = database.get_cw_id_for_iterm(iterm_window.window_id)
            if cw_id:
                continue  # skip tracked windows

        titles.append(title)

    return {"ok": True, "data": {"titles": titles}}


async def _cmd_open(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Restore closed windows of a Context (or a specific window).

    Creates new iTerm windows with the saved layout:
    tabs, panes, CWDs, geometry.

    @param args: {"name": "MyProject"} or {"name": "MyProject/WindowName"}
    """
    raw_name = args.get("name", "").strip()
    if not raw_name:
        return {"ok": False, "error": "Context name is required"}

    # Parse "ContextName/WindowName" format
    context_name, _, window_filter = raw_name.partition("/")
    window_filter = window_filter.strip()

    context = database.get_context_by_name(context_name)
    if not context:
        return {"ok": False, "error": f"Context '{context_name}' not found"}

    restored_count = 0
    for window in context.windows:
        if not window.is_member:
            continue
        if window.is_open:
            continue  # already open
        if window_filter and window.name != window_filter:
            continue

        # Restore this window
        try:
            new_iterm_window = await _restore_window(app, window, context)
            if new_iterm_window:
                # Create new mapping for the fresh iTerm window
                database.set_mapping(window.id, new_iterm_window.window_id, "window")
                database.update_window_state(window.id, is_open=True)
                # Set CW user variables
                await _set_window_cw_vars(
                    new_iterm_window, context.id, window.id,
                    context.name, window.name,
                )
                # Sync the new layout
                new_state = await read_iterm_window_state(new_iterm_window)
                database.sync_window_layout(window.id, new_state["tabs"])
                restored_count += 1
                logger.info("Restored window '%s' in context '%s'", window.name, context.name)
        except Exception:
            logger.exception("Failed to restore window '%s'", window.name)

    if restored_count == 0:
        if window_filter:
            return {"ok": False, "error": f"No closed window '{window_filter}' found in '{context_name}'"}
        return {"ok": False, "error": f"No closed windows to restore in '{context_name}'"}

    database.save_snapshot(context.id, "context_opened")
    return {"ok": True, "data": {"restored_windows": restored_count}}


async def _cmd_close(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Close a Context (or specific window): save state, then close in iTerm.

    This follows the save-before-close principle:
    1. Read current state from iTerm
    2. Persist to DB
    3. Save snapshot
    4. Close in iTerm
    5. Mark as closed

    If persistence fails, we ABORT — never close without saving.

    @param args: {"name": "MyProject"} or {"name": "MyProject/WindowName"}
    """
    raw_name = args.get("name", "").strip()
    if not raw_name:
        return {"ok": False, "error": "Context name is required"}

    context_name, _, window_filter = raw_name.partition("/")
    window_filter = window_filter.strip()

    context = database.get_context_by_name(context_name)
    if not context:
        return {"ok": False, "error": f"Context '{context_name}' not found"}

    # Step 1: Save current state of all open windows
    closed_count = 0
    windows_to_close: list[tuple[str, iterm2.Window]] = []  # (cw_id, iterm_window)

    for window in context.windows:
        if not window.is_member or not window.is_open:
            continue
        if window_filter and window.name != window_filter:
            continue

        iterm_id = database.get_iterm_id_for_cw(window.id)
        if not iterm_id:
            continue
        iterm_window = app.get_window_by_id(iterm_id)
        if not iterm_window:
            # Already gone — just mark closed
            database.update_window_state(window.id, is_open=False)
            database.deactivate_mappings_for_cw_id(window.id)
            closed_count += 1
            continue

        # Save current state
        try:
            window_state = await read_iterm_window_state(iterm_window)
            database.update_window_state(
                window.id,
                frame_x=window_state["frame_x"],
                frame_y=window_state["frame_y"],
                frame_width=window_state["frame_width"],
                frame_height=window_state["frame_height"],
                fullscreen=window_state["fullscreen"],
            )
            database.sync_window_layout(window.id, window_state["tabs"])
            windows_to_close.append((window.id, iterm_window))
        except Exception:
            logger.exception("Failed to save window '%s' — aborting close", window.name)
            return {"ok": False, "error": f"Could not safely save window '{window.name}'. No windows were closed."}

    # Step 2: Save snapshot before closing
    database.save_snapshot(context.id, "before_close")

    # Step 3: Close windows in iTerm and mark as closed
    for cw_id, iterm_window in windows_to_close:
        try:
            await iterm_window.async_close(force=True)
        except Exception:
            logger.exception("Failed to close iTerm window — marking closed anyway")
        database.update_window_state(cw_id, is_open=False)
        database.deactivate_mappings_for_cw_id(cw_id)
        closed_count += 1

    logger.info("Closed %d window(s) in context '%s'", closed_count, context_name)
    return {"ok": True, "data": {"closed_windows": closed_count}}


async def _cmd_save(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Force an explicit snapshot of a Context's current state.

    @param args: {"name": "MyProject"} (optional — saves all if omitted)
    """
    name = args.get("name", "").strip()

    if name:
        context = database.get_context_by_name(name)
        if not context:
            return {"ok": False, "error": f"Context '{name}' not found"}
        contexts_to_save = [context]
    else:
        contexts_to_save = database.list_contexts()

    saved_count = 0
    for context in contexts_to_save:
        # Re-read live state for open windows
        for window in context.windows:
            if not window.is_open:
                continue
            iterm_id = database.get_iterm_id_for_cw(window.id)
            if not iterm_id:
                continue
            iterm_window = app.get_window_by_id(iterm_id)
            if iterm_window:
                window_state = await read_iterm_window_state(iterm_window)
                database.update_window_state(
                    window.id,
                    frame_x=window_state["frame_x"],
                    frame_y=window_state["frame_y"],
                    frame_width=window_state["frame_width"],
                    frame_height=window_state["frame_height"],
                    fullscreen=window_state["fullscreen"],
                )
                database.sync_window_layout(window.id, window_state["tabs"])

        database.save_snapshot(context.id, "manual_save")
        saved_count += 1

    return {"ok": True, "data": {"saved_contexts": saved_count}}


async def _cmd_list(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    List all Contexts with live iTerm status comparison.

    Returns both the current state AND any discrepancies between
    what the DB thinks and what iTerm actually has.

    @param args: {} (no arguments needed)
    """
    live_status = await get_live_status(app, database)
    return {"ok": True, "data": live_status}


async def _cmd_status(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Return daemon status info.

    @param args: {} (no arguments needed)
    """
    return {
        "ok": True,
        "data": {
            "running": True,
            "db_path": str(database.db_path),
            "socket_path": str(SOCKET_PATH),
        },
    }


async def _cmd_current(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Identify which Context the currently focused window belongs to.

    Returns context name, window name, and IDs. If the window is
    not tracked, returns null context info.

    @param args: {} (no arguments needed)
    """
    iterm_window = app.current_terminal_window
    if not iterm_window:
        return {"ok": True, "data": {"context_name": None, "window_name": None}}

    cw_id = database.get_cw_id_for_iterm(iterm_window.window_id)
    if not cw_id:
        return {"ok": True, "data": {
            "context_name": None, "window_name": None,
            "iterm_id": iterm_window.window_id,
        }}

    cw_window = database.get_window_by_id(cw_id)
    if not cw_window:
        return {"ok": True, "data": {"context_name": None, "window_name": None}}

    context = database.get_context_by_id(cw_window.context_id)
    return {"ok": True, "data": {
        "context_name": context.name if context else None,
        "context_id": cw_window.context_id,
        "window_name": cw_window.name,
        "window_id": cw_id,
    }}


async def _cmd_all_windows(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    List ALL iTerm windows with their Context membership.

    Each window gets:
    - ref: a short numeric reference for use with `cw join --ref`
    - context_name: which Context it belongs to (null if untracked)
    - window_name: CW window name (null if untracked)
    - title: iTerm window title
    - tabs/panes count

    @param args: {"filter": "all" | "untracked" | "tracked"} (default: "all")
    """
    window_filter = args.get("filter", "all")
    results = []

    for ref_index, iterm_window in enumerate(app.terminal_windows, start=1):
        # Get iTerm window title
        try:
            window_title = await iterm_window.async_get_variable("titleOverride") or ""
        except Exception:
            window_title = ""

        # Check CW membership
        cw_id = database.get_cw_id_for_iterm(iterm_window.window_id)
        context_name = None
        window_name = None
        if cw_id:
            cw_window = database.get_window_by_id(cw_id)
            if cw_window:
                context = database.get_context_by_id(cw_window.context_id)
                context_name = context.name if context else None
                window_name = cw_window.name

        is_tracked = context_name is not None

        # Apply filter
        if window_filter == "untracked" and is_tracked:
            continue
        if window_filter == "tracked" and not is_tracked:
            continue

        # Count tabs and panes
        tab_count = len(iterm_window.tabs)
        pane_count = sum(len(tab.sessions) for tab in iterm_window.tabs)

        results.append({
            "ref": ref_index,
            "iterm_id": iterm_window.window_id,
            "iterm_title": window_title,
            "context_name": context_name,
            "window_name": window_name,
            "tracked": is_tracked,
            "tabs": tab_count,
            "panes": pane_count,
        })

    return {"ok": True, "data": {"windows": results}}


async def _cmd_focus(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Focus (switch to) a specific Context window, or jump between Contexts.

    Activates the iTerm window, bringing it to front.

    @param args: {"name": "ContextName/WindowName"} or {"name": "ContextName"}
                 If just ContextName, focuses the first open window.
                 Use {"name": "-"} to jump to the previous Context.
    """
    raw_name = args.get("name", "").strip()
    if not raw_name:
        return {"ok": False, "error": "Context name is required"}

    # Handle "-" for jumping back to previous context
    # (stored in a module-level variable)
    global _last_focused_context
    if raw_name == "-":
        if not _last_focused_context:
            return {"ok": False, "error": "No previous context to jump to"}
        raw_name = _last_focused_context

    context_name, _, window_filter = raw_name.partition("/")
    window_filter = window_filter.strip()

    context = database.get_context_by_name(context_name)
    if not context:
        return {"ok": False, "error": f"Context '{context_name}' not found"}

    # Remember current context before switching (for "cw focus -")
    current_context_name = None
    current_window = app.current_terminal_window
    if current_window:
        current_cw_id = database.get_cw_id_for_iterm(current_window.window_id)
        if current_cw_id:
            current_cw_win = database.get_window_by_id(current_cw_id)
            if current_cw_win:
                current_ctx = database.get_context_by_id(current_cw_win.context_id)
                if current_ctx:
                    current_context_name = current_ctx.name

    # Find the target window:
    # If a specific window name is given, use that.
    # Otherwise, use the LAST focused window for this context (if known),
    # falling back to the first open window.
    target_iterm_window = None
    target_cw_window_name = None

    if window_filter:
        # Explicit window name requested
        for window in context.windows:
            if not window.is_member or not window.is_open:
                continue
            if window.name == window_filter:
                iterm_id = database.get_iterm_id_for_cw(window.id)
                if iterm_id:
                    target_iterm_window = app.get_window_by_id(iterm_id)
                    target_cw_window_name = window.name
                break
    else:
        # Try last-used window for this context first
        last_window_id = _last_focused_window_per_context.get(context_name)
        if last_window_id:
            iterm_id = database.get_iterm_id_for_cw(last_window_id)
            if iterm_id:
                target_iterm_window = app.get_window_by_id(iterm_id)
                if target_iterm_window:
                    cw_win = database.get_window_by_id(last_window_id)
                    target_cw_window_name = cw_win.name if cw_win else None

        # Fall back to first open window
        if not target_iterm_window:
            for window in context.windows:
                if not window.is_member or not window.is_open:
                    continue
                iterm_id = database.get_iterm_id_for_cw(window.id)
                if iterm_id:
                    target_iterm_window = app.get_window_by_id(iterm_id)
                    if target_iterm_window:
                        target_cw_window_name = window.name
                        break

    if not target_iterm_window:
        if window_filter:
            return {"ok": False, "error": f"Window '{window_filter}' not found or not open in '{context_name}'"}
        return {"ok": False, "error": f"No open windows in '{context_name}'"}

    # Focus the window
    try:
        await target_iterm_window.async_activate()
        # Remember: previous context (for "cw focus -")
        if current_context_name and current_context_name != context_name:
            _last_focused_context = current_context_name
        # Remember: which window was last used in THIS context
        cw_id_focused = database.get_cw_id_for_iterm(target_iterm_window.window_id)
        if cw_id_focused:
            _last_focused_window_per_context[context_name] = cw_id_focused
        return {"ok": True, "data": {"focused": context_name, "window": target_cw_window_name}}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to focus window: {exc}"}


# Module-level state for focus navigation
_last_focused_context: str | None = None
# Remembers the last focused CW window ID per context name
_last_focused_window_per_context: dict[str, str] = {}


async def _cmd_focus_ref(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Focus (jump to) a window by its ref number from `cw windows --all`.

    @param args: {"ref": int}
    """
    ref = args.get("ref")
    if ref is None:
        return {"ok": False, "error": "ref number is required"}

    try:
        ref_index = int(ref) - 1
        windows_list = list(app.terminal_windows)
        if ref_index < 0 or ref_index >= len(windows_list):
            return {"ok": False, "error": f"Invalid ref #{ref} — use `cw windows --all` to see refs"}
        iterm_window = windows_list[ref_index]
    except (ValueError, TypeError):
        return {"ok": False, "error": f"Invalid ref: {ref}"}

    try:
        title = await iterm_window.async_get_variable("titleOverride") or iterm_window.window_id
        await iterm_window.async_activate()
        return {"ok": True, "data": {"focused": f"#{ref} ({title})"}}
    except Exception as exc:
        return {"ok": False, "error": f"Failed to focus window: {exc}"}


async def _cmd_focus_title(args: dict, app: iterm2.App, database: CwDatabase) -> dict:
    """
    Focus (jump to) a window by its iTerm title (case-insensitive match).

    @param args: {"title": str}
    """
    query = args.get("title", "").strip()
    if not query:
        return {"ok": False, "error": "Window title is required"}

    query_lower = query.lower()
    for iterm_window in app.terminal_windows:
        try:
            title = await iterm_window.async_get_variable("titleOverride") or ""
        except Exception:
            title = ""
        if title.lower() == query_lower or query_lower in title.lower():
            try:
                await iterm_window.async_activate()
                return {"ok": True, "data": {"focused": title}}
            except Exception as exc:
                return {"ok": False, "error": f"Failed to focus window: {exc}"}

    return {"ok": False, "error": f"No window with title matching '{query}'"}


# ─── Window restore helper ────────────────────────────────────────

async def _restore_window(
    app: iterm2.App,
    window: "from cw.models import Window",
    context: "from cw.models import Context",
) -> iterm2.Window | None:
    """
    Restore a closed window in iTerm: create window, tabs, panes, set CWDs.

    Strategy:
    1. Create a new window with the first pane's profile/CWD
    2. For each additional tab, create a new tab
    3. For each additional pane in a tab, split as needed
    4. Set the window geometry

    @param app: iTerm2 App singleton.
    @param window: CW Window model with tabs/panes loaded.
    @param context: Parent Context (for naming).
    @returns: The newly created iTerm Window, or None on failure.
    """
    if not window.tabs:
        return None

    first_tab = window.tabs[0]
    first_pane = first_tab.panes[0] if first_tab.panes else None
    if not first_pane:
        return None

    # Create the initial window with the first pane
    profile = first_pane.profile or "Default"
    cwd = first_pane.cwd or None
    new_window = await iterm2.Window.async_create(
        app.connection,
        profile=profile,
        command=None,
    )
    if not new_window:
        return None

    # Helper to set up a restored session (CWD, name, title)
    async def _setup_session(session: iterm2.Session, pane_data):
        if pane_data.cwd:
            await session.async_send_text(f"cd {_shell_escape(pane_data.cwd)}\n")
        if pane_data.title:
            try:
                await session.async_set_name(pane_data.title)
            except Exception:
                pass

    # Set up the first pane
    first_session = new_window.current_tab.sessions[0] if new_window.current_tab else None
    if first_session:
        await _setup_session(first_session, first_pane)

    # Set first tab title
    if new_window.current_tab and first_tab.title:
        try:
            await new_window.current_tab.async_set_title(first_tab.title)
        except Exception:
            pass

    # Create additional panes in the first tab
    if first_tab.panes and len(first_tab.panes) > 1:
        for pane in first_tab.panes[1:]:
            try:
                new_session = await first_session.async_split_pane(
                    vertical=True,
                    profile=pane.profile or "Default",
                )
                if new_session:
                    await _setup_session(new_session, pane)
                first_session = new_session
            except Exception:
                logger.exception("Failed to split pane during restore")

    # Create additional tabs
    for tab in window.tabs[1:]:
        try:
            first_pane_in_tab = tab.panes[0] if tab.panes else None
            tab_profile = first_pane_in_tab.profile if first_pane_in_tab else "Default"
            new_tab = await new_window.async_create_tab(profile=tab_profile)
            if not new_tab:
                continue

            # Set tab title
            if tab.title:
                try:
                    await new_tab.async_set_title(tab.title)
                except Exception:
                    pass

            # Set up first pane in this tab
            tab_session = new_tab.sessions[0] if new_tab.sessions else None
            if tab_session and first_pane_in_tab:
                await _setup_session(tab_session, first_pane_in_tab)

            # Additional panes in this tab
            if tab.panes and len(tab.panes) > 1:
                base_session = tab_session
                for pane in tab.panes[1:]:
                    try:
                        new_session = await base_session.async_split_pane(
                            vertical=True,
                            profile=pane.profile or "Default",
                        )
                        if new_session:
                            await _setup_session(new_session, pane)
                        base_session = new_session
                    except Exception:
                        logger.exception("Failed to split pane during tab restore")
        except Exception:
            logger.exception("Failed to create tab during restore")

    # Set window title
    try:
        title = f"{context.name} / {window.name}" if window.name else context.name
        await new_window.async_set_title(title)
    except Exception:
        pass

    # Set window geometry if saved
    if window.frame_x is not None and window.frame_width is not None:
        try:
            frame = iterm2.Frame(
                iterm2.Point(window.frame_x, window.frame_y),
                iterm2.Size(window.frame_width, window.frame_height),
            )
            await new_window.async_set_frame(frame)
        except Exception:
            logger.exception("Failed to set window geometry — using default position")

    return new_window


# ─── iTerm user variable helpers ───────────────────────────────────

async def _set_window_cw_vars(
    iterm_window: iterm2.Window,
    context_id: str,
    window_id: str,
    context_name: str,
    window_name: str,
) -> None:
    """
    Set CW identification variables on all sessions in a window.

    These variables serve two purposes:
    1. Let CW re-identify windows after iTerm restart (reconciliation)
    2. Let the user see Context/Window name in iTerm badge/title

    The user can configure their iTerm profile to show these in the badge:
        \\(user.cw_context_name) / \\(user.cw_window_name)

    @param iterm_window: The iTerm2 Window to tag.
    @param context_id: CW Context UUID.
    @param window_id: CW Window UUID.
    @param context_name: Human-readable Context name.
    @param window_name: Human-readable Window name.
    """
    for tab in iterm_window.tabs:
        for session in tab.sessions:
            try:
                await session.async_set_variable(ITERM_VAR_CONTEXT_ID, context_id)
                await session.async_set_variable(ITERM_VAR_WINDOW_ID, window_id)
                # Human-readable names for iTerm badge display
                await session.async_set_variable("user.cw_context_name", context_name)
                await session.async_set_variable("user.cw_window_name", window_name)
                # Set iTerm2 badge directly so user doesn't need manual config
                badge = f"{context_name} / {window_name}" if window_name else context_name
                profile = await session.async_get_profile()
                await profile.async_set_badge_text(badge)
            except Exception:
                logger.exception("Failed to set CW vars on session %s", session.session_id)


def _shell_escape(path: str) -> str:
    """
    Escape a path for safe use in shell commands.

    @param path: File system path to escape.
    @returns: Shell-safe quoted path.
    """
    return "'" + path.replace("'", "'\"'\"'") + "'"


# ─── iTerm2 entry point ───────────────────────────────────────────

if __name__ == "__main__":
    iterm2.run_forever(main)
