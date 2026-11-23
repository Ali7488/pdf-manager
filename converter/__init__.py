"""PDF Manager: local PDF/PPT/PPTX conversion, image flattening, OCR and merge.

The original inputs are never modified.  Results are staged in a temporary folder
and only copied to the chosen destination after all requested conversion is done.

How a job flows through the package:

1. ``pipeline.process_files`` is the entry point. For each input it calls
   ``pipeline.prepare_pdf``, which uses ``powerpoint.powerpoint_to_pdf`` for
   PowerPoint files, then validates the PDF with ``pipeline.check_pdf``.
2. In the flatten modes, ``flatten.flatten_searchable`` rasterizes every page
   and adds a Tesseract OCR text layer (Tesseract is found by ``tools``).
3. In the merge modes, ``merge.merge_pdfs`` combines the files in order.
4. The caller copies the results out of the scratch folder, using
   ``output.safe_destination`` to avoid overwriting existing files.

Modules:
    common      Constants (modes, supported extensions, DPI) and the progress type.
    tools       Finding Tesseract and LibreOffice; running external programs.
    powerpoint  PPT/PPTX to PDF via Microsoft PowerPoint, falling back to LibreOffice.
    flatten     Page rasterization plus OCR text layer.
    merge       Joining PDFs in order.
    pipeline    The job orchestration described above.
    output      Collision-safe output file names.
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
