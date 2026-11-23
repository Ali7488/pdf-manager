"""The API layer's single import point for the service layer (``converter/``).

Every other ``api`` module imports service-layer names from here, and calls
the functions through this module (``service.run_action(...)``), so:

* tests replace a service function in one place
  (``monkeypatch.setattr(service, "run_action", fake)``), and
* a reorganisation of ``converter/`` only touches this file.

Transitional: ``converter/`` is being reorganised in parallel (``core/``,
``files/``, ``tools/`` and ``actions/`` packages). The first block imports
that layout; the fallback imports the original flat modules. Delete the
fallback once both branches are merged.
"""

# Every name below is re-exported, so "imported but unused" doesn't apply.
# ruff: noqa: F401

try:  # Reorganised layout: converter.core.*, converter.files, converter.tools.check, ...
    from converter.actions.run import run_action
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
    from converter.tools.check import ToolCheck, ToolStatus, check_tools

    from converter.files import FileInfo, FileKind, inspect_file, safe_destination
except ImportError:  # Original flat layout (converter.common, converter.toolcheck, ...).
    from converter import issues
    from converter.common import (
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
    from converter.context import CancelToken
    from converter.files import FileInfo, FileKind, inspect_file
    from converter.issues import (
        Cancelled,
        ConversionError,
        Issue,
        IssueCode,
        Severity,
        job_already_running,
        ocr_install_failed,
        ocr_missing,
        save_failed,
        unexpected_error,
    )
    from converter.output import safe_destination
    from converter.pipeline import run_action
    from converter.toolcheck import ToolCheck, ToolStatus, check_tools

# The same path in both layouts (a module before, a package after).
from converter.tools import find_tesseract, run_command, tesseract_languages
