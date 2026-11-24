"""Rendering PowerPoint files (PPT/PPTX) to PDF with LibreOffice Impress.

**One renderer everywhere (decision C17).** LibreOffice Impress, running
headless with a throwaway profile, converts every presentation on every
supported operating system, whether it was dropped, uploaded or picked with
Add files. Microsoft PowerPoint is never automated. Macros never run: a
headless conversion doesn't execute document macros under LibreOffice's
default macro security. For decks that need a closer visual match, the
documented route is to export them to PDF in PowerPoint and add that PDF.

If LibreOffice isn't installed, the job stops with ``SLIDE_RENDERER_MISSING``
(the Convert window's tool check normally catches that first); if it fails,
with ``POWERPOINT_CONVERSION_FAILED`` and LibreOffice's output.

The input is always copied into scratch first (keeping any Windows
Mark-of-the-Web, which is never stripped, audit R1), so the original is never
touched, and LibreOffice writes into a fresh, empty folder, so a leftover file
can never be mistaken for its result (audit R3).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import platforms
from ..core.context import JobContext
from ..core.issues import ConversionError, powerpoint_failed, slide_renderer_missing
from ..core.types import Stage
from ..tools import find_libreoffice, run_command

log = logging.getLogger(__name__)

# Seconds LibreOffice may take for one presentation before it is stopped.
LIBREOFFICE_TIMEOUT_SEC = 300


class LibreOfficeError(RuntimeError):
    """LibreOffice failed; the message holds its output."""


def copy_for_rendering(source: Path, folder: Path) -> Path:
    """Copy ``source`` into ``folder``, keeping its file name **and** its provenance.

    The Windows Mark-of-the-Web is copied too (``platforms.copy_with_provenance``),
    so the renderer sees the copy exactly as trusted as the original (audit R1).
    """
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    platforms.copy_with_provenance(source, target)
    return target


def _fresh_folder(folder: Path) -> Path:
    """Return ``folder``, emptied first if it exists, so no leftover can pose as output."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    return folder


def libreoffice_convert(
    source: Path,
    dest_dir: Path,
    filter_spec: str,
    extension: str,
    ctx: JobContext | None = None,
    timeout: float = LIBREOFFICE_TIMEOUT_SEC,
) -> Path:
    """Convert a document with LibreOffice running headless (no window).

    Args:
        source: The file to convert.
        dest_dir: Folder where LibreOffice writes the result.
        filter_spec: LibreOffice's ``--convert-to`` value, e.g.
            ``"pdf:impress_pdf_Export"`` for slides to PDF.
        extension: Extension of the expected output, e.g. ``".pdf"``. LibreOffice
            names the output after the source, so this locates it.
        ctx: Job context, so Cancel can stop LibreOffice.
        timeout: Seconds before LibreOffice is stopped.

    Returns:
        Path to the converted file, ``dest_dir / (source stem + extension)``.

    Raises:
        ConversionError: LibreOffice isn't installed (``SLIDE_RENDERER_MISSING``).
        LibreOfficeError: The conversion failed, timed out or wrote nothing.
        Cancelled: The user cancelled.
    """
    office = find_libreoffice()
    if office is None:
        raise ConversionError(slide_renderer_missing())
    cancel = ctx.cancel if ctx else None
    # A throwaway LibreOffice profile for this one run. Without it, if the user
    # already has LibreOffice open, the command hands the job to that running
    # instance and exits without converting anything.
    with tempfile.TemporaryDirectory(prefix="pdf-manager-lo-") as profile:
        try:
            proc = run_command(
                [
                    office,
                    f"-env:UserInstallation={Path(profile).as_uri()}",
                    "--headless",
                    "--convert-to",
                    filter_spec,
                    "--outdir",
                    dest_dir,
                    source,
                ],
                timeout=timeout,
                cancel=cancel,
            )
        except subprocess.TimeoutExpired:
            raise LibreOfficeError(f"LibreOffice didn't finish within {int(timeout)} seconds.")
    # LibreOffice often exits with code 0 even when it failed, so also check
    # that the output file exists and isn't empty.
    target = dest_dir / f"{source.stem}{extension}"
    if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        output = (proc.stderr or proc.stdout or "").strip()
        raise LibreOfficeError(
            f"LibreOffice exit code {proc.returncode}; output: {output or '(none)'}"
        )
    return target


def render_slides(source: Path, dest_dir: Path, ctx: JobContext, file_label: str) -> Path:
    """Render a PowerPoint file to PDF with LibreOffice Impress, one page per slide.

    Args:
        source: The ``.ppt`` or ``.pptx`` file. It is never modified.
        dest_dir: This file's scratch folder; the PDF is written under it.
        ctx: Job context (progress, cancel).
        file_label: Input file name, for messages.

    Returns:
        Path to the rendered PDF.

    Raises:
        ConversionError: LibreOffice isn't installed (``SLIDE_RENDERER_MISSING``)
            or couldn't convert the file (``POWERPOINT_CONVERSION_FAILED``).
        Cancelled: The user cancelled.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = copy_for_rendering(source, dest_dir / "input")
    ctx.check_cancel()
    ctx.report(Stage.RENDERING_SLIDES, f"Converting slides with LibreOffice: {file_label}")
    try:
        return libreoffice_convert(
            local, _fresh_folder(dest_dir / "libreoffice"), "pdf:impress_pdf_Export", ".pdf", ctx
        )
    except LibreOfficeError as exc:
        raise ConversionError(powerpoint_failed(file_label, f"LibreOffice: {exc}")) from exc
