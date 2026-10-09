"""Tests for DB schema migrations."""

import sqlite3
from pathlib import Path

import pytest

from cw.db import CwDatabase


@pytest.fixture
def old_db(tmp_path: Path) -> Path:
    """Create a DB without is_active column (simulates old schema)."""
    db_path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE contexts (
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, is_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE windows (
            id TEXT PRIMARY KEY, context_id TEXT NOT NULL,
            name TEXT DEFAULT '', is_member INTEGER DEFAULT 1,
            is_open INTEGER DEFAULT 1, frame_x REAL, frame_y REAL,
            frame_width REAL, frame_height REAL,
            fullscreen INTEGER DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE tabs (
            id TEXT PRIMARY KEY, window_id TEXT NOT NULL,
            title TEXT DEFAULT '', tab_order INTEGER DEFAULT 0,
            is_selected INTEGER DEFAULT 0, updated_at TEXT NOT NULL
        );
        CREATE TABLE panes (
            id TEXT PRIMARY KEY, tab_id TEXT NOT NULL,
            parent_pane_id TEXT, split_direction TEXT,
            profile TEXT DEFAULT '', title TEXT DEFAULT '',
            cwd TEXT DEFAULT '', hostname TEXT DEFAULT '',
            username TEXT DEFAULT '', relative_size REAL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS id_mappings (
            cw_id TEXT NOT NULL, iterm_id TEXT NOT NULL,
            object_type TEXT NOT NULL, is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL, PRIMARY KEY (cw_id, iterm_id)
        );
        CREATE TABLE IF NOT EXISTS state_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            context_id TEXT NOT NULL, event_type TEXT NOT NULL,
            snapshot_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
    """)
    conn.close()
    return db_path


class TestMigration:
    """Tests for schema migration (adding is_active to panes)."""

    def test_old_db_gets_is_active_column(self, old_db: Path):
        """Opening old DB and calling init_schema adds is_active column."""
        db = CwDatabase(db_path=old_db)
        db.init_schema()
        # Should not raise
        row = db.conn.execute("SELECT is_active FROM panes LIMIT 1").fetchone()
        db.close()

    def test_new_db_has_is_active(self, tmp_path: Path):
        """Fresh DB has is_active column from the start."""
        db = CwDatabase(db_path=tmp_path / "new.sqlite")
        db.init_schema()
        ctx = db.create_context("Test")
        win = db.create_window(ctx.id, name="Win")
        tab = db.create_tab(win.id, title="Tab1")
        pane = db.create_pane(tab.id)
        loaded = db.get_context_by_name("Test")
        assert loaded.windows[0].tabs[0].panes[0].is_active is False
        db.close()
