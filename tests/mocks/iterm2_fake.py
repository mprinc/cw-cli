"""
Fake iTerm2 API objects for testing daemon commands without a live iTerm2.

These fakes implement the same interface as iterm2.App, Window, Tab, Session
but operate entirely in memory. This lets us test daemon command logic,
UUID stability, HISTFILE flow, etc. without needing iTerm2 running.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


class FakeSession:
    """Fake iterm2.Session — an in-memory terminal session (pane)."""

    def __init__(self, session_id: str | None = None, cwd: str = "/tmp", title: str = "bash"):
        self.session_id = session_id or f"fake-sess-{uuid.uuid4().hex[:8]}"
        self._variables: dict[str, str] = {
            "path": cwd,
            "autoName": title,
            "hostname": "localhost",
            "username": "testuser",
            "profileName": "Default",
            "shell": "/bin/bash",
        }
        self._name: str = title
        self._sent_text: list[str] = []  # tracks async_send_text calls

    async def async_get_variable(self, name: str) -> str | None:
        return self._variables.get(name)

    async def async_set_variable(self, name: str, value: str) -> None:
        self._variables[name] = value

    async def async_set_name(self, name: str) -> None:
        self._name = name

    async def async_send_text(self, text: str) -> None:
        self._sent_text.append(text)

    async def async_get_profile(self) -> "FakeProfile":
        return FakeProfile()

    async def async_split_pane(self, vertical: bool = True, profile: str = "Default") -> "FakeSession":
        new_session = FakeSession(cwd=self._variables.get("path", "/tmp"))
        # Parent tab adds the session (caller must handle this)
        return new_session

    @property
    def sent_text(self) -> list[str]:
        """All text sent via async_send_text (for assertions)."""
        return self._sent_text


class FakeProfile:
    """Fake iterm2.Profile."""

    async def async_set_badge_text(self, text: str) -> None:
        pass


class FakeTab:
    """Fake iterm2.Tab — contains sessions (panes)."""

    def __init__(self, tab_id: str | None = None, sessions: list[FakeSession] | None = None):
        self.tab_id = tab_id or f"fake-tab-{uuid.uuid4().hex[:8]}"
        self._sessions = sessions or [FakeSession()]
        self._title: str = ""

    @property
    def sessions(self) -> list[FakeSession]:
        return self._sessions

    @property
    def current_session(self) -> FakeSession | None:
        return self._sessions[0] if self._sessions else None

    async def async_get_variable(self, name: str) -> str | None:
        if name == "titleOverride":
            return self._title or None
        if name == "title":
            return self._title or (self._sessions[0]._name if self._sessions else None)
        return None

    async def async_set_title(self, title: str) -> None:
        self._title = title

    async def async_close(self, force: bool = False) -> None:
        pass

    async def async_move_to_window(self) -> "FakeWindow":
        """Move tab to its own new window (no arguments = new window)."""
        new_window = FakeWindow(tabs=[self])
        return new_window

    async def async_invoke_function(self, func: str) -> str:
        return ""

    def add_session(self, session: FakeSession) -> None:
        """Add a session (pane) to this tab."""
        self._sessions.append(session)


class FakeWindow:
    """Fake iterm2.Window — contains tabs."""

    def __init__(
        self,
        window_id: str | None = None,
        tabs: list[FakeTab] | None = None,
        title: str = "",
    ):
        self.window_id = window_id or f"fake-win-{uuid.uuid4().hex[:8]}"
        self._tabs = tabs or [FakeTab()]
        self._title = title
        self._frame = FakeFrame()
        self._fullscreen = False
        self._active = False

    @property
    def tabs(self) -> list[FakeTab]:
        return self._tabs

    @property
    def current_tab(self) -> FakeTab | None:
        return self._tabs[0] if self._tabs else None

    async def async_get_variable(self, name: str) -> str | None:
        if name == "titleOverride":
            return self._title or None
        return None

    async def async_set_title(self, title: str) -> None:
        self._title = title

    async def async_get_frame(self) -> "FakeFrame":
        return self._frame

    async def async_set_frame(self, frame: "FakeFrame") -> None:
        self._frame = frame

    async def async_get_fullscreen(self) -> bool:
        return self._fullscreen

    async def async_create_tab(self, profile: str = "Default") -> FakeTab:
        tab = FakeTab()
        self._tabs.append(tab)
        return tab

    async def async_set_tabs(self, tabs: list[FakeTab]) -> None:
        """Move/reorder tabs (supports cross-window moves)."""
        self._tabs = list(tabs)

    async def async_close(self, force: bool = False) -> None:
        pass

    async def async_activate(self) -> None:
        self._active = True

    async def async_save_window_as_arrangement(self, name: str) -> None:
        pass


class FakeFrame:
    """Fake iterm2.Frame."""

    def __init__(self, x: float = 0, y: float = 0, width: float = 800, height: float = 600):
        self.origin = FakePoint(x, y)
        self.size = FakeSize(width, height)


class FakePoint:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


class FakeSize:
    def __init__(self, width: float, height: float):
        self.width = width
        self.height = height


class FakeApp:
    """Fake iterm2.App — the top-level container for windows."""

    def __init__(self, windows: list[FakeWindow] | None = None):
        self._windows = windows or []
        self._current_window: FakeWindow | None = None
        self.connection = FakeConnection()

    @property
    def terminal_windows(self) -> list[FakeWindow]:
        return self._windows

    @property
    def current_terminal_window(self) -> FakeWindow | None:
        return self._current_window or (self._windows[0] if self._windows else None)

    def get_window_by_id(self, window_id: str) -> FakeWindow | None:
        for w in self._windows:
            if w.window_id == window_id:
                return w
        return None

    def get_tab_by_id(self, tab_id: str) -> FakeTab | None:
        for w in self._windows:
            for t in w.tabs:
                if t.tab_id == tab_id:
                    return t
        return None

    def get_session_by_id(self, session_id: str) -> FakeSession | None:
        for w in self._windows:
            for t in w.tabs:
                for s in t.sessions:
                    if s.session_id == session_id:
                        return s
        return None

    def add_window(self, window: FakeWindow) -> None:
        self._windows.append(window)

    def set_current_window(self, window: FakeWindow) -> None:
        self._current_window = window

    def remove_window(self, window: FakeWindow) -> None:
        self._windows = [w for w in self._windows if w.window_id != window.window_id]


class FakeConnection:
    """Fake iterm2.Connection."""
    pass
