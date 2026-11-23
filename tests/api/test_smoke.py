"""Tests for api.smoke: the start-up check's logic, with a scripted fake window."""

from __future__ import annotations

import io
import json
import threading

from api import smoke


class LoadedEvent:
    """Stands in for ``window.events.loaded`` (a pywebview Event with ``wait``)."""

    def __init__(self, fires: bool):
        self.fires = fires

    def wait(self, timeout=None):
        return self.fires


class Events:
    def __init__(self, loads: bool):
        self.loaded = LoadedEvent(loads)


class ScriptedWindow:
    """A window whose page answers the probe from a list of states.

    Args:
        states: Successive probe results; the last one repeats.
        loads: Whether the page's loaded event fires.
        answers: Whether the get_app_info round trip ever answers.
    """

    def __init__(self, states, loads=True, answers=True):
        self.states = list(states)
        self.events = Events(loads)
        self.answers = answers
        self.round_trip_started = False
        self.scripts = []
        self.destroyed = False

    def evaluate_js(self, script):
        self.scripts.append(script)
        if script == smoke.ROUND_TRIP_SCRIPT:
            self.round_trip_started = True
            return None
        state = dict(self.states.pop(0) if len(self.states) > 1 else self.states[0])
        if self.round_trip_started and self.answers:
            state["appInfo"] = {"version": "1.1.1", "logsDir": "/logs", "platform": "linux"}
        return state

    def destroy(self):
        self.destroyed = True


READY = {"protocol": "file:", "title": "PDF Manager", "rootRendered": True, "apiReady": True}
LOADING = {"protocol": "file:", "title": "PDF Manager", "rootRendered": False, "apiReady": False}


def run_check(window, timeout=1.0):
    """Run a SmokeCheck to the end and return it with its printed line."""
    out = io.StringIO()
    exits = []
    check = smoke.SmokeCheck(window, timeout=timeout, out=out, hard_exit=exits.append, poll=0.001)
    check.run()
    assert exits == []
    return check, out.getvalue()


def parse(line):
    """Split ``SMOKE TEST <VERDICT> {json}`` into the verdict and the parsed JSON."""
    words = line.strip().split(" ", 3)
    assert words[:2] == ["SMOKE", "TEST"]
    return words[2], json.loads(words[3])


def test_enabled_only_with_1(monkeypatch):
    """Only PDF_MANAGER_SMOKE_TEST=1 switches the mode on."""
    monkeypatch.delenv(smoke.SMOKE_ENV, raising=False)
    assert not smoke.enabled()
    monkeypatch.setenv(smoke.SMOKE_ENV, "0")
    assert not smoke.enabled()
    monkeypatch.setenv(smoke.SMOKE_ENV, "1")
    assert smoke.enabled()


def test_passes_when_root_rendered_and_bridge_answers():
    """Rendered root + a get_app_info answer: PASSED, exit 0, window closed."""
    window = ScriptedWindow([LOADING, LOADING, READY])
    check, printed = run_check(window)
    verdict, result = parse(printed)
    assert verdict == "PASSED" and result["ok"] is True
    assert result["appInfo"]["platform"] == "linux"
    assert check.exit_code == 0 and window.destroyed
    assert window.scripts.count(smoke.ROUND_TRIP_SCRIPT) == 1  # Started once only.


def test_fails_when_ui_missing():
    """The "interface files are missing" page has no #root content: FAILED, exit 1."""
    window = ScriptedWindow([{**READY, "rootRendered": False}])
    check, printed = run_check(window, timeout=0.05)
    verdict, result = parse(printed)
    assert verdict == "FAILED" and check.exit_code == 1
    assert "didn't render into #root" in result["error"]
    assert window.destroyed


def test_fails_without_bridge():
    """No window.pywebview.api: FAILED, and no round trip is attempted."""
    window = ScriptedWindow([{**READY, "apiReady": False}])
    check, printed = run_check(window, timeout=0.05)
    verdict, result = parse(printed)
    assert verdict == "FAILED" and check.exit_code == 1
    assert "window.pywebview.api is missing" in result["error"]
    assert smoke.ROUND_TRIP_SCRIPT not in window.scripts


def test_fails_when_bridge_never_answers():
    """The API object exists but get_app_info never comes back: FAILED."""
    window = ScriptedWindow([READY], answers=False)
    check, printed = run_check(window, timeout=0.05)
    verdict, result = parse(printed)
    assert verdict == "FAILED" and "get_app_info didn't answer" in result["error"]


def test_fails_when_page_never_loads():
    """No loaded event: FAILED without probing."""
    window = ScriptedWindow([READY], loads=False)
    check, printed = run_check(window)
    verdict, result = parse(printed)
    assert verdict == "FAILED" and "didn't finish loading" in result["error"]
    assert window.scripts == [] and window.destroyed


def test_probe_error_is_a_failure():
    """A JavaScript error while probing is reported, not raised."""

    class Broken(ScriptedWindow):
        def evaluate_js(self, script):
            raise RuntimeError("JavaScript error")

    check, printed = run_check(Broken([READY]))
    verdict, result = parse(printed)
    assert verdict == "FAILED" and "JavaScript error" in result["error"]
    assert check.exit_code == 1


def test_watchdog_reports_and_exits_when_hung(monkeypatch):
    """If the check hangs, the watchdog prints FAILED and exits with code 2."""
    monkeypatch.setattr(smoke, "CLOSE_GRACE_SEC", 0.01)
    out = io.StringIO()
    exited = threading.Event()
    codes = []

    def hard_exit(code):
        codes.append(code)
        exited.set()

    check = smoke.SmokeCheck(ScriptedWindow([READY]), timeout=0.0, out=out, hard_exit=hard_exit)
    try:
        check.arm()
        assert exited.wait(5)
    finally:
        check.disarm()
    assert codes == [2]
    verdict, result = parse(out.getvalue())
    assert verdict == "FAILED" and "Timed out" in result["error"]


def test_watchdog_after_pass_still_fails_if_window_stays_open():
    """A passed check whose window never closes still ends the process with code 2."""
    out = io.StringIO()
    codes = []
    check = smoke.SmokeCheck(ScriptedWindow([READY]), out=out, hard_exit=codes.append)
    check._report({"ok": True})
    check._on_timeout()
    assert codes == [2]
    assert out.getvalue().splitlines()[-1].startswith("SMOKE TEST FAILED")


def test_disarm_without_arm_is_safe():
    """disarm() before arm() does nothing."""
    smoke.SmokeCheck(ScriptedWindow([READY])).disarm()
