"""Tests for CW config functions."""

import json
from pathlib import Path

from cw.cli import _load_config, _save_config, _resolve_backup_dir
from cw.constants import DEFAULT_BACKUP_DIR


class TestConfig:
    """Tests for config load/save."""

    def test_load_missing_config(self, tmp_path, monkeypatch):
        """Loading nonexistent config returns empty dict."""
        monkeypatch.setattr("cw.cli.CONFIG_PATH", tmp_path / "nonexistent.json")
        assert _load_config() == {}

    def test_save_and_load(self, tmp_path, monkeypatch):
        """Config round-trips through save/load."""
        config_path = tmp_path / "config.json"
        monkeypatch.setattr("cw.cli.CONFIG_PATH", config_path)
        _save_config({"backup_dir": "/tmp/backups"})
        loaded = _load_config()
        assert loaded["backup_dir"] == "/tmp/backups"

    def test_resolve_backup_dir_default(self, tmp_path, monkeypatch):
        """Without config, uses default backup dir."""
        monkeypatch.setattr("cw.cli.CONFIG_PATH", tmp_path / "nonexistent.json")
        result = _resolve_backup_dir()
        assert result == DEFAULT_BACKUP_DIR

    def test_resolve_backup_dir_override(self):
        """Explicit override takes priority."""
        result = _resolve_backup_dir("/custom/path")
        assert result == Path("/custom/path")
