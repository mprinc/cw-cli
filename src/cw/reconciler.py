"""
CW Reconciler — diffs live iTerm state against the CW database.

This is the safety net that runs:
1. On daemon startup (catch changes that happened while daemon was down)
2. On daemon reconnect after connection loss
3. Periodically as a checkpoint

The reconciler never trusts events alone — it reads the FULL iTerm state,
compares with what the DB says, and fixes any discrepancies atomically.

Principles:
- iTerm is the authority for "what exists right now"
- CW DB is the authority for "what belongs to which Context"
- Reconciler merges these two truths
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import iterm2

from cw.constants import (
    ITERM_VAR_CONTEXT_ID,
    ITERM_VAR_WINDOW_ID,
)
from cw.db import CwDatabase

if TYPE_CHECKING:
    pass

logger = logging.getLogger("cw.reconciler")


@dataclass
class ReconcileResult:
    """
    Summary of what reconciliation found and fixed.

    @param windows_marked_closed: Windows in DB that were open but missing in iTerm.
    @param windows_marked_open: Windows in DB that were closed but found in iTerm.
    @param windows_updated: Windows whose layout/geometry was refreshed.
    @param untracked_windows: iTerm windows not belonging to any Context.
    """
    windows_marked_closed: int = 0
    windows_marked_open: int = 0
    windows_updated: int = 0
    untracked_windows: int = 0


async def read_iterm_window_state(iterm_window: iterm2.Window) -> dict:
    """
    Read the full state of one iTerm window: geometry, tabs, panes, CWDs.

    @param iterm_window: An iTerm2 Window object from the API.
    @returns: Dict with window info including nested tabs and panes.
    """
    frame = await iterm_window.async_get_frame()
    fullscreen = await iterm_window.async_get_fullscreen()

    tabs_data = []
    for tab_index, iterm_tab in enumerate(iterm_window.tabs):
        # Find the active session in this tab
        active_session_id = None
        try:
            if iterm_tab.current_session:
                active_session_id = iterm_tab.current_session.session_id
        except Exception:
            pass

        panes_data = []
        for iterm_session in iterm_tab.sessions:
            # Read pane/session properties safely
            try:
                session_cwd = await iterm_session.async_get_variable("path")
            except Exception:
                session_cwd = ""
            try:
                session_title = await iterm_session.async_get_variable("autoName")
            except Exception:
                session_title = ""
            try:
                session_hostname = await iterm_session.async_get_variable("hostname")
            except Exception:
                session_hostname = ""
            try:
                session_username = await iterm_session.async_get_variable("username")
            except Exception:
                session_username = ""
            try:
                profile_name = await iterm_session.async_get_variable("profileName")
            except Exception:
                profile_name = ""

            panes_data.append({
                "iterm_id": iterm_session.session_id,
                "title": session_title or "",
                "cwd": session_cwd or "",
                "hostname": session_hostname or "",
                "username": session_username or "",
                "profile": profile_name or "",
                "split_direction": None,
                "relative_size": None,
                "is_active": iterm_session.session_id == active_session_id,
            })

        # Check if this tab is selected
        current_tab = await iterm_window.async_get_variable("currentTab")
        is_selected = (iterm_tab.tab_id == current_tab) if current_tab else (tab_index == 0)

        tabs_data.append({
            "iterm_id": iterm_tab.tab_id,
            "title": await _safe_tab_title(iterm_tab),
            "tab_order": tab_index,
            "is_selected": is_selected,
            "panes": panes_data,
        })

    return {
        "iterm_id": iterm_window.window_id,
        "frame_x": frame.origin.x if frame else None,
        "frame_y": frame.origin.y if frame else None,
        "frame_width": frame.size.width if frame else None,
        "frame_height": frame.size.height if frame else None,
        "fullscreen": fullscreen,
        "tabs": tabs_data,
    }


async def _safe_tab_title(iterm_tab: iterm2.Tab) -> str:
    """
    Read a tab's title using multiple fallbacks.

    Priority: titleOverride (user-set) → title → first session autoName.

    @param iterm_tab: An iTerm2 Tab object.
    @returns: Tab title string.
    """
    # 1. User-set title override
    try:
        title = await iterm_tab.async_get_variable("titleOverride")
        if title:
            return title
    except Exception:
        pass

    # 2. Tab's computed title
    try:
        title = await iterm_tab.async_get_variable("title")
        if title:
            return title
    except Exception:
        pass

    # 3. First session's auto name
    try:
        if iterm_tab.sessions:
            title = await iterm_tab.sessions[0].async_get_variable("autoName")
            if title:
                return title
    except Exception:
        pass

    return ""


async def reconcile(
    app: iterm2.App,
    database: CwDatabase,
) -> ReconcileResult:
    """
    Full reconciliation: compare DB state with live iTerm state.

    Algorithm:
    1. Read all iTerm windows and their CW user variables.
    2. For each iTerm window WITH a CW context variable:
       - Find the CW window in DB via id_mapping or user variable.
       - Update its layout, geometry, and mark as open.
    3. For each CW window marked open in DB but NOT found in iTerm:
       - Mark as closed (is_open=false). Do NOT remove from Context.
    4. Save a reconciliation snapshot for each affected Context.

    @param app: The iTerm2 App singleton.
    @param database: CW database instance.
    @returns: Summary of what changed.
    """
    result = ReconcileResult()

    # Gather all live iTerm window IDs and their CW associations
    live_iterm_window_ids: set[str] = set()
    iterm_windows_with_cw: dict[str, dict] = {}  # iterm_window_id -> state_dict

    for iterm_window in app.terminal_windows:
        live_iterm_window_ids.add(iterm_window.window_id)

        # Check if this window has CW user variables
        try:
            cw_context_id = await _get_window_cw_var(iterm_window, ITERM_VAR_CONTEXT_ID)
            cw_window_id = await _get_window_cw_var(iterm_window, ITERM_VAR_WINDOW_ID)
        except Exception:
            cw_context_id = None
            cw_window_id = None

        if cw_context_id and cw_window_id:
            # This window belongs to a CW Context
            window_state = await read_iterm_window_state(iterm_window)
            window_state["cw_context_id"] = cw_context_id
            window_state["cw_window_id"] = cw_window_id
            iterm_windows_with_cw[iterm_window.window_id] = window_state
        else:
            # Check by id_mapping (maybe user vars weren't set yet)
            cw_id = database.get_cw_id_for_iterm(iterm_window.window_id)
            if cw_id:
                window_state = await read_iterm_window_state(iterm_window)
                cw_window = database.get_window_by_id(cw_id)
                if cw_window:
                    window_state["cw_context_id"] = cw_window.context_id
                    window_state["cw_window_id"] = cw_id
                    iterm_windows_with_cw[iterm_window.window_id] = window_state
                else:
                    result.untracked_windows += 1
            else:
                result.untracked_windows += 1

    # Update CW windows that are live in iTerm
    affected_context_ids: set[str] = set()
    for iterm_id, state in iterm_windows_with_cw.items():
        cw_window_id = state["cw_window_id"]
        cw_window = database.get_window_by_id(cw_window_id)
        if not cw_window:
            logger.warning(
                "iTerm window %s has CW ID %s but not found in DB — skipping",
                iterm_id, cw_window_id,
            )
            continue

        # Update mapping
        database.set_mapping(cw_window_id, iterm_id, "window")

        # Update geometry
        database.update_window_state(
            cw_window_id,
            is_open=True,
            frame_x=state["frame_x"],
            frame_y=state["frame_y"],
            frame_width=state["frame_width"],
            frame_height=state["frame_height"],
            fullscreen=state["fullscreen"],
        )

        # Sync tab/pane layout
        database.sync_window_layout(cw_window_id, state["tabs"])

        if not cw_window.is_open:
            result.windows_marked_open += 1
        result.windows_updated += 1
        affected_context_ids.add(state["cw_context_id"])

    # Find CW windows that DB says are open but iTerm doesn't have
    all_active_window_mappings = database.get_all_active_mappings("window")
    for mapping in all_active_window_mappings:
        if mapping.iterm_id not in live_iterm_window_ids:
            # Window is gone from iTerm — mark as closed
            cw_window = database.get_window_by_id(mapping.cw_id)
            if cw_window and cw_window.is_open:
                database.update_window_state(mapping.cw_id, is_open=False)
                database.deactivate_mappings_for_cw_id(mapping.cw_id)
                result.windows_marked_closed += 1
                affected_context_ids.add(cw_window.context_id)
                logger.info(
                    "Window %s (%s) no longer in iTerm — marked closed",
                    cw_window.name, mapping.cw_id,
                )

    # Save reconciliation snapshot for each affected context
    for context_id in affected_context_ids:
        database.save_snapshot(context_id, "reconciliation")

    logger.info(
        "Reconciliation complete: updated=%d, marked_closed=%d, "
        "marked_open=%d, untracked=%d",
        result.windows_updated, result.windows_marked_closed,
        result.windows_marked_open, result.untracked_windows,
    )
    return result


async def get_live_status(
    app: iterm2.App,
    database: CwDatabase,
) -> dict:
    """
    Build a live status report comparing DB state with iTerm reality.

    Used by `cw list` to show accurate status AND discrepancies.

    @param app: The iTerm2 App singleton.
    @param database: CW database instance.
    @returns: Dict with 'contexts' list and 'discrepancies' list.
    """
    # Gather live iTerm window IDs
    live_iterm_ids: set[str] = set()
    for iterm_window in app.terminal_windows:
        live_iterm_ids.add(iterm_window.window_id)

    contexts = database.list_contexts()
    discrepancies: list[str] = []
    context_reports: list[dict] = []

    for context in contexts:
        window_reports: list[dict] = []
        for window in context.windows:
            if not window.is_member:
                continue
            iterm_id = database.get_iterm_id_for_cw(window.id)
            actually_live = iterm_id in live_iterm_ids if iterm_id else False
            db_says_open = window.is_open

            # Check for discrepancy
            if db_says_open and not actually_live:
                discrepancies.append(
                    f"⚠ Window \"{window.name}\" in \"{context.name}\" — "
                    f"DB says OPEN but not found in iTerm"
                )
            elif not db_says_open and actually_live:
                discrepancies.append(
                    f"⚠ Window \"{window.name}\" in \"{context.name}\" — "
                    f"DB says CLOSED but found in iTerm"
                )

            window_reports.append({
                "name": window.name,
                "db_open": db_says_open,
                "actually_live": actually_live,
                "id": window.id,
            })

        # Compute real status based on live state
        live_open = sum(1 for w in window_reports if w["actually_live"])
        total = len(window_reports)
        if total == 0:
            live_status = "CLOSED"
        elif live_open == 0:
            live_status = "CLOSED"
        elif live_open == total:
            live_status = "OPEN"
        else:
            live_status = "PARTIAL"

        context_reports.append({
            "name": context.name,
            "status": live_status,
            "db_status": context.status,
            "open_windows": live_open,
            "total_windows": total,
            "updated_at": context.updated_at,
            "windows": window_reports,
        })

    return {
        "contexts": context_reports,
        "discrepancies": discrepancies,
    }


async def _get_window_cw_var(
    iterm_window: iterm2.Window, variable_name: str,
) -> str | None:
    """
    Read a CW user variable from the first session in a window.

    iTerm user variables are set on sessions, so we check the first
    session of the first tab as the representative.

    @param iterm_window: An iTerm2 Window object.
    @param variable_name: Variable name (e.g. "user.cw_context_id").
    @returns: Variable value, or None.
    """
    for tab in iterm_window.tabs:
        for session in tab.sessions:
            try:
                value = await session.async_get_variable(variable_name)
                if value:
                    return value
            except Exception:
                continue
    return None
