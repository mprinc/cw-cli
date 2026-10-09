"""Tests for CLI helper functions."""

from cw.cli import _strip_trailing_slash, _format_timestamp


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
