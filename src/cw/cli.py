"""
CW CLI — command-line interface for Contextual-Walker.

Usage:
    cw list                         Show all Contexts with live status
    cw create <name>                Create a new Context (current window)
    cw join <name>                  Add current window to a Context
    cw open <ctx>[/<window>]        Restore closed windows
    cw close <ctx>[/<window>]       Save and close windows
    cw save [<ctx>]                 Force a snapshot
    cw history <ctx>                Show state history
    cw status                       Show daemon status
    cw windows [<ctx>]              Show windows (default: current Context)
    cw windows --all                Show ALL iTerm windows with Context info
    cw windows --untracked          Show only untracked windows
    cw focus <ctx>[/<window>]       Jump to a Context window
    cw focus -                      Jump back to previous Context
    cw backup                       Backup database to timestamped folder
    cw completion <shell>           Output shell completion script

Communication:
    Most commands talk to the daemon via a Unix socket.
    Read-only commands (history) can read SQLite directly.
    If daemon is down, commands that need it show a clear error.
"""

from __future__ import annotations

import json
import socket
import sys
from datetime import datetime
from pathlib import Path

import click

from cw.constants import (
    CONFIG_PATH, CW_HOME, DB_PATH, DEFAULT_BACKUP_DIR,
    SOCKET_BUFFER_SIZE, SOCKET_PATH, SOCKET_TIMEOUT_SECONDS,
)


# ─── Socket communication helpers ─────────────────────────────────

def _send_to_daemon(command: str, args: dict | None = None) -> dict:
    """
    Send a JSON command to the daemon and return the response.

    @param command: Command name (e.g. "create", "list").
    @param args: Arguments dict for the command.
    @returns: Response dict from daemon.
    @raises ConnectionError: If daemon is not running.
    """
    if not SOCKET_PATH.exists():
        raise ConnectionError(
            "CW daemon is not running (socket not found).\n"
            "Start iTerm2 with the CW daemon installed, or run: cw status"
        )

    request = {"cmd": command, "args": args or {}}
    request_bytes = json.dumps(request, ensure_ascii=False).encode("utf-8")

    client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client_socket.settimeout(SOCKET_TIMEOUT_SECONDS)
    try:
        client_socket.connect(str(SOCKET_PATH))
        client_socket.sendall(request_bytes)
        # Read response
        chunks = []
        while True:
            chunk = client_socket.recv(SOCKET_BUFFER_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
        response_data = b"".join(chunks)
        return json.loads(response_data.decode("utf-8"))
    except ConnectionRefusedError:
        raise ConnectionError(
            "CW daemon is not responding.\n"
            "It may have crashed — check: ~/.contextual-walker/daemon.log"
        )
    except socket.timeout:
        raise ConnectionError("CW daemon timed out — it may be overloaded or hung.")
    finally:
        client_socket.close()


def _daemon_required(command: str, args: dict | None = None) -> dict:
    """
    Send a command to daemon, handling errors gracefully.

    @param command: Command name.
    @param args: Arguments dict.
    @returns: Response dict.
    """
    try:
        return _send_to_daemon(command, args)
    except ConnectionError as connection_error:
        click.echo(f"Error: {connection_error}", err=True)
        sys.exit(1)


def _strip_trailing_slash(name: str) -> str:
    """Strip trailing / from context names (added by tab completion)."""
    return name.rstrip("/")


# ─── Status indicators ────────────────────────────────────────────

STATUS_ICONS = {
    "OPEN": "●",
    "PARTIAL": "◐",
    "CLOSED": "○",
}


# ─── CLI group ─────────────────────────────────────────────────────

CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(package_name="contextual-walker")
def main():
    """Contextual-Walker - persistent context manager for iTerm2."""
    pass


# ─── cw list ───────────────────────────────────────────────────────

@main.command("list")
def cmd_list():
    """
    Show all Contexts with their live status.

    Contacts the daemon to compare DB state with actual iTerm state.
    If there are discrepancies, they are shown as warnings.
    Falls back to DB-only if daemon is not running.
    """
    try:
        response = _send_to_daemon("list")
    except ConnectionError:
        # Fallback: read DB directly (no live comparison)
        click.echo("⚠ CW daemon is not running — showing DB state only\n", err=True)
        _list_from_db()
        return

    if not response.get("ok"):
        click.echo(f"Error: {response.get('error', 'Unknown error')}", err=True)
        sys.exit(1)

    data = response["data"]
    contexts = data.get("contexts", [])
    discrepancies = data.get("discrepancies", [])

    if not contexts:
        click.echo("No contexts found. Create one with: cw create <name>")
        return

    # Print contexts table
    click.echo(f"{'CONTEXT':<22} {'STATUS':<12} {'WINDOWS':<12} {'UPDATED'}")
    click.echo("─" * 60)
    for ctx in contexts:
        status = ctx["status"]
        icon = STATUS_ICONS.get(status, "?")
        window_info = f"{ctx['open_windows']}/{ctx['total_windows']}"
        updated = _format_timestamp(ctx.get("updated_at", ""))
        click.echo(f"{ctx['name']:<22} {icon} {status:<10} {window_info:<12} {updated}")

    # Print discrepancies if any
    if discrepancies:
        click.echo()
        click.echo("⚠ Discrepancies detected (DB ≠ iTerm):")
        for discrepancy_message in discrepancies:
            click.echo(f"  {discrepancy_message}")
        click.echo()
        click.echo("Run `cw save` to sync, or these will auto-resolve on next checkpoint.")
    else:
        click.echo()
        click.echo("✓ DB and iTerm state match.")


def _list_from_db():
    """
    Fallback: list Contexts from SQLite when daemon is not available.

    Shows DB state only, with a warning that live comparison is not possible.
    """
    from cw.db import CwDatabase

    if not DB_PATH.exists():
        click.echo("No CW database found. Create a context with: cw create <name>")
        return

    database = CwDatabase()
    contexts = database.list_contexts()
    database.close()

    if not contexts:
        click.echo("No contexts found. Create one with: cw create <name>")
        return

    click.echo(f"{'CONTEXT':<22} {'DB STATUS':<12} {'WINDOWS':<12} {'UPDATED'}")
    click.echo("─" * 60)
    for ctx in contexts:
        status = ctx.status
        icon = STATUS_ICONS.get(status, "?")
        window_info = f"{ctx.open_window_count}/{ctx.total_window_count}"
        updated = _format_timestamp(ctx.updated_at)
        click.echo(f"{ctx.name:<22} {icon} {status:<10} {window_info:<12} {updated}")

    click.echo()
    click.echo("⚠ Live iTerm comparison not available (daemon not running).")


# ─── cw create ─────────────────────────────────────────────────────

@main.command("create")
@click.argument("name")
@click.option("--description", "-d", default="", help="Optional description for the Context.")
@click.option("--add", "-a", is_flag=True, help="Also add the current window to the new Context.")
def cmd_create(name: str, description: str, add: bool):
    """
    Create a new Context.

    By default creates an empty Context. Use -a to also add the current window.

    \b
    Examples:
      cw create MyProject            empty Context
      cw create MyProject -a         create + add current window
      cw create MyProject -a -d "Frontend dev"
    """
    name = _strip_trailing_slash(name) if name else name
    response = _daemon_required("create", {"name": name, "description": description})
    if not response.get("ok"):
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)

    if add:
        join_response = _daemon_required("join", {"name": name})
        if join_response.get("ok"):
            click.echo(f"✓ Context '{name}' created. Current window added.")
        else:
            click.echo(f"✓ Context '{name}' created, but failed to add window: {join_response.get('error')}", err=True)
    else:
        click.echo(f"✓ Context '{name}' created. Add windows with: cw join {name}")


# ─── cw join ───────────────────────────────────────────────────────

@main.command("join")
@click.argument("name")
@click.argument("target", required=False)
@click.option("--window-name", "-w", default="", help="Name for this window within the Context.")
def cmd_join(name: str, target: str | None, window_name: str):
    """
    Add a window to an existing Context.

    NAME can include /WindowName to set the window's name in the Context.
    TARGET can be a ref number or an iTerm window title.
    If TARGET is omitted, adds the current (focused) window.

    \b
    Examples:
      cw join MyProject              add current window
      cw join MyProject/Dev          add current window, name it "Dev"
      cw join MyProject 3            add window by ref number
      cw join MyProject IoT          add window by iTerm title
      cw join MyProject/Dev IoT      add IoT window, name it "Dev"
    """
    name = _strip_trailing_slash(name) if name else name
    # Parse Context/WindowName from name argument
    if "/" in name:
        context_name, join_window_name = name.split("/", 1)
    else:
        context_name = name
        join_window_name = ""
    # -w flag overrides /WindowName
    effective_window_name = window_name or join_window_name
    args = {"name": context_name, "window_name": effective_window_name}
    if target is not None:
        try:
            args["ref"] = int(target)
        except ValueError:
            args["iterm_title"] = target

    response = _daemon_required("join", args)
    if response.get("ok"):
        source = f"\"{target}\"" if target else "Current window"
        win_label = f" as \"{effective_window_name}\"" if effective_window_name else ""
        click.echo(f"✓ {source} joined context '{context_name}'{win_label}.")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw rename ─────────────────────────────────────────────────────

@main.command("rename")
@click.argument("target")
@click.argument("new_name")
def cmd_rename(target: str, new_name: str):
    """
    Rename a Context or a Window within a Context.

    \b
    Examples:
      cw rename OldName NewName                rename Context
      cw rename MyProject/OldWin NewWinName    rename Window
    """
    target = _strip_trailing_slash(target) if target else target
    response = _daemon_required("rename", {"target": target, "new_name": new_name})
    if response.get("ok"):
        click.echo(f"✓ Renamed to '{new_name}'.")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw leave ──────────────────────────────────────────────────────

@main.command("leave")
@click.argument("target", required=False)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def cmd_leave(target: str | None, yes: bool):
    """
    Remove a window from its Context.

    Without TARGET, removes the current (focused) window.
    TARGET can be Context/Window, a ref number, or an iTerm title.

    \b
    Examples:
      cw leave                         current window
      cw leave LitTerra/ДРУЖБА         specific window by name
      cw leave 14                      by ref number
      cw leave IoT                     by iTerm title
    """
    target = _strip_trailing_slash(target) if target else target
    args: dict = {"confirm": yes}
    if target is not None:
        try:
            args["ref"] = int(target)
        except ValueError:
            if "/" in target:
                args["context_window"] = target
            else:
                args["iterm_title"] = target

    response = _daemon_required("leave", args)
    if not response.get("ok"):
        error = response.get("error", "")
        if error == "confirm":
            data = response.get("data", {})
            ctx = data.get("context_name", "?")
            win = data.get("window_name", "?")
            if click.confirm(f"Remove window \"{win}\" from Context \"{ctx}\"?"):
                args["confirm"] = True
                response = _daemon_required("leave", args)
                if response.get("ok"):
                    click.echo(f"✓ Window \"{win}\" removed from \"{ctx}\".")
                else:
                    click.echo(f"Error: {response.get('error')}", err=True)
                    sys.exit(1)
            else:
                click.echo("Cancelled.")
        else:
            click.echo(f"Error: {error}", err=True)
            sys.exit(1)
    else:
        data = response.get("data", {})
        click.echo(f"✓ Window \"{data.get('window_name', '?')}\" removed from \"{data.get('context_name', '?')}\".")


# ─── cw open ───────────────────────────────────────────────────────

@main.command("open")
@click.argument("name")
def cmd_open(name: str):
    """
    Restore closed windows of a Context.

    NAME can be "ContextName" (restore all) or "ContextName/WindowName" (one window).
    """
    name = _strip_trailing_slash(name) if name else name
    response = _daemon_required("open", {"name": name})
    if response.get("ok"):
        restored = response["data"].get("restored_windows", 0)
        if restored == 0:
            click.echo("No closed windows to restore (already open?).")
        else:
            click.echo(f"✓ Restored {restored} window(s).")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw close ──────────────────────────────────────────────────────

@main.command("close")
@click.argument("name", required=False)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation when closing current window.")
def cmd_close(name: str | None, yes: bool):
    """
    Save state and close windows of a Context.

    Without NAME, closes the current window (asks for confirmation).
    NAME can be "ContextName" (close all) or "ContextName/WindowName" (one window).
    State is saved before closing — if save fails, close is aborted.

    \b
    Examples:
      cw close                         close current window (confirm)
      cw close -y                      close current window (no confirm)
      cw close MyProject               close all windows in Context
      cw close MyProject/Development   close one window
    """
    name = _strip_trailing_slash(name) if name else name
    if name is None:
        # Close current window — need to find which context it belongs to
        response = _daemon_required("close_current", {"confirm": yes})
        if not response.get("ok"):
            error = response.get("error", "")
            if error == "confirm":
                data = response.get("data", {})
                ctx = data.get("context_name", "?")
                win = data.get("window_name", "?")
                prompt = (
                    "Close the "
                    + click.style("current", bold=True, fg="yellow")
                    + f" window \"{win}\" in Context \"{ctx}\"?"
                )
                if click.confirm(prompt):
                    response = _daemon_required("close_current", {"confirm": True})
                    if response.get("ok"):
                        click.echo(f"✓ Saved and closed \"{win}\".")
                    else:
                        click.echo(f"Error: {response.get('error')}", err=True)
                        sys.exit(1)
                else:
                    click.echo("Cancelled.")
            else:
                click.echo(f"Error: {error}", err=True)
                sys.exit(1)
        else:
            data = response.get("data", {})
            click.echo(f"✓ Saved and closed \"{data.get('window_name', '?')}\".")
    else:
        response = _daemon_required("close", {"name": name})
        if response.get("ok"):
            closed = response["data"].get("closed_windows", 0)
            if closed == 0:
                click.echo("No open windows to close (already closed?).")
            else:
                click.echo(f"✓ Saved and closed {closed} window(s).")
        else:
            click.echo(f"Error: {response.get('error')}", err=True)
            sys.exit(1)


# ─── cw save ───────────────────────────────────────────────────────

@main.command("save")
@click.argument("name", required=False)
def cmd_save(name: str | None):
    """
    Force an explicit snapshot of a Context (or all Contexts).

    NAME is optional — if omitted, saves all Contexts.
    """
    name = _strip_trailing_slash(name) if name else name
    args = {"name": name} if name else {}
    response = _daemon_required("save", args)
    if response.get("ok"):
        saved = response["data"].get("saved_contexts", 0)
        click.echo(f"✓ Snapshot saved for {saved} context(s).")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw history ────────────────────────────────────────────────────

@main.command("history")
@click.argument("name")
@click.option("--limit", "-n", default=20, help="Number of entries to show.")
def cmd_history(name: str, limit: int):
    """
    Show state history (snapshots) for a Context.

    This reads directly from the database — daemon not required.
    """
    name = _strip_trailing_slash(name) if name else name
    from cw.db import CwDatabase

    if not DB_PATH.exists():
        click.echo("No CW database found.", err=True)
        sys.exit(1)

    database = CwDatabase()
    context = database.get_context_by_name(name)
    if not context:
        database.close()
        click.echo(f"Context '{name}' not found.", err=True)
        sys.exit(1)

    entries = database.get_history(context.id, limit=limit)
    database.close()

    if not entries:
        click.echo(f"No history for '{name}'. Use `cw save {name}` to create a snapshot.")
        return

    click.echo(f"History for '{name}' (newest first):\n")
    click.echo(f"  {'TIMESTAMP':<24} {'EVENT'}")
    click.echo(f"  {'─' * 50}")
    for entry in entries:
        timestamp = _format_timestamp(entry.created_at)
        click.echo(f"  {timestamp:<24} {entry.event_type}")


# ─── cw windows ───────────────────────────────────────────────────

@main.command("windows")
@click.argument("name", required=False)
@click.option(
    "-v", "--verbose", count=True,
    help="Detail level: -v shows tabs, -vv shows tabs+panes with CWDs.",
)
@click.option("--all", "show_all", is_flag=True, help="Show ALL iTerm windows with Context info.")
@click.option("--untracked", is_flag=True, help="Show only windows NOT belonging to any Context.")
def cmd_windows(name: str | None, verbose: int, show_all: bool, untracked: bool):
    """
    Show windows belonging to a Context, or all iTerm windows.

    \b
    Modes:
      cw windows                  current Context (auto-detected)
      cw windows MyProject        specific Context
      cw windows --all            ALL iTerm windows (tracked + untracked)
      cw windows --untracked      only windows NOT in any Context

    \b
    Detail levels:
      (default)                   windows only
      -v                          windows + tabs
      -vv                         windows + tabs + panes with CWDs

    \b
    With --all/--untracked, each window shows a ref number (#1, #2, ...)
    that you can use with `cw join` to add it to a Context:
      cw join MyProject 3
    """
    name = _strip_trailing_slash(name) if name else name
    # ─── Mode: --all or --untracked (live iTerm windows) ───────────
    if show_all or untracked:
        filter_mode = "untracked" if untracked else "all"
        response = _daemon_required("all_windows", {"filter": filter_mode})
        if not response.get("ok"):
            click.echo(f"Error: {response.get('error')}", err=True)
            sys.exit(1)
        windows = response["data"]["windows"]
        if not windows:
            if untracked:
                click.echo("All windows are tracked by a Context.")
            else:
                click.echo("No iTerm windows found.")
            return

        click.echo(f"\n  {'REF':<5} {'CONTEXT':<18} {'WINDOW':<18} {'ITERM TITLE':<25} {'TABS':>4}  {'PANES':>5}")
        click.echo("  " + "─" * 80)
        for win in windows:
            is_cur = win.get("is_current")
            ctx = win["context_name"] or "—"
            wname = win["window_name"] or "—"
            title = (win["iterm_title"] or "")[:24]
            tracked_icon = "●" if win["tracked"] else "○"

            # REF: bold yellow for current, normal otherwise
            ref_str = str(win['ref'])
            if is_cur:
                ref_part = click.style(f"{ref_str:<5}", bold=True, fg="yellow")
            else:
                ref_part = f"{ref_str:<5}"

            wname_part = f"{wname:<18}"

            post = f" {title:<25} {win['tabs']:>3}  {win['panes']:>5}"
            if is_cur:
                # ▶ is 2 chars wide in terminal — steal 1 from ctx padding, 1 from space before wname
                pre = f"  {ref_part} {tracked_icon} {ctx:<16}"
                arrow = click.style("▶", bold=True, fg="yellow")
                wname_styled = click.style(f" {wname:<18}", underline=True)
                click.echo(f"{pre}{arrow}{wname_styled}{post}")
            else:
                pre = f"  {ref_part} {tracked_icon} {ctx:<17} "
                click.echo(f"{pre}{wname_part}{post}")
        if untracked:
            click.echo(f"\nTo add: cw join MyContext <ref>    To jump: cw go <ref>")
        return

    # ─── Mode: specific Context or auto-detect ─────────────────────
    if not name:
        # Auto-detect: ask daemon which Context the current window belongs to
        try:
            response = _send_to_daemon("current")
            if response.get("ok"):
                name = response["data"].get("context_name")
        except ConnectionError:
            pass

        if not name:
            click.echo("Current window is not tracked by any Context.", err=True)
            click.echo("Use `cw windows --all` to see all windows,", err=True)
            click.echo("or specify a context: cw windows <name>", err=True)
            sys.exit(1)

    # Try live state from daemon (always fresh); fall back to DB
    live_data = None
    try:
        resp = _send_to_daemon("windows_live", {"context_name": name})
        if resp.get("ok"):
            live_data = resp["data"]
    except Exception:
        pass

    if live_data:
        _display_context_live(live_data, verbose)
    else:
        # Fallback to DB
        from cw.db import CwDatabase
        if not DB_PATH.exists():
            click.echo("No CW database found.", err=True)
            sys.exit(1)
        database = CwDatabase()
        context = database.get_context_by_name(name)
        database.close()
        if not context:
            click.echo(f"Context '{name}' not found.", err=True)
            sys.exit(1)
        click.echo(f"\n{context.name} (DB state — daemon not available)\n")
        for window in context.windows:
            if not window.is_member:
                continue
            icon = "●" if window.is_open else "○"
            click.echo(f"  {icon}  {window.name:<20} {len(window.tabs)} tab(s)")


def _display_context_live(data: dict, verbose: int):
    """Display context windows from live daemon data."""
    click.echo(f"\n{data['context_name']}\n")
    for window in data["windows"]:
        icon = "●" if window["is_open"] else "○"
        tabs = window["tabs"]
        tab_count = len(tabs)
        pane_count = sum(len(t["panes"]) for t in tabs)
        is_cur = window.get("is_current", False)

        wname_styled = click.style(window["name"], bold=True, fg="yellow")
        counts_styled = click.style(f"{tab_count} tab(s), {pane_count} pane(s)", fg="yellow")
        if is_cur:
            arrow = click.style("▶", bold=True, fg="yellow")
            click.echo(f" {icon}{arrow} {wname_styled}  {counts_styled}")
        else:
            click.echo(f" {icon}   {wname_styled}  {counts_styled}")

        if verbose >= 1:
            for tab in tabs:
                is_selected = tab.get("is_selected", False)
                tab_num = click.style(str(tab["tab_order"] + 1), bold=True, fg="blue")
                tab_title = tab.get("title", "")
                if tab_title:
                    tab_label = f"{tab_num}: {click.style(tab_title, fg='blue')}"
                else:
                    tab_label = tab_num

                if is_selected:
                    arrow = click.style("▶", bold=True, fg="blue")
                    click.echo(f"    {arrow} {tab_label}")
                else:
                    click.echo(f"       {tab_label}")

                if verbose >= 2:
                    panes = tab.get("panes", [])
                    for pane_index, pane in enumerate(panes):
                        is_last = (pane_index == len(panes) - 1)
                        connector = "└──" if is_last else "├──"
                        pane_num = click.style(f"({pane_index + 1})", bold=True)
                        pane_title = pane.get("title", "") or pane.get("profile", "") or ""
                        cwd_info = f"  [{pane['cwd']}]" if pane.get("cwd") else ""
                        if pane.get("is_active"):
                            marker = click.style("▶", bold=True, fg="green")
                            click.echo(f"      │  {connector} {marker} {pane_num} {pane_title}{cwd_info}")
                        else:
                            click.echo(f"      │  {connector}    {pane_num} {pane_title}{cwd_info}")


# ─── cw move ───────────────────────────────────────────────────────

@main.command("move")
@click.argument("target")
def cmd_move(target: str):
    """
    Move the current tab to a Context/Window.

    Creates the Context and/or Window if they don't exist (asks first).

    \b
    Examples:
      cw move MyProject/Dev          move tab to window "Dev" in "MyProject"
      cw move NewProject/Main        creates both if needed
    """
    target = _strip_trailing_slash(target) if target else target
    if "/" not in target:
        click.echo("Error: specify Context/Window (e.g. cw move MyProject/Dev)", err=True)
        sys.exit(1)

    context_name, window_name = target.split("/", 1)
    if not context_name or not window_name:
        click.echo("Error: both Context and Window name required (e.g. cw move MyProject/Dev)", err=True)
        sys.exit(1)

    # First check what exists
    response = _daemon_required("move_tab", {
        "context_name": context_name,
        "window_name": window_name,
        "confirm_create": False,
    })

    if not response.get("ok"):
        error = response.get("error", "")
        if error == "confirm_context":
            if not click.confirm(f"Context \"{context_name}\" doesn't exist. Create it?"):
                click.echo("Cancelled.")
                return
            response = _daemon_required("move_tab", {
                "context_name": context_name,
                "window_name": window_name,
                "confirm_create": True,
                "create_context": True,
                "create_window": True,
            })
        elif error == "confirm_window":
            if not click.confirm(f"Window \"{window_name}\" doesn't exist in \"{context_name}\". Create it?"):
                click.echo("Cancelled.")
                return
            response = _daemon_required("move_tab", {
                "context_name": context_name,
                "window_name": window_name,
                "confirm_create": True,
                "create_window": True,
            })

    if response.get("ok"):
        click.echo(f"✓ Tab moved to {context_name}/{window_name}.")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw current ────────────────────────────────────────────────────

@main.command("current")
def cmd_current():
    """
    Show which Context the current window belongs to.
    """
    response = _daemon_required("current")
    if not response.get("ok"):
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)
    data = response["data"]
    ctx = data.get("context_name")
    win = data.get("window_name")
    if ctx:
        click.echo(f"{ctx} / {win}")
    else:
        click.echo("Current window is not tracked by any Context.")


# ─── cw refresh ────────────────────────────────────────────────────

@main.command("refresh")
def cmd_refresh():
    """
    Re-apply CW user variables (badge, context/window names) to all
    tracked windows. Use after changing badge settings or after daemon
    code updates.
    """
    response = _daemon_required("refresh")
    if response.get("ok"):
        count = response["data"].get("refreshed", 0)
        click.echo(f"✓ Refreshed {count} window(s).")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw go ─────────────────────────────────────────────────────────

@main.command("go")
@click.argument("target")
def cmd_go(target: str):
    """
    Jump to a window (bring it to front).

    TARGET can be a Context name, Context/Window, ref number,
    iTerm window title, or "-" to jump back.

    \b
    Examples:
      cw go MyProject                last used window in Context
      cw go MyProject/Development    specific window by CW name
      cw go -                        jump back to previous Context
      cw go 3                        window by ref number
      cw go IoT                      window by iTerm title
    """
    target = _strip_trailing_slash(target) if target else target
    # Number = ref
    try:
        ref = int(target)
        response = _daemon_required("focus_ref", {"ref": ref})
    except ValueError:
        # Try as context name first, fall back to iTerm title
        response = _daemon_required("focus", {"name": target})
        if not response.get("ok") and "not found" in response.get("error", ""):
            response = _daemon_required("focus_title", {"title": target})

    if response.get("ok"):
        data = response["data"]
        click.echo(f"✓ {data.get('focused', '')}")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw reload ─────────────────────────────────────────────────────

@main.command("reload")
def cmd_reload():
    """
    Reload daemon code without restarting iTerm2.

    Use after editing CW source code. The daemon reloads all
    Python modules so changes take effect immediately.
    """
    response = _daemon_required("reload")
    if response.get("ok"):
        data = response["data"]
        modules = data.get("reloaded", [])
        warnings = data.get("warnings", [])
        click.echo(f"✓ Daemon reloaded ({len(modules)} modules)")
        for warning in warnings:
            click.echo(f"⚠ {warning}")
    else:
        click.echo(f"Error: {response.get('error')}", err=True)
        sys.exit(1)


# ─── cw status ─────────────────────────────────────────────────────

@main.command("status")
def cmd_status():
    """Show CW daemon status."""
    try:
        response = _send_to_daemon("status")
        if response.get("ok"):
            click.echo("✓ CW daemon is running.")
            data = response["data"]
            click.echo(f"  Database: {data.get('db_path', '?')}")
            click.echo(f"  Socket:   {data.get('socket_path', '?')}")
        else:
            click.echo(f"⚠ Daemon responded with error: {response.get('error')}", err=True)
    except ConnectionError as connection_error:
        click.echo(f"✗ {connection_error}", err=True)
        sys.exit(1)


# ─── cw backup ─────────────────────────────────────────────────────

@main.command("backup")
@click.option(
    "--target", "-t", default=None,
    help="Backup directory. Default: configured dir or ~/.contextual-walker/backups/",
)
def cmd_backup(target: str | None):
    """
    Backup the CW database to a timestamped folder.

    Creates a new subfolder with the current date and time,
    copies the database and config into it.

    The backup directory can be configured during install or
    with: cw config --backup-dir /path/to/backups
    """
    backup_dir = _resolve_backup_dir(target)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    destination = backup_dir / timestamp

    if not DB_PATH.exists():
        click.echo("No CW database found — nothing to backup.", err=True)
        sys.exit(1)

    destination.mkdir(parents=True, exist_ok=True)

    # Copy database (use SQLite backup API for consistency)
    import shutil
    import sqlite3

    backup_db_path = destination / "cw.sqlite"
    source_conn = sqlite3.connect(str(DB_PATH))
    backup_conn = sqlite3.connect(str(backup_db_path))
    source_conn.backup(backup_conn)
    backup_conn.close()
    source_conn.close()

    # Copy config if it exists
    if CONFIG_PATH.exists():
        shutil.copy2(str(CONFIG_PATH), str(destination / "config.json"))

    # Copy daemon log if it exists
    daemon_log = CW_HOME / "daemon.log"
    if daemon_log.exists():
        shutil.copy2(str(daemon_log), str(destination / "daemon.log"))

    click.echo(f"✓ Backup created at: {destination}")
    click.echo(f"  Database:  {backup_db_path}")

    # Show backup size
    total_size = sum(f.stat().st_size for f in destination.iterdir())
    if total_size < 1024:
        size_str = f"{total_size} B"
    elif total_size < 1024 * 1024:
        size_str = f"{total_size / 1024:.1f} KB"
    else:
        size_str = f"{total_size / (1024 * 1024):.1f} MB"
    click.echo(f"  Size:      {size_str}")


# ─── cw config ─────────────────────────────────────────────────────

@main.command("config")
@click.option(
    "--backup-dir", default=None,
    help="Set the default backup directory.",
)
@click.option("--show", is_flag=True, help="Show current configuration.")
def cmd_config(backup_dir: str | None, show: bool):
    """
    View or update CW configuration.

    Configuration is stored in ~/.contextual-walker/config.json.
    """
    config = _load_config()

    if show or (backup_dir is None):
        click.echo("CW Configuration:")
        click.echo(f"  Backup dir:  {config.get('backup_dir', str(DEFAULT_BACKUP_DIR))}")
        click.echo(f"  Config file: {CONFIG_PATH}")
        return

    if backup_dir is not None:
        resolved = Path(backup_dir).expanduser().resolve()
        config["backup_dir"] = str(resolved)
        click.echo(f"✓ Backup directory set to: {resolved}")

    _save_config(config)


# ─── Config helpers ───────────────────────────────────────────────

def _load_config() -> dict:
    """
    Load CW configuration from config.json.

    @returns: Config dict. Empty dict if file doesn't exist.
    """
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def _save_config(config: dict) -> None:
    """
    Save CW configuration to config.json.

    @param config: Config dict to save.
    """
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")


def _resolve_backup_dir(override: str | None = None) -> Path:
    """
    Determine the backup directory from (in priority order):
    1. Explicit --target argument
    2. Config file backup_dir setting
    3. Default: ~/.contextual-walker/backups/

    @param override: Explicit path from --target, or None.
    @returns: Resolved Path to backup directory.
    """
    if override:
        return Path(override).expanduser().resolve()
    config = _load_config()
    if "backup_dir" in config:
        return Path(config["backup_dir"])
    return DEFAULT_BACKUP_DIR


# ─── cw completion ─────────────────────────────────────────────────

@main.command("completion")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]))
def cmd_completion(shell: str):
    """
    Output shell completion script.

    Install with:
        cw completion bash >> ~/.bashrc
        cw completion zsh  >> ~/.zshrc
        cw completion fish > ~/.config/fish/completions/cw.fish
    """
    from cw.completion import generate_completion
    click.echo(generate_completion(shell))


# ─── Helpers ───────────────────────────────────────────────────────

def _format_timestamp(iso_timestamp: str) -> str:
    """
    Format an ISO timestamp for human-friendly display.

    Shows time if today, date otherwise.

    @param iso_timestamp: ISO-8601 timestamp string.
    @returns: Formatted string like "18:14" or "Oct 06".
    """
    if not iso_timestamp:
        return "—"
    try:
        parsed_timestamp = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        now = datetime.now(parsed_timestamp.tzinfo)
        if parsed_timestamp.date() == now.date():
            return parsed_timestamp.strftime("%H:%M:%S")
        return parsed_timestamp.strftime("%b %d %H:%M:%S")
    except (ValueError, TypeError):
        return iso_timestamp[:16]


if __name__ == "__main__":
    main()
