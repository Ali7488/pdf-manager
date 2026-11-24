"""The app's workflow, shared by the desktop window and the browser mode.

Both front doors call these methods: :class:`api.bridge.Api` (the pywebview
window) and :mod:`api.web.operations` (the local HTTP API used by browser
mode). Everything here works on real host paths; turning the UI's values into
paths (pywebview passes them directly, browser mode only ever sees opaque IDs)
and opening native dialogs is the caller's job, passed in as callables.

Rules every public method follows (as in docs/API.md):

* **Never raise into the UI.** Expected failures and bugs alike are logged and
  answered with a contract-shaped result carrying an ``Issue``.
* **Plain JSON out.** Results are built by :mod:`api.dto`.
* **Events** go through the ``emit(name, payload)`` callback given to the
  constructor (pywebview turns them into DOM events; browser mode keeps the
  latest status for the page to poll).
"""

from __future__ import annotations

import dataclasses
import logging
import os
import subprocess
import threading
import time
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from . import __version__, build_info, dto, logging_setup, paths, platforms, service
from .jobs import JobManager
from .logging_setup import log_issue
from .service import ConversionError, Issue, ocr_install_failed, ocr_missing, unexpected_error
from .settings_store import DEFAULTS, SettingsStore

log = logging.getLogger(__name__)

TESSERACT_VERSION_TIMEOUT_SEC = 15

Emit = Callable[[str, Any], None]
AskFolder = Callable[[str], "Path | None"]
AskProgram = Callable[[], "Path | None"]


def describe_files(candidates: Iterable[str | Path]) -> list[dict[str, Any]]:
    """Turn paths into the contract's ``InputFile`` objects.

    Unsupported types, folders and missing files are skipped (and logged);
    duplicates are dropped, keeping the first. Order is preserved.

    Args:
        candidates: Paths from a picker, a drop or an upload.

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


def check_tesseract(path: Path) -> str | None:
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
        return f"Expected a file named {platforms.tesseract_file_name()}: {path}"
    try:
        proc = service.run_command([path, "--version"], timeout=TESSERACT_VERSION_TIMEOUT_SEC)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Couldn't run {path} --version: {exc}"
    output = f"{proc.stdout or ''}{proc.stderr or ''}"
    if proc.returncode != 0 or "tesseract" not in output.casefold():
        return f"{path} --version exited with {proc.returncode}:\n{output.strip()}"
    return None


class Workflow:
    """Settings, tool checks, OCR, jobs and saving, independent of the window.

    Args:
        settings: The loaded settings store.
        emit: Sends an event to the UI. Must not raise.
        jobs: Job manager; a default one emitting through ``emit`` is created
            if omitted.
    """

    def __init__(self, settings: SettingsStore, emit: Emit, jobs: JobManager | None = None):
        self.settings = settings
        self._emit = emit
        self.jobs = jobs if jobs is not None else JobManager(emit)
        self._install_lock = threading.Lock()
        self._installing = False

    @property
    def installing_ocr(self) -> bool:
        """Whether an OCR install is running."""
        with self._install_lock:
            return self._installing

    def guard(self, name: str, fallback: Callable[[Issue], Any], func: Callable[..., Any], *args):
        """Run a method's body so that it never raises into the UI.

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
            log.error("Call %s failed", name)
            return fallback(log_issue(unexpected_error(traceback.format_exc()), exc))
        log.debug("Call %s took %.0f ms", name, (time.monotonic() - started) * 1000)
        return result

    def logs_folder(self) -> Path:
        """The logs folder in use (it may be a fallback folder, see logging_setup)."""
        current = logging_setup.log_file()
        return current.parent if current is not None else paths.logs_dir()

    def shutdown(self) -> None:
        """Cancel a running job and delete all scratch folders. Never raises."""
        try:
            self.jobs.shutdown()
        except Exception:
            log.exception("Error during shutdown")

    # ----- Contract operations -----

    def app_info(self) -> dict[str, Any]:
        """The app version, logs and licences folders, and platform (``AppInfo``)."""

        def body() -> dict[str, Any]:
            source = build_info.source_revision()
            return {
                "version": __version__,
                "logsDir": str(self.logs_folder()),
                "licensesDir": str(paths.licenses_dir()),
                "platform": platforms.platform_name(),
                # The exact commit this copy was built from (decision P37), or null.
                "sourceRevision": source["revision"] if source else None,
                "sourceModified": bool(source and source["modified"]),
            }

        return self.guard(
            "get_app_info",
            lambda issue: {
                "version": __version__,
                "logsDir": "",
                "licensesDir": "",
                "platform": platforms.platform_name(),
                "sourceRevision": None,
                "sourceModified": False,
            },
            body,
        )

    def get_settings(self) -> dict[str, Any]:
        """The saved ``Settings``."""
        return self.guard("get_settings", lambda issue: dict(DEFAULTS), self.settings.get)

    def save_settings(self, patch: dict) -> dict[str, Any]:
        """Merge and persist a partial ``Settings`` (``SaveSettingsResult``).

        Invalid fields are ignored (and logged), so the returned settings show
        what was actually kept. If the file can't be written, the settings
        still apply until the app closes and ``issue`` is ``SETTINGS_SAVE_FAILED``.
        Concurrent calls are applied one at a time, in the order they arrive.
        """

        def body() -> dict[str, Any]:
            update = self.settings.update(patch)
            return dto.save_settings_json(update.settings, update.issue)

        return self.guard(
            "save_settings",
            lambda issue: dto.save_settings_json(self.settings.get(), issue),
            body,
        )

    def check_tools(self, action: str, settings: dict, data: dict) -> dict[str, Any]:
        """Check the programs this job needs (``ToolCheckResult``). Same arguments as start_job."""

        def body() -> dict[str, Any]:
            parsed = dto.parse_action(action)
            job_settings = dto.action_settings_from_json(settings, self.settings.get())
            job_data = dto.action_data_from_json(data)
            check = service.check_tools(parsed, job_settings, job_data)
            check.issues = [log_issue(issue) for issue in check.issues]
            log.debug("Tool check for %s: %s", parsed, check)
            return dto.tool_check_to_json(check)

        return self.guard("check_tools", dto.failed_tool_check_json, body)

    def ocr_status(self) -> dict[str, Any]:
        """Whether Tesseract OCR is installed, and where (``OcrStatus``, for Settings)."""

        def body() -> dict[str, Any]:
            found = service.find_tesseract(self.settings.get().get("tesseractPath"))
            return {"present": found is not None, "path": str(found) if found else None}

        return self.guard("get_ocr_status", lambda issue: {"present": False, "path": None}, body)

    def ocr_languages(self) -> list[str]:
        """The installed Tesseract languages, e.g. ``["eng", "deu"]``; empty if no OCR."""

        def body() -> list[str]:
            tesseract = service.find_tesseract(self.settings.get().get("tesseractPath"))
            return service.tesseract_languages(tesseract) if tesseract else []

        return self.guard("get_ocr_languages", lambda issue: [], body)

    def search_ocr(self, ask_program: AskProgram | None) -> dict[str, Any]:
        """Find Tesseract, asking the user to pick the program if needed (``OcrSearchResult``).

        The usual places are searched first. If nothing is found and a picker
        is available, it opens; the chosen file must be named like the
        platform's Tesseract program and answer ``--version``. A found path is
        saved as ``tesseractPath``.

        Args:
            ask_program: Opens the native file picker for the program and
                returns the choice (``None`` if cancelled), or ``None`` when no
                native picker is available (browser mode without one).
        """

        def not_found(issue: Issue) -> dict[str, Any]:
            return {"found": False, "path": None, "issue": dto.issue_to_json(issue)}

        def body() -> dict[str, Any]:
            found = service.find_tesseract(self.settings.get().get("tesseractPath"))
            if found is None:
                chosen = ask_program() if ask_program is not None else None
                if chosen is None:
                    return not_found(log_issue(ocr_missing()))
                problem = check_tesseract(chosen)
                if problem:
                    # Proposed: move this wording into converter/issues.py as its own factory.
                    issue = dataclasses.replace(
                        ocr_missing(),
                        message="The chosen file isn't the OCR program (Tesseract).",
                        details=problem,
                    )
                    return not_found(log_issue(issue))
                found = chosen
            # A failed save is already logged by the store; the path still applies
            # for this session. OcrSearchResult has no slot for that warning.
            self.settings.update({"tesseractPath": str(found)})
            log.info("OCR found at %s", found)
            return {"found": True, "path": str(found), "issue": None}

        return self.guard("search_ocr", not_found, body)

    def install_ocr(self) -> None:
        """Start installing Tesseract with the platform's installer. Returns at once.

        Progress arrives as ``ocrInstallProgress`` and the end as
        ``ocrInstallFinished``. Where the app can't or mustn't install it
        itself (always on Linux, decision C16; on Windows without App
        Installer), the install ends straight away with an
        ``OCR_INSTALL_FAILED`` issue explaining what to do. A second call
        while an install runs is ignored.
        """

        def finish_failed(issue: Issue) -> None:
            self._emit("ocrInstallFinished", {"ok": False, "issue": dto.issue_to_json(issue)})

        def body() -> None:
            unavailable = platforms.ocr_install_unavailable()
            if unavailable is not None:
                raise ConversionError(unavailable)
            with self._install_lock:
                if self._installing:
                    log.info("OCR install already running; ignoring the request")
                    return
                self._installing = True
            threading.Thread(target=self._install_worker, name="ocr-install", daemon=True).start()

        self.guard("install_ocr", finish_failed, body)

    def _install_worker(self) -> None:
        """Background thread: run the install, then check Tesseract is there. Never raises."""
        try:
            self._emit(
                "ocrInstallProgress",
                {"message": "Downloading and installing OCR. This can take a few minutes."},
            )
            details = platforms.run_ocr_install()
            self._emit("ocrInstallProgress", {"message": "Checking the installation."})
            # Judge by the result, not the exit code: an installer may also exit
            # non-zero when Tesseract is already installed.
            found = service.find_tesseract(self.settings.get().get("tesseractPath"))
            if found is not None:
                self.settings.update({"tesseractPath": str(found)})
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

        Returns:
            ``{ jobId }``, or ``{ issue }`` if the job can't start (for
            example another job is running).
        """

        def body() -> dict[str, Any]:
            parsed = dto.parse_action(action)
            job_settings = dto.action_settings_from_json(settings, self.settings.get())
            job_data = dto.action_data_from_json(data)
            return {"jobId": self.jobs.start(parsed, job_settings, job_data)}

        return self.guard("start_job", lambda issue: {"issue": dto.issue_to_json(issue)}, body)

    def cancel_job(self, job_id: str) -> None:
        """Ask a running job to stop; it then ends with status ``"cancelled"``."""
        self.guard(
            "cancel_job", lambda issue: None, lambda: self.jobs.cancel(dto.parse_job_id(job_id))
        )

    def save_results(self, job_id: str, options: dict, ask_folder: AskFolder) -> dict[str, Any]:
        """Copy a job's results out of scratch, never overwriting (``SaveOutcome``).

        Args:
            job_id: The finished job.
            options: ``SaveOptions``: ``folder`` (``null`` asks with
                ``ask_folder``) and ``asZip``.
            ask_folder: Opens the folder picker, starting in the given folder
                (may be empty); returns the choice or ``None`` if cancelled.

        Returns:
            ``SaveOutcome``. If the picker is cancelled, ``cancelled`` is true
            and the results are kept (decision F12).
        """

        def body() -> dict[str, Any]:
            parsed_id = dto.parse_job_id(job_id)
            folder, as_zip = dto.parse_save_options(options)
            if folder is None:
                folder = ask_folder(self.settings.get().get("defaultSaveFolder") or "")
                if folder is None:
                    log.info("Save of job %s cancelled in the folder picker", parsed_id)
                    return dto.save_outcome_json(cancelled=True)
            saved = self.jobs.save(parsed_id, folder, as_zip)
            return dto.save_outcome_json(saved=saved, folder=folder)

        return self.guard("save_results", lambda issue: dto.save_outcome_json(issue=issue), body)

    def discard_results(self, job_id: str) -> None:
        """Delete a finished job's scratch folder. Safe to repeat, and after saving."""
        self.guard(
            "discard_results",
            lambda issue: None,
            lambda: self.jobs.discard(dto.parse_job_id(job_id)),
        )

    def open_folder(self, path: str) -> None:
        """Open a folder in the file manager. Anything but an existing folder is ignored."""

        def body() -> None:
            if not isinstance(path, str) or not path:
                raise dto.invalid_request(f"path must be a folder path; got {path!r}")
            folder = Path(path)
            # Only folders: opening a file would open (or run) it.
            if not folder.is_dir():
                log.warning("Not opening %s: not an existing folder", folder)
                return
            platforms.open_folder(folder)

        self.guard("open_folder", lambda issue: None, body)

    def open_logs_folder(self) -> None:
        """Open the logs folder in the file manager, creating it if needed."""

        def body() -> None:
            folder = self.logs_folder()
            folder.mkdir(parents=True, exist_ok=True)
            platforms.open_folder(folder)

        self.guard("open_logs_folder", lambda issue: None, body)
