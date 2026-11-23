"""The API layer's single import point for the service layer (``converter/``).

Every other ``api`` module imports service-layer names from here, and calls
the functions through this module (``service.run_action(...)``), so:

* tests replace a service function in one place
  (``monkeypatch.setattr(service, "run_action", fake)``), and
* a reorganisation of ``converter/`` only touches this file.

The imports are plain, with no fallback: if the service layer can't be
imported, the app must fail loudly at startup rather than run half-wired.
"""

# Every name below is re-exported, so "imported but unused" doesn't apply.
# ruff: noqa: F401

from converter.actions import run_action
from converter.core import issues
from converter.core.context import CancelToken
from converter.core.issues import (
    Cancelled,
    ConversionError,
    Issue,
    IssueCode,
    Severity,
    job_already_running,
    ocr_install_failed,
    ocr_missing,
    save_failed,
    settings_save_failed,
    unexpected_error,
)
from converter.core.types import (
    DPI,
    OCR_LANGUAGE,
    OCR_PAGE_TIMEOUT_SEC,
    Action,
    ActionData,
    ActionSettings,
    CompressLevel,
    JobResult,
    OutputFile,
    ProgressEvent,
    SplitMethod,
    SplitSettings,
    Stage,
)
from converter.files import FileInfo, FileKind, file_kind, inspect_file, safe_destination
from converter.tools import find_tesseract, run_command, tesseract_languages
from converter.tools.check import ToolCheck, ToolStatus, check_tools
