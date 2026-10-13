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

    def test_sync_preserves_existing_pane_uuids(self, database: CwDatabase):
        """sync_window_layout must reuse existing pane UUIDs when mapping exists.
        This is critical for per-pane history files — UUID change = history lost."""
        context = database.create_context("Proj")
        window = database.create_window(context.id, name="Dev")

        # First sync — creates initial pane UUIDs
        tabs_data_v1 = [{
            "title": "tab1", "tab_order": 0, "is_selected": True,
            "iterm_id": "tab-100",
            "panes": [
                {"iterm_id": "sess-100", "cwd": "/app", "title": "dev"},
                {"iterm_id": "sess-101", "cwd": "/app", "title": "git"},
            ],
        }]
        database.sync_window_layout(window.id, tabs_data_v1)

        # Capture the generated UUIDs
        pane1_uuid = database.get_cw_id_for_iterm("sess-100")
        pane2_uuid = database.get_cw_id_for_iterm("sess-101")
        tab_uuid = database.get_cw_id_for_iterm("tab-100")
        assert pane1_uuid is not None
        assert pane2_uuid is not None

        # Second sync — same iTerm IDs, should KEEP the same UUIDs
        tabs_data_v2 = [{
            "title": "tab1-updated", "tab_order": 0, "is_selected": True,
            "iterm_id": "tab-100",
            "panes": [
                {"iterm_id": "sess-100", "cwd": "/app/new", "title": "dev-updated"},
                {"iterm_id": "sess-101", "cwd": "/app", "title": "git"},
            ],
        }]
        database.sync_window_layout(window.id, tabs_data_v2)

        # UUIDs must be the SAME
        assert database.get_cw_id_for_iterm("sess-100") == pane1_uuid
        assert database.get_cw_id_for_iterm("sess-101") == pane2_uuid
        assert database.get_cw_id_for_iterm("tab-100") == tab_uuid

        # Data should be updated
        loaded = database.get_context_by_name("Proj")
        assert loaded.windows[0].tabs[0].title == "tab1-updated"
        # Find pane by UUID (order may vary)
        pane_cwds = {p.id: p.cwd for p in loaded.windows[0].tabs[0].panes}
        assert pane_cwds[pane1_uuid] == "/app/new"
        assert pane_cwds[pane2_uuid] == "/app"

    def test_sync_generates_new_uuid_for_new_sessions(self, database: CwDatabase):
        """New iTerm sessions (not seen before) get new UUIDs."""
        context = database.create_context("Proj")
        window = database.create_window(context.id, name="Dev")

        tabs_data = [{
            "title": "tab1", "tab_order": 0, "is_selected": True,
            "iterm_id": "tab-200",
            "panes": [
                {"iterm_id": "sess-200", "cwd": "/app", "title": "dev"},
            ],
        }]
        database.sync_window_layout(window.id, tabs_data)
        uuid_first = database.get_cw_id_for_iterm("sess-200")

        # Sync with a DIFFERENT session ID (simulates restore with new iTerm session)
        tabs_data_new = [{
            "title": "tab1", "tab_order": 0, "is_selected": True,
            "iterm_id": "tab-201",
            "panes": [
                {"iterm_id": "sess-999", "cwd": "/app", "title": "dev"},
            ],
        }]
        database.sync_window_layout(window.id, tabs_data_new)
        uuid_new = database.get_cw_id_for_iterm("sess-999")

        # New session → new UUID (different from first)
        assert uuid_new is not None
        assert uuid_new != uuid_first

    def test_sync_preserves_uuid_after_pre_mapping(self, database: CwDatabase):
        """Simulates cw open flow: pre-create mapping, then sync reuses it."""
        context = database.create_context("Proj")
        window = database.create_window(context.id, name="Dev")

        # First sync — original session
        tabs_data_v1 = [{
            "title": "tab1", "tab_order": 0, "is_selected": True,
            "iterm_id": "tab-300",
            "panes": [
                {"iterm_id": "sess-300", "cwd": "/app", "title": "dev"},
            ],
        }]
        database.sync_window_layout(window.id, tabs_data_v1)
        original_uuid = database.get_cw_id_for_iterm("sess-300")

        # Simulate close: deactivate mapping
        database.deactivate_mappings_for_cw_id(original_uuid)

        # Simulate open: pre-create mapping OLD_UUID → NEW_SESSION
        database.set_mapping(original_uuid, "sess-NEW", "session")

        # Sync with new session ID
        tabs_data_v2 = [{
            "title": "tab1", "tab_order": 0, "is_selected": True,
            "iterm_id": "tab-301",
            "panes": [
                {"iterm_id": "sess-NEW", "cwd": "/app", "title": "dev"},
            ],
        }]
        database.sync_window_layout(window.id, tabs_data_v2)

        # UUID must be the SAME as original (preserved across close/open)
        assert database.get_cw_id_for_iterm("sess-NEW") == original_uuid

    def test_tab_uuid_reused_when_closed_window_has_same_tab(self, database: CwDatabase):
        """Tab UUID from a CLOSED window should be reused (stale data cleaned up)."""
        context = database.create_context("Proj")
        win_a = database.create_window(context.id, name="WinA")
        win_b = database.create_window(context.id, name="WinB")

        # Sync tab into window A
        tabs = [{"title": "tab1", "tab_order": 0, "is_selected": True,
                 "iterm_id": "tab-400", "panes": [{"iterm_id": "s-400", "cwd": "/a"}]}]
        database.sync_window_layout(win_a.id, tabs)
        tab_uuid = database.get_cw_id_for_iterm("tab-400")
        assert tab_uuid is not None

        # Close window A
        database.update_window_state(win_a.id, is_open=False)

        # Sync SAME tab into window B — should reuse UUID (A is closed = stale)
        tabs_b = [{"title": "tab1", "tab_order": 0, "is_selected": True,
                   "iterm_id": "tab-400", "panes": [{"iterm_id": "s-400", "cwd": "/b"}]}]
        database.sync_window_layout(win_b.id, tabs_b)

        # Tab UUID preserved
        assert database.get_cw_id_for_iterm("tab-400") == tab_uuid

        # Tab now belongs to window B, not A
        loaded = database.get_context_by_name("Proj")
        win_b_tabs = [w for w in loaded.windows if w.name == "WinB"][0].tabs
        assert len(win_b_tabs) == 1
        assert win_b_tabs[0].id == tab_uuid

    def test_tab_uuid_conflict_with_open_window_generates_new(self, database: CwDatabase):
        """Tab UUID conflict with an OPEN window should generate new UUID (real conflict)."""
        context = database.create_context("Proj")
        win_a = database.create_window(context.id, name="WinA")
        win_b = database.create_window(context.id, name="WinB")

        # Sync tab into window A (window stays OPEN)
        tabs_a = [{"title": "tab1", "tab_order": 0, "is_selected": True,
                   "iterm_id": "tab-500", "panes": [{"iterm_id": "s-500", "cwd": "/a"}]}]
        database.sync_window_layout(win_a.id, tabs_a)
        tab_uuid_a = database.get_cw_id_for_iterm("tab-500")

        # Window A stays open (is_open=True by default)
        # Sync SAME tab ID into window B — conflict with open window
        # Should generate NEW UUID, not crash
        tabs_b = [{"title": "tab1", "tab_order": 0, "is_selected": True,
                   "iterm_id": "tab-500", "panes": [{"iterm_id": "s-501", "cwd": "/b"}]}]
        database.sync_window_layout(win_b.id, tabs_b)

        # Should not crash — window B gets a different tab UUID
        loaded = database.get_context_by_name("Proj")
        win_b_tabs = [w for w in loaded.windows if w.name == "WinB"][0].tabs
        assert len(win_b_tabs) == 1
        # Tab UUID in B should be DIFFERENT from A (conflict avoided)
        assert win_b_tabs[0].id != tab_uuid_a

    def test_no_crash_on_cross_window_sync(self, database: CwDatabase):
        """sync_window_layout must NEVER crash, regardless of cross-window state."""
        context = database.create_context("Proj")
        win_a = database.create_window(context.id, name="WinA")
        win_b = database.create_window(context.id, name="WinB")

        shared_tabs = [{"title": "shared", "tab_order": 0, "is_selected": True,
                        "iterm_id": "tab-600",
                        "panes": [{"iterm_id": "s-600", "cwd": "/shared"}]}]

        # Sync to A, then to B, then to A again — no crashes
        database.sync_window_layout(win_a.id, shared_tabs)
        database.sync_window_layout(win_b.id, shared_tabs)
        database.sync_window_layout(win_a.id, shared_tabs)
        # If we got here, no crash — pass
