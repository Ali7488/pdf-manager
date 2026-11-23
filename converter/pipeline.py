"""Orchestration: prepare each input as a PDF, validate it, then flatten and/or merge."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import fitz

from .common import ALLOWED, FLATTEN, FLATTEN_MERGE, MERGE, MODES, Progress
from .flatten import flatten_searchable
from .merge import merge_pdfs
from .powerpoint import powerpoint_to_pdf
from .tools import require_tesseract


def prepare_pdf(source: Path, work: Path, report: Progress) -> Path:
    """Get a PDF version of one input file.

    PDFs are used directly (the original file is only ever read). PowerPoint
    files are rendered to PDF inside ``work``.

    Args:
        source: Input file: ``.pdf``, ``.pptx`` or ``.ppt``.
        work: This file's scratch folder; created if needed.
        report: Progress callback.

    Returns:
        Path to a PDF: ``source`` itself for PDFs, otherwise the rendered file.

    Raises:
        ValueError: The file doesn't exist or has an unsupported extension.
        RuntimeError: PowerPoint rendering failed.
    """
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in ALLOWED:
        raise ValueError(f"Unsupported input: {source.name}. Choose PDF, PPTX or PPT.")
    work.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".pdf":
        return source
    return powerpoint_to_pdf(source, work, report)


def check_pdf(source: Path) -> None:
    """Reject PDFs the converter can't process.

    Args:
        source: PDF to check.

    Raises:
        ValueError: The PDF needs a password to open, or has no pages.
        fitz.FileDataError: The file is not a valid PDF.
    """
    with fitz.open(str(source)) as doc:
        if doc.needs_pass:
            raise ValueError(f"Password-protected PDF not supported: {source.name}")
        if len(doc) < 1:
            raise ValueError(f"PDF is empty: {source.name}")


def process_files(
    files: Sequence[Path],
    mode: str,
    scratch: Path,
    report: Progress,
    engine: str | Path | None = None,
) -> list[tuple[str, Path]]:
    """Run a whole conversion job and return the results, still in the scratch folder.

    This is the converter's main entry point. Nothing is written to the user's
    output folder here: results stay in ``scratch`` so the caller can let the
    user choose where to save them (see :func:`converter.output.safe_destination`).

    Each input is processed in order, in its own ``scratch/item_NNN`` folder:
    converted to PDF if needed (:func:`prepare_pdf`), validated
    (:func:`check_pdf`), and, unless the mode is Merge, flattened with OCR.

    Modes:
        * ``FLATTEN``: one image-only + OCR PDF per input, named
          ``"<input name> - Flattened Searchable.pdf"``.
        * ``FLATTEN_MERGE``: all inputs flattened, then merged into one PDF in
          list order, named ``"<first name> + N more - Flattened Searchable Merged.pdf"``.
        * ``MERGE``: inputs merged as they are, keeping their original text and
          annotations, named ``"<first name> + N more - Merged.pdf"``.

    Args:
        files: Input files, in the order they should appear when merged.
        mode: One of :data:`FLATTEN`, :data:`FLATTEN_MERGE` or :data:`MERGE`.
        scratch: Empty working folder for all intermediate and final files.
        report: Progress callback for status messages.
        engine: Optional user-chosen path to ``tesseract.exe``.

    Returns:
        ``(suggested file name, path in scratch)`` for each output file.

    Raises:
        ValueError: Unknown mode, no files, or an unusable input file.
        RuntimeError: OCR is missing (in a flatten mode) or a conversion step
            failed.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown conversion mode: {mode}")
    if not files:
        raise ValueError("Choose at least one file.")
    scratch.mkdir(parents=True, exist_ok=True)
    # Fail fast, before any slow PowerPoint rendering, if OCR will be needed
    # but isn't installed.
    if mode != MERGE:
        require_tesseract(engine)
    prepped: list[Path] = []  # Each input as a PDF (used by Merge).
    flattened: list[Path] = []  # Each input flattened (used by both flatten modes).
    for idx, item in enumerate(files, 1):
        source = Path(item)
        report(f"Preparing {idx} / {len(files)}: {source.name}")
        work = scratch / f"item_{idx:03d}"
        pdf = prepare_pdf(source, work, report)
        check_pdf(pdf)
        prepped.append(pdf)
        if mode != MERGE:
            rendered = work / "flattened_searchable.pdf"
            flatten_searchable(pdf, rendered, work / "ocr_work", report, engine=engine)
            flattened.append(rendered)

    if mode == FLATTEN:
        return [
            (f"{Path(original).stem} - Flattened Searchable.pdf", result)
            for original, result in zip(files, flattened)
        ]

    # Both merge modes produce a single file named after the first input.
    final = scratch / "combined.pdf"
    merge_pdfs(flattened if mode == FLATTEN_MERGE else prepped, final, report)
    stem = Path(files[0]).stem
    prefix = f"{stem} + {len(files) - 1} more" if len(files) > 1 else stem
    suffix = "Flattened Searchable Merged.pdf" if mode == FLATTEN_MERGE else "Merged.pdf"
    return [(f"{prefix} - {suffix}", final)]


def run_action(
    action,
    settings,
    data,
    *,
    scratch: Path,
    progress=None,
    cancel=None,
):
    """Run one conversion job: the single entry point for every action.

    Interface stub, replaced by the full implementation. Contract:

    Args:
        action (Action): What to do.
        settings (ActionSettings): How to do it; each action reads only its fields.
        data (ActionData): The input files, in the user's order.
        scratch (Path): Empty working folder; outputs are left here.
        progress (Progress | None): Receives ProgressEvent updates.
        cancel (CancelToken | None): Lets the caller stop the job.

    Returns:
        JobResult: Output files (in scratch) and non-fatal warnings.

    Raises:
        ConversionError: A fatal, user-explainable problem (``.issue``).
        Cancelled: The job was cancelled.
        Exception: Anything else is a bug; the caller reports it as unexpected.
    """
    raise NotImplementedError
