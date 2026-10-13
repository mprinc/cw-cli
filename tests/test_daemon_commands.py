"""
Tests for daemon command handlers using fake iTerm2 objects.

These tests verify the logic of _cmd_* functions without needing
a live iTerm2 instance.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cw.db import CwDatabase
from tests.mocks.iterm2_fake import FakeApp, FakeWindow, FakeTab, FakeSession


@pytest.fixture
def database(tmp_path: Path) -> CwDatabase:
    db_path = tmp_path / "test.sqlite"
    db = CwDatabase(db_path=db_path)
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def app() -> FakeApp:
    """Create a FakeApp with one window, one tab, one session."""
    session = FakeSession(session_id="sess-1", cwd="/home/user/project", title="dev")
    tab = FakeTab(tab_id="tab-1", sessions=[session])
    window = FakeWindow(window_id="win-1", tabs=[tab], title="MyProject")
    app = FakeApp(windows=[window])
    app.set_current_window(window)
    return app


def run(coro):
    """Helper to run async functions in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestCmdCreate:
    """Tests for _cmd_create (context creation)."""

    def test_create_empty_context(self, database, app):
        from cw.daemon import _cmd_create
        result = run(_cmd_create({"name": "TestProject"}, app, database))
        assert result["ok"] is True
        ctx = database.get_context_by_name("TestProject")
        assert ctx is not None
        assert len(ctx.windows) == 0  # empty, no auto-add

    def test_create_duplicate_name(self, database, app):
        from cw.daemon import _cmd_create
        run(_cmd_create({"name": "Dup"}, app, database))
        result = run(_cmd_create({"name": "Dup"}, app, database))
        assert result["ok"] is False
        assert "already exists" in result["error"]

    def test_create_empty_name(self, database, app):
        from cw.daemon import _cmd_create
        result = run(_cmd_create({"name": ""}, app, database))
        assert result["ok"] is False


class TestCmdJoin:
    """Tests for _cmd_join (adding window to context)."""

    def test_join_current_window(self, database, app):
        from cw.daemon import _cmd_create, _cmd_join
        run(_cmd_create({"name": "Proj"}, app, database))
        result = run(_cmd_join({"name": "Proj"}, app, database))
        assert result["ok"] is True

        # Window should be in context
        ctx = database.get_context_by_name("Proj")
        assert len(ctx.windows) == 1
        assert ctx.windows[0].is_open is True
        assert ctx.windows[0].is_member is True

    def test_join_creates_mapping(self, database, app):
        from cw.daemon import _cmd_create, _cmd_join
        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))

        # Mapping should exist for the window
        ctx = database.get_context_by_name("Proj")
        iterm_id = database.get_iterm_id_for_cw(ctx.windows[0].id)
        assert iterm_id == "win-1"

    def test_join_nonexistent_context(self, database, app):
        from cw.daemon import _cmd_join
        result = run(_cmd_join({"name": "NoSuch"}, app, database))
        assert result["ok"] is False

    def test_join_already_tracked(self, database, app):
        from cw.daemon import _cmd_create, _cmd_join
        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))
        result = run(_cmd_join({"name": "Proj"}, app, database))
        assert result["ok"] is False
        assert "already belongs" in result["error"]


class TestCmdCurrent:
    """Tests for _cmd_current (identify current context)."""

    def test_tracked_window(self, database, app):
        from cw.daemon import _cmd_create, _cmd_join, _cmd_current
        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))

        result = run(_cmd_current({}, app, database))
        assert result["ok"] is True
        assert result["data"]["context_name"] == "Proj"

    def test_untracked_window(self, database, app):
        from cw.daemon import _cmd_current
        result = run(_cmd_current({}, app, database))
        assert result["ok"] is True
        assert result["data"]["context_name"] is None


class TestCmdCloseOpen:
    """Tests for close/open cycle — the most critical flow."""

    def test_close_saves_state(self, database, app):
        from cw.daemon import _cmd_create, _cmd_join, _cmd_close
        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))

        result = run(_cmd_close({"name": "Proj"}, app, database))
        assert result["ok"] is True
        assert result["data"]["closed_windows"] == 1

        # Window should be marked closed
        ctx = database.get_context_by_name("Proj")
        assert ctx.windows[0].is_open is False
        assert ctx.windows[0].is_member is True  # still a member!

    def test_close_preserves_tabs_panes(self, database, app):
        """After close, DB should still have tab/pane data."""
        from cw.daemon import _cmd_create, _cmd_join, _cmd_close
        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))
        run(_cmd_close({"name": "Proj"}, app, database))

        ctx = database.get_context_by_name("Proj")
        assert len(ctx.windows[0].tabs) >= 1
        assert len(ctx.windows[0].tabs[0].panes) >= 1
        assert ctx.windows[0].tabs[0].panes[0].cwd == "/home/user/project"

    def test_open_already_open_focuses(self, database, app):
        """Opening an already-open window should focus it, not error."""
        from cw.daemon import _cmd_create, _cmd_join, _cmd_open
        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))

        result = run(_cmd_open({"name": "Proj"}, app, database))
        assert result["ok"] is True
        assert result["data"].get("already_open") is not None


class TestCmdLeave:
    """Tests for _cmd_leave (remove window from context)."""

    def test_leave_with_confirm(self, database, app):
        from cw.daemon import _cmd_create, _cmd_join, _cmd_leave
        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))

        # Without confirm → asks
        result = run(_cmd_leave({}, app, database))
        assert result["ok"] is False
        assert result["error"] == "confirm"

        # With confirm → removes
        result = run(_cmd_leave({"confirm": True}, app, database))
        assert result["ok"] is True

        # Window no longer a member
        ctx = database.get_context_by_name("Proj")
        assert ctx.windows[0].is_member is False


class TestUUIDStability:
    """Tests that pane UUIDs stay stable across operations."""

    def test_uuid_stable_across_syncs(self, database, app):
        """sync_window_layout called multiple times should keep same UUID."""
        from cw.daemon import _cmd_create, _cmd_join
        from cw.reconciler import read_iterm_window_state

        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))

        # Get initial UUID
        uuid_1 = database.get_cw_id_for_iterm("sess-1")
        assert uuid_1 is not None

        # Sync again (simulates checkpoint)
        ctx = database.get_context_by_name("Proj")
        window_state = run(read_iterm_window_state(app.terminal_windows[0]))
        database.sync_window_layout(ctx.windows[0].id, window_state["tabs"])

        # UUID should be the same
        uuid_2 = database.get_cw_id_for_iterm("sess-1")
        assert uuid_2 == uuid_1

    def test_session_mapping_preserved_after_join(self, database, app):
        """After join, session should have a CW mapping."""
        from cw.daemon import _cmd_create, _cmd_join

        run(_cmd_create({"name": "Proj"}, app, database))
        run(_cmd_join({"name": "Proj"}, app, database))

        # Session mapping exists
        cw_id = database.get_cw_id_for_iterm("sess-1")
        assert cw_id is not None

        # Window mapping exists
        ctx = database.get_context_by_name("Proj")
        win_iterm_id = database.get_iterm_id_for_cw(ctx.windows[0].id)
        assert win_iterm_id == "win-1"
