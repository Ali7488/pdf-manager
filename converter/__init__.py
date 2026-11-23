"""PDF Manager's conversion engine (the service layer).

The original inputs are never modified. Results are staged in a scratch folder
and only copied to the user's chosen destination (by the API layer) after the
job is done.

How a job flows (see ``docs/ARCHITECTURE.md`` for the full picture):

1. ``run_action(action, settings, data, scratch=..., progress=..., cancel=...)``
   is the single entry point (decision F34). It validates the inputs and, if
   "Use OCR" is on, that Tesseract is installed.
2. Each input becomes a PDF: PDFs are used as they are; PowerPoint files are
   rendered by Microsoft PowerPoint when available (Windows) or LibreOffice.
3. The action runs: flatten (optionally with OCR), merge (bookmarks, optional
   contents page, page labels), split, images to PDF, or compress. OCR on
   non-flatten actions only adds a text layer to pages that have no text.
4. ``JobResult`` lists the outputs (still in scratch) and any warnings.
   Fatal problems raise ``ConversionError`` carrying a user-facing ``Issue``.

Supporting pieces: ``check_tools`` (the Convert modal's tool check),
``inspect_file`` (file list entries), ``safe_destination`` (never overwrite
when saving), and ``converter.platforms`` (all OS-specific code).
"""

from .common import (
    ACCEPTS,
    DOCUMENT_EXTENSIONS,
    DPI,
    IMAGE_EXTENSIONS,
    Action,
    ActionData,
    ActionSettings,
    CompressLevel,
    JobResult,
    OutputFile,
    Progress,
    ProgressEvent,
    SplitMethod,
    SplitSettings,
    Stage,
)
from .context import CancelToken, JobContext
from .files import FileInfo, FileKind, inspect_file
from .issues import Cancelled, ConversionError, Issue, IssueCode, Severity
from .output import safe_destination
from .pipeline import run_action
from .toolcheck import ToolCheck, ToolStatus, check_tools
from .tools import find_libreoffice, find_powerpoint, find_tesseract, tesseract_languages

__all__ = [
    "ACCEPTS",
    "DOCUMENT_EXTENSIONS",
    "DPI",
    "IMAGE_EXTENSIONS",
    "Action",
    "ActionData",
    "ActionSettings",
    "CancelToken",
    "Cancelled",
    "CompressLevel",
    "ConversionError",
    "FileInfo",
    "FileKind",
    "Issue",
    "IssueCode",
    "JobContext",
    "JobResult",
    "OutputFile",
    "Progress",
    "ProgressEvent",
    "Severity",
    "SplitMethod",
    "SplitSettings",
    "Stage",
    "ToolCheck",
    "ToolStatus",
    "check_tools",
    "find_libreoffice",
    "find_powerpoint",
    "find_tesseract",
    "inspect_file",
    "run_action",
    "safe_destination",
    "tesseract_languages",
]
