"""SlideStitch: local PDF/PPT/PPTX conversion, image flattening, OCR and merge.

The original inputs are never modified.  Results are staged in a temporary folder
and only copied to the chosen destination after all requested conversion is done.
"""

from .common import ALLOWED, DPI, FLATTEN, FLATTEN_MERGE, MERGE, MODES, Progress
from .flatten import flatten_searchable
from .merge import merge_pdfs
from .output import safe_destination
from .pipeline import check_pdf, prepare_pdf, process_files
from .powerpoint import libreoffice_convert, powerpoint_to_pdf
from .tools import find_libreoffice, find_tesseract, require_tesseract, run_command

__all__ = [
    "ALLOWED",
    "DPI",
    "FLATTEN",
    "FLATTEN_MERGE",
    "MERGE",
    "MODES",
    "Progress",
    "check_pdf",
    "find_libreoffice",
    "find_tesseract",
    "flatten_searchable",
    "libreoffice_convert",
    "merge_pdfs",
    "powerpoint_to_pdf",
    "prepare_pdf",
    "process_files",
    "require_tesseract",
    "run_command",
    "safe_destination",
]
