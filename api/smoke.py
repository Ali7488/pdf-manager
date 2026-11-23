"""Start-up smoke test: open the real window, check the UI and the bridge, then quit.

Enabled with ``PDF_MANAGER_SMOKE_TEST=1`` (used by CI under ``xvfb-run``; see
``.github/workflows/ci.yml``). :func:`api.app.main` then starts the real app
as usual, and once the page has loaded this module checks, from inside the
page with ``evaluate_js``, that:

* the React app rendered into ``#root`` (so the built UI loaded, not the
  "interface files are missing" page), and
* ``window.pywebview.api`` exists, and a real call through it
  (``get_app_info``) comes back from Python.

The result is printed to stdout as one line, ``SMOKE TEST PASSED {...}`` or
``SMOKE TEST FAILED {...}`` (JSON details), the window is closed, and the
exit code is 0 on success and non-zero on failure. A watchdog ends the
process with exit code 2 if the whole check (including closing the window)
takes longer than the overall timeout, so a hung GUI can never block CI.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, TextIO

log = logging.getLogger(__name__)

SMOKE_ENV = "PDF_MANAGER_SMOKE_TEST"
TIMEOUT_SEC = 90  # Qt WebEngine's first start on a cold CI runner can be slow.
CLOSE_GRACE_SEC = 15  # Extra time for the window to close after the result.
POLL_SEC = 0.25
EXIT_PASSED = 0
EXIT_FAILED = 1
EXIT_TIMEOUT = 2

# Runs inside the page. Returns plain JSON; pywebview parses it into a dict.
PROBE_SCRIPT = """(function () {
  var root = document.getElementById("root");
  var api = window.pywebview && window.pywebview.api;
  return {
    protocol: location.protocol,
    title: document.title,
    rootRendered: !!root && root.childElementCount > 0,
    apiReady: !!api && typeof api.get_app_info === "function",
    appInfo: window.__pdfManagerSmokeAppInfo || null
  };
})()"""
# A real JS -> Python -> JS round trip; the answer is stored for the next probe.
ROUND_TRIP_SCRIPT = (
    "window.pywebview.api.get_app_info().then(function (info) {"
    " window.__pdfManagerSmokeAppInfo = info; }); null"
)


def enabled() -> bool:
    """Whether the smoke-test mode is switched on (``PDF_MANAGER_SMOKE_TEST=1``)."""
    return os.environ.get(SMOKE_ENV) == "1"


class SmokeCheck:
    """Checks one window, reports the result and closes it.

    Args:
        window: The pywebview window (or a test double with ``events.loaded``,
            ``evaluate_js`` and ``destroy``).
        timeout: Seconds allowed for the page to load and pass every check.
        out: Where the one-line result is written.
        hard_exit: Called with an exit code by the watchdog (``os._exit``).
        poll: Seconds between probes.

    Attributes:
        exit_code: 0 once the check passed; non-zero until then.
        result: The reported result, or ``None`` before it is known.
    """

    def __init__(
        self,
        window: Any,
        *,
        timeout: float = TIMEOUT_SEC,
        out: TextIO | None = None,
        hard_exit: Callable[[int], Any] = os._exit,
        poll: float = POLL_SEC,
    ):
        self._window = window
        self._timeout = timeout
        self._out = out
        self._hard_exit = hard_exit
        self._poll = poll
        self._lock = threading.Lock()
        self._watchdog: threading.Timer | None = None
        self.exit_code = EXIT_FAILED
        self.result: dict[str, Any] | None = None

    def arm(self) -> None:
        """Start the watchdog; call before ``webview.start`` to catch a GUI that never starts."""
        self._watchdog = threading.Timer(self._timeout + CLOSE_GRACE_SEC, self._on_timeout)
        self._watchdog.daemon = True
        self._watchdog.start()

    def disarm(self) -> None:
        """Stop the watchdog (the GUI loop has ended)."""
        if self._watchdog is not None:
            self._watchdog.cancel()

    def run(self) -> None:
        """Check the page, report, close the window. Runs on pywebview's worker thread.

        Never raises: any error is reported as a failed check.
        """
        try:
            result = self._probe()
        except Exception as exc:
            log.exception("Smoke test probe failed")
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._report(result)
        try:
            self._window.destroy()
        except Exception:
            log.exception("Smoke test couldn't close the window")

    def _probe(self) -> dict[str, Any]:
        """Wait for the page, the React root and the bridge, then do one real call.

        Returns:
            The result: ``ok`` plus what was seen in the page.
        """
        deadline = time.monotonic() + self._timeout
        if not self._window.events.loaded.wait(self._timeout):
            return {"ok": False, "error": "The page didn't finish loading in time."}
        state: dict[str, Any] = {}
        round_trip_started = False
        while time.monotonic() < deadline:
            state = self._window.evaluate_js(PROBE_SCRIPT) or {}
            if state.get("apiReady") and not round_trip_started:
                self._window.evaluate_js(ROUND_TRIP_SCRIPT)
                round_trip_started = True
            app_info = state.get("appInfo")
            if state.get("rootRendered") and isinstance(app_info, dict) and app_info.get("version"):
                return {"ok": True, **state}
            time.sleep(self._poll)
        missing = [
            text
            for text, seen in (
                ("the React app didn't render into #root", state.get("rootRendered")),
                ("window.pywebview.api is missing", state.get("apiReady")),
                ("get_app_info didn't answer", state.get("appInfo")),
            )
            if not seen
        ]
        return {"ok": False, "error": "; ".join(missing) or "timed out", **state}

    def _report(self, result: dict[str, Any]) -> None:
        """Print and log the result once, and set the exit code."""
        with self._lock:
            if self.result is not None:
                return
            self.result = result
            self.exit_code = EXIT_PASSED if result.get("ok") else EXIT_FAILED
        verdict = "PASSED" if result.get("ok") else "FAILED"
        self._print(f"SMOKE TEST {verdict} {json.dumps(result, sort_keys=True, default=str)}")

    def _print(self, line: str) -> None:
        """Write one line to the log and to stdout (where CI reads it)."""
        log.info(line)
        out = self._out if self._out is not None else sys.stdout
        if out is not None:  # A windowed build has no stdout.
            print(line, file=out, flush=True)

    def _on_timeout(self) -> None:
        """Watchdog: the check (or closing the window) hung. Report and end the process."""
        if self.result is None:
            self._report({"ok": False, "error": "Timed out; the window never finished the check."})
        else:
            self._print("SMOKE TEST FAILED the window didn't close in time")
        self._hard_exit(EXIT_TIMEOUT)
