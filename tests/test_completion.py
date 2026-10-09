"""Tests for shell completion generation and transliteration."""

from cw.completion import generate_completion


class TestCompletionGeneration:
    """Tests for completion script generation."""

    def test_bash(self):
        script = generate_completion("bash")
        assert "_cw_completions" in script
        assert "compgen" in script or "_cw_fuzzy_match" in script
        assert "move" in script
        assert "current" in script
        assert "refresh" in script

    def test_zsh(self):
        script = generate_completion("zsh")
        assert "compdef _cw cw" in script
        assert "move" in script

    def test_fish(self):
        script = generate_completion("fish")
        assert "complete -c cw" in script
        assert "move" in script

    def test_invalid_shell(self):
        try:
            generate_completion("powershell")
            assert False, "Should have raised"
        except ValueError:
            pass


class TestTransliteration:
    """Tests for Latin→Cyrillic transliteration in bash completion."""

    def test_bash_has_transliterate(self):
        script = generate_completion("bash")
        assert "transliterate" in script
        assert "lat2cyr" in script

    def test_bash_has_fuzzy_match(self):
        script = generate_completion("bash")
        assert "_cw_fuzzy_match" in script

    def test_all_commands_present(self):
        """All CLI commands must appear in completion scripts."""
        commands = [
            "list", "create", "join", "leave", "move", "open", "close",
            "save", "history", "status", "windows", "go", "rename",
            "current", "refresh", "reload", "backup", "config", "completion",
        ]
        for shell in ["bash", "zsh", "fish"]:
            script = generate_completion(shell)
            for cmd in commands:
                assert cmd in script, f"'{cmd}' missing from {shell} completion"
