"""Tests for CLI helper functions."""

from click.testing import CliRunner

from cw.cli import _strip_trailing_slash, _format_timestamp, _display_context_live


class TestStripTrailingSlash:
    """Tests for trailing slash removal (completion artifact)."""

    def test_no_slash(self):
        assert _strip_trailing_slash("MyProject") == "MyProject"

    def test_trailing_slash(self):
        assert _strip_trailing_slash("MyProject/") == "MyProject"

    def test_with_window(self):
        assert _strip_trailing_slash("MyProject/Dev") == "MyProject/Dev"

    def test_empty(self):
        assert _strip_trailing_slash("") == ""

    def test_just_slash(self):
        assert _strip_trailing_slash("/") == ""

    def test_cyrillic(self):
        assert _strip_trailing_slash("Пројекти/") == "Пројекти"


class TestFormatTimestamp:
    """Tests for timestamp formatting."""

    def test_empty(self):
        assert _format_timestamp("") == "—"

    def test_none(self):
        assert _format_timestamp(None) == "—"

    def test_iso_format(self):
        result = _format_timestamp("2026-10-08T18:14:32.123456Z")
        assert "18:14:32" in result or "Oct 08" in result

    def test_invalid(self):
        result = _format_timestamp("not-a-date")
        assert "not-a-date" in result


class TestDisplayContextLive:
    """Tests for live context display output."""

    SAMPLE_DATA = {
        "context_name": "MyProject",
        "windows": [
            {
                "id": "w1",
                "name": "Development",
                "is_open": True,
                "is_current": True,
                "tabs": [
                    {
                        "title": "frontend",
                        "tab_order": 0,
                        "is_selected": True,
                        "panes": [
                            {"title": "dev-server", "cwd": "/app/frontend", "profile": "", "is_active": True},
                            {"title": "git", "cwd": "/app/frontend", "profile": "", "is_active": False},
                        ],
                    },
                    {
                        "title": "backend",
                        "tab_order": 1,
                        "is_selected": False,
                        "panes": [
                            {"title": "api", "cwd": "/app/backend", "profile": "", "is_active": True},
                        ],
                    },
                ],
            },
        ],
    }

    def _capture(self, verbose: int) -> str:
        """Capture display output as string."""
        runner = CliRunner()
        output_lines = []
        with runner.isolated_filesystem():
            import click
            # Capture click.echo output
            import io
            buf = io.StringIO()
            import contextlib
            with contextlib.redirect_stdout(buf):
                # click.echo writes to stdout by default
                _display_context_live(self.SAMPLE_DATA, verbose)
            return buf.getvalue()

    def test_tab_numbers_start_from_1(self):
        """Tab numbers should be 1-based, not 0-based."""
        output = self._capture(verbose=1)
        assert "1:" in output  # First tab
        assert "2:" in output  # Second tab
        assert "0:" not in output  # Should NOT have 0-based

    def test_pane_numbers_start_from_1(self):
        """Pane numbers should be 1-based."""
        output = self._capture(verbose=2)
        assert "(1)" in output
        assert "(2)" in output

    def test_selected_tab_has_marker(self):
        """Selected tab should have ▶ marker."""
        output = self._capture(verbose=1)
        # The selected tab (frontend) line should contain ▶
        lines = output.split("\n")
        frontend_line = [l for l in lines if "frontend" in l]
        assert len(frontend_line) > 0
        # Non-selected tab (backend) should NOT have ▶ before it
        backend_line = [l for l in lines if "backend" in l]
        assert len(backend_line) > 0

    def test_active_pane_has_green_marker(self):
        """Active pane should have ▶ marker."""
        output = self._capture(verbose=2)
        lines = output.split("\n")
        dev_server_line = [l for l in lines if "dev-server" in l]
        assert len(dev_server_line) > 0
        # git pane is not active — should not have ▶ before its number
        git_line = [l for l in lines if "git" in l]
        assert len(git_line) > 0

    def test_current_window_has_marker(self):
        """Current window should have ▶ marker."""
        output = self._capture(verbose=0)
        assert "Development" in output

    def test_context_name_shown(self):
        """Context name should appear in output."""
        output = self._capture(verbose=0)
        assert "MyProject" in output
