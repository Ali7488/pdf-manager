"""Start and stop browser mode: ``uv run main.py --browser``.

1. Take this profile's instance lock (``platforms.lock_instance``). If another
   launch holds it, ask that instance for a new link, open it and exit, so
   simultaneous launches reach one server (decision P41). The system releases
   the lock when an instance dies, so a killed instance never blocks the next.
2. Otherwise start the server on ``127.0.0.1`` with a port the system picks,
   and wait (briefly) until it answers.
3. Open the link in the default browser: in app mode (``--app=<url>``: its
   own window, no tabs or address bar) when that is Edge, Chrome, Brave or
   Chromium, otherwise as a normal tab through the system's URL opener.
   PDF Manager never installs, chooses or forces another browser.
4. Run until the page's Quit button, Ctrl+C / a termination signal, or an
   hour without requests while no job or OCR install is running and no
   finished result is unsaved (decision P35). Closing the
   browser window alone doesn't stop the app: a browser can hand the window to
   an already running process or keep running itself, so the app doesn't rely
   on it. Starting the app again reopens the same instance.
5. Shut down: refuse new changes, let requests in progress end, cancel a
   running job, delete scratch and upload folders.

``--no-browser`` starts the server without opening a browser (for tests and
headless use); the launch link is printed and, with ``--url-file``, written
to a file only this user can read. Without a browser on this desktop to put a
picker in front of, it also uses the browser's own file chooser and downloads,
as ``--no-native-dialogs`` does.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import secrets
import signal
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

from .. import paths, platforms
from ..logging_setup import configure_logging
from ..settings_store import SettingsStore
from ..workflow import Workflow
from .operations import Context
from .server import HOST, INSTANCE_HEADER, AppServer
from .session import Session

log = logging.getLogger(__name__)

STATE_FILE = "browser-mode.json"
LOCK_FILE = "browser-mode.lock"
# How long a second launch waits for the instance that holds the lock to answer.
JOIN_TIMEOUT_SEC = 20
READY_TIMEOUT_SEC = 10
REUSE_TIMEOUT_SEC = 3
IDLE_SHUTDOWN_SEC = 60 * 60
SHUTDOWN_GRACE_SEC = 10


def _state_path() -> Path:
    return paths.settings_path().parent / STATE_FILE


def _lock_path() -> Path:
    return paths.settings_path().parent / LOCK_FILE


def _join_or_lock() -> tuple[str | None, Any]:
    """Become this profile's one instance, or find the one that already is (P41).

    The instance lock decides atomically, so two launches at the same moment
    can't both start a server. A launch that doesn't get it asks the owner
    for a link, waiting while the owner is still starting. If the owner goes
    away meanwhile (it quit, or was killed, which releases the lock), this
    launch takes the lock itself.

    Returns:
        ``(url, None)`` to open the running instance, ``(None, lock)`` to start
        a new one (keep ``lock`` open while it runs), or ``(None, None)`` if
        neither worked within ``JOIN_TIMEOUT_SEC``.
    """
    deadline = time.monotonic() + JOIN_TIMEOUT_SEC
    while True:
        lock = platforms.lock_instance(_lock_path())
        if lock is not None:
            return None, lock
        url = _running_instance_url()
        if url:
            return url, None
        if time.monotonic() > deadline:
            return None, None
        time.sleep(0.2)


def _write_private(path: Path, text: str) -> None:
    """Write a file readable by this user only (on POSIX; Windows' profile is per user)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)


def _running_instance_url() -> str | None:
    """A new launch link from an already running browser-mode instance, if there is one."""
    try:
        state = json.loads(_state_path().read_text(encoding="utf-8"))
        port, key = int(state["port"]), str(state["key"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/instance/launch",
        data=b"",
        method="POST",
        headers={INSTANCE_HEADER: key},
    )
    try:
        with urllib.request.urlopen(request, timeout=REUSE_TIMEOUT_SEC) as response:
            return str(json.load(response)["url"])
    except (OSError, ValueError, KeyError):
        return None  # Not running any more (a stale file), or not ours.


def _wait_ready(server: AppServer) -> bool:
    """True once the server answers its health check, within READY_TIMEOUT_SEC."""
    url = f"{server.origin}/api/health"
    request = urllib.request.Request(url, headers={"Host": server.host})
    try:
        with urllib.request.urlopen(request, timeout=READY_TIMEOUT_SEC) as response:
            return response.status == 200
    except OSError:
        log.exception("Browser mode didn't answer at %s", server.origin)
        return False


def open_in_browser(url: str) -> str:
    """Open the link in the default browser.

    Returns:
        ``"app"`` (an app-mode window), ``"tab"`` (the system's URL opener) or
        ``"none"`` (nothing could open it).
    """
    browser = platforms.default_browser()
    if browser.app_command:
        try:
            platforms.start_browser([*browser.app_command, f"--app={url}"])
            log.info("Opened in %s (app mode)", browser.name)
            return "app"
        except OSError:
            log.warning("Couldn't start %s in app mode; opening a tab", browser.name, exc_info=True)
    else:
        log.info("Default browser %s has no app mode here; opening a tab", browser.name)
    try:
        platforms.open_url(url)
        return "tab"
    except OSError:
        log.exception("Couldn't open the browser")
        return "none"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="PDF Manager", description="PDF Manager in your browser")
    parser.add_argument("--browser", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true", help="start without opening a browser")
    parser.add_argument("--url-file", type=Path, help="write the launch link to this file")
    parser.add_argument(
        "--no-native-dialogs",
        action="store_true",
        help="use the browser's file chooser and downloads instead of native pickers",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run browser mode until it is told to stop. Returns the process exit code."""
    args = _parse(argv)
    configure_logging()
    url, lock = _join_or_lock()
    if url:
        log.info("PDF Manager is already running; opening it again")
        if args.url_file:
            _write_private(args.url_file, url)
        if args.no_browser:
            print(f"PDF Manager is already running. Open this link once: {url}", flush=True)
        else:
            open_in_browser(url)
        return 0
    if lock is None:
        log.error("Another PDF Manager holds this profile but didn't answer")
        print("PDF Manager is already starting or closing. Try again in a moment.", flush=True)
        return 1
    try:
        return _serve(args)
    finally:
        lock.close()  # Released only after the state file is gone (see _shut_down).


def _serve(args: argparse.Namespace) -> int:
    """Run this profile's one instance (the caller holds the instance lock)."""
    store = SettingsStore(paths.settings_path())
    store.load()
    session = Session()
    workflow = Workflow(store, session.record)
    stop = threading.Event()
    native = platforms.dialogs_available() and not (args.no_browser or args.no_native_dialogs)
    ctx = Context(workflow, session, native, request_stop=stop.set)
    instance_key = secrets.token_urlsafe(32)
    server = AppServer(ctx, paths.ui_index().parent, instance_key)
    thread = threading.Thread(target=server.serve_forever, name="http", daemon=True)
    thread.start()
    state = _state_path()
    try:
        if not _wait_ready(server):
            return 1
        _write_private(state, json.dumps({"port": server.server_port, "key": instance_key}))
        log.info(
            "Browser mode on %s (native pickers: %s)",
            server.origin,
            "yes" if ctx.native_dialogs else "no",
        )
        url = server.launch_url()
        if args.url_file:
            _write_private(args.url_file, url)
        if args.no_browser:
            print(f"PDF Manager is running. Open this link once: {url}", flush=True)
        elif open_in_browser(url) == "none":
            print(f"Open this link in your browser: {url}", flush=True)
        _stop_on_signals(stop)
        wait_for_stop(server, stop)
        return 0
    finally:
        _shut_down(server, workflow, session, state, instance_key)


def wait_for_stop(
    server: AppServer,
    stop: threading.Event,
    idle_limit: float = IDLE_SHUTDOWN_SEC,
    poll: float = 1.0,
) -> str:
    """Block until the app should close.

    The app closes when ``stop`` is set (Quit, a signal), or after
    ``idle_limit`` seconds without requests, but only while nothing is
    running and no finished result is unsaved (decision P35): such results
    exist only in the app, so idle shutdown waits for them to be saved or
    discarded.

    Returns:
        ``"stopped"`` or ``"idle"``.
    """
    while not stop.wait(poll):
        if server.idle_for() > idle_limit and not server.busy():
            log.info("No activity for %.0f seconds and nothing unsaved; closing", idle_limit)
            return "idle"
    return "stopped"


def _stop_on_signals(stop: threading.Event) -> None:
    """Ctrl+C and termination signals stop the app cleanly (main thread only)."""
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), lambda *_: stop.set())


def _shut_down(server: AppServer, workflow: Workflow, session: Session, state: Path, key: str):
    """Refuse new changes, let requests end, then clean up. Never raises."""
    server.closing = True
    server.wait_idle(SHUTDOWN_GRACE_SEC)
    workflow.shutdown()
    server.shutdown()
    server.server_close()
    session.close()
    try:
        if json.loads(state.read_text(encoding="utf-8")).get("key") == key:
            state.unlink()
    except (OSError, ValueError):
        pass
    log.info("Browser mode stopped")


if __name__ == "__main__":
    sys.exit(main())
