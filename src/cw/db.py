"""
CW database layer — SQLite schema, CRUD operations, and atomic transactions.

This module is the ONLY place that touches the database file.
Both daemon and CLI import from here. Concurrent access is safe
because we use WAL mode (one writer + many readers).

Database location: ~/.contextual-walker/cw.sqlite
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from cw.constants import DB_PATH, CW_HOME
from cw.models import Context, IdMapping, Pane, StateLogEntry, Tab, Window


# ─── Schema ────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Contexts: top-level named groups of windows
CREATE TABLE IF NOT EXISTS contexts (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    is_deleted      INTEGER NOT NULL DEFAULT 0
);

-- Windows: persistent members of a Context
-- Closing a window sets is_open=0 but keeps is_member=1.
CREATE TABLE IF NOT EXISTS windows (
    id              TEXT PRIMARY KEY,
    context_id      TEXT NOT NULL REFERENCES contexts(id) ON DELETE CASCADE,
    name            TEXT NOT NULL DEFAULT '',
    is_member       INTEGER NOT NULL DEFAULT 1,
    is_open         INTEGER NOT NULL DEFAULT 1,
    frame_x         REAL,
    frame_y         REAL,
    frame_width     REAL,
    frame_height    REAL,
    fullscreen      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Tabs: mutable layout inside a window
CREATE TABLE IF NOT EXISTS tabs (
    id              TEXT PRIMARY KEY,
    window_id       TEXT NOT NULL REFERENCES windows(id) ON DELETE CASCADE,
    title           TEXT NOT NULL DEFAULT '',
    tab_order       INTEGER NOT NULL DEFAULT 0,
    is_selected     INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL
);

-- Panes: terminal sessions inside a tab, with split tree structure
CREATE TABLE IF NOT EXISTS panes (
    id              TEXT PRIMARY KEY,
    tab_id          TEXT NOT NULL REFERENCES tabs(id) ON DELETE CASCADE,
    parent_pane_id  TEXT REFERENCES panes(id) ON DELETE SET NULL,
    split_direction TEXT,
    profile         TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    cwd             TEXT NOT NULL DEFAULT '',
    hostname        TEXT NOT NULL DEFAULT '',
    username        TEXT NOT NULL DEFAULT '',
    relative_size   REAL,
    updated_at      TEXT NOT NULL
);

-- ID mappings: CW persistent UUID ↔ iTerm runtime ID
-- iTerm IDs change on every window/tab/session recreation.
CREATE TABLE IF NOT EXISTS id_mappings (
    cw_id           TEXT NOT NULL,
    iterm_id        TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (cw_id, iterm_id)
);
CREATE INDEX IF NOT EXISTS idx_mappings_iterm_active
    ON id_mappings(iterm_id) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_mappings_cw_active
    ON id_mappings(cw_id) WHERE is_active = 1;

-- State log: historical snapshots for cw history / cw restore
CREATE TABLE IF NOT EXISTS state_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    context_id      TEXT NOT NULL REFERENCES contexts(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    snapshot_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_state_log_ctx_time
    ON state_log(context_id, created_at DESC);
"""


# ─── Helpers ───────────────────────────────────────────────────────

def _now() -> str:
    """ISO-8601 UTC timestamp for consistent time recording."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_id() -> str:
    """Generate a new CW persistent UUID."""
    return str(uuid.uuid4())


# ─── Database connection ──────────────────────────────────────────

class CwDatabase:
    """
    SQLite database wrapper for all CW persistence operations.

    Usage:
        db = CwDatabase()        # opens/creates DB at default path
        db.init_schema()         # creates tables if missing
        ctx = db.create_context("MyProject")
    """

    def __init__(self, db_path: Path = DB_PATH):
        """
        Open (or create) the CW database.

        @param db_path: Path to the SQLite file. Parent dirs created automatically.
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(
            str(db_path),
            # Allow concurrent reads while daemon writes
            isolation_level=None,  # autocommit off — we manage transactions ourselves
        )
        self.conn.row_factory = sqlite3.Row
        # Enable WAL mode for safe concurrent access (daemon writes, CLI reads)
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Enable foreign key enforcement
        self.conn.execute("PRAGMA foreign_keys=ON")

    def init_schema(self) -> None:
        """Create all tables and indexes if they don't exist."""
        self.conn.executescript(SCHEMA_SQL)

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Cursor, None, None]:
        """
        Atomic transaction context manager.

        All changes inside the `with` block are committed together,
        or rolled back if an exception occurs. This is how we ensure
        crash-safety — a half-written state is never persisted.

        Usage:
            with db.transaction() as cursor:
                cursor.execute(...)
                cursor.execute(...)
            # committed here
        """
        cursor = self.conn.cursor()
        cursor.execute("BEGIN")
        try:
            yield cursor
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise

    # ─── Context CRUD ──────────────────────────────────────────────

    def create_context(self, name: str, description: str = "") -> Context:
        """
        Create a new Context.

        @param name: Unique human-readable name (e.g. "EcoColabo").
        @param description: Optional longer description.
        @returns: The newly created Context object.
        @raises sqlite3.IntegrityError: If a Context with this name already exists.
        """
        context_id = _new_id()
        now = _now()
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO contexts (id, name, description, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (context_id, name, description, now, now),
            )
        return Context(
            id=context_id, name=name, description=description,
            created_at=now, updated_at=now,
        )

    def get_context_by_name(self, name: str) -> Context | None:
        """
        Look up a Context by its unique name.

        @param name: Context name to search for.
        @returns: Context with all its windows/tabs/panes loaded, or None.
        """
        row = self.conn.execute(
            "SELECT * FROM contexts WHERE name = ? AND is_deleted = 0", (name,)
        ).fetchone()
        if row is None:
            return None
        return self._load_full_context(row)

    def get_context_by_id(self, context_id: str) -> Context | None:
        """
        Look up a Context by its UUID.

        @param context_id: CW persistent UUID.
        @returns: Context with all its windows/tabs/panes loaded, or None.
        """
        row = self.conn.execute(
            "SELECT * FROM contexts WHERE id = ? AND is_deleted = 0", (context_id,)
        ).fetchone()
        if row is None:
            return None
        return self._load_full_context(row)

    def list_contexts(self) -> list[Context]:
        """
        List all non-deleted Contexts with their full hierarchy loaded.

        @returns: List of Context objects, each with windows/tabs/panes.
        """
        rows = self.conn.execute(
            "SELECT * FROM contexts WHERE is_deleted = 0 ORDER BY name"
        ).fetchall()
        return [self._load_full_context(row) for row in rows]

    def delete_context(self, context_id: str) -> None:
        """
        Soft-delete a Context (set is_deleted=1). NOT a purge.

        @param context_id: CW persistent UUID of the Context to delete.
        """
        with self.transaction() as cursor:
            cursor.execute(
                "UPDATE contexts SET is_deleted = 1, updated_at = ? WHERE id = ?",
                (_now(), context_id),
            )

    def _load_full_context(self, row: sqlite3.Row) -> Context:
        """
        Build a complete Context object from a DB row, including all
        windows, tabs, and panes.

        @param row: A sqlite3.Row from the contexts table.
        @returns: Fully populated Context dataclass.
        """
        context = Context(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            is_deleted=bool(row["is_deleted"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        # Load windows for this context
        window_rows = self.conn.execute(
            "SELECT * FROM windows WHERE context_id = ? ORDER BY name",
            (context.id,),
        ).fetchall()
        for window_row in window_rows:
            window = Window(
                id=window_row["id"],
                context_id=window_row["context_id"],
                name=window_row["name"],
                is_member=bool(window_row["is_member"]),
                is_open=bool(window_row["is_open"]),
                frame_x=window_row["frame_x"],
                frame_y=window_row["frame_y"],
                frame_width=window_row["frame_width"],
                frame_height=window_row["frame_height"],
                fullscreen=bool(window_row["fullscreen"]),
            )
            # Load tabs for this window
            tab_rows = self.conn.execute(
                "SELECT * FROM tabs WHERE window_id = ? ORDER BY tab_order",
                (window.id,),
            ).fetchall()
            for tab_row in tab_rows:
                tab = Tab(
                    id=tab_row["id"],
                    window_id=tab_row["window_id"],
                    title=tab_row["title"],
                    tab_order=tab_row["tab_order"],
                    is_selected=bool(tab_row["is_selected"]),
                )
                # Load panes for this tab
                pane_rows = self.conn.execute(
                    "SELECT * FROM panes WHERE tab_id = ? ORDER BY id",
                    (tab.id,),
                ).fetchall()
                for pane_row in pane_rows:
                    tab.panes.append(Pane(
                        id=pane_row["id"],
                        tab_id=pane_row["tab_id"],
                        parent_pane_id=pane_row["parent_pane_id"],
                        split_direction=pane_row["split_direction"],
                        profile=pane_row["profile"],
                        title=pane_row["title"],
                        cwd=pane_row["cwd"],
                        hostname=pane_row["hostname"],
                        username=pane_row["username"],
                        relative_size=pane_row["relative_size"],
                    ))
                window.tabs.append(tab)
            context.windows.append(window)
        return context

    # ─── Window CRUD ───────────────────────────────────────────────

    def create_window(
        self, context_id: str, name: str = "",
        frame_x: float | None = None, frame_y: float | None = None,
        frame_width: float | None = None, frame_height: float | None = None,
        fullscreen: bool = False,
    ) -> Window:
        """
        Add a new window to a Context.

        @param context_id: UUID of the parent Context.
        @param name: Semantic name for the window (e.g. "Development").
        @returns: The newly created Window.
        """
        window_id = _new_id()
        now = _now()
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO windows
                   (id, context_id, name, is_member, is_open,
                    frame_x, frame_y, frame_width, frame_height, fullscreen,
                    created_at, updated_at)
                   VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?)""",
                (window_id, context_id, name,
                 frame_x, frame_y, frame_width, frame_height, int(fullscreen),
                 now, now),
            )
            # Update context timestamp
            cursor.execute(
                "UPDATE contexts SET updated_at = ? WHERE id = ?",
                (now, context_id),
            )
        return Window(
            id=window_id, context_id=context_id, name=name,
            frame_x=frame_x, frame_y=frame_y,
            frame_width=frame_width, frame_height=frame_height,
            fullscreen=fullscreen,
        )

    def update_window_state(
        self, window_id: str, *,
        is_open: bool | None = None,
        is_member: bool | None = None,
        name: str | None = None,
        frame_x: float | None = None, frame_y: float | None = None,
        frame_width: float | None = None, frame_height: float | None = None,
        fullscreen: bool | None = None,
    ) -> None:
        """
        Update one or more fields on a window.

        Only provided (non-None) fields are updated. This is how
        the daemon records state changes without overwriting unrelated fields.

        @param window_id: CW UUID of the window to update.
        """
        updates: list[str] = []
        values: list[object] = []
        if is_open is not None:
            updates.append("is_open = ?")
            values.append(int(is_open))
        if is_member is not None:
            updates.append("is_member = ?")
            values.append(int(is_member))
        if name is not None:
            updates.append("name = ?")
            values.append(name)
        if frame_x is not None:
            updates.append("frame_x = ?")
            values.append(frame_x)
        if frame_y is not None:
            updates.append("frame_y = ?")
            values.append(frame_y)
        if frame_width is not None:
            updates.append("frame_width = ?")
            values.append(frame_width)
        if frame_height is not None:
            updates.append("frame_height = ?")
            values.append(frame_height)
        if fullscreen is not None:
            updates.append("fullscreen = ?")
            values.append(int(fullscreen))
        if not updates:
            return
        updates.append("updated_at = ?")
        values.append(_now())
        values.append(window_id)
        with self.transaction() as cursor:
            cursor.execute(
                f"UPDATE windows SET {', '.join(updates)} WHERE id = ?",
                values,
            )

    def get_window_by_id(self, window_id: str) -> Window | None:
        """
        Look up a single window by its CW UUID.

        @param window_id: CW persistent UUID.
        @returns: Window (without tabs/panes loaded), or None.
        """
        row = self.conn.execute(
            "SELECT * FROM windows WHERE id = ?", (window_id,)
        ).fetchone()
        if row is None:
            return None
        return Window(
            id=row["id"], context_id=row["context_id"], name=row["name"],
            is_member=bool(row["is_member"]), is_open=bool(row["is_open"]),
            frame_x=row["frame_x"], frame_y=row["frame_y"],
            frame_width=row["frame_width"], frame_height=row["frame_height"],
            fullscreen=bool(row["fullscreen"]),
        )

    # ─── Tab CRUD ──────────────────────────────────────────────────

    def create_tab(
        self, window_id: str, title: str = "",
        tab_order: int = 0, is_selected: bool = False,
    ) -> Tab:
        """
        Add a new tab to a window.

        @param window_id: CW UUID of the parent window.
        @param title: Tab title.
        @param tab_order: Position within the window (0-based).
        @param is_selected: Whether this is the active tab.
        @returns: The newly created Tab.
        """
        tab_id = _new_id()
        now = _now()
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO tabs (id, window_id, title, tab_order, is_selected, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (tab_id, window_id, title, tab_order, int(is_selected), now),
            )
        return Tab(id=tab_id, window_id=window_id, title=title,
                   tab_order=tab_order, is_selected=is_selected)

    def delete_tabs_for_window(self, window_id: str) -> None:
        """
        Remove all tabs (and their panes via CASCADE) for a window.

        Used before re-syncing the full tab/pane layout from iTerm.

        @param window_id: CW UUID of the window whose tabs to remove.
        """
        with self.transaction() as cursor:
            cursor.execute("DELETE FROM tabs WHERE window_id = ?", (window_id,))

    # ─── Pane CRUD ─────────────────────────────────────────────────

    def create_pane(
        self, tab_id: str, *,
        parent_pane_id: str | None = None,
        split_direction: str | None = None,
        profile: str = "", title: str = "",
        cwd: str = "", hostname: str = "", username: str = "",
        relative_size: float | None = None,
    ) -> Pane:
        """
        Add a new pane to a tab.

        @param tab_id: CW UUID of the parent tab.
        @param parent_pane_id: Parent pane in split tree (None = root).
        @param split_direction: 'horizontal' or 'vertical'.
        @param cwd: Current working directory of the pane.
        @returns: The newly created Pane.
        """
        pane_id = _new_id()
        now = _now()
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO panes
                   (id, tab_id, parent_pane_id, split_direction,
                    profile, title, cwd, hostname, username,
                    relative_size, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pane_id, tab_id, parent_pane_id, split_direction,
                 profile, title, cwd, hostname, username,
                 relative_size, now),
            )
        return Pane(
            id=pane_id, tab_id=tab_id,
            parent_pane_id=parent_pane_id, split_direction=split_direction,
            profile=profile, title=title, cwd=cwd,
            hostname=hostname, username=username, relative_size=relative_size,
        )

    # ─── ID Mapping ───────────────────────────────────────────────

    def set_mapping(self, cw_id: str, iterm_id: str, object_type: str) -> None:
        """
        Record a mapping between a CW UUID and an iTerm runtime ID.

        Deactivates any previous active mapping for the same cw_id,
        then creates the new one.

        @param cw_id: CW persistent UUID.
        @param iterm_id: iTerm runtime ID (e.g. "w0t17").
        @param object_type: One of 'window', 'tab', 'session'.
        """
        now = _now()
        with self.transaction() as cursor:
            # Deactivate old mappings for this CW object
            cursor.execute(
                """UPDATE id_mappings SET is_active = 0
                   WHERE cw_id = ? AND is_active = 1""",
                (cw_id,),
            )
            # Insert new mapping
            cursor.execute(
                """INSERT OR REPLACE INTO id_mappings
                   (cw_id, iterm_id, object_type, is_active, created_at)
                   VALUES (?, ?, ?, 1, ?)""",
                (cw_id, iterm_id, object_type, now),
            )

    def get_cw_id_for_iterm(self, iterm_id: str) -> str | None:
        """
        Find the CW UUID that maps to a given iTerm runtime ID.

        @param iterm_id: iTerm runtime ID to look up.
        @returns: CW UUID, or None if no active mapping.
        """
        row = self.conn.execute(
            """SELECT cw_id FROM id_mappings
               WHERE iterm_id = ? AND is_active = 1""",
            (iterm_id,),
        ).fetchone()
        return row["cw_id"] if row else None

    def get_iterm_id_for_cw(self, cw_id: str) -> str | None:
        """
        Find the active iTerm runtime ID for a CW UUID.

        @param cw_id: CW persistent UUID to look up.
        @returns: iTerm runtime ID, or None if no active mapping.
        """
        row = self.conn.execute(
            """SELECT iterm_id FROM id_mappings
               WHERE cw_id = ? AND is_active = 1""",
            (cw_id,),
        ).fetchone()
        return row["iterm_id"] if row else None

    def get_all_active_mappings(self, object_type: str | None = None) -> list[IdMapping]:
        """
        Get all active ID mappings, optionally filtered by type.

        @param object_type: Filter by 'window', 'tab', or 'session'. None = all.
        @returns: List of active IdMapping objects.
        """
        if object_type:
            rows = self.conn.execute(
                """SELECT * FROM id_mappings
                   WHERE is_active = 1 AND object_type = ?""",
                (object_type,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM id_mappings WHERE is_active = 1"
            ).fetchall()
        return [
            IdMapping(
                cw_id=r["cw_id"], iterm_id=r["iterm_id"],
                object_type=r["object_type"], is_active=True,
            )
            for r in rows
        ]

    def deactivate_mappings_for_cw_id(self, cw_id: str) -> None:
        """
        Mark all mappings for a CW object as inactive.

        Called when an iTerm object disappears (closed).

        @param cw_id: CW persistent UUID whose mappings to deactivate.
        """
        with self.transaction() as cursor:
            cursor.execute(
                "UPDATE id_mappings SET is_active = 0 WHERE cw_id = ? AND is_active = 1",
                (cw_id,),
            )

    # ─── State Log (history/snapshots) ─────────────────────────────

    def save_snapshot(self, context_id: str, event_type: str) -> None:
        """
        Save a complete snapshot of a Context's current state to the log.

        This is how `cw history` and `cw restore` work — each snapshot
        captures the full Context tree as JSON.

        @param context_id: CW UUID of the Context to snapshot.
        @param event_type: Why the snapshot was taken (e.g. 'manual_save',
                           'window_close', 'layout_change').
        """
        context = self.get_context_by_id(context_id)
        if context is None:
            return
        snapshot_data = _context_to_dict(context)
        now = _now()
        with self.transaction() as cursor:
            cursor.execute(
                """INSERT INTO state_log (context_id, event_type, snapshot_json, created_at)
                   VALUES (?, ?, ?, ?)""",
                (context_id, event_type, json.dumps(snapshot_data, ensure_ascii=False), now),
            )

    def get_history(self, context_id: str, limit: int = 20) -> list[StateLogEntry]:
        """
        Get recent snapshots for a Context, newest first.

        @param context_id: CW UUID of the Context.
        @param limit: Maximum number of entries to return.
        @returns: List of StateLogEntry objects.
        """
        rows = self.conn.execute(
            """SELECT * FROM state_log
               WHERE context_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (context_id, limit),
        ).fetchall()
        return [
            StateLogEntry(
                id=r["id"], context_id=r["context_id"],
                event_type=r["event_type"], snapshot_json=r["snapshot_json"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ─── Bulk sync (used by reconciler) ────────────────────────────

    def sync_window_layout(
        self, window_id: str, tabs_data: list[dict],
    ) -> None:
        """
        Replace all tabs and panes for a window with fresh data from iTerm.

        This is an atomic operation — old layout is deleted and new one
        written in a single transaction.

        @param window_id: CW UUID of the window to sync.
        @param tabs_data: List of tab dicts, each containing:
            - title: str
            - tab_order: int
            - is_selected: bool
            - iterm_id: str (iTerm tab ID for mapping)
            - panes: list of pane dicts with fields matching Pane dataclass
        """
        now = _now()
        with self.transaction() as cursor:
            # Remove old tabs (panes cascade-deleted)
            cursor.execute("DELETE FROM tabs WHERE window_id = ?", (window_id,))
            for tab_data in tabs_data:
                tab_id = _new_id()
                cursor.execute(
                    """INSERT INTO tabs (id, window_id, title, tab_order, is_selected, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (tab_id, window_id, tab_data.get("title", ""),
                     tab_data.get("tab_order", 0),
                     int(tab_data.get("is_selected", False)), now),
                )
                # Map iTerm tab ID → CW tab ID
                iterm_tab_id = tab_data.get("iterm_id")
                if iterm_tab_id:
                    # Deactivate old tab mapping
                    cursor.execute(
                        "UPDATE id_mappings SET is_active = 0 WHERE iterm_id = ? AND is_active = 1",
                        (iterm_tab_id,),
                    )
                    cursor.execute(
                        """INSERT OR REPLACE INTO id_mappings
                           (cw_id, iterm_id, object_type, is_active, created_at)
                           VALUES (?, ?, 'tab', 1, ?)""",
                        (tab_id, iterm_tab_id, now),
                    )
                for pane_data in tab_data.get("panes", []):
                    pane_id = _new_id()
                    cursor.execute(
                        """INSERT INTO panes
                           (id, tab_id, parent_pane_id, split_direction,
                            profile, title, cwd, hostname, username,
                            relative_size, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (pane_id, tab_id,
                         pane_data.get("parent_pane_id"),
                         pane_data.get("split_direction"),
                         pane_data.get("profile", ""),
                         pane_data.get("title", ""),
                         pane_data.get("cwd", ""),
                         pane_data.get("hostname", ""),
                         pane_data.get("username", ""),
                         pane_data.get("relative_size"),
                         now),
                    )
                    # Map iTerm session ID → CW pane ID
                    iterm_session_id = pane_data.get("iterm_id")
                    if iterm_session_id:
                        cursor.execute(
                            "UPDATE id_mappings SET is_active = 0 WHERE iterm_id = ? AND is_active = 1",
                            (iterm_session_id,),
                        )
                        cursor.execute(
                            """INSERT OR REPLACE INTO id_mappings
                               (cw_id, iterm_id, object_type, is_active, created_at)
                               VALUES (?, ?, 'session', 1, ?)""",
                            (pane_id, iterm_session_id, now),
                        )


# ─── Serialization helper ──────────────────────────────────────────

def _context_to_dict(context: Context) -> dict:
    """
    Serialize a full Context tree to a dict for JSON snapshot storage.

    @param context: Context object with windows/tabs/panes loaded.
    @returns: Dict suitable for json.dumps().
    """
    return {
        "id": context.id,
        "name": context.name,
        "description": context.description,
        "windows": [
            {
                "id": w.id,
                "name": w.name,
                "is_member": w.is_member,
                "is_open": w.is_open,
                "frame": [w.frame_x, w.frame_y, w.frame_width, w.frame_height],
                "fullscreen": w.fullscreen,
                "tabs": [
                    {
                        "id": t.id,
                        "title": t.title,
                        "tab_order": t.tab_order,
                        "is_selected": t.is_selected,
                        "panes": [
                            {
                                "id": p.id,
                                "cwd": p.cwd,
                                "title": p.title,
                                "profile": p.profile,
                                "hostname": p.hostname,
                                "username": p.username,
                                "split_direction": p.split_direction,
                                "relative_size": p.relative_size,
                            }
                            for p in t.panes
                        ],
                    }
                    for t in w.tabs
                ],
            }
            for w in context.windows
        ],
    }
