"""
CW data models — pure dataclasses representing the persistent state.

These models mirror the SQLite schema and are the shared language
between daemon, CLI, and database layer.

Hierarchy:
    Context
      └── Window      (persistent member, survives close)
            └── Tab   (mutable layout, removed on close)
                  └── Pane  (mutable layout, removed on close)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Pane:
    """
    A single terminal pane inside a tab.

    @param id: CW persistent UUID — survives iTerm restarts.
    @param tab_id: Parent tab this pane belongs to.
    @param parent_pane_id: Parent pane in the split tree (None = root).
    @param split_direction: 'horizontal' or 'vertical' (None for unsplit).
    @param profile: iTerm profile name used by this pane.
    @param title: Pane title (from iTerm or user-set).
    @param cwd: Last known working directory.
    @param hostname: Hostname (from shell integration).
    @param username: Username (from shell integration).
    @param relative_size: Fraction of parent split (0.0–1.0).
    """
    id: str
    tab_id: str
    parent_pane_id: str | None = None
    split_direction: str | None = None
    profile: str = ""
    title: str = ""
    cwd: str = ""
    hostname: str = ""
    username: str = ""
    relative_size: float | None = None


@dataclass
class Tab:
    """
    A tab inside a window, containing one or more panes.

    @param id: CW persistent UUID.
    @param window_id: Parent window this tab belongs to.
    @param title: Tab title.
    @param tab_order: Position index within the window (0-based).
    @param is_selected: Whether this tab is currently active/focused.
    @param panes: List of panes in this tab.
    """
    id: str
    window_id: str
    title: str = ""
    tab_order: int = 0
    is_selected: bool = False
    panes: list[Pane] = field(default_factory=list)


@dataclass
class Window:
    """
    A window belonging to a Context.

    Windows are *persistent members* of a Context — closing a window
    sets is_open=False but does NOT remove it from the Context.
    Only explicit `cw leave` or `cw remove-window` changes membership.

    @param id: CW persistent UUID.
    @param context_id: Parent Context this window belongs to.
    @param name: Semantic name (e.g. "Development", "Infrastructure").
    @param is_member: Whether this window is a member of the Context.
    @param is_open: Whether this window currently exists in iTerm.
    @param frame_x: Window X position on screen.
    @param frame_y: Window Y position on screen.
    @param frame_width: Window width in pixels.
    @param frame_height: Window height in pixels.
    @param fullscreen: Whether the window is in fullscreen mode.
    @param tabs: List of tabs in this window.
    """
    id: str
    context_id: str
    name: str = ""
    is_member: bool = True
    is_open: bool = True
    frame_x: float | None = None
    frame_y: float | None = None
    frame_width: float | None = None
    frame_height: float | None = None
    fullscreen: bool = False
    tabs: list[Tab] = field(default_factory=list)


@dataclass
class Context:
    """
    A named group of iTerm windows representing one project or activity.

    This is the top-level CW entity. A Context can be OPEN (some/all
    windows visible), PARTIAL (some windows open), or CLOSED (no windows
    visible but definition preserved).

    @param id: CW persistent UUID.
    @param name: Human-readable name (e.g. "EcoColabo").
    @param description: Optional longer description.
    @param is_deleted: Soft-delete flag (True = logically deleted).
    @param created_at: When the Context was first created.
    @param updated_at: When the Context was last modified.
    @param windows: List of windows belonging to this Context.
    """
    id: str
    name: str
    description: str = ""
    is_deleted: bool = False
    created_at: str = ""
    updated_at: str = ""
    windows: list[Window] = field(default_factory=list)

    @property
    def status(self) -> str:
        """
        Compute Context status from window states.

        @returns: 'OPEN' if all member windows are open,
                  'PARTIAL' if some are open,
                  'CLOSED' if none are open.
        """
        member_windows = [w for w in self.windows if w.is_member]
        if not member_windows:
            return "CLOSED"
        open_count = sum(1 for w in member_windows if w.is_open)
        if open_count == 0:
            return "CLOSED"
        if open_count == len(member_windows):
            return "OPEN"
        return "PARTIAL"

    @property
    def open_window_count(self) -> int:
        """Number of currently open member windows."""
        return sum(1 for w in self.windows if w.is_member and w.is_open)

    @property
    def total_window_count(self) -> int:
        """Total number of member windows (open + closed)."""
        return sum(1 for w in self.windows if w.is_member)


@dataclass
class IdMapping:
    """
    Maps a CW persistent ID to an iTerm runtime ID.

    iTerm IDs change every time a window/tab/session is recreated.
    CW IDs are stable across restarts.

    @param cw_id: CW persistent UUID.
    @param iterm_id: Current iTerm runtime ID (e.g. "w0t17").
    @param object_type: One of 'window', 'tab', 'session'.
    @param is_active: False when the iTerm object no longer exists.
    """
    cw_id: str
    iterm_id: str
    object_type: str
    is_active: bool = True


@dataclass
class StateLogEntry:
    """
    A historical snapshot of a Context's state at a point in time.

    @param id: Auto-increment row ID.
    @param context_id: Which Context this snapshot belongs to.
    @param event_type: What triggered the snapshot (e.g. 'manual_save',
                       'window_close', 'layout_change', 'reconciliation').
    @param snapshot_json: Full Context state serialized as JSON.
    @param created_at: When the snapshot was taken.
    """
    id: int
    context_id: str
    event_type: str
    snapshot_json: str
    created_at: str
