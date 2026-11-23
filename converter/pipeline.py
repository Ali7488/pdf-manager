"""Orchestration: prepare each input as a PDF, validate it, then flatten and/or merge."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import fitz

from .common import ALLOWED, FLATTEN, FLATTEN_MERGE, MERGE, MODES, Progress
from .flatten import flatten_searchable
from .merge import merge_pdfs
from .notes import notes_pdf, speaker_notes
from .powerpoint import powerpoint_to_pdf
from .tools import require_tesseract


def prepare_pdf(source: Path, work: Path, report: Progress) -> Path:
    """Convert PPT/PPTX and attach notes appendix. Keep PDFs unchanged for merge."""
    source = source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in ALLOWED:
        raise ValueError(f"Unsupported input: {source.name}. Choose PDF, PPTX or PPT.")
    work.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() == ".pdf":
        return source
    slide_pdf = powerpoint_to_pdf(source, work, report)
    notes = speaker_notes(source, work, report)
    if not notes:
        return slide_pdf
    report(f"Appending speaker notes from {len(notes)} slides...")
    appendix = work / "speaker_notes.pdf"
    notes_pdf(notes, appendix)
    combined = work / "slides_with_notes.pdf"
    with fitz.open(str(slide_pdf)) as presentation, fitz.open(str(appendix)) as notes_doc:
        with fitz.open() as result:
            result.insert_pdf(presentation, links=True, annots=True)
            result.insert_pdf(notes_doc, links=True, annots=True)
            result.save(str(combined), garbage=4, deflate=True)
    return combined


def check_pdf(source: Path) -> None:
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
    """Stage all results without writing to users' chosen output directory.

    Flatten -> one image-only+OCR PDF per input.
    Flatten & Merge -> one merged image+OCR PDF, order of input list.
    Merge -> one combined PDF, retaining original PDF text and annotations.
    """
    if mode not in MODES:
        raise ValueError(f"Unknown conversion mode: {mode}")
    if not files:
        raise ValueError("Choose at least one file.")
    scratch.mkdir(parents=True, exist_ok=True)
    if mode != MERGE:
        require_tesseract(engine)
    prepped: list[Path] = []
    flattened: list[Path] = []
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

    final = scratch / "combined.pdf"
    merge_pdfs(flattened if mode == FLATTEN_MERGE else prepped, final, report)
    stem = Path(files[0]).stem
    prefix = f"{stem} + {len(files) - 1} more" if len(files) > 1 else stem
    suffix = "Flattened Searchable Merged.pdf" if mode == FLATTEN_MERGE else "Merged.pdf"
    return [(f"{prefix} - {suffix}", final)]
