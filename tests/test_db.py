"""
Tests for CW database layer.

These tests use an in-memory SQLite database, so they don't
touch the real CW database.
"""

from pathlib import Path
import tempfile

import pytest

from cw.db import CwDatabase


@pytest.fixture
def database(tmp_path: Path) -> CwDatabase:
    """Create a fresh CW database in a temp directory."""
    db_path = tmp_path / "test_cw.sqlite"
    db = CwDatabase(db_path=db_path)
    db.init_schema()
    yield db
    db.close()


class TestContextCRUD:
    """Tests for Context create/read/list/delete."""

    def test_create_context(self, database: CwDatabase):
        """Creating a Context returns a valid object with generated UUID."""
        context = database.create_context("TestProject", "A test project")
        assert context.name == "TestProject"
        assert context.description == "A test project"
        assert context.id  # UUID should be non-empty
        assert not context.is_deleted

    def test_get_context_by_name(self, database: CwDatabase):
        """Can retrieve a Context by its unique name."""
        database.create_context("MyProject")
        found = database.get_context_by_name("MyProject")
        assert found is not None
        assert found.name == "MyProject"

    def test_get_context_not_found(self, database: CwDatabase):
        """Looking up a nonexistent Context returns None."""
        assert database.get_context_by_name("DoesNotExist") is None

    def test_list_contexts(self, database: CwDatabase):
        """list_contexts returns all non-deleted Contexts."""
        database.create_context("Alpha")
        database.create_context("Beta")
        contexts = database.list_contexts()
        names = [c.name for c in contexts]
        assert "Alpha" in names
        assert "Beta" in names

    def test_soft_delete_context(self, database: CwDatabase):
        """Soft-deleted Contexts don't appear in list or lookup."""
        context = database.create_context("ToDelete")
        database.delete_context(context.id)
        assert database.get_context_by_name("ToDelete") is None
        assert all(c.name != "ToDelete" for c in database.list_contexts())

    def test_duplicate_name_raises(self, database: CwDatabase):
        """Cannot create two Contexts with the same name."""
        database.create_context("Unique")
        with pytest.raises(Exception):
            database.create_context("Unique")


class TestWindowCRUD:
    """Tests for Window operations."""

    def test_create_window(self, database: CwDatabase):
        """Creating a window under a context works."""
        context = database.create_context("Proj")
        window = database.create_window(context.id, name="Dev")
        assert window.context_id == context.id
        assert window.name == "Dev"
        assert window.is_open
        assert window.is_member

    def test_window_appears_in_context(self, database: CwDatabase):
        """Windows are loaded when fetching a Context."""
        context = database.create_context("Proj")
        database.create_window(context.id, name="Dev")
        database.create_window(context.id, name="Infra")
        loaded = database.get_context_by_name("Proj")
        assert len(loaded.windows) == 2
        window_names = [w.name for w in loaded.windows]
        assert "Dev" in window_names
        assert "Infra" in window_names

    def test_update_window_state(self, database: CwDatabase):
        """Can update individual window fields."""
        context = database.create_context("Proj")
        window = database.create_window(context.id, name="Dev")
        database.update_window_state(window.id, is_open=False)
        updated = database.get_window_by_id(window.id)
        assert not updated.is_open
        assert updated.is_member  # closing doesn't change membership

    def test_context_status_computation(self, database: CwDatabase):
        """Context status reflects window open/closed states."""
        context = database.create_context("Proj")
        w1 = database.create_window(context.id, name="A")
        w2 = database.create_window(context.id, name="B")

        # Both open → OPEN
        loaded = database.get_context_by_name("Proj")
        assert loaded.status == "OPEN"

        # Close one → PARTIAL
        database.update_window_state(w1.id, is_open=False)
        loaded = database.get_context_by_name("Proj")
        assert loaded.status == "PARTIAL"

        # Close both → CLOSED
        database.update_window_state(w2.id, is_open=False)
        loaded = database.get_context_by_name("Proj")
        assert loaded.status == "CLOSED"


class TestIdMapping:
    """Tests for CW ↔ iTerm ID mapping."""

    def test_set_and_get_mapping(self, database: CwDatabase):
        """Can create and retrieve an ID mapping."""
        database.set_mapping("cw-123", "w0t17", "window")
        assert database.get_cw_id_for_iterm("w0t17") == "cw-123"
        assert database.get_iterm_id_for_cw("cw-123") == "w0t17"

    def test_remapping_deactivates_old(self, database: CwDatabase):
        """Setting a new mapping for same CW ID deactivates the old one."""
        database.set_mapping("cw-123", "w0t17", "window")
        database.set_mapping("cw-123", "w0t99", "window")
        # New mapping active
        assert database.get_iterm_id_for_cw("cw-123") == "w0t99"
        # Old mapping no longer active
        assert database.get_cw_id_for_iterm("w0t17") is None

    def test_deactivate_mappings(self, database: CwDatabase):
        """Can deactivate all mappings for a CW ID."""
        database.set_mapping("cw-123", "w0t17", "window")
        database.deactivate_mappings_for_cw_id("cw-123")
        assert database.get_iterm_id_for_cw("cw-123") is None


class TestStateLog:
    """Tests for snapshot/history functionality."""

    def test_save_and_get_history(self, database: CwDatabase):
        """Can save a snapshot and retrieve it from history."""
        context = database.create_context("Proj")
        database.create_window(context.id, name="Dev")
        database.save_snapshot(context.id, "manual_save")

        history = database.get_history(context.id)
        assert len(history) == 1
        assert history[0].event_type == "manual_save"
        assert '"name": "Proj"' in history[0].snapshot_json

    def test_history_ordered_newest_first(self, database: CwDatabase):
        """History entries are returned newest first."""
        context = database.create_context("Proj")
        database.save_snapshot(context.id, "first")
        database.save_snapshot(context.id, "second")
        database.save_snapshot(context.id, "third")

        history = database.get_history(context.id)
        assert history[0].event_type == "third"
        assert history[-1].event_type == "first"


class TestSyncWindowLayout:
    """Tests for bulk layout sync (used by reconciler)."""

    def test_sync_creates_tabs_and_panes(self, database: CwDatabase):
        """sync_window_layout replaces all tabs/panes atomically."""
        context = database.create_context("Proj")
        window = database.create_window(context.id, name="Dev")

        tabs_data = [
            {
                "title": "frontend",
                "tab_order": 0,
                "is_selected": True,
                "iterm_id": "tab-1",
                "panes": [
                    {"iterm_id": "sess-1", "cwd": "/home/user/frontend", "title": "dev"},
                    {"iterm_id": "sess-2", "cwd": "/home/user/frontend", "title": "git"},
                ],
            },
            {
                "title": "backend",
                "tab_order": 1,
                "is_selected": False,
                "iterm_id": "tab-2",
                "panes": [
                    {"iterm_id": "sess-3", "cwd": "/home/user/backend", "title": "api"},
                ],
            },
        ]
        database.sync_window_layout(window.id, tabs_data)

        # Reload and verify
        loaded = database.get_context_by_name("Proj")
        dev_window = loaded.windows[0]
        assert len(dev_window.tabs) == 2
        assert dev_window.tabs[0].title == "frontend"
        assert len(dev_window.tabs[0].panes) == 2
        assert dev_window.tabs[0].panes[0].cwd == "/home/user/frontend"
        assert dev_window.tabs[1].title == "backend"
        assert len(dev_window.tabs[1].panes) == 1
