"""Describing input files for the shared file list."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pymupdf

from ..core.types import IMAGE_EXTENSIONS

log = logging.getLogger(__name__)


class FileKind(StrEnum):
    """Input file type; must match ``FileKind`` in ``frontend/src/api/types.ts``."""

    PDF = "pdf"
    PPTX = "pptx"
    PPT = "ppt"
    IMAGE = "image"


@dataclass
class FileInfo:
    """What the file list shows about one input file."""

    path: Path
    name: str
    kind: FileKind
    size_bytes: int
    page_count: int | None  # PDFs only; None for PowerPoints, images and unreadable PDFs.


def file_kind(path: Path) -> FileKind | None:
    """Classify a file by its extension, or return ``None`` if it isn't supported."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return FileKind.PDF
    if suffix == ".pptx":
        return FileKind.PPTX
    if suffix == ".ppt":
        return FileKind.PPT
    if suffix in IMAGE_EXTENSIONS:
        return FileKind.IMAGE
    return None


def inspect_file(path: Path) -> FileInfo | None:
    """Describe a file for the file list, or return ``None`` if it can't be used.

    Unsupported types, folders and missing files return ``None``. A PDF that
    can't be opened (or needs a password) still gets an entry with
    ``page_count=None``, so the user sees it and gets a clear error on Convert.

    Args:
        path: File to inspect.
    """
    path = Path(path)
    kind = file_kind(path)
    if kind is None or not path.is_file():
        return None
    page_count = None
    if kind is FileKind.PDF:
        try:
            with pymupdf.open(str(path)) as doc:
                page_count = None if doc.needs_pass else len(doc)
        except Exception as exc:  # Damaged files are reported on Convert, not here.
            log.debug("Couldn't count pages of %s: %s", path, exc)
    return FileInfo(path, path.name, kind, path.stat().st_size, page_count)
