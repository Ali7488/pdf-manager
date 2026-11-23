"""Browser mode's HTTP server, on 127.0.0.1 only.

It serves the built interface and the operations in :data:`ROUTES`, and
nothing else. Every request must use the exact ``Host`` the app opened
(``127.0.0.1:<port>``), which defeats DNS rebinding. Every API request must
also carry:

* the session cookie, which the browser only gets by opening the single-use
  launch link the app itself opened (the session secret never appears in a
  URL, a log or a referrer);
* the ``X-PDF-Manager: 1`` header, which another site's page can't add
  without a CORS preflight, which this server never approves;
* when the browser sends them, ``Origin`` equal to this app's origin
  (required for POST) and ``Sec-Fetch-Site: same-origin``.

Limits: a bounded number of requests at once, a socket timeout for slow
clients, bounded JSON bodies and uploads, and no new changes once the app has
started closing (:attr:`AppServer.closing`).
"""

from __future__ import annotations

import html
import json
import logging
import mimetypes
import re
import secrets
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from . import operations as ops

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
MAX_CONCURRENT_REQUESTS = 24
REQUEST_TIMEOUT_SEC = 30  # Per socket read: a stalled client is dropped.
MAX_JSON_BYTES = 256 * 1024
MAX_UPLOAD_BYTES = 2 * 1024**3
LAUNCH_CODE_TTL_SEC = 120
REQUEST_HEADER = "X-PDF-Manager"
INSTANCE_HEADER = "X-PDF-Manager-Instance"
_JOB = r"(?P<id>[0-9a-f]{32})"
_DOWNLOAD = r"(?P<id>x-[A-Za-z0-9_-]{16})"

PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    ),
}
COMMON_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cross-Origin-Opener-Policy": "same-origin",
}


@dataclass(frozen=True)
class Route:
    """One API operation: ``METHOD path`` -> function. ``changes`` marks mutations."""

    method: str
    pattern: re.Pattern[str]
    run: Callable[..., Any]
    changes: bool


def _route(method: str, path: str, run: Callable[..., Any], changes: bool = False) -> Route:
    return Route(method, re.compile(f"^{path}$"), run, changes)


# The complete list of what the page may call. Uploads and downloads stream
# their bodies, so they are handled separately (see Handler).
ROUTES = (
    _route("GET", "/api/app-info", ops.app_info),
    _route("GET", "/api/settings", ops.get_settings),
    _route("POST", "/api/settings", ops.save_settings, changes=True),
    _route("POST", "/api/files/pick", ops.pick_files, changes=True),
    _route("POST", "/api/folders/pick", ops.pick_folder, changes=True),
    _route("POST", "/api/folders/open", ops.open_folder, changes=True),
    _route("POST", "/api/logs/open", ops.open_logs_folder, changes=True),
    _route("POST", "/api/tools/check", ops.check_tools),
    _route("POST", "/api/jobs", ops.start_job, changes=True),
    _route("GET", "/api/jobs/latest", ops.latest_job),
    _route("GET", f"/api/jobs/{_JOB}", ops.job_status),
    _route("POST", f"/api/jobs/{_JOB}/cancel", ops.cancel_job, changes=True),
    _route("POST", f"/api/jobs/{_JOB}/save", ops.save_results, changes=True),
    _route("POST", f"/api/jobs/{_JOB}/download", ops.prepare_download, changes=True),
    _route("POST", f"/api/jobs/{_JOB}/discard", ops.discard_results, changes=True),
    _route("GET", "/api/ocr/status", ops.ocr_status),
    _route("GET", "/api/ocr/languages", ops.ocr_languages),
    _route("POST", "/api/ocr/search", ops.search_ocr, changes=True),
    _route("POST", "/api/ocr/install", ops.install_ocr, changes=True),
    _route("GET", "/api/ocr/install", ops.ocr_install_status),
    _route("POST", "/api/quit", ops.quit_app, changes=True),
)
UPLOAD_PATH = "/api/files/upload"
DOWNLOAD_PATTERN = re.compile(f"^/api/downloads/{_DOWNLOAD}$")


def message_page(title: str, text: str) -> bytes:
    """A small self-contained HTML page for situations without the interface."""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:48px;color:#222}</style>"
        f"</head><body><h1>{html.escape(title)}</h1><p>{html.escape(text)}</p></body></html>"
    ).encode()


def bootstrap_page(index: bytes, native_dialogs: bool) -> bytes:
    """The built page with browser mode's bootstrap tag added to its ``<head>``.

    The tag tells the interface to use the HTTP client (``frontend/src/api/http.ts``)
    and whether native pickers are available.
    """
    tag = (
        '<meta name="pdf-manager-mode" content="browser" '
        f'data-native-dialogs="{"true" if native_dialogs else "false"}">'
    ).encode()
    return re.sub(rb"<head[^>]*>", lambda m: m.group(0) + tag, index, count=1)


class AppServer(ThreadingHTTPServer):
    """The loopback server, with the session, launch codes and activity tracking.

    Args:
        ctx: What the operations use.
        ui_dir: The built interface's folder (``frontend/dist``).
        instance_key: Secret a second launch of the app uses to ask this one
            for a new launch link (from the state file only this user can read).
    """

    daemon_threads = True
    allow_reuse_address = False
    request_queue_size = 32

    def __init__(self, ctx: ops.Context, ui_dir: Path, instance_key: str):
        super().__init__((HOST, 0), Handler)
        self.ctx = ctx
        self.ui_dir = ui_dir
        self.instance_key = instance_key
        self.secret = secrets.token_urlsafe(32)
        self.host = f"{HOST}:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.cookie_name = f"pdf-manager-{self.server_port}"
        self.closing = False
        self.page_requests = 0  # Times the interface was served (for smoke tests).
        self._slots = threading.BoundedSemaphore(MAX_CONCURRENT_REQUESTS)
        self._lock = threading.Lock()
        self._codes: dict[str, float] = {}
        self._in_flight = 0
        self._last_activity = time.monotonic()

    # ----- Launch links and the session -----

    def launch_url(self) -> str:
        """A new single-use link that gives the browser this session's cookie."""
        code = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._lock:
            self._codes = {c: t for c, t in self._codes.items() if now - t < LAUNCH_CODE_TTL_SEC}
            self._codes[code] = now
        return f"{self.origin}/?launch={code}"

    def redeem(self, code: str) -> bool:
        """Use a launch code: true once, within its lifetime."""
        with self._lock:
            issued = self._codes.pop(code, None)
        return issued is not None and time.monotonic() - issued < LAUNCH_CODE_TTL_SEC

    # ----- Activity, for idle shutdown -----

    def touch(self) -> None:
        with self._lock:
            self._last_activity = time.monotonic()

    def idle_for(self) -> float:
        """Seconds since the last request."""
        with self._lock:
            return time.monotonic() - self._last_activity

    def busy(self) -> bool:
        """Whether idle shutdown must wait: work in progress, or results not yet saved.

        Requests in progress, a running job, an OCR install, and finished
        results that exist only in the app (decision P35) all keep the app
        running past the idle limit.
        """
        workflow = self.ctx.workflow
        with self._lock:
            in_flight = self._in_flight
        return bool(
            in_flight
            or workflow.jobs.running_job()
            or workflow.installing_ocr
            or workflow.jobs.unsaved_jobs()
        )

    def enter(self) -> None:
        with self._lock:
            self._in_flight += 1

    def leave(self) -> None:
        with self._lock:
            self._in_flight -= 1

    def wait_idle(self, timeout: float) -> None:
        """Wait (up to ``timeout``) for requests in progress to finish."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._in_flight == 0:
                    return
            time.sleep(0.05)
        log.warning("Requests still running at shutdown")

    # ----- Concurrency limit -----

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def handle_error(self, request, client_address) -> None:
        """A client that went away is normal; anything else is logged, not printed."""
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionError, TimeoutError)):
            log.debug("Connection ended: %s", error)
        else:
            log.exception("Error handling a request")

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


class Handler(BaseHTTPRequestHandler):
    """One request. Only GET and POST exist; anything else is "not implemented"."""

    server: AppServer
    protocol_version = "HTTP/1.1"
    timeout = REQUEST_TIMEOUT_SEC
    server_version = "PDFManager"
    sys_version = ""

    # Logged by route only: never the query (launch codes, file names) or bodies.
    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        log.debug("%s %s -> %s", self.command, urlsplit(self.path).path, code)

    def log_error(self, format: str, *args: Any) -> None:
        log.debug("HTTP error: " + format, *args)

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    # ----- Dispatch -----

    def _handle(self) -> None:
        self._consumed = False
        try:
            self._dispatch()
        finally:
            # A request answered without reading its body (refused, or an upload
            # that stopped early) leaves that body on the connection, where it
            # would be read as the next request. Close the connection instead.
            if not self._consumed and self.headers.get("Content-Length", "0") != "0":
                self.close_connection = True

    def _dispatch(self) -> None:
        url = urlsplit(self.path)
        if self.headers.get("Host") != self.server.host:
            self._send_json(421, {"error": "wrong host"})
            return
        if url.path == "/api/health" and self.command == "GET":
            self._send_json(200, {"app": "PDF Manager"})  # Readiness; reveals nothing.
            return
        if url.path == "/api/instance/launch" and self.command == "POST":
            self._instance_launch()
            return
        self.server.touch()
        if not url.path.startswith("/api/"):
            self._page(url)
            return
        if not self._authorised():
            self._send_json(403, {"error": "forbidden"})
            return
        self.server.enter()
        try:
            self._api(url)
        finally:
            self.server.leave()

    def _api(self, url) -> None:
        if url.path == UPLOAD_PATH and self.command == "POST":
            self._gate(lambda: self._upload(url))
            return
        download = DOWNLOAD_PATTERN.match(url.path)
        if download and self.command == "GET":
            self._download(download.group("id"))
            return
        for route in ROUTES:
            match = route.pattern.match(url.path)
            if match and route.method == self.command:
                runner = lambda r=route, m=match: self._call(r, m)  # noqa: E731
                if route.changes:
                    self._gate(runner)
                else:
                    runner()
                return
        self._send_json(404, {"error": "not found"})

    def _gate(self, run: Callable[[], None]) -> None:
        """Run a change, unless the app is closing."""
        if self.server.closing:
            self._send_json(503, {"error": "closing"})
            self.close_connection = True
            return
        run()

    def _call(self, route: Route, match: re.Match[str]) -> None:
        body: Any = None
        if self.command == "POST":
            body = self._read_json()
            if body is _BAD:
                return
        args = match.groupdict().values()
        result = route.run(self.server.ctx, body, *args)
        if result is None and "id" in match.groupdict() and route.method == "GET":
            self._send_json(404, {"error": "unknown job"})
            return
        self._send_json(200, {"result": result})

    # ----- Security -----

    def _session_cookie(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            morsel = SimpleCookie(raw).get(self.server.cookie_name)
        except Exception:
            return None
        return morsel.value if morsel else None

    def _has_session(self) -> bool:
        cookie = self._session_cookie()
        return cookie is not None and secrets.compare_digest(cookie, self.server.secret)

    def _authorised(self) -> bool:
        """Session cookie, the request header, and a same-origin request."""
        if not self._has_session() or self.headers.get(REQUEST_HEADER) != "1":
            return False
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            return False
        if self.command == "POST" and origin is None:
            return False
        site = self.headers.get("Sec-Fetch-Site")
        return site in (None, "same-origin")

    def _instance_launch(self) -> None:
        """A second start of the app asks for a link to this one."""
        key = self.headers.get(INSTANCE_HEADER) or ""
        if not secrets.compare_digest(key, self.server.instance_key) or self.server.closing:
            self._send_json(403, {"error": "forbidden"})
            return
        self._send_json(200, {"url": self.server.launch_url()})

    # ----- The page -----

    def _page(self, url) -> None:
        if self.command != "GET":
            self._send_json(405, {"error": "method not allowed"})
            return
        query = parse_qs(url.query)
        if url.path == "/" and "launch" in query:
            if self.server.redeem(query["launch"][0]):
                cookie = (
                    f"{self.server.cookie_name}={self.server.secret}; "
                    "HttpOnly; SameSite=Strict; Path=/"
                )
                self._send(303, b"", "text/plain", {"Location": "/", "Set-Cookie": cookie})
            else:
                self._send_html(
                    403,
                    "This link has already been used",
                    "Start PDF Manager again from its shortcut to open it in your browser.",
                )
            return
        if not self._has_session():
            self._send_html(
                403,
                "PDF Manager",
                "Start PDF Manager from its shortcut to open it in your browser.",
            )
            return
        if url.path in ("/", "/index.html"):
            index = self.server.ui_dir / "index.html"
            if not index.is_file():
                self._send_html(
                    500,
                    "PDF Manager can't start",
                    "The app's interface files are missing. Please reinstall PDF Manager.",
                )
                return
            page = bootstrap_page(index.read_bytes(), self.server.ctx.native_dialogs)
            self.server.page_requests += 1
            self._send(200, page, "text/html; charset=utf-8", PAGE_HEADERS)
            return
        self._static(url.path)

    def _static(self, path: str) -> None:
        """Other files of the built interface (none today: it is one HTML file)."""
        root = self.server.ui_dir.resolve()
        target = (root / path.lstrip("/")).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            self._send_json(404, {"error": "not found"})
            return
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self._send(200, target.read_bytes(), kind)

    # ----- Uploads and downloads -----

    def _upload(self, url) -> None:
        query = parse_qs(url.query)
        name = (query.get("name") or [""])[0]
        length = self._content_length()
        if self.headers.get("Content-Type") != "application/octet-stream" or length is None:
            self._refuse(400, "uploads must be application/octet-stream with a length")
            return
        if length > MAX_UPLOAD_BYTES:
            self._refuse(413, "file too large")
            return
        received = 0

        def read(size: int) -> bytes:
            nonlocal received
            chunk = self.rfile.read(size)
            received += len(chunk)
            return chunk

        files = ops.upload(self.server.ctx, name, length, read)
        self._consumed = received == length  # Otherwise the connection is closed.
        self._send_json(200, {"result": files})

    def _download(self, download_id: str) -> None:
        taken = self.server.ctx.session.take_download(download_id)
        if taken is None or not taken[0].is_file():
            self._send_json(404, {"error": "not found"})
            return
        path, name = taken
        fallback = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
        disposition = f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}"
        try:
            size = path.stat().st_size
            self.send_response(200)
            self._headers(
                {
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(size),
                    "Content-Disposition": disposition,
                }
            )
            with open(path, "rb") as source:
                while chunk := source.read(1024 * 1024):
                    self.wfile.write(chunk)
        finally:
            path.unlink(missing_ok=True)

    # ----- Bodies and responses -----

    def _content_length(self) -> int | None:
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None
        return length if length >= 0 else None

    def _read_json(self) -> Any:
        length = self._content_length()
        if length is None or not (self.headers.get("Content-Type") or "").startswith(
            "application/json"
        ):
            self._refuse(400, "expected a JSON body with a length")
            return _BAD
        if length > MAX_JSON_BYTES:
            self._refuse(413, "request too large")
            return _BAD
        raw = self.rfile.read(length)
        self._consumed = True
        try:
            return json.loads(raw or b"null")
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "invalid JSON"})
            return _BAD

    def _refuse(self, status: int, reason: str) -> None:
        self._send_json(status, {"error": reason})
        self.close_connection = True  # The unread body would be taken for the next request.

    def _headers(self, extra: dict[str, str]) -> None:
        for key, value in {**COMMON_HEADERS, **extra}.items():
            self.send_header(key, value)
        self.end_headers()

    def _send(self, status: int, body: bytes, kind: str, extra: dict[str, str] | None = None):
        self.send_response(status)
        self._headers({"Content-Type": kind, "Content-Length": str(len(body)), **(extra or {})})
        self.wfile.write(body)

    def _send_json(self, status: int, value: Any) -> None:
        body = json.dumps(value, ensure_ascii=True, allow_nan=False).encode()
        self._send(status, body, "application/json")

    def _send_html(self, status: int, title: str, text: str) -> None:
        self._send(status, message_page(title, text), "text/html; charset=utf-8", PAGE_HEADERS)


_BAD = object()  # _read_json's "already answered" marker.
