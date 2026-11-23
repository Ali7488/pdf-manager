"""Tests for api.bridge: contract shapes, never raising, events, pickers, OCR and drag and drop."""

from __future__ import annotations

import inspect
import json
import subprocess
import threading
import time
from pathlib import Path

import fitz
import pytest

from api import bridge, paths, service
from api.bridge import Api, event_script
from api.jobs import JobManager
from api.service import JobResult, OutputFile, ToolCheck, ToolStatus, ocr_missing
from api.settings_store import SettingsStore

# Every method in the contract's Calls table, with its argument names.
CONTRACT = {
    "get_app_info": [],
    "get_settings": [],
    "save_settings": ["patch"],
    "pick_files": ["kind"],
    "pick_folder": [],
    "check_tools": ["action", "settings", "data"],
    "get_ocr_status": [],
    "get_ocr_languages": [],
    "search_ocr": [],
    "install_ocr": [],
    "start_job": ["action", "settings", "data"],
    "cancel_job": ["job_id"],
    "save_results": ["job_id", "options"],
    "discard_results": ["job_id"],
    "open_folder": ["path"],
    "open_logs_folder": [],
}

ISSUE_KEYS = {
    "code",
    "severity",
    "title",
    "message",
    "troubleshooting",
    "details",
    "logFile",
    "file",
}
SETTINGS = {
    "useOcr": False,
    "contentsPage": False,
    "split": {"method": "ranges", "ranges": "", "everyN": 1},
    "combineImages": True,
    "compressLevel": "balanced",
}


def make_pdf(path: Path, pages: int = 2) -> Path:
    """Write a small PDF with neutral sample text."""
    with fitz.open() as doc:
        for number in range(pages):
            doc.new_page().insert_text((72, 72), f"Sample page {number + 1}")
        doc.save(str(path))
    return path


def wait_for(predicate, timeout=5.0):
    """Poll until predicate() is truthy."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeRun:
    """A fake service run_action that records its call and writes one output."""

    def __init__(self):
        self.calls = []
        self.release = threading.Event()
        self.release.set()

    def __call__(self, action, settings, data, *, scratch, progress=None, cancel=None):
        self.calls.append((action, settings, data))
        self.release.wait(5)
        out = scratch / "out.pdf"
        make_pdf(out, 1)
        return JobResult([OutputFile("Sample - Merged.pdf", out, 1, out.stat().st_size)])


@pytest.fixture
def run():
    return FakeRun()


@pytest.fixture
def store(tmp_path):
    store = SettingsStore(tmp_path / "config" / "settings.json")
    store.load()
    return store


@pytest.fixture
def api_obj(window, store, run, tmp_path, logs):
    """An Api bound to the fake window, with a fake run_action."""
    api = Api(store)
    api._jobs = JobManager(api._emit, run_action=run, temp_dir=tmp_path)
    api._bind_window(window)
    yield api
    api._shutdown()


def assert_issue(value, code=None):
    """Check a contract-shaped Issue."""
    assert set(value) == ISSUE_KEYS
    assert isinstance(value["troubleshooting"], list)
    if code:
        assert value["code"] == code


# ----- Exposure and signatures -----


def test_public_surface_is_exactly_the_contract(api_obj):
    """pywebview exposes public attributes, so only contract methods may be public."""
    public = {name for name in dir(api_obj) if not name.startswith("_")}
    assert public == set(CONTRACT)


@pytest.mark.parametrize(("name", "args"), CONTRACT.items())
def test_signatures_match_contract(name, args):
    """pywebview builds the JS stubs from the argument names, so they must be real."""
    assert inspect.getfullargspec(getattr(Api, name)).args == ["self", *args]


def test_methods_never_raise_on_garbage(api_obj, window):
    """Malformed arguments return contract-shaped results instead of raising."""
    window.dialog_results = [None] * 10
    garbage = {"x": object()}
    assert api_obj.save_settings("not an object")["theme"] == "system"
    assert api_obj.pick_files(42) == []
    result = api_obj.check_tools("nope", None, 5)
    assert result["ok"] is False
    assert_issue(result["issues"][0], "UNEXPECTED_ERROR")
    assert_issue(api_obj.start_job(None, garbage, [])["issue"], "UNEXPECTED_ERROR")
    assert api_obj.cancel_job(None) is None
    assert_issue(api_obj.save_results(3, "x")["issue"], "UNEXPECTED_ERROR")
    assert api_obj.discard_results({}) is None
    assert api_obj.open_folder(None) is None


def test_methods_never_raise_without_window(store, logs):
    """Even with no window (a bug), dialogs and events fail softly."""
    api = Api(store)
    assert api.pick_files("documents") == []
    assert api.pick_folder() is None
    assert api.install_ocr() is None
    api._shutdown()


def test_unexpected_exception_becomes_issue(api_obj, monkeypatch, logs):
    """A bug inside a method is logged with its traceback and returned as an issue."""

    def broken(*args):
        raise ZeroDivisionError("bug")

    monkeypatch.setattr(service, "check_tools", broken)
    result = api_obj.check_tools("merge", SETTINGS, {"files": []})
    assert result["ok"] is False
    issue = result["issues"][0]
    assert_issue(issue, "UNEXPECTED_ERROR")
    assert "ZeroDivisionError" in issue["details"]
    assert issue["logFile"] == str(logs)
    assert "Traceback" in logs.read_text(encoding="utf-8")


# ----- Events -----


def test_event_script_escapes_payload():
    """File names with markup, quotes and line separators can't break out of the script."""
    name = "A </script><script>alert(\"x\")</script> 'q' \u2028 & \\ .pdf"
    script = event_script("filesAdded", {"files": [{"name": name}]})
    assert "<" not in script and ">" not in script and "&" not in script
    assert "\u2028" not in script and "\n" not in script
    prefix = 'window.dispatchEvent(new CustomEvent("pdfmanager:filesAdded", {detail: '
    assert script.startswith(prefix) and script.endswith("}));")
    literal = script[len(prefix) : -len("}));")]
    assert json.loads(literal) == {"files": [{"name": name}]}


@pytest.mark.parametrize("bad", ["", "files Added", 'x"); alert(1); ("', "1abc"])
def test_event_script_rejects_bad_names(bad):
    """Event names are checked, so they can't inject code."""
    with pytest.raises(ValueError):
        event_script(bad, {})


def test_event_script_rejects_nan():
    """NaN isn't JSON; it's refused rather than sent."""
    with pytest.raises(ValueError):
        event_script("jobProgress", {"fraction": float("nan")})


def test_emit_failure_is_swallowed(api_obj, window):
    """A window that fails to run scripts doesn't break the caller."""

    def broken(script):
        raise RuntimeError("window closed")

    window.evaluate_js = broken
    api_obj._emit("filesAdded", {"files": []})


# ----- App info and settings -----


def test_get_app_info(api_obj, logs):
    """AppInfo has version, logs folder and platform."""
    info = api_obj.get_app_info()
    assert set(info) == {"version", "logsDir", "platform"}
    assert info["logsDir"] == str(logs.parent)
    assert info["platform"] in {"windows", "linux", "mac"}


def test_settings_round_trip(api_obj, store):
    """save_settings merges, persists and returns the full settings."""
    assert api_obj.get_settings()["dpi"] == 200
    saved = api_obj.save_settings({"dpi": 300, "theme": "neon"})
    assert saved["dpi"] == 300 and saved["theme"] == "system"
    assert json.loads(store.path.read_text(encoding="utf-8"))["dpi"] == 300
    assert api_obj.get_settings() == saved


# ----- Pickers -----


def test_pick_files_describes_usable_files(api_obj, window, tmp_path):
    """Only existing, supported files come back, in order, without duplicates."""
    pdf = make_pdf(tmp_path / "Report.pdf", 3)
    image = tmp_path / "Scan.png"
    image.write_bytes(b"\x89PNG sample")
    other = tmp_path / "notes.txt"
    other.write_text("sample")
    window.dialog_results = [
        (str(pdf), str(tmp_path / "missing.pdf"), str(other), str(image), str(pdf))
    ]
    files = api_obj.pick_files("documents")
    assert [f["name"] for f in files] == ["Report.pdf", "Scan.png"]
    assert files[0] == {
        "path": str(pdf),
        "name": "Report.pdf",
        "kind": "pdf",
        "sizeBytes": pdf.stat().st_size,
        "pageCount": 3,
    }
    call = window.dialog_calls[0]
    assert call["multiple"] is True
    assert call["file_types"] == ("PDF and PowerPoint files (*.pdf;*.pptx;*.ppt)",)


def test_pick_files_images_filter_and_cancel(api_obj, window):
    """The images picker uses the image filter; cancelling returns an empty list."""
    window.dialog_results = [None]
    assert api_obj.pick_files("images") == []
    assert window.dialog_calls[0]["file_types"] == ("Images (*.png;*.jpg;*.jpeg)",)


def test_pick_files_all_kinds(api_obj, window, tmp_path):
    """ "all" offers every supported type in one filter and returns documents and images."""
    pdf = make_pdf(tmp_path / "Report.pdf", 1)
    image = tmp_path / "Scan.jpg"
    image.write_bytes(b"\xff\xd8 sample")
    window.dialog_results = [(str(pdf), str(image))]
    files = api_obj.pick_files("all")
    assert [(f["name"], f["kind"]) for f in files] == [("Report.pdf", "pdf"), ("Scan.jpg", "image")]
    filters = window.dialog_calls[0]["file_types"]
    assert len(filters) == 1
    assert all(ext in filters[0] for ext in ("*.pdf", "*.pptx", "*.ppt", "*.png", "*.jpg"))


def test_pick_files_rejects_unknown_kind(api_obj, window):
    """An unknown kind opens no dialog."""
    assert api_obj.pick_files("videos") == []
    assert window.dialog_calls == []


def test_pick_folder(api_obj, window, store, tmp_path):
    """pick_folder returns the chosen folder (starting in the default folder) or None."""
    store.update({"defaultSaveFolder": str(tmp_path)})
    window.dialog_results = [(str(tmp_path / "out"),), None]
    assert api_obj.pick_folder() == str(tmp_path / "out")
    assert window.dialog_calls[0]["directory"] == str(tmp_path)
    assert api_obj.pick_folder() is None


# ----- Tool check and OCR -----


def test_check_tools_shape_and_logged_issues(api_obj, monkeypatch, logs):
    """check_tools forwards parsed arguments and returns ToolCheckResult with logged issues."""
    seen = {}

    def fake(action, settings, data):
        seen.update(action=action, ocr=settings.use_ocr, files=data.files)
        return ToolCheck(
            False,
            ToolStatus(True, False, None),
            ToolStatus(False, False, None),
            ToolStatus(False, False, None),
            [ocr_missing()],
        )

    monkeypatch.setattr(service, "check_tools", fake)
    result = api_obj.check_tools("flatten", dict(SETTINGS, useOcr=True), {"files": ["/a.pdf"]})
    assert seen == {"action": "flatten", "ocr": True, "files": [Path("/a.pdf")]}
    assert result["ok"] is False
    assert result["ocr"] == {"required": True, "present": False, "path": None}
    assert_issue(result["issues"][0], "OCR_MISSING")
    assert result["issues"][0]["logFile"] == str(logs)


def test_get_ocr_status(api_obj, monkeypatch, store, window):
    """OcrStatus reports presence and path, using the saved path, without saving or asking."""
    seen = []

    def fake_find(configured=None):
        seen.append(configured)
        return Path("/apps/tesseract") if configured else None

    monkeypatch.setattr(service, "find_tesseract", fake_find)
    assert api_obj.get_ocr_status() == {"present": False, "path": None}
    store.update({"tesseractPath": "/apps/tesseract"})
    assert api_obj.get_ocr_status() == {"present": True, "path": str(Path("/apps/tesseract"))}
    assert seen == [None, "/apps/tesseract"]
    assert window.dialog_calls == []


def test_get_ocr_status_never_raises(api_obj, monkeypatch):
    """A failing search reports OCR as not present."""

    def broken(configured=None):
        raise OSError("registry unavailable")

    monkeypatch.setattr(service, "find_tesseract", broken)
    assert api_obj.get_ocr_status() == {"present": False, "path": None}


def test_get_ocr_languages(api_obj, monkeypatch):
    """Languages come from the found Tesseract; none if it's missing."""
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: None)
    assert api_obj.get_ocr_languages() == []
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: Path("/t/tesseract"))
    monkeypatch.setattr(service, "tesseract_languages", lambda path: ["deu", "eng"])
    assert api_obj.get_ocr_languages() == ["deu", "eng"]


def test_search_ocr_found_automatically(api_obj, monkeypatch, store, window):
    """A Tesseract found in the usual places is saved without opening a picker."""
    found = Path("/apps/Tesseract-OCR/tesseract.exe")
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: found)
    assert api_obj.search_ocr() == {"found": True, "path": str(found), "issue": None}
    assert store.get()["tesseractPath"] == str(found)
    assert window.dialog_calls == []


def test_search_ocr_picker_cancelled(api_obj, monkeypatch, window):
    """Not found and picker cancelled: OCR_MISSING."""
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: None)
    window.dialog_results = [None]
    result = api_obj.search_ocr()
    assert result["found"] is False and result["path"] is None
    assert_issue(result["issue"], "OCR_MISSING")


def test_search_ocr_rejects_wrong_file(api_obj, monkeypatch, window, tmp_path, store):
    """A picked file that isn't named tesseract is refused and not saved."""
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: None)
    wrong = tmp_path / "notepad.exe"
    wrong.write_bytes(b"sample")
    window.dialog_results = [(str(wrong),)]
    result = api_obj.search_ocr()
    assert result["found"] is False
    assert "isn't the OCR program" in result["issue"]["message"]
    assert "notepad.exe" in result["issue"]["details"]
    assert store.get()["tesseractPath"] is None


def test_search_ocr_validates_with_version(api_obj, monkeypatch, window, tmp_path, store):
    """A picked tesseract is accepted only if --version runs and mentions tesseract."""
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: None)
    exe = tmp_path / "tesseract.exe"
    exe.write_bytes(b"sample")
    outputs = iter(
        [
            subprocess.CompletedProcess([], 1, "", "boom"),
            subprocess.CompletedProcess([], 0, "tesseract 5.4.0\n leptonica-1.84", ""),
        ]
    )
    monkeypatch.setattr(service, "run_command", lambda cmd, timeout=0, cancel=None: next(outputs))
    window.dialog_results = [(str(exe),), (str(exe),)]
    failed = api_obj.search_ocr()
    assert failed["found"] is False and "exited with 1" in failed["issue"]["details"]
    assert api_obj.search_ocr() == {"found": True, "path": str(exe), "issue": None}
    assert store.get()["tesseractPath"] == str(exe)


def test_install_ocr_off_windows_fails_with_guidance(api_obj, monkeypatch, window):
    """Without Windows/winget the install ends at once with OCR_INSTALL_FAILED."""
    monkeypatch.setattr(paths, "on_windows", lambda: False)
    assert api_obj.install_ocr() is None
    finished = window.events_named("ocrInstallFinished")
    assert len(finished) == 1 and finished[0]["ok"] is False
    assert_issue(finished[0]["issue"], "OCR_INSTALL_FAILED")
    assert "Search for OCR" in finished[0]["issue"]["details"]


def test_install_ocr_with_winget(api_obj, monkeypatch, window, store):
    """On Windows, winget runs in the background and the found path is saved."""
    monkeypatch.setattr(paths, "on_windows", lambda: True)
    monkeypatch.setattr(bridge.shutil, "which", lambda name: "C:\\winget.exe")
    commands = []

    def fake_run(cmd, timeout=0, cancel=None):
        commands.append((list(cmd), timeout))
        return subprocess.CompletedProcess(cmd, 0, "Successfully installed", "")

    found = Path("C:/Users/Example/AppData/Local/Programs/Tesseract-OCR/tesseract.exe")
    monkeypatch.setattr(service, "run_command", fake_run)
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: found)
    api_obj.install_ocr()
    assert wait_for(lambda: window.events_named("ocrInstallFinished"))
    assert window.events_named("ocrInstallFinished") == [{"ok": True, "issue": None}]
    assert window.events_named("ocrInstallProgress")
    assert commands[0][0][:4] == ["winget", "install", "--id", "UB-Mannheim.TesseractOCR"]
    assert "--silent" in commands[0][0] and commands[0][1] == 20 * 60
    assert store.get()["tesseractPath"] == str(found)


def test_install_ocr_failure_reports_winget_output(api_obj, monkeypatch, window):
    """If Tesseract still isn't found afterwards, the issue carries winget's output."""
    monkeypatch.setattr(paths, "on_windows", lambda: True)
    monkeypatch.setattr(bridge.shutil, "which", lambda name: "C:\\winget.exe")
    monkeypatch.setattr(
        service,
        "run_command",
        lambda cmd, timeout=0, cancel=None: subprocess.CompletedProcess(cmd, 5, "", "No network"),
    )
    monkeypatch.setattr(service, "find_tesseract", lambda configured=None: None)
    api_obj.install_ocr()
    assert wait_for(lambda: window.events_named("ocrInstallFinished"))
    finished = window.events_named("ocrInstallFinished")[0]
    assert finished["ok"] is False
    assert "exit code 5" in finished["issue"]["details"]
    assert "No network" in finished["issue"]["details"]


# ----- Jobs -----


def finished_events(window):
    """Wait for and return jobFinished payloads."""
    assert wait_for(lambda: window.events_named("jobFinished"))
    return window.events_named("jobFinished")


def test_start_job_and_save(api_obj, window, run, store, tmp_path):
    """start_job returns a jobId, forwards saved settings, and save_results copies outputs."""
    store.update({"dpi": 300, "ocrLanguage": "deu"})
    started = api_obj.start_job("merge", SETTINGS, {"files": ["/in/Sample.pdf"]})
    assert set(started) == {"jobId"}
    finished = finished_events(window)[0]
    assert finished["jobId"] == started["jobId"] and finished["status"] == "succeeded"
    action, settings, data = run.calls[0]
    assert action == "merge" and settings.dpi == 300 and settings.ocr_language == "deu"
    assert data.files == [Path("/in/Sample.pdf")]

    # The picker is cancelled: nothing is lost.
    window.dialog_results = [None]
    outcome = api_obj.save_results(started["jobId"], {"folder": None, "asZip": False})
    assert outcome == {"cancelled": True, "savedPaths": [], "folder": None, "issue": None}

    out = tmp_path / "out"
    out.mkdir()
    outcome = api_obj.save_results(started["jobId"], {"folder": str(out), "asZip": False})
    assert outcome == {
        "cancelled": False,
        "savedPaths": [str(out / "Sample - Merged.pdf")],
        "folder": str(out),
        "issue": None,
    }


def test_save_results_via_picker(api_obj, window, tmp_path):
    """folder null opens the picker and saves into the chosen folder."""
    job_id = api_obj.start_job("merge", SETTINGS, {"files": ["/in/Sample.pdf"]})["jobId"]
    finished_events(window)
    window.dialog_results = [(str(tmp_path),)]
    outcome = api_obj.save_results(job_id, {"folder": None, "asZip": False})
    assert outcome["folder"] == str(tmp_path) and outcome["savedPaths"]


def test_save_failure_returns_issue(api_obj, window, tmp_path):
    """A save into a missing folder returns SAVE_FAILED and keeps the results."""
    job_id = api_obj.start_job("merge", SETTINGS, {"files": ["/in/Sample.pdf"]})["jobId"]
    finished_events(window)
    outcome = api_obj.save_results(job_id, {"folder": str(tmp_path / "gone"), "asZip": False})
    assert outcome["cancelled"] is False and outcome["savedPaths"] == []
    assert_issue(outcome["issue"], "SAVE_FAILED")
    assert outcome["issue"]["logFile"]
    retry = api_obj.save_results(job_id, {"folder": str(tmp_path), "asZip": False})
    assert retry["issue"] is None


def test_second_job_is_refused(api_obj, window, run):
    """Only one job at a time: the second start returns JOB_ALREADY_RUNNING."""
    run.release.clear()
    first = api_obj.start_job("merge", SETTINGS, {"files": ["/in/a.pdf"]})
    second = api_obj.start_job("merge", SETTINGS, {"files": ["/in/b.pdf"]})
    assert "jobId" in first
    assert_issue(second["issue"], "JOB_ALREADY_RUNNING")
    run.release.set()
    finished_events(window)


def test_cancel_and_discard(api_obj, window, run, tmp_path):
    """cancel_job and discard_results return None and do their work."""
    run.release.clear()
    job_id = api_obj.start_job("merge", SETTINGS, {"files": ["/in/a.pdf"]})["jobId"]
    assert api_obj.cancel_job(job_id) is None
    run.release.set()
    finished_events(window)
    assert api_obj.discard_results(job_id) is None
    assert not list(tmp_path.glob("pdf-manager-*"))


def test_discard_results_repeated_and_after_save(api_obj, window, tmp_path):
    """discard_results is safe twice, after saving, and for unknown ids."""
    job_id = api_obj.start_job("merge", SETTINGS, {"files": ["/in/a.pdf"]})["jobId"]
    finished_events(window)
    assert api_obj.save_results(job_id, {"folder": str(tmp_path), "asZip": False})["savedPaths"]
    assert api_obj.discard_results(job_id) is None
    assert api_obj.discard_results(job_id) is None
    assert api_obj.discard_results("never-existed") is None
    assert (tmp_path / "Sample - Merged.pdf").is_file()


# ----- Folders -----


def test_open_folder_only_opens_folders(api_obj, monkeypatch, tmp_path):
    """open_folder opens existing folders and refuses files (which would launch them)."""
    opened = []
    monkeypatch.setattr(bridge, "_open_in_file_manager", opened.append)
    program = tmp_path / "setup.exe"
    program.write_bytes(b"sample")
    api_obj.open_folder(str(program))
    api_obj.open_folder(str(tmp_path / "missing"))
    api_obj.open_folder(str(tmp_path))
    assert opened == [tmp_path]


def test_open_logs_folder_creates_it(api_obj, monkeypatch, logs):
    """open_logs_folder creates the logs folder if needed, then opens it."""
    opened = []
    monkeypatch.setattr(bridge, "_open_in_file_manager", opened.append)
    for handler in list(bridge.logging_setup._handlers):
        handler.close()
    logs.unlink()
    logs.parent.rmdir()
    api_obj.open_logs_folder()
    assert opened == [logs.parent] and logs.parent.is_dir()


# ----- Drag and drop -----


def test_loaded_subscribes_drop_and_dragover(api_obj, window):
    """When the page loads, drop and dragover are subscribed with preventDefault."""
    assert window.events.loaded.handlers == [api_obj._on_loaded]
    api_obj._on_loaded()
    subscriptions = window.dom.document.events.subscriptions
    assert set(subscriptions) == {"drop", "dragover"}
    assert all(h.prevent_default for handlers in subscriptions.values() for h in handlers)
    assert subscriptions["drop"][0].callback == api_obj._on_drop
    assert subscriptions["dragover"][0].debounce > 0


def test_drop_emits_files_added(api_obj, window, tmp_path):
    """Dropped files with full paths become filesAdded; others are skipped."""
    # Valid on Windows too (no < > " /); the </script> case is covered by event_script tests.
    pdf = make_pdf(tmp_path / "Report 'quoted' & more.pdf", 2)
    image = tmp_path / "Photo.JPG"
    image.write_bytes(b"\xff\xd8 sample")
    folder = tmp_path / "A folder"
    folder.mkdir()
    event = {
        "type": "drop",
        "dataTransfer": {
            "files": [
                {"name": pdf.name, "pywebviewFullPath": str(pdf)},
                {"name": "no-path.pdf"},  # pywebview couldn't match it to a path.
                {"name": folder.name, "pywebviewFullPath": str(folder)},
                {"name": "gone.pdf", "pywebviewFullPath": str(tmp_path / "gone.pdf")},
                {"name": "notes.txt", "pywebviewFullPath": str(tmp_path / "notes.txt")},
                {"name": image.name, "pywebviewFullPath": str(image)},
            ]
        },
    }
    api_obj._on_drop(event)
    added = window.events_named("filesAdded")
    assert len(added) == 1
    files = added[0]["files"]
    assert [f["name"] for f in files] == [pdf.name, "Photo.JPG"]
    assert files[0]["pageCount"] == 2 and files[1]["kind"] == "image"
    # The raw script carries the name escaped.
    assert "&" not in window.scripts[-1] and "\\u0026" in window.scripts[-1]


def test_drop_with_nothing_usable_emits_nothing(api_obj, window):
    """A drop with no usable files sends no event, and malformed events don't raise."""
    api_obj._on_drop({"dataTransfer": {"files": [{"name": "x"}]}})
    api_obj._on_drop({})
    api_obj._on_drop({"dataTransfer": None})
    assert window.events_named("filesAdded") == []
