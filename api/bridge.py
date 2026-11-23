"""The ``Api`` object exposed to JavaScript as ``window.pywebview.api`` (desktop mode).

Method names and argument order follow ``docs/API.md`` exactly; the
frontend's typed client (``frontend/src/api/client.ts``) wraps them in
camelCase. The work itself is done by :class:`api.workflow.Workflow`, which
browser mode shares; this module adds only what belongs to the pywebview
window: its native dialogs, its drop events and DOM-event delivery. Rules
every public method follows:

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

import json
import logging
import re
from pathlib import Path
from typing import Any

import webview
from webview.dom import DOMEventHandler

from . import dto, platforms
from .jobs import JobManager
from .settings_store import SettingsStore
from .workflow import Workflow, describe_files

log = logging.getLogger(__name__)

EVENT_PREFIX = "pdfmanager:"
_EVENT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")

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


def _ignore_event(_event: Any) -> None:
    """DOM event callback that does nothing (the JS side already called preventDefault)."""


def _first_path(picked: Any) -> Path | None:
    """The first path of a pywebview dialog result (a sequence, or a plain string)."""
    if not picked:
        return None
    return Path(picked if isinstance(picked, str) else picked[0])


class Api:
    """The methods the UI calls. Exposed to JavaScript as ``window.pywebview.api``.

    Args:
        settings: The loaded settings store.
        jobs: Job manager; a default one emitting through this object is
            created if omitted.
    """

    def __init__(self, settings: SettingsStore, jobs: JobManager | None = None):
        self._window: Any = None  # The pywebview window, set by _bind_window.
        self._workflow = Workflow(settings, self._emit, jobs)

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
            files = describe_files(c for c in candidates if c)
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
        self._workflow.shutdown()

    def _ask_folder(self, start: str) -> Path | None:
        """Open the window's native folder picker.

        Args:
            start: Folder to start in (may be empty).

        Returns:
            The chosen folder, or ``None`` if the user cancelled.
        """
        return _first_path(
            self._window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
        )

    def _ask_program(self) -> Path | None:
        """Open the window's file picker for the Tesseract program."""
        return _first_path(
            self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                allow_multiple=False,
                file_types=platforms.program_filters(),
            )
        )

    # ----- Contract methods (public: exposed to JavaScript) -----

    def get_app_info(self) -> dict[str, Any]:
        """Return the app version, logs and licences folders, and platform (``AppInfo``)."""
        return self._workflow.app_info()

    def get_settings(self) -> dict[str, Any]:
        """Return the saved ``Settings``."""
        return self._workflow.get_settings()

    def save_settings(self, patch: dict) -> dict[str, Any]:
        """Merge and persist a partial ``Settings`` (``SaveSettingsResult``).

        pywebview runs each call on its own thread; the store applies them one
        at a time, in the order they arrive.

        Args:
            patch: Partial ``Settings`` (camelCase).

        Returns:
            ``{ settings, issue }``; ``issue`` is ``None`` when saved.
        """
        return self._workflow.save_settings(patch)

    def pick_files(self, kind: str) -> list[dict[str, Any]]:
        """Open the native file picker (multiple selection) and return ``InputFile[]``.

        Args:
            kind: ``"all"`` (every supported type), ``"documents"`` (PDF/PPTX/PPT)
                or ``"images"`` (PNG/JPG).

        Returns:
            The chosen usable files; empty if cancelled.
        """

        def body() -> list[dict[str, Any]]:
            filters = platforms.file_filters()
            if kind not in filters:
                raise dto.invalid_request(f"kind must be all, documents or images; got {kind!r}")
            picked = self._window.create_file_dialog(
                webview.FileDialog.OPEN, allow_multiple=True, file_types=filters[kind]
            )
            return describe_files(picked or [])

        return self._workflow.guard("pick_files", lambda issue: [], body)

    def pick_folder(self) -> str | None:
        """Open the native folder picker. Returns the folder path, or ``None`` if cancelled."""

        def body() -> str | None:
            start = self._workflow.settings.get().get("defaultSaveFolder") or ""
            folder = self._ask_folder(start)
            return str(folder) if folder else None

        return self._workflow.guard("pick_folder", lambda issue: None, body)

    def check_tools(self, action: str, settings: dict, data: dict) -> dict[str, Any]:
        """Check the programs this job needs (``ToolCheckResult``). Same arguments as start_job.

        Args:
            action: ``Action`` value.
            settings: Frontend ``ActionSettings``.
            data: ``ActionData`` (``{ files }``).
        """
        return self._workflow.check_tools(action, settings, data)

    def get_ocr_status(self) -> dict[str, Any]:
        """Whether Tesseract OCR is installed, and where (``OcrStatus``, for Settings).

        Uses the saved ``tesseractPath`` first, then the usual places. Nothing
        is saved and no picker opens (that is ``search_ocr``).
        """
        return self._workflow.ocr_status()

    def get_ocr_languages(self) -> list[str]:
        """Return the installed Tesseract languages, e.g. ``["eng", "deu"]``; empty if no OCR."""
        return self._workflow.ocr_languages()

    def search_ocr(self) -> dict[str, Any]:
        """Find Tesseract, asking the user to pick the program if needed.

        The usual places are searched first. If nothing is found, a file
        picker opens; the chosen file must be named like the platform's
        Tesseract program (``tesseract.exe`` on Windows, ``tesseract`` on
        Linux) and answer ``--version``. A found path is saved as ``tesseractPath``.

        Returns:
            ``OcrSearchResult``.
        """
        return self._workflow.search_ocr(self._ask_program)

    def install_ocr(self) -> None:
        """Start installing Tesseract with the platform's installer. Returns at once.

        Progress arrives as ``ocrInstallProgress`` and the end as
        ``ocrInstallFinished``. Where the app can't or mustn't install it
        itself (always on Linux, decision C16; on Windows without App
        Installer), the install ends straight away with an
        ``OCR_INSTALL_FAILED`` issue explaining what to do; on Linux its
        ``command`` holds the exact install command to copy. A second call
        while an install runs is ignored.
        """
        self._workflow.install_ocr()

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
        return self._workflow.start_job(action, settings, data)

    def cancel_job(self, job_id: str) -> None:
        """Ask a running job to stop; it then ends with status ``"cancelled"``."""
        self._workflow.cancel_job(job_id)

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
        return self._workflow.save_results(job_id, options, self._ask_folder)

    def discard_results(self, job_id: str) -> None:
        """Delete a finished job's scratch folder. Safe to repeat, and after saving."""
        self._workflow.discard_results(job_id)

    def open_folder(self, path: str) -> None:
        """Open a folder in the file manager. Anything but an existing folder is ignored.

        Args:
            path: Folder to open.
        """
        self._workflow.open_folder(path)

    def open_logs_folder(self) -> None:
        """Open the logs folder in the file manager, creating it if needed."""
        self._workflow.open_logs_folder()
