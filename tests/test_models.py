"""Tests for CW data models."""

from cw.models import Context, Window, Pane, Tab


class TestContextStatus:
    """Tests for Context.status property."""

    def test_no_windows(self):
        ctx = Context(id="1", name="Test")
        assert ctx.status == "CLOSED"

    def test_all_open(self):
        ctx = Context(id="1", name="Test", windows=[
            Window(id="w1", context_id="1", is_member=True, is_open=True),
            Window(id="w2", context_id="1", is_member=True, is_open=True),
        ])
        assert ctx.status == "OPEN"

    def test_all_closed(self):
        ctx = Context(id="1", name="Test", windows=[
            Window(id="w1", context_id="1", is_member=True, is_open=False),
            Window(id="w2", context_id="1", is_member=True, is_open=False),
        ])
        assert ctx.status == "CLOSED"

    def test_partial(self):
        ctx = Context(id="1", name="Test", windows=[
            Window(id="w1", context_id="1", is_member=True, is_open=True),
            Window(id="w2", context_id="1", is_member=True, is_open=False),
        ])
        assert ctx.status == "PARTIAL"

    def test_non_member_ignored(self):
        ctx = Context(id="1", name="Test", windows=[
            Window(id="w1", context_id="1", is_member=False, is_open=True),
        ])
        assert ctx.status == "CLOSED"

    def test_window_counts(self):
        ctx = Context(id="1", name="Test", windows=[
            Window(id="w1", context_id="1", is_member=True, is_open=True),
            Window(id="w2", context_id="1", is_member=True, is_open=False),
            Window(id="w3", context_id="1", is_member=False, is_open=True),
        ])
        assert ctx.open_window_count == 1
        assert ctx.total_window_count == 2


class TestPaneActive:
    """Tests for Pane.is_active field."""

    def test_default_inactive(self):
        pane = Pane(id="p1", tab_id="t1")
        assert pane.is_active is False

    def test_active(self):
        pane = Pane(id="p1", tab_id="t1", is_active=True)
        assert pane.is_active is True
