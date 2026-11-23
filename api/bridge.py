"""The ``Api`` object exposed to JavaScript as ``window.pywebview.api``.

Method names and argument order follow ``docs/API.md`` exactly; the
frontend's typed client (``frontend/src/api/client.ts``) wraps them in
camelCase. Rules every public method follows:

* **Never raise into JavaScript.** A rejected promise means a bug (see the
  contract), so every public method catches everything, logs it and returns
  a contract-shaped result carrying an ``Issue``.
* **Only contract methods are public.** pywebview exposes every public
  attribute of this object (recursively), so all other state and helpers
  start with an underscore.
* **Plain JSON out.** Results are built by :mod:`api.dto`.

Python -> UI events are DOM events on ``window`` named ``pdfmanager:<name>``,
dispatched with ``window.evaluate_js`` (see :func:`event_script`).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler

from . import __version__, dto, logging_setup, paths, service
from .jobs import JobManager
from .logging_setup import log_issue
from .service import ConversionError, Issue, ocr_install_failed, ocr_missing, unexpected_error
from .settings_store import DEFAULTS, SettingsStore

log = logging.getLogger(__name__)

EVENT_PREFIX = "pdfmanager:"
_EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")

# Native picker filters, in pywebview's "Description (*.ext;*.ext)" format.
FILE_FILTERS = {
    "documents": ("PDF and PowerPoint files (*.pdf;*.pptx;*.ppt)",),
    "images": ("Images (*.png;*.jpg;*.jpeg)",),
}

# Tesseract from the UB Mannheim build, the usual Windows distribution.
WINGET_INSTALL = (
    "winget",
    "install",
    "--id",
    "UB-Mannheim.TesseractOCR",
    "-e",
    "--silent",
    "--accept-source-agreements",
    "--accept-package-agreements",
)
WINGET_TIMEOUT_SEC = 20 * 60
TESSERACT_VERSION_TIMEOUT_SEC = 15
DRAGOVER_DEBOUNCE_MS = 500  # Only preventDefault matters for dragover; Python ignores it.


def event_script(name: str, payload: Any) -> str:
    """Build the JavaScript that dispatches ``pdfmanager:<name>`` with ``payload``.

    The payload is embedded as a JSON literal. ``json.dumps`` with
    ``ensure_ascii`` escapes quotes, backslashes, control characters and
    every non-ASCII character (including U+2028/U+2029, which older engines
    treat as line breaks). ``<``, ``>`` and ``&`` are escaped as well, so a
    file name such as ``</script>`` can never be read as markup even if the
    script ends up inside HTML. The event name is checked against a strict
    pattern, so it can't inject code either.

    Args:
        name: Event name from the contract, e.g. ``"jobFinished"``.
        payload: JSON-serializable payload (``event.detail`` in the UI).

    Returns:
        A one-line script.

    Raises:
        ValueError: Invalid event name, or the payload holds NaN/Infinity.
        TypeError: The payload isn't JSON-serializable.
    """
    if not _EVENT_NAME_RE.match(name):
        raise ValueError(f"Invalid event name: {name!r}")
    literal = json.dumps(payload, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    literal = literal.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'window.dispatchEvent(new CustomEvent("{EVENT_PREFIX}{name}", {{detail: {literal}}}));'


def _platform_name() -> str:
    """The contract's ``AppInfo.platform``: ``"windows"``, ``"mac"`` or ``"linux"``."""
    if paths.on_windows():
        return "windows"
    return "mac" if sys.platform == "darwin" else "linux"


def _ignore_event(_event: Any) -> None:
    """DOM event callback that does nothing (the JS side already called preventDefault)."""


def _describe_files(candidates: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Turn paths into the contract's ``InputFile`` objects.

    Unsupported types, folders and missing files are skipped (and logged);
    duplicates are dropped, keeping the first. Order is preserved.

    Args:
        candidates: Paths from a picker or a drop.

    Returns:
        ``InputFile`` objects.
    """
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        path = Path(candidate)
        key = os.path.normcase(str(path))  # Case-insensitive on Windows, as Explorer is.
        if key in seen:
            continue
        seen.add(key)
        info = service.inspect_file(path)
        if info is None:
            log.info("Skipped (unsupported, a folder, or missing): %s", path)
            continue
        files.append(dto.input_file_to_json(info))
    return files


def _open_in_file_manager(folder: Path) -> None:
    """Open a folder in File Explorer (or the desktop's file manager elsewhere).

    Args:
        folder: An existing folder. The caller checks it is a folder, so this
            can never be used to launch a program.

    Raises:
        OSError: The file manager couldn't be started.
    """
    if paths.on_windows():
        os.startfile(str(folder))  # Opens Explorer; the caller checked it's a folder.
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen(
        [opener, str(folder)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # Don't tie the file manager to this app's lifetime.
    )


def _check_tesseract(path: Path) -> str | None:
    """Check that a user-picked file really is Tesseract.

    Args:
        path: The chosen file.

    Returns:
        ``None`` if it is Tesseract, otherwise a technical reason for the
        issue's details.
    """
    if not path.is_file():
        return f"Not a file: {path}"
    if path.stem.casefold() != "tesseract":
        return f"Expected a file named tesseract{'.exe' if paths.on_windows() else ''}: {path}"
    try:
        proc = service.run_command([path, "--version"], timeout=TESSERACT_VERSION_TIMEOUT_SEC)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Couldn't run {path} --version: {exc}"
    output = f"{proc.stdout or ''}{proc.stderr or ''}"
    if proc.returncode != 0 or "tesseract" not in output.casefold():
        return f"{path} --version exited with {proc.returncode}:\n{output.strip()}"
    return None


class Api:
    """The methods the UI calls. Exposed to JavaScript as ``window.pywebview.api``.

    Args:
        settings: The loaded settings store.
        jobs: Job manager; a default one emitting through this object is
            created if omitted.
    """

    def __init__(self, settings: SettingsStore, jobs: JobManager | None = None):
        self._window: Any = None  # The pywebview window, set by _bind_window.
        self._settings = settings
        self._jobs = jobs if jobs is not None else JobManager(self._emit)
        self._install_lock = threading.Lock()
        self._installing = False

    # ----- Wiring (private: not exposed to JavaScript) -----

    def _bind_window(self, window: Any) -> None:
        """Attach the window events are sent to, and subscribe to its load event.

        Args:
            window: A ``webview.Window`` (or a test double).
        """
        self._window = window
        window.events.loaded += self._on_loaded

    def _on_loaded(self) -> None:
        """Window loaded: listen for files dropped anywhere on the page.

        Runs again after every page load (for example a dev-server reload), as
        the new page has no listeners. ``prevent_default`` stops the browser
        from navigating to a dropped file; ``dragover`` must be cancelled too,
        or ``drop`` never fires.
        """
        try:
            document = self._window.dom.document
            document.events.dragover += DOMEventHandler(
                _ignore_event, prevent_default=True, debounce=DRAGOVER_DEBOUNCE_MS
            )
            document.events.drop += DOMEventHandler(self._on_drop, prevent_default=True)
            log.debug("Drag and drop listeners attached")
        except Exception:
            log.exception("Couldn't attach drag and drop listeners")

    def _on_drop(self, event: dict) -> None:
        """Handle a ``drop`` on the document: describe the files and emit ``filesAdded``.

        pywebview adds each dropped file's full path as ``pywebviewFullPath``
        (a web page alone can't see real paths). Files without one, folders,
        unsupported types and missing files are skipped. Never raises.

        Args:
            event: The serialized DOM event from pywebview.
        """
        try:
            dropped = (event.get("dataTransfer") or {}).get("files") or []
            candidates = [f.get("pywebviewFullPath") for f in dropped if isinstance(f, dict)]
            missing = sum(1 for c in candidates if not c)
            if missing:
                log.info("%d dropped item(s) had no full path and were skipped", missing)
            files = _describe_files(c for c in candidates if c)
            log.info("Dropped %d item(s), %d usable", len(dropped), len(files))
            if files:
                self._emit("filesAdded", {"files": files})
        except Exception:
            log.exception("Couldn't handle dropped files")

    def _emit(self, name: str, payload: Any) -> None:
        """Send an event to the UI. Never raises; without a window it is dropped.

        Args:
            name: Contract event name, e.g. ``"jobProgress"``.
            payload: JSON-serializable payload.
        """
        window = self._window
        if window is None:
            log.debug("No window; dropped event %s", name)
            return
        try:
            window.evaluate_js(event_script(name, payload))
        except Exception:
            # Typically the window is closing. Events are best effort.
            log.warning("Couldn't send event %s", name, exc_info=True)

    def _shutdown(self) -> None:
        """Cancel a running job and delete all scratch folders. Never raises."""
        try:
            self._jobs.shutdown()
        except Exception:
            log.exception("Error during shutdown")

    def _guard(
        self,
        name: str,
        fallback: Callable[[Issue], Any],
        func: Callable[..., Any],
        *args: Any,
    ) -> Any:
        """Run a public method's body so that it never raises into JavaScript.

        Expected failures (:class:`ConversionError`, including malformed
        input from :mod:`api.dto`) are logged and answered with
        ``fallback(issue)``. Anything else is a bug: it is logged with its
        traceback and answered with an ``UNEXPECTED_ERROR`` issue.

        Args:
            name: Method name, for the log.
            fallback: Builds the contract-shaped result from an issue.
            func: The method body.
            *args: Its arguments.

        Returns:
            ``func(*args)``, or ``fallback(issue)`` on failure.
        """
        started = time.monotonic()
        try:
            result = func(*args)
        except ConversionError as exc:
            return fallback(log_issue(exc.issue))
        except Exception as exc:
            log.error("Bridge call %s failed", name)
            return fallback(log_issue(unexpected_error(traceback.format_exc()), exc))
        log.debug("Bridge call %s took %.0f ms", name, (time.monotonic() - started) * 1000)
        return result

    def _ask_folder(self) -> Path | None:
        """Open the native folder picker, starting in the default save folder if set.

        Returns:
            The chosen folder, or ``None`` if the user cancelled.
        """
        start = self._settings.get().get("defaultSaveFolder") or ""
        picked = self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        if not picked:
            return None
        # pywebview returns a sequence of paths; some backends return a plain string.
        return Path(picked if isinstance(picked, str) else picked[0])

    def _logs_folder(self) -> Path:
        """The logs folder in use (it may be a fallback folder, see logging_setup)."""
        current = logging_setup.log_file()
        return current.parent if current is not None else paths.logs_dir()

    # ----- Contract methods (public: exposed to JavaScript) -----

    def get_app_info(self) -> dict[str, Any]:
        """Return the app version, logs folder and platform (``AppInfo``)."""

        def body() -> dict[str, Any]:
            return {
                "version": __version__,
                "logsDir": str(self._logs_folder()),
                "platform": _platform_name(),
            }

        return self._guard(
            "get_app_info",
            lambda issue: {"version": __version__, "logsDir": "", "platform": _platform_name()},
            body,
        )

    def get_settings(self) -> dict[str, Any]:
        """Return the saved ``Settings``."""
        return self._guard("get_settings", lambda issue: dict(DEFAULTS), self._settings.get)

    def save_settings(self, patch: dict) -> dict[str, Any]:
        """Merge and persist a partial ``Settings``; return the full settings.

        Invalid fields are ignored (and logged), so the returned settings show
        what was actually kept.

        Args:
            patch: Partial ``Settings`` (camelCase).
        """
        return self._guard(
            "save_settings", lambda issue: self._settings.get(), self._settings.update, patch
        )

    def pick_files(self, kind: str) -> list[dict[str, Any]]:
        """Open the native file picker (multiple selection) and return ``InputFile[]``.

        Args:
            kind: ``"documents"`` (PDF/PPTX/PPT) or ``"images"`` (PNG/JPG).

        Returns:
            The chosen usable files; empty if cancelled.
        """

        def body() -> list[dict[str, Any]]:
            if kind not in FILE_FILTERS:
                raise dto.invalid_request(f"kind must be documents or images; got {kind!r}")
            picked = self._window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=True, file_types=FILE_FILTERS[kind]
            )
            return _describe_files(picked or [])

        return self._guard("pick_files", lambda issue: [], body)

    def pick_folder(self) -> str | None:
        """Open the native folder picker. Returns the folder path, or ``None`` if cancelled."""

        def body() -> str | None:
            folder = self._ask_folder()
            return str(folder) if folder else None

        return self._guard("pick_folder", lambda issue: None, body)

    def check_tools(self, action: str, settings: dict, data: dict) -> dict[str, Any]:
        """Check the programs this job needs (``ToolCheckResult``). Same arguments as start_job.

        Args:
            action: ``Action`` value.
            settings: Frontend ``ActionSettings``.
            data: ``ActionData`` (``{ files }``).
        """

        def body() -> dict[str, Any]:
            parsed = dto.parse_action(action)
            job_settings = dto.action_settings_from_json(settings, self._settings.get())
            job_data = dto.action_data_from_json(data)
            check = service.check_tools(parsed, job_settings, job_data)
            check.issues = [log_issue(issue) for issue in check.issues]
            log.debug("Tool check for %s: %s", parsed, check)
            return dto.tool_check_to_json(check)

        return self._guard("check_tools", dto.failed_tool_check_json, body)

    def get_ocr_languages(self) -> list[str]:
        """Return the installed Tesseract languages, e.g. ``["eng", "deu"]``; empty if no OCR."""

        def body() -> list[str]:
            tesseract = service.find_tesseract(self._settings.get().get("tesseractPath"))
            return service.tesseract_languages(tesseract) if tesseract else []

        return self._guard("get_ocr_languages", lambda issue: [], body)

    def search_ocr(self) -> dict[str, Any]:
        """Find Tesseract, asking the user to pick ``tesseract.exe`` if needed.

        The usual places are searched first. If nothing is found, a file
        picker opens; the chosen file must be named ``tesseract(.exe)`` and
        answer ``--version``. A found path is saved as ``tesseractPath``.

        Returns:
            ``OcrSearchResult``.
        """

        def not_found(issue: Issue) -> dict[str, Any]:
            return {"found": False, "path": None, "issue": dto.issue_to_json(issue)}

        def body() -> dict[str, Any]:
            found = service.find_tesseract(self._settings.get().get("tesseractPath"))
            if found is None:
                filters = ("Programs (*.exe)",) if paths.on_windows() else ()
                picked = self._window.create_file_dialog(
                    webview.FileDialog.OPEN, allow_multiple=False, file_types=filters
                )
                if not picked:
                    return not_found(log_issue(ocr_missing()))
                chosen = Path(picked if isinstance(picked, str) else picked[0])
                problem = _check_tesseract(chosen)
                if problem:
                    # Proposed: move this wording into converter/issues.py as its own factory.
                    issue = dataclasses.replace(
                        ocr_missing(),
                        message="The chosen file isn't the OCR program (Tesseract).",
                        details=problem,
                    )
                    return not_found(log_issue(issue))
                found = chosen
            self._settings.update({"tesseractPath": str(found)})
            log.info("OCR found at %s", found)
            return {"found": True, "path": str(found), "issue": None}

        return self._guard("search_ocr", not_found, body)

    def install_ocr(self) -> None:
        """Start installing Tesseract with winget. Returns at once.

        Progress arrives as ``ocrInstallProgress`` and the end as
        ``ocrInstallFinished``. Without Windows and winget, the install ends
        straight away with an ``OCR_INSTALL_FAILED`` issue that explains how
        to install Tesseract manually. A second call while an install runs is
        ignored.
        """

        def finish_failed(issue: Issue) -> None:
            self._emit("ocrInstallFinished", {"ok": False, "issue": dto.issue_to_json(issue)})

        def body() -> None:
            if not paths.on_windows() or shutil.which("winget") is None:
                raise ConversionError(
                    ocr_install_failed(
                        "Automatic install needs Windows with winget (App Installer). "
                        "Install Tesseract OCR yourself, then click Search for OCR in Settings."
                    )
                )
            with self._install_lock:
                if self._installing:
                    log.info("OCR install already running; ignoring the request")
                    return
                self._installing = True
            threading.Thread(target=self._install_worker, name="ocr-install", daemon=True).start()

        self._guard("install_ocr", finish_failed, body)
        return None

    def _install_worker(self) -> None:
        """Background thread: run winget, then check Tesseract is really there. Never raises."""
        try:
            self._emit(
                "ocrInstallProgress",
                {"message": "Downloading and installing OCR. This can take a few minutes."},
            )
            log.info("Installing OCR: %s", " ".join(WINGET_INSTALL))
            details = None
            try:
                proc = service.run_command(WINGET_INSTALL, timeout=WINGET_TIMEOUT_SEC)
                details = (
                    f"winget exit code {proc.returncode}\n"
                    f"{(proc.stdout or '').strip()}\n{(proc.stderr or '').strip()}"
                ).strip()
            except subprocess.TimeoutExpired:
                details = f"winget didn't finish within {WINGET_TIMEOUT_SEC // 60} minutes."
            except OSError as exc:
                details = f"Couldn't run winget: {exc}"
            self._emit("ocrInstallProgress", {"message": "Checking the installation."})
            # Judge by the result, not the exit code: winget also exits non-zero
            # when Tesseract is already installed.
            found = service.find_tesseract(self._settings.get().get("tesseractPath"))
            if found is not None:
                self._settings.update({"tesseractPath": str(found)})
                log.info("OCR installed at %s", found)
                self._emit("ocrInstallFinished", {"ok": True, "issue": None})
            else:
                issue = log_issue(ocr_install_failed(details))
                self._emit("ocrInstallFinished", {"ok": False, "issue": dto.issue_to_json(issue)})
        except Exception as exc:
            issue = log_issue(ocr_install_failed(traceback.format_exc()), exc)
            self._emit("ocrInstallFinished", {"ok": False, "issue": dto.issue_to_json(issue)})
        finally:
            with self._install_lock:
                self._installing = False

    def start_job(self, action: str, settings: dict, data: dict) -> dict[str, Any]:
        """Start a conversion: the single entry point for every action (decision F34).

        Args:
            action: ``Action`` value.
            settings: Frontend ``ActionSettings``.
            data: ``ActionData`` (``{ files }``).

        Returns:
            ``{ jobId }``, or ``{ issue }`` if the job can't start (for
            example another job is running).
        """

        def body() -> dict[str, Any]:
            parsed = dto.parse_action(action)
            job_settings = dto.action_settings_from_json(settings, self._settings.get())
            job_data = dto.action_data_from_json(data)
            return {"jobId": self._jobs.start(parsed, job_settings, job_data)}

        return self._guard("start_job", lambda issue: {"issue": dto.issue_to_json(issue)}, body)

    def cancel_job(self, job_id: str) -> None:
        """Ask a running job to stop; it then ends with status ``"cancelled"``."""
        self._guard(
            "cancel_job", lambda issue: None, lambda: self._jobs.cancel(dto.parse_job_id(job_id))
        )
        return None

    def save_results(self, job_id: str, options: dict) -> dict[str, Any]:
        """Copy a job's results out of scratch, never overwriting (``SaveOutcome``).

        Args:
            job_id: The finished job.
            options: ``SaveOptions``: ``folder`` (``null`` opens the folder
                picker) and ``asZip``.

        Returns:
            ``SaveOutcome``. If the picker is cancelled, ``cancelled`` is true
            and the results are kept (decision F12).
        """

        def body() -> dict[str, Any]:
            parsed_id = dto.parse_job_id(job_id)
            folder, as_zip = dto.parse_save_options(options)
            if folder is None:
                folder = self._ask_folder()
                if folder is None:
                    log.info("Save of job %s cancelled in the folder picker", parsed_id)
                    return dto.save_outcome_json(cancelled=True)
            saved = self._jobs.save(parsed_id, folder, as_zip)
            return dto.save_outcome_json(saved=saved, folder=folder)

        return self._guard("save_results", lambda issue: dto.save_outcome_json(issue=issue), body)

    def discard_results(self, job_id: str) -> None:
        """Delete a finished job's scratch folder."""
        self._guard(
            "discard_results",
            lambda issue: None,
            lambda: self._jobs.discard(dto.parse_job_id(job_id)),
        )
        return None

    def open_folder(self, path: str) -> None:
        """Open a folder in File Explorer. Anything but an existing folder is ignored.

        Args:
            path: Folder to open.
        """

        def body() -> None:
            if not isinstance(path, str) or not path:
                raise dto.invalid_request(f"path must be a folder path; got {path!r}")
            folder = Path(path)
            # Only folders: os.startfile on a file would open (or run) it.
            if not folder.is_dir():
                log.warning("Not opening %s: not an existing folder", folder)
                return
            _open_in_file_manager(folder)

        self._guard("open_folder", lambda issue: None, body)
        return None

    def open_logs_folder(self) -> None:
        """Open the logs folder in File Explorer, creating it if needed."""

        def body() -> None:
            folder = self._logs_folder()
            folder.mkdir(parents=True, exist_ok=True)
            _open_in_file_manager(folder)

        self._guard("open_logs_folder", lambda issue: None, body)
        return None
