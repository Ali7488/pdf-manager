"""Tests for api.app: what the window shows, and main() wiring without a real window."""

from __future__ import annotations

import sys

import pytest

from api import app, logging_setup, paths, platforms, smoke
from api.bridge import Api


@pytest.fixture
def index(monkeypatch, tmp_path):
    """Point ui_index() at a temporary dist/index.html (not created)."""
    path = tmp_path / "frontend" / "dist" / "index.html"
    monkeypatch.setattr(paths, "ui_index", lambda: path)
    monkeypatch.delenv(app.UI_URL_ENV, raising=False)
    return path


def test_built_ui_loads_as_file_url(index):
    """The built UI is loaded as a file:// URL (no local server)."""
    index.parent.mkdir(parents=True)
    index.write_text("<!doctype html>", encoding="utf-8")
    url, page = app.ui_source()
    assert url == index.resolve().as_uri() and url.startswith("file://")
    assert page is None


def test_missing_ui_shows_message(index, logs):
    """Without a built UI, an explanation page is shown instead of a blank window."""
    url, page = app.ui_source()
    assert url is None
    assert "interface files are missing" in page
    assert "npm run build" in page  # Development hint.


def test_missing_ui_page_production_and_escaping(monkeypatch, tmp_path):
    """The production page asks for a reinstall and escapes the path."""
    monkeypatch.setattr(logging_setup, "dev_mode", lambda: False)
    monkeypatch.setattr(app, "dev_mode", lambda: False)
    # No "/" in the hostile name: Windows would treat it as a folder separator.
    page = app.missing_ui_page(tmp_path / "<script>alert(1)" / "index.html")
    assert "reinstall" in page and "npm" not in page
    assert "<script>alert(1)" not in page and "&lt;script&gt;alert(1)" in page


def test_dev_url_override(index, monkeypatch):
    """In dev mode PDF_MANAGER_UI_URL loads a dev server."""
    monkeypatch.setenv(app.UI_URL_ENV, "http://localhost:5173")
    assert app.ui_source() == ("http://localhost:5173", None)


def test_dev_url_ignored_in_production(index, monkeypatch, logs):
    """The override is ignored in the installed app."""
    monkeypatch.setenv(app.UI_URL_ENV, "http://localhost:5173")
    monkeypatch.setattr(app, "dev_mode", lambda: False)
    url, page = app.ui_source()
    assert url is None and page is not None


def test_dev_url_must_be_http(index, monkeypatch, logs):
    """Only http(s) URLs are accepted as an override."""
    monkeypatch.setenv(app.UI_URL_ENV, "javascript:alert(1)")
    url, _ = app.ui_source()
    assert url is None


class FakeWebview:
    """Records create_window/start calls instead of opening a window."""

    def __init__(self, window, fail=False):
        self.window = window
        self.fail = fail
        self.created = None
        self.started = None

    def create_window(self, title, **kwargs):
        self.created = {"title": title, **kwargs}
        return self.window

    def start(self, func=None, **kwargs):
        self.started = kwargs
        if self.fail:
            raise RuntimeError("no GUI backend")
        if func is not None:
            self.started["func"] = func
            func()


def run_main(monkeypatch, tmp_path, window, fail=False, smoke_test=False):
    """Run app.main() with a fake webview module and temporary folders."""
    fake = FakeWebview(window, fail)
    monkeypatch.setattr(app, "webview", fake)
    monkeypatch.setattr(platforms, "prepare_gui", lambda: "fake-gui")
    if smoke_test:
        monkeypatch.setenv(smoke.SMOKE_ENV, "1")
    else:
        monkeypatch.delenv(smoke.SMOKE_ENV, raising=False)
    monkeypatch.setattr(paths, "logs_dir", lambda: tmp_path / "logs")
    monkeypatch.setattr(paths, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(paths, "ui_index", lambda: tmp_path / "missing" / "index.html")
    shutdowns = []
    monkeypatch.setattr(Api, "_shutdown", lambda self: shutdowns.append(self))
    code = app.main()
    return code, fake, shutdowns


def test_main_creates_window_and_shuts_down(monkeypatch, tmp_path, window, logs):
    """main() creates the window with the Api, starts pywebview and cleans up."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    code, fake, shutdowns = run_main(monkeypatch, tmp_path, window)
    assert code == 0
    created = fake.created
    assert created["title"] == "PDF Manager"
    assert (created["width"], created["height"]) == (1040, 720)
    assert created["min_size"] == (860, 600)
    assert isinstance(created["js_api"], Api)
    assert created["url"] is None and "missing" in created["html"]
    # The GUI comes from the platform module (Qt with PySide6 on Linux, P18/P19).
    assert fake.started == {"debug": True, "gui": "fake-gui"}
    # The Api is bound to the window and listens for page loads (drag and drop).
    assert window.events.loaded.handlers == [created["js_api"]._on_loaded]
    # Closing the window asks first when that would lose work (P41).
    assert window.events.closing.handlers == [created["js_api"]._confirm_close]
    assert shutdowns == [created["js_api"]]


def test_main_reports_startup_failure(monkeypatch, tmp_path, window, logs):
    """A GUI failure is logged, still cleans up, and gives exit code 1."""
    code, fake, shutdowns = run_main(monkeypatch, tmp_path, window, fail=True)
    assert code == 1
    assert len(shutdowns) == 1
    log_text = (tmp_path / "logs" / "pdf-manager.log").read_text(encoding="utf-8")
    assert "no GUI backend" in log_text


def test_windows_start_is_unchanged(monkeypatch, tmp_path, window, logs):
    """On Windows no GUI is forced, so pywebview keeps using Edge WebView2."""
    from api.platforms import windows

    monkeypatch.delattr(sys, "frozen", raising=False)
    fake = FakeWebview(window)
    monkeypatch.setattr(app, "webview", fake)
    monkeypatch.setattr(platforms, "prepare_gui", windows.prepare_gui)
    monkeypatch.delenv(smoke.SMOKE_ENV, raising=False)
    monkeypatch.setattr(paths, "settings_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(Api, "_shutdown", lambda self: None)
    assert app.main() == 0
    assert fake.started == {"debug": True, "gui": None}


class FakeSmokeCheck:
    """Stands in for smoke.SmokeCheck: records how main() drives it."""

    instances: list = []
    next_exit_code = 0

    def __init__(self, window):
        self.window = window
        self.calls = []
        self.exit_code = FakeSmokeCheck.next_exit_code
        FakeSmokeCheck.instances.append(self)

    def arm(self):
        self.calls.append("arm")

    def run(self):
        self.calls.append("run")

    def disarm(self):
        self.calls.append("disarm")


@pytest.mark.parametrize("exit_code", [0, 1])
def test_smoke_test_mode(monkeypatch, tmp_path, window, logs, exit_code):
    """With PDF_MANAGER_SMOKE_TEST=1 the check runs in pywebview's thread and sets the exit code."""
    FakeSmokeCheck.instances = []
    FakeSmokeCheck.next_exit_code = exit_code
    monkeypatch.setattr(smoke, "SmokeCheck", FakeSmokeCheck)
    code, fake, shutdowns = run_main(monkeypatch, tmp_path, window, smoke_test=True)
    assert code == exit_code
    check = FakeSmokeCheck.instances[0]
    assert check.window is window
    assert check.calls == ["arm", "run", "disarm"]
    # No devtools window in smoke mode; same GUI as a normal start.
    assert fake.started == {"debug": False, "gui": "fake-gui", "func": check.run}
    assert len(shutdowns) == 1


def test_smoke_test_mode_gui_failure(monkeypatch, tmp_path, window, logs):
    """If the GUI can't start in smoke mode, main() fails with 1 and disarms the watchdog."""
    FakeSmokeCheck.instances = []
    FakeSmokeCheck.next_exit_code = 0
    monkeypatch.setattr(smoke, "SmokeCheck", FakeSmokeCheck)
    code, fake, shutdowns = run_main(monkeypatch, tmp_path, window, fail=True, smoke_test=True)
    assert code == 1
    assert FakeSmokeCheck.instances[0].calls == ["arm", "disarm"]
