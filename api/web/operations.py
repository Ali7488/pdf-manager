"""The operations browser mode's page may call, one function each.

Each takes the request :class:`Context` and the parsed JSON body (or the URL's
``{id}``) and returns a JSON-ready value in the contract's shapes
(``frontend/src/api/types.ts``). They check their input, turn the page's
opaque IDs into host paths through the :class:`~api.web.session.Session`, and
call the shared :class:`~api.workflow.Workflow`. The page can never name a
host file, folder or program itself:

* files are IDs from a native pick or an upload;
* a save goes to a folder the user picked (by ID) or the saved default folder;
* "open folder" only opens folders this session showed for that purpose;
* the Tesseract path is never taken from the page (``search_ocr`` asks with a
  native picker; settings patches can't set it).

The routes are in :data:`api.web.server.ROUTES`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import dto, platforms
from ..service import ConversionError
from ..workflow import Workflow, describe_files
from .session import OPEN, SAVE, Session, UploadError

log = logging.getLogger(__name__)

# Settings the page may change. tesseractPath is set only by search_ocr and
# the OCR install; defaultSaveFolder only to a folder the user picked.
PAGE_SETTINGS = {"theme", "dpi", "ocrLanguage", "ocrPageTimeoutSec", "defaultSaveFolder"}


@dataclass
class Context:
    """What an operation may use.

    Attributes:
        workflow: The shared workflow.
        session: This run's IDs and status.
        native_dialogs: Whether native pickers can be shown here.
        request_stop: Asks the app to quit (``POST /api/quit``).
    """

    workflow: Workflow
    session: Session
    native_dialogs: bool
    request_stop: Any = None
    dialog_lock: threading.Lock = field(default_factory=threading.Lock)

    def ask_files(self, filters: tuple[str, ...], multiple: bool) -> list[Path]:
        """Show the native Open dialog (one dialog at a time)."""
        with self.dialog_lock:
            return platforms.ask_files(filters, multiple)

    def ask_folder(self, start: str) -> Path | None:
        """Show the native folder picker (one dialog at a time)."""
        with self.dialog_lock:
            return platforms.ask_folder(start)


def _body(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise dto.invalid_request("the request body must be a JSON object")
    return body


def _no_picker(name: str) -> ConversionError:
    return dto.invalid_request(f"{name} needs a native picker, which isn't available here")


# ----- App and settings -----


def app_info(ctx: Context, body: Any) -> dict[str, Any]:
    info = ctx.workflow.app_info()
    ctx.session.know_folder(info["logsDir"], OPEN)
    ctx.session.know_folder(info["licensesDir"], OPEN)
    return info


def get_settings(ctx: Context, body: Any) -> dict[str, Any]:
    settings = ctx.workflow.get_settings()
    ctx.session.know_folder(settings.get("defaultSaveFolder"), OPEN, SAVE)
    return settings


def save_settings(ctx: Context, body: Any) -> dict[str, Any]:
    """Apply the fields the page may change; a default folder must be a picked folder."""

    def run() -> dict[str, Any]:
        patch = _body(body)
        unknown = set(patch) - PAGE_SETTINGS
        if unknown:
            log.warning("Settings the page may not change were ignored: %s", sorted(unknown))
        patch = {k: v for k, v in patch.items() if k in PAGE_SETTINGS}
        if patch.get("defaultSaveFolder") not in (None, ""):
            folder = ctx.session.resolve_folder(patch["defaultSaveFolder"], SAVE)
            if folder is None:
                log.warning("defaultSaveFolder ignored: not a folder the user picked")
                del patch["defaultSaveFolder"]
            else:
                patch["defaultSaveFolder"] = str(folder)
        result = ctx.workflow.save_settings(patch)
        ctx.session.know_folder(result["settings"].get("defaultSaveFolder"), OPEN, SAVE)
        return result

    return ctx.workflow.guard(
        "save_settings",
        lambda issue: dto.save_settings_json(ctx.workflow.settings.get(), issue),
        run,
    )


# ----- Files and folders -----


def pick_files(ctx: Context, body: Any) -> list[dict[str, Any]]:
    """Native Open dialog: the chosen files as ``InputFile[]`` with file IDs."""

    def run() -> list[dict[str, Any]]:
        kind = _body(body).get("kind")
        filters = platforms.file_filters()
        if kind not in filters:
            raise dto.invalid_request(f"kind must be all, documents or images; got {kind!r}")
        if not ctx.native_dialogs:
            raise _no_picker("pick_files")
        return ctx.session.for_page(describe_files(ctx.ask_files(filters[kind], True)))

    return ctx.workflow.guard("pick_files", lambda issue: [], run)


def pick_folder(ctx: Context, body: Any) -> str | None:
    """Native folder picker: the chosen folder's ID (for Settings), or ``None``."""

    def run() -> str | None:
        if not ctx.native_dialogs:
            raise _no_picker("pick_folder")
        start = ctx.workflow.settings.get().get("defaultSaveFolder") or ""
        folder = ctx.ask_folder(start)
        return ctx.session.folder_id(folder) if folder else None

    return ctx.workflow.guard("pick_folder", lambda issue: None, run)


def open_folder(ctx: Context, body: Any) -> None:
    """Open a folder this session showed the page (results, logs, licences, default)."""

    def run() -> None:
        folder = ctx.session.resolve_folder(_body(body).get("folder"), OPEN)
        if folder is None:
            raise dto.invalid_request("folder isn't one this session may open")
        ctx.workflow.open_folder(str(folder))

    ctx.workflow.guard("open_folder", lambda issue: None, run)


def open_logs_folder(ctx: Context, body: Any) -> None:
    ctx.workflow.open_logs_folder()


# ----- Tool check and jobs -----


def _job_data(ctx: Context, body: dict[str, Any]) -> dict[str, Any]:
    data = body.get("data")
    if not isinstance(data, dict):
        raise dto.invalid_request("data must be an object with files")
    return {"files": ctx.session.resolve_files(data.get("files"))}


def check_tools(ctx: Context, body: Any) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        request = _body(body)
        data = _job_data(ctx, request)
        return ctx.workflow.check_tools(request.get("action"), request.get("settings"), data)

    return ctx.workflow.guard("check_tools", dto.failed_tool_check_json, run)


def start_job(ctx: Context, body: Any) -> dict[str, Any]:
    """Start a job. A retried request (same ``requestId``) gets the same answer."""

    def run() -> dict[str, Any]:
        request = _body(body)
        request_id = request.get("requestId")
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 64:
            raise dto.invalid_request("requestId must be a string of 8 to 64 characters")
        earlier = ctx.session.started(request_id)
        if earlier is not None:
            return earlier
        data = _job_data(ctx, request)
        action = request.get("action")
        result = ctx.workflow.start_job(action, request.get("settings"), data)
        ctx.session.job_started(request_id, str(action), result)
        return result

    return ctx.workflow.guard("start_job", lambda issue: {"issue": dto.issue_to_json(issue)}, run)


def job_status(ctx: Context, body: Any, job_id: str) -> dict[str, Any] | None:
    """``{jobId, progress, finished}``; ``None`` (404) for a job this session didn't start."""
    return ctx.session.job_status(job_id)


def latest_job(ctx: Context, body: Any) -> dict[str, Any]:
    """The newest job not yet discarded (after a page refresh), or ``{job: null}``."""
    return {"job": ctx.session.latest_job()}


def cancel_job(ctx: Context, body: Any, job_id: str) -> None:
    if ctx.session.job_status(job_id) is not None:
        ctx.workflow.cancel_job(job_id)


def save_results(ctx: Context, body: Any, job_id: str) -> dict[str, Any]:
    """Save to a picked folder (ID), the default folder, or ask (``folder: null``)."""

    def run() -> dict[str, Any]:
        request = _body(body)
        if ctx.session.job_status(job_id) is None:
            raise dto.invalid_request("unknown job")
        as_zip = request.get("asZip")
        value = request.get("folder")
        if value is None:
            if not ctx.native_dialogs:
                raise _no_picker("save_results")
            options = {"folder": None, "asZip": as_zip}
        else:
            folder = ctx.session.resolve_folder(value, SAVE)
            if folder is None:
                raise dto.invalid_request("folder isn't one the user chose for saving")
            options = {"folder": str(folder), "asZip": as_zip}
        outcome = ctx.workflow.save_results(job_id, options, ctx.ask_folder)
        ctx.session.know_folder(outcome.get("folder"), OPEN)
        return outcome

    return ctx.workflow.guard("save_results", lambda i: dto.save_outcome_json(issue=i), run)


def prepare_download(ctx: Context, body: Any, job_id: str) -> dict[str, Any]:
    """Copy the results for downloading; they stay saved in the app for a retry.

    Returns:
        ``{downloads: [{id, name, sizeBytes}], issue}``.
    """

    def run() -> dict[str, Any]:
        request = _body(body)
        if ctx.session.job_status(job_id) is None:
            raise dto.invalid_request("unknown job")
        as_zip = request.get("asZip")
        if not isinstance(as_zip, bool):
            raise dto.invalid_request("asZip must be true or false")
        written = ctx.workflow.jobs.save(job_id, ctx.session.download_folder(), as_zip, keep=True)
        return {"downloads": [ctx.session.add_download(p) for p in written], "issue": None}

    return ctx.workflow.guard(
        "prepare_download",
        lambda issue: {"downloads": [], "issue": dto.issue_to_json(issue)},
        run,
    )


def discard_results(ctx: Context, body: Any, job_id: str) -> None:
    if ctx.session.job_status(job_id) is not None:
        ctx.workflow.discard_results(job_id)
        ctx.session.forget_job(job_id)


# ----- OCR -----


def ocr_status(ctx: Context, body: Any) -> dict[str, Any]:
    return ctx.workflow.ocr_status()


def ocr_languages(ctx: Context, body: Any) -> list[str]:
    return ctx.workflow.ocr_languages()


def search_ocr(ctx: Context, body: Any) -> dict[str, Any]:
    """Search the usual places, then (with a native picker) ask for the program."""

    def ask() -> Path | None:
        chosen = ctx.ask_files(platforms.program_filters(), False)
        return chosen[0] if chosen else None

    return ctx.workflow.search_ocr(ask if ctx.native_dialogs else None)


def install_ocr(ctx: Context, body: Any) -> None:
    """Start the platform's fixed OCR install (see ``platforms.run_ocr_install``)."""
    if not ctx.workflow.installing_ocr:
        ctx.session.ocr_install_started()
    ctx.workflow.install_ocr()


def ocr_install_status(ctx: Context, body: Any) -> dict[str, Any]:
    return ctx.session.ocr_install_status()


# ----- The app -----


def quit_app(ctx: Context, body: Any) -> None:
    """Quit PDF Manager (after this answer is sent)."""
    log.info("Quit requested from the page")
    if ctx.request_stop is not None:
        ctx.request_stop()


def upload(ctx: Context, name: str, size: int, modified: str, read) -> list[dict[str, Any]]:
    """Stage a dropped or browser-selected file; ``InputFile[]`` (empty if unusable)."""

    def run() -> list[dict[str, Any]]:
        try:
            path = ctx.session.stage_upload(name, size, modified, read)
        except UploadError as exc:
            log.info("Upload refused: %s", exc)
            return []
        files = describe_files([path])
        if not files:
            path.unlink(missing_ok=True)
        return ctx.session.for_page(files)

    return ctx.workflow.guard("upload", lambda issue: [], run)
