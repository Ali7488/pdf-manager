"""Tests for browser mode (api.web): the real server on 127.0.0.1, in-process.

The workflow is real; only the conversion (``run_action``), the native
pickers and opening folders or browsers are replaced. Requests are made with
http.client so every header (Host, Origin, Cookie) is under the test's control.
"""

from __future__ import annotations

import http.client
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlsplit

import fitz
import pytest

from api import platforms, service
from api.jobs import JobManager
from api.settings_store import SettingsStore
from api.web import launch, server
from api.web.operations import Context
from api.web.server import AppServer
from api.web.session import Session, UploadError, safe_upload_name
from api.workflow import Workflow
from converter.core.types import JobResult, OutputFile

ROOT = Path(__file__).resolve().parents[2]


def make_pdf(path: Path, pages: int = 1) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    doc.save(path)
    doc.close()
    return path


class FakeRun:
    """A fake run_action: optionally waits, then writes one or two outputs."""

    def __init__(self):
        self.release = threading.Event()
        self.release.set()
        self.calls = []
        self.outputs = 1

    def __call__(self, action, settings, data, *, scratch, progress=None, cancel=None):
        self.calls.append((action, data))
        self.release.wait(5)
        outputs = []
        for index in range(self.outputs):
            out = make_pdf(scratch / f"out{index}.pdf")
            outputs.append(OutputFile(f"Result {index}.pdf", out, 1, out.stat().st_size))
        return JobResult(outputs)


class Client:
    """A browser stand-in: keeps the cookie, sends the headers a same-origin page sends."""

    def __init__(self, app: AppServer):
        self.app = app
        self.cookie = None

    def raw(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection(server.HOST, self.app.server_port, timeout=10)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def launch(self):
        url = urlsplit(self.app.launch_url())
        response, _ = self.raw("GET", f"/?{url.query}", headers={"Host": self.app.host})
        assert response.status == 303
        self.cookie = response.getheader("Set-Cookie").split(";")[0]
        return response

    def headers(self, extra=None, json_body=True):
        base = {"Host": self.app.host, "X-PDF-Manager": "1", "Origin": self.app.origin}
        if self.cookie:
            base["Cookie"] = self.cookie
        if json_body:
            base["Content-Type"] = "application/json"
        return {**base, **(extra or {})}

    def get(self, path, extra=None):
        headers = self.headers(extra, json_body=False)
        headers.pop("Origin", None)  # Browsers don't send Origin on same-origin GET.
        response, data = self.raw("GET", path, headers=headers)
        return response.status, (json.loads(data) if data.startswith(b"{") else data)

    def post(self, path, body=None, extra=None):
        response, data = self.raw("POST", path, json.dumps(body or {}), self.headers(extra))
        return response.status, json.loads(data)

    def result(self, method, path, body=None):
        status, data = self.get(path) if method == "GET" else self.post(path, body)
        assert status == 200, (status, data)
        return data["result"]


@pytest.fixture
def ui_dir(tmp_path):
    folder = tmp_path / "ui"
    folder.mkdir()
    (folder / "index.html").write_text(
        "<!doctype html><html><head><title>PDF Manager</title></head><body>app</body></html>"
    )
    return folder


@pytest.fixture
def opened(monkeypatch):
    """Folders the app opened (instead of a real file manager)."""
    folders = []
    monkeypatch.setattr(platforms, "open_folder", folders.append)
    return folders


@pytest.fixture
def app(tmp_path, ui_dir, logs, opened):
    store = SettingsStore(tmp_path / "config" / "settings.json")
    store.load()
    session = Session(tmp_path)
    run = FakeRun()
    workflow = Workflow(store, session.record)
    workflow.jobs = JobManager(session.record, run_action=run, temp_dir=tmp_path)
    stopped = threading.Event()
    ctx = Context(workflow, session, native_dialogs=True, request_stop=stopped.set)
    instance = AppServer(ctx, ui_dir, "instance-key")
    instance.run = run
    instance.stopped = stopped
    thread = threading.Thread(
        target=instance.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
    )
    thread.start()
    yield instance
    instance.closing = True
    workflow.shutdown()
    instance.shutdown()
    instance.server_close()
    session.close()


@pytest.fixture
def client(app):
    c = Client(app)
    c.launch()
    return c


def upload(client, path: Path, name=None, body=None):
    name = name or path.name
    response, data = client.raw(
        "POST",
        f"/api/files/upload?name={quote(name)}",
        body=path.read_bytes() if body is None else body,
        headers=client.headers({"Content-Type": "application/octet-stream"}),
    )
    assert response.status == 200, data
    return json.loads(data)["result"]


def wait_finished(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.result("GET", f"/api/jobs/{job_id}")
        if status["finished"]:
            return status["finished"]
        time.sleep(0.02)
    raise AssertionError("job didn't finish")


# ----- The page and the session -----


def test_page_needs_the_single_use_launch_link(app):
    client = Client(app)
    response, body = client.raw("GET", "/", headers={"Host": app.host})
    assert response.status == 403 and b"Start PDF Manager" in body
    url = urlsplit(app.launch_url())
    first, _ = client.raw("GET", f"/?{url.query}", headers={"Host": app.host})
    assert first.status == 303 and first.getheader("Location") == "/"
    cookie = first.getheader("Set-Cookie")
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie and app.secret in cookie
    again, body = client.raw("GET", f"/?{url.query}", headers={"Host": app.host})
    assert again.status == 403 and b"already been used" in body


def test_page_carries_the_bootstrap_tag_and_strict_headers(client, app):
    response, body = client.raw("GET", "/", headers={"Host": app.host, "Cookie": client.cookie})
    assert response.status == 200
    assert b'<meta name="pdf-manager-mode" content="browser" data-native-dialogs="true">' in body
    csp = response.getheader("Content-Security-Policy")
    assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert response.getheader("Cache-Control") == "no-store"
    assert response.getheader("Referrer-Policy") == "no-referrer"


def test_launch_codes_expire(app, monkeypatch):
    url = urlsplit(app.launch_url())
    code = url.query.removeprefix("launch=")
    monkeypatch.setattr(server, "LAUNCH_CODE_TTL_SEC", -1)
    assert app.redeem(code) is False


@pytest.mark.parametrize(
    "change",
    [
        {"Cookie": None},
        {"Cookie": "pdf-manager-1=wrong"},
        {"X-PDF-Manager": None},
        {"Origin": "http://evil.example"},
        {"Origin": None},  # POST without Origin.
        {"Sec-Fetch-Site": "cross-site"},
        {"Host": "localhost:1"},
        {"Host": "evil.example"},
    ],
)
def test_api_refuses_requests_that_arent_from_the_apps_page(client, change):
    headers = client.headers()
    for key, value in change.items():
        if value is None:
            headers.pop(key, None)
        else:
            headers[key] = value
    response, _ = client.raw("POST", "/api/settings", json.dumps({"theme": "dark"}), headers)
    assert response.status in (403, 421)
    assert client.result("GET", "/api/settings")["theme"] == "system"


def test_wrong_session_cookie_for_reads_too(client, app):
    response, _ = client.raw(
        "GET",
        "/api/settings",
        headers={"Host": app.host, "X-PDF-Manager": "1", "Cookie": f"{app.cookie_name}=guess"},
    )
    assert response.status == 403


@pytest.mark.parametrize("method", ["PUT", "DELETE", "OPTIONS", "PATCH"])
def test_only_get_and_post_exist_and_there_is_no_cors(client, method):
    response, _ = client.raw(method, "/api/settings", headers=client.headers())
    assert response.status == 501
    assert response.getheader("Access-Control-Allow-Origin") is None


def test_unknown_routes_and_jobs(client):
    assert client.get("/api/nothing")[0] == 404
    assert client.get("/api/jobs/" + "0" * 32)[0] == 404


def test_bodies_are_bounded_and_must_be_json(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_JSON_BYTES", 10)
    assert client.post("/api/settings", {"theme": "dark" * 10})[0] == 413
    monkeypatch.setattr(server, "MAX_JSON_BYTES", 1000)
    response, _ = client.raw("POST", "/api/settings", "{nope", client.headers())
    assert response.status == 400
    headers = client.headers({"Content-Type": "text/plain"})
    response, _ = client.raw("POST", "/api/settings", "{}", headers)
    assert response.status == 400


def test_health_and_instance_launch(app):
    client = Client(app)
    response, body = client.raw("GET", "/api/health", headers={"Host": app.host})
    assert response.status == 200 and json.loads(body) == {"app": "PDF Manager"}
    response, _ = client.raw(
        "POST", "/api/instance/launch", headers={"Host": app.host, "X-PDF-Manager-Instance": "x"}
    )
    assert response.status == 403
    response, body = client.raw(
        "POST",
        "/api/instance/launch",
        headers={"Host": app.host, "X-PDF-Manager-Instance": "instance-key"},
    )
    assert response.status == 200 and json.loads(body)["url"].startswith(app.origin + "/?launch=")


def test_changes_are_refused_while_closing(client, app):
    app.closing = True
    assert client.post("/api/settings", {"theme": "dark"})[0] == 503
    assert client.get("/api/settings")[0] == 200


def test_concurrency_is_bounded(app):
    class FakeSocket:
        sent = b""

        def sendall(self, data):
            FakeSocket.sent += data

    for _ in range(server.MAX_CONCURRENT_REQUESTS):
        assert app._slots.acquire(blocking=False)
    closed = []
    app.shutdown_request = closed.append
    app.process_request(FakeSocket(), ("127.0.0.1", 1))
    assert FakeSocket.sent.startswith(b"HTTP/1.1 503") and closed
    for _ in range(server.MAX_CONCURRENT_REQUESTS):
        app._slots.release()


def test_quit_stops_the_app(client, app):
    assert client.result("POST", "/api/quit") is None
    assert app.stopped.is_set()


# ----- No host paths from the page -----


def test_settings_never_take_paths_or_programs_from_the_page(client, tmp_path):
    result = client.result(
        "POST",
        "/api/settings",
        {"defaultSaveFolder": str(tmp_path), "tesseractPath": "/bin/sh", "theme": "dark"},
    )
    settings = result["settings"]
    assert settings["theme"] == "dark"
    assert settings["defaultSaveFolder"] is None and settings["tesseractPath"] is None


def test_raw_paths_are_refused_everywhere(client, tmp_path, opened):
    pdf = make_pdf(tmp_path / "a.pdf")
    check = client.result(
        "POST",
        "/api/tools/check",
        {"action": "merge", "settings": {}, "data": {"files": [str(pdf)]}},
    )
    assert check["ok"] is False and "unknown file ID" in check["issues"][0]["details"]
    started = client.result(
        "POST",
        "/api/jobs",
        {"action": "merge", "settings": {}, "data": {"files": [str(pdf)]}, "requestId": "r" * 10},
    )
    assert "unknown file ID" in started["issue"]["details"]
    client.result("POST", "/api/folders/open", {"folder": str(tmp_path)})
    assert opened == []


def test_folders_the_session_showed_can_be_opened_but_not_saved_to(client, app, opened):
    info = client.result("GET", "/api/app-info")
    client.result("POST", "/api/folders/open", {"folder": info["licensesDir"]})
    assert opened == [Path(info["licensesDir"])]
    assert app.ctx.session.resolve_folder(info["licensesDir"], "save") is None


# ----- Files: native picks and uploads -----


def staged_bytes(app, file_id: str) -> bytes:
    """The bytes the session's ID resolves to."""
    return Path(app.ctx.session.resolve_files([file_id])[0]).read_bytes()


def upload_folders(app) -> list[Path]:
    root = app.ctx.session.staging / "uploads"
    return sorted(p for p in root.iterdir()) if root.is_dir() else []


def test_each_upload_gets_its_own_uuid_for_storage_and_lookup(client, app, tmp_path):
    pdf = make_pdf(tmp_path / "Report.pdf", 2)
    files = upload(client, pdf)
    assert len(files) == 1
    file_id = files[0]["path"]
    assert files[0]["name"] == "Report.pdf" and files[0]["pageCount"] == 2
    assert str(tmp_path) not in json.dumps(files)
    staged = Path(app.ctx.session.resolve_files([file_id])[0])
    # The ID is f-<uuid> and the same UUID names the private folder; the name is kept.
    assert file_id.startswith("f-") and len(file_id) == 34
    assert staged.parent == app.ctx.session.staging / "uploads" / file_id[2:]
    assert staged.name == "Report.pdf" and staged.read_bytes() == pdf.read_bytes()
    # The same file again is a new upload with a fresh UUID; the first is untouched.
    again = upload(client, pdf)[0]["path"]
    assert again != file_id and staged.read_bytes() == pdf.read_bytes()
    assert len(upload_folders(app)) == 2


def test_different_files_with_identical_name_size_and_time_stay_apart(client, app, tmp_path):
    """What the old name+size+time key would have merged must stay two uploads."""
    bodies = []
    for letter in "AB":
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), letter * 20)
        path = tmp_path / f"{letter}.pdf"
        doc.save(path)
        doc.close()
        bodies.append(path.read_bytes())
    body_a, body_b = bodies
    assert len(body_a) == len(body_b) and body_a != body_b
    first = tmp_path / "A.pdf"
    id_a = upload(client, first, name="Lecture.pdf", body=body_a)[0]["path"]
    id_b = upload(client, first, name="Lecture.pdf", body=body_b)[0]["path"]
    assert id_a != id_b
    assert staged_bytes(app, id_a) == body_a and staged_bytes(app, id_b) == body_b


def test_simultaneous_uploads_with_the_same_name_resolve_to_their_own_bytes(client, app, tmp_path):
    bodies = []
    for index in range(8):
        path = make_pdf(tmp_path / f"src{index}.pdf", index + 1)
        bodies.append(path.read_bytes())
    results: dict[int, str] = {}
    errors = []

    def send(index: int) -> None:
        try:
            files = upload(client, tmp_path / "src0.pdf", name="Same.pdf", body=bodies[index])
            results[index] = files[0]["path"]
        except Exception as exc:  # Reported below; a thread can't fail the test itself.
            errors.append(exc)

    threads = [threading.Thread(target=send, args=(i,)) for i in range(len(bodies))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not errors and len(results) == len(bodies)
    assert len(set(results.values())) == len(bodies)
    for index, file_id in results.items():
        assert staged_bytes(app, file_id) == bodies[index]
    assert len(upload_folders(app)) == len(bodies)


def test_a_failed_upload_leaves_nothing_and_a_retry_is_a_fresh_upload(
    client, app, tmp_path, monkeypatch
):
    pdf = make_pdf(tmp_path / "Report.pdf")
    body = pdf.read_bytes()
    attempts = []
    real = app.ctx.session.add_upload

    def counted(*args, **kwargs):
        try:
            return real(*args, **kwargs)
        finally:
            attempts.append(1)

    monkeypatch.setattr(app.ctx.session, "add_upload", counted)
    # The body stops early: the server sees fewer bytes than Content-Length.
    connection = http.client.HTTPConnection(server.HOST, app.server_port, timeout=10)
    connection.putrequest("POST", "/api/files/upload?name=Report.pdf", skip_host=True)
    for key, value in client.headers({"Content-Type": "application/octet-stream"}).items():
        connection.putheader(key, value)
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders()
    connection.send(body[: len(body) // 2])
    connection.close()  # The client gives up half way.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not attempts:
        time.sleep(0.02)
    assert attempts and upload_folders(app) == []  # Cleaned up, and no ID was published.
    assert app.ctx.session._files == {}
    retried = upload(client, pdf)[0]["path"]
    assert staged_bytes(app, retried) == body
    assert len(upload_folders(app)) == 1


def test_an_upload_is_published_only_after_it_is_staged_and_checked(tmp_path):
    session = Session(tmp_path)
    body = b"%PDF-1.4 whole"
    seen = []

    def describe(paths):
        # While the file is checked, its ID isn't known to the session yet.
        seen.append((paths[0].read_bytes(), dict(session._files)))
        return [{"path": str(paths[0]), "name": paths[0].name, "kind": "pdf"}]

    def reader():
        chunks = iter([body])
        return lambda size: next(chunks, b"")

    files = session.add_upload("a.pdf", len(body), reader(), describe)
    assert seen == [(body, {})]
    assert session.resolve_files([files[0]["path"]]) == [str(next(session.staging.rglob("a.pdf")))]
    unusable = session.add_upload("b.pdf", len(body), reader(), lambda paths: [])
    assert unusable == [] and len(list((session.staging / "uploads").iterdir())) == 1
    session.close()


def test_unusable_uploads_add_nothing(client, tmp_path, monkeypatch):
    other = tmp_path / "notes.txt"
    other.write_text("text")
    assert upload(client, other) == []
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    assert upload(client, broken) == [] or upload(client, broken)[0]["pageCount"] is None
    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 5)
    response, _ = client.raw(
        "POST",
        "/api/files/upload?name=a.pdf",
        body=b"0123456789",
        headers=client.headers({"Content-Type": "application/octet-stream"}),
    )
    assert response.status == 413


def test_upload_names_are_made_safe():
    assert safe_upload_name("..\\..\\Windows\\evil.pdf") == "evil.pdf"
    assert safe_upload_name('a<b>:"c".pdf') == "a_b___c_.pdf"
    with pytest.raises(UploadError):
        safe_upload_name("..")


def test_an_upload_that_ends_early_leaves_nothing(tmp_path):
    session = Session(tmp_path)
    chunks = iter([b"%PDF-1.4 part", b""])
    with pytest.raises(UploadError):
        session.add_upload("a.pdf", 1000, lambda n: next(chunks), lambda paths: [])
    assert list((session.staging / "uploads").iterdir()) == []
    assert session._files == {}
    session.close()


def test_native_pick_returns_ids_for_the_real_files(client, tmp_path, monkeypatch):
    pdf = make_pdf(tmp_path / "Picked.pdf")
    monkeypatch.setattr(platforms, "ask_files", lambda filters, multiple: [pdf])
    files = client.result("POST", "/api/files/pick", {"kind": "documents"})
    assert files[0]["path"].startswith("f-") and files[0]["name"] == "Picked.pdf"
    assert client.result("POST", "/api/files/pick", {"kind": "anything"}) == []


def test_without_native_pickers_the_page_must_upload(client, app):
    app.ctx.native_dialogs = False
    assert client.result("POST", "/api/files/pick", {"kind": "all"}) == []
    assert client.result("POST", "/api/folders/pick") is None


def test_picked_folder_becomes_the_default_save_folder(client, tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(platforms, "ask_folder", lambda start: out)
    folder_id = client.result("POST", "/api/folders/pick")
    assert folder_id.startswith("d-")
    settings = client.result("POST", "/api/settings", {"defaultSaveFolder": folder_id})["settings"]
    assert settings["defaultSaveFolder"] == str(out)


def test_search_ocr_never_uses_a_path_from_the_page(client, app, monkeypatch):
    monkeypatch.setattr(service, "find_tesseract", lambda saved=None: None)
    asked = []
    monkeypatch.setattr(platforms, "ask_files", lambda f, m: asked.append(1) or [])
    result = client.result("POST", "/api/ocr/search", {"path": "/bin/sh"})
    assert result["found"] is False and asked == [1]
    app.ctx.native_dialogs = False
    assert client.result("POST", "/api/ocr/search")["found"] is False and asked == [1]


# ----- Jobs, saving and downloads -----


def start(client, file_ids, request_id="request-0001"):
    body = {
        "action": "merge",
        "settings": {},
        "data": {"files": file_ids},
        "requestId": request_id,
    }
    return client.result("POST", "/api/jobs", body)


def test_job_runs_and_its_status_can_be_polled(client, app, tmp_path):
    ids = [f["path"] for f in upload(client, make_pdf(tmp_path / "a.pdf"))]
    job = start(client, ids)
    finished = wait_finished(client, job["jobId"])
    assert finished["status"] == "succeeded" and finished["outputs"][0]["name"] == "Result 0.pdf"
    _, data = app.run.calls[0]
    assert data.files[0].is_relative_to(app.ctx.session.staging)
    latest = client.result("GET", "/api/jobs/latest")["job"]
    assert latest["jobId"] == job["jobId"] and latest["action"] == "merge"


def test_a_retried_start_gets_the_same_job(client, app, tmp_path):
    ids = [f["path"] for f in upload(client, make_pdf(tmp_path / "a.pdf"))]
    app.run.release.clear()
    first = start(client, ids, "same-request")
    assert start(client, ids, "same-request") == first
    other = start(client, ids, "other-request")
    assert other["issue"]["code"] == "JOB_ALREADY_RUNNING"
    app.run.release.set()
    wait_finished(client, first["jobId"])


def test_save_only_to_folders_the_user_chose(client, app, tmp_path, monkeypatch):
    ids = [f["path"] for f in upload(client, make_pdf(tmp_path / "a.pdf"))]
    job_id = start(client, ids)["jobId"]
    wait_finished(client, job_id)
    refused = client.result(
        "POST", f"/api/jobs/{job_id}/save", {"folder": str(tmp_path), "asZip": False}
    )
    assert refused["issue"] and refused["savedPaths"] == []
    out = tmp_path / "chosen"
    out.mkdir()
    monkeypatch.setattr(platforms, "ask_folder", lambda start: out)
    saved = client.result("POST", f"/api/jobs/{job_id}/save", {"folder": None, "asZip": False})
    assert saved["issue"] is None and saved["folder"] == str(out)
    assert (out / "Result 0.pdf").is_file()
    assert app.ctx.session.resolve_folder(str(out), "open") == out


def test_download_copies_keep_the_results_and_are_fetched_once(client, app, tmp_path):
    ids = [f["path"] for f in upload(client, make_pdf(tmp_path / "a.pdf"))]
    app.run.outputs = 2
    job_id = start(client, ids)["jobId"]
    wait_finished(client, job_id)
    prepared = client.result("POST", f"/api/jobs/{job_id}/download", {"asZip": False})
    assert [d["name"] for d in prepared["downloads"]] == ["Result 0.pdf", "Result 1.pdf"]
    response, body = client.raw(
        "GET",
        f"/api/downloads/{prepared['downloads'][0]['id']}",
        headers={"Host": app.host, "X-PDF-Manager": "1", "Cookie": client.cookie},
    )
    assert response.status == 200 and body.startswith(b"%PDF")
    assert "attachment" in response.getheader("Content-Disposition")
    again, _ = client.raw(
        "GET",
        f"/api/downloads/{prepared['downloads'][0]['id']}",
        headers={"Host": app.host, "X-PDF-Manager": "1", "Cookie": client.cookie},
    )
    assert again.status == 404
    zipped = client.result("POST", f"/api/jobs/{job_id}/download", {"asZip": True})
    assert zipped["downloads"][0]["name"].endswith(".zip")
    client.result("POST", f"/api/jobs/{job_id}/discard")
    assert client.get(f"/api/jobs/{job_id}")[0] == 404


def test_activity_and_busy(client, app, tmp_path):
    assert app.idle_for() < 5 and not app.busy()
    ids = [f["path"] for f in upload(client, make_pdf(tmp_path / "a.pdf"))]
    app.run.release.clear()
    job_id = start(client, ids)["jobId"]
    assert app.busy()
    app.run.release.set()
    wait_finished(client, job_id)


# ----- Launch -----


def test_app_mode_for_chromium_family_defaults(monkeypatch):
    started = []
    monkeypatch.setattr(
        platforms, "default_browser", lambda: platforms.DefaultBrowser("Brave", ("brave",))
    )
    monkeypatch.setattr(platforms, "start_browser", started.append)
    assert launch.open_in_browser("http://127.0.0.1:1/?launch=x") == "app"
    assert started == [["brave", "--app=http://127.0.0.1:1/?launch=x"]]


def test_other_defaults_get_a_normal_tab(monkeypatch):
    urls = []
    monkeypatch.setattr(platforms, "default_browser", lambda: platforms.DefaultBrowser("firefox"))
    monkeypatch.setattr(platforms, "open_url", urls.append)
    assert launch.open_in_browser("http://127.0.0.1:1/") == "tab" and urls == [
        "http://127.0.0.1:1/"
    ]


def test_a_second_start_reuses_the_running_instance(app, monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"port": app.server_port, "key": "instance-key"}))
    monkeypatch.setattr(launch, "_state_path", lambda: state)
    assert launch._running_instance_url().startswith(app.origin + "/?launch=")
    state.write_text(json.dumps({"port": app.server_port, "key": "wrong"}))
    assert launch._running_instance_url() is None
    state.write_text("not json")
    assert launch._running_instance_url() is None


def test_browser_mode_never_imports_the_desktop_toolkits():
    code = (
        "import sys\n"
        "for name in ('webview', 'PySide6', 'clr', 'pythonnet', 'qtpy'):\n"
        "    sys.modules[name] = None\n"
        "import api.web.launch, api.web.server, api.web.operations\n"
        "print('ok')\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0 and proc.stdout.strip() == "ok", proc.stderr


def test_a_refused_body_is_never_read_as_the_next_request(app):
    """A body the server didn't read closes the connection (no request desync)."""
    import socket

    body = b"GET /api/health HTTP/1.1\r\nHost: x\r\n\r\n"
    first = (
        f"POST /api/settings HTTP/1.1\r\nHost: {app.host}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n\r\n"
    ).encode() + body
    with socket.create_connection((server.HOST, app.server_port), timeout=5) as sock:
        sock.sendall(first)
        received = b""
        while chunk := sock.recv(65536):
            received += chunk
    assert received.count(b"HTTP/1.1 ") == 1 and received.startswith(b"HTTP/1.1 403")
