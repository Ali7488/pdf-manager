"""Conversion at the boundary: the UI's camelCase JSON <-> the service layer's dataclasses.

Everything coming from JavaScript is untrusted: it is type-checked here and
anything malformed raises the service layer's ``ConversionError`` carrying
an ``UNEXPECTED_ERROR`` issue (a malformed call is a UI bug, not a user
mistake), so the bridge can answer with an issue instead of crashing.

Everything going to JavaScript is built from plain ``dict``/``list``/``str``/
``int``/``float``/``bool``/``None`` values, so it serializes to JSON as is.
The shapes match ``frontend/src/api/types.ts``.
"""

from __future__ import annotations

import math
from enum import StrEnum
from pathlib import Path
from typing import Any

from .service import (
    Action,
    ActionData,
    ActionSettings,
    CompressLevel,
    ConversionError,
    FileInfo,
    Issue,
    OutputFile,
    ProgressEvent,
    SplitMethod,
    SplitSettings,
    ToolCheck,
    ToolStatus,
    unexpected_error,
)

# jobFinished statuses.
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"


def invalid_request(reason: str) -> ConversionError:
    """Build the error raised for a malformed call from the UI.

    Args:
        reason: What was wrong, for the "Show details" section and the log.

    Returns:
        A :class:`ConversionError` with an ``UNEXPECTED_ERROR`` issue.
    """
    return ConversionError(unexpected_error(f"Invalid request from the interface: {reason}"))


def _enum(kind: type[StrEnum], value: Any, field: str) -> Any:
    """Parse an enum value sent as a string.

    Args:
        kind: The enum class.
        value: Value from JSON.
        field: Field name, for the error message.

    Returns:
        The enum member.

    Raises:
        ConversionError: Not one of the enum's values.
    """
    try:
        return kind(value)
    except (ValueError, TypeError):
        allowed = ", ".join(member.value for member in kind)
        raise invalid_request(f"{field} must be one of {allowed}; got {value!r}") from None


def _bool(source: dict, key: str, default: bool, field: str) -> bool:
    """Read an optional boolean field. Raises ConversionError if it isn't a boolean."""
    value = source.get(key, default)
    if not isinstance(value, bool):
        raise invalid_request(f"{field} must be true or false; got {value!r}")
    return value


def _object(value: Any, field: str) -> dict:
    """Check a value is a JSON object. Raises ConversionError otherwise."""
    if not isinstance(value, dict):
        raise invalid_request(f"{field} must be an object; got {type(value).__name__}")
    return value


def parse_action(value: Any) -> Action:
    """Parse the ``action`` argument of ``check_tools``/``start_job``.

    Raises:
        ConversionError: Unknown action.
    """
    return _enum(Action, value, "action")


def parse_job_id(value: Any) -> str:
    """Check a job id sent by the UI. Raises ConversionError if it isn't a non-empty string."""
    if not isinstance(value, str) or not value:
        raise invalid_request(f"jobId must be a non-empty string; got {value!r}")
    return value


def action_settings_from_json(value: Any, saved: dict[str, Any]) -> ActionSettings:
    """Build the service layer's settings from the UI's per-job options and saved settings.

    Missing per-job fields take the service-layer defaults; fields that are
    present must have the right type.

    Args:
        value: The frontend ``ActionSettings`` object.
        saved: The persisted ``Settings`` (already validated by the settings store).

    Returns:
        The service layer's ``ActionSettings``.

    Raises:
        ConversionError: Malformed settings.
    """
    source = _object(value, "settings")
    base = ActionSettings()
    split_source = _object(source.get("split", {}), "settings.split")
    every_n = split_source.get("everyN", base.split.every_n)
    # JavaScript numbers may arrive as floats (2.0); bool is an int subclass, so exclude it.
    if isinstance(every_n, float) and every_n.is_integer():
        every_n = int(every_n)
    if isinstance(every_n, bool) or not isinstance(every_n, int) or every_n < 1:
        raise invalid_request(f"settings.split.everyN must be a whole number >= 1; got {every_n!r}")
    ranges = split_source.get("ranges", base.split.ranges)
    if not isinstance(ranges, str):
        raise invalid_request(f"settings.split.ranges must be text; got {ranges!r}")
    split = SplitSettings(
        method=_enum(
            SplitMethod, split_source.get("method", base.split.method), "settings.split.method"
        ),
        ranges=ranges,
        every_n=every_n,
    )
    return ActionSettings(
        use_ocr=_bool(source, "useOcr", base.use_ocr, "settings.useOcr"),
        contents_page=_bool(source, "contentsPage", base.contents_page, "settings.contentsPage"),
        split=split,
        combine_images=_bool(
            source, "combineImages", base.combine_images, "settings.combineImages"
        ),
        compress_level=_enum(
            CompressLevel,
            source.get("compressLevel", base.compress_level),
            "settings.compressLevel",
        ),
        dpi=saved.get("dpi", base.dpi),
        ocr_language=saved.get("ocrLanguage", base.ocr_language),
        ocr_page_timeout_sec=saved.get("ocrPageTimeoutSec", base.ocr_page_timeout_sec),
        tesseract_path=saved.get("tesseractPath", base.tesseract_path),
    )


def action_settings_to_json(settings: ActionSettings) -> dict[str, Any]:
    """The per-job part of :class:`ActionSettings` as the frontend's ``ActionSettings``.

    Used for logging a job request and in tests; saved settings (DPI and so
    on) are not part of the frontend object and are left out.

    Args:
        settings: Service-layer settings.

    Returns:
        The camelCase object.
    """
    return {
        "useOcr": settings.use_ocr,
        "contentsPage": settings.contents_page,
        "split": {
            "method": settings.split.method.value,
            "ranges": settings.split.ranges,
            "everyN": settings.split.every_n,
        },
        "combineImages": settings.combine_images,
        "compressLevel": settings.compress_level.value,
    }


def action_data_from_json(value: Any) -> ActionData:
    """Build :class:`ActionData` from the UI's ``{ files: string[] }``.

    Raises:
        ConversionError: ``files`` is missing or holds anything but non-empty strings.
    """
    source = _object(value, "data")
    files = source.get("files")
    if not isinstance(files, list) or not all(isinstance(f, str) and f for f in files):
        raise invalid_request("data.files must be a list of file paths")
    return ActionData([Path(f) for f in files])


def parse_save_options(value: Any) -> tuple[Path | None, bool]:
    """Parse ``SaveOptions`` (``{ folder, asZip }``).

    Returns:
        ``(folder or None for "ask", as_zip)``.

    Raises:
        ConversionError: Malformed options.
    """
    source = _object(value, "options")
    folder = source.get("folder")
    if folder is not None and (not isinstance(folder, str) or not folder.strip()):
        raise invalid_request(f"options.folder must be a path or null; got {folder!r}")
    as_zip = _bool(source, "asZip", False, "options.asZip")
    return (Path(folder) if folder else None), as_zip


def issue_to_json(issue: Issue) -> dict[str, Any]:
    """Convert an :class:`Issue` to the contract's ``Issue`` object.

    ``command`` (a command the user can copy and run themselves, decision
    C16) is always present: ``None`` (JSON ``null``) when the issue has none.
    """
    return {
        "code": str(issue.code),
        "severity": str(issue.severity),
        "title": issue.title,
        "message": issue.message,
        "troubleshooting": list(issue.troubleshooting),
        "details": issue.details,
        "logFile": issue.log_file,
        "command": issue.command,
        "file": issue.file,
    }


def input_file_to_json(info: FileInfo) -> dict[str, Any]:
    """Convert a :class:`FileInfo` to the contract's ``InputFile``."""
    return {
        "path": str(info.path),
        "name": info.name,
        "kind": str(info.kind),
        "sizeBytes": info.size_bytes,
        "pageCount": info.page_count,
    }


def progress_to_json(job_id: str, event: ProgressEvent) -> dict[str, Any]:
    """Convert a :class:`ProgressEvent` to the contract's ``JobProgress``.

    Args:
        job_id: The job the event belongs to.
        event: Progress from the service layer.

    Returns:
        The ``JobProgress`` object; ``fraction`` is clamped to 0..1.
    """
    fraction = float(event.fraction)
    if not math.isfinite(fraction):  # NaN can't be sent as JSON; show "no progress yet".
        fraction = 0.0
    return {
        "jobId": job_id,
        "stage": str(event.stage),
        "fileIndex": event.file_index,
        "fileCount": event.file_count,
        "page": event.page,
        "pageCount": event.page_count,
        "fraction": min(max(fraction, 0.0), 1.0),
        "message": event.message,
    }


def output_to_json(output: OutputFile) -> dict[str, Any]:
    """Convert an :class:`OutputFile` to the contract's ``OutputFile`` (no scratch path)."""
    return {"name": output.name, "sizeBytes": output.size_bytes, "pageCount": output.page_count}


def tool_status_to_json(status: ToolStatus) -> dict[str, Any]:
    """Convert a :class:`ToolStatus` to the contract's ``ToolStatus``."""
    return {
        "required": status.required,
        "present": status.present,
        "path": str(status.path) if status.path else None,
    }


def tool_check_to_json(check: ToolCheck) -> dict[str, Any]:
    """Convert a :class:`ToolCheck` to the contract's ``ToolCheckResult``.

    The caller logs the issues first (so ``logFile`` is set).
    """
    return {
        "ok": check.ok,
        "ocr": tool_status_to_json(check.ocr),
        "powerpoint": tool_status_to_json(check.powerpoint),
        "libreoffice": tool_status_to_json(check.libreoffice),
        "issues": [issue_to_json(issue) for issue in check.issues],
    }


def failed_tool_check_json(issue: Issue) -> dict[str, Any]:
    """A ``ToolCheckResult`` for when the check itself couldn't run.

    Args:
        issue: Why (already logged).

    Returns:
        ``ok`` False, every tool "not required, not present", and the issue.
    """
    unknown = {"required": False, "present": False, "path": None}
    return {
        "ok": False,
        "ocr": dict(unknown),
        "powerpoint": dict(unknown),
        "libreoffice": dict(unknown),
        "issues": [issue_to_json(issue)],
    }


def job_finished_json(
    job_id: str,
    status: str,
    outputs: list[OutputFile],
    warnings: list[Issue],
    error: Issue | None,
) -> dict[str, Any]:
    """Build the contract's ``JobFinished`` payload.

    Args:
        job_id: The job.
        status: ``"succeeded"``, ``"failed"`` or ``"cancelled"``.
        outputs: Results (only sent when succeeded).
        warnings: Non-fatal issues (already logged).
        error: The fatal issue when failed (already logged).

    Returns:
        The ``JobFinished`` object.
    """
    return {
        "jobId": job_id,
        "status": status,
        "outputs": [output_to_json(o) for o in outputs] if status == SUCCEEDED else [],
        "warnings": [issue_to_json(w) for w in warnings],
        "error": issue_to_json(error) if error is not None else None,
    }


def save_outcome_json(
    *,
    cancelled: bool = False,
    saved: list[Path] | None = None,
    folder: Path | None = None,
    issue: Issue | None = None,
) -> dict[str, Any]:
    """Build the contract's ``SaveOutcome``.

    Args:
        cancelled: The user closed the folder picker.
        saved: Full paths written.
        folder: Folder saved into.
        issue: Why saving failed (already logged).

    Returns:
        The ``SaveOutcome`` object.
    """
    return {
        "cancelled": cancelled,
        "savedPaths": [str(p) for p in saved or []],
        "folder": str(folder) if folder else None,
        "issue": issue_to_json(issue) if issue is not None else None,
    }


def save_settings_json(settings: dict[str, Any], issue: Issue | None) -> dict[str, Any]:
    """Build the contract's ``SaveSettingsResult``.

    Args:
        settings: The full settings now in effect (already camelCase).
        issue: ``SETTINGS_SAVE_FAILED`` if they weren't written to disk, or why
            the call failed (already logged); ``None`` when saved.

    Returns:
        The ``SaveSettingsResult`` object.
    """
    return {"settings": settings, "issue": issue_to_json(issue) if issue is not None else None}
