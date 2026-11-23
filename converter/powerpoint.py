"""Rendering PowerPoint files (PPT/PPTX) to PDF.

Two renderers, tried in this order:

1. **Microsoft PowerPoint** (optional, Windows only, via
   ``platforms.export_slides_with_powerpoint``): the most faithful rendering.
2. **LibreOffice** (cross-platform): always the fallback, and the only
   renderer on Linux.

If PowerPoint fails and LibreOffice succeeds, the job continues with a
``POWERPOINT_FALLBACK`` warning that carries PowerPoint's real error. If both
fail, the job stops with ``POWERPOINT_CONVERSION_FAILED`` and both errors.

Why the input is copied first: files downloaded from the internet or email
carry a Windows "Mark of the Web" tag (a hidden ``Zone.Identifier`` stream).
PowerPoint opens such files in Protected View, which hidden automation can't
use, so the export fails and every such file fell back to LibreOffice. A plain
byte-for-byte copy into the scratch folder doesn't carry the tag. The copy also
guarantees the original is never touched by either renderer.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import platforms
from .common import Stage
from .context import JobContext
from .issues import (
    ConversionError,
    powerpoint_failed,
    powerpoint_fallback,
    slide_renderer_missing,
)
from .tools import find_libreoffice, run_command

log = logging.getLogger(__name__)

# Seconds a renderer may take for one presentation before it is stopped.
POWERPOINT_TIMEOUT_SEC = 300
LIBREOFFICE_TIMEOUT_SEC = 300


class LibreOfficeError(RuntimeError):
    """LibreOffice failed; the message holds its output."""


def copy_for_rendering(source: Path, folder: Path) -> Path:
    """Copy ``source`` into ``folder`` as plain bytes, keeping its file name.

    ``shutil.copyfileobj`` copies only the file's contents, never Windows
    alternate data streams such as the Mark-of-the-Web ``Zone.Identifier``.
    """
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / source.name
    with open(source, "rb") as src, open(target, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    return target


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
    """Render a PowerPoint file to PDF, one page per slide.

    Args:
        source: The ``.ppt`` or ``.pptx`` file. It is never modified.
        dest_dir: This file's scratch folder; ``<stem>.pdf`` is written here.
        ctx: Job context (progress, cancel, warnings).
        file_label: Input file name, for messages.

    Returns:
        Path to the rendered PDF.

    Raises:
        ConversionError: Both renderers failed (``POWERPOINT_CONVERSION_FAILED``)
            or neither is installed (``SLIDE_RENDERER_MISSING``).
        Cancelled: The user cancelled.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    local = copy_for_rendering(source, dest_dir / "input")
    output = dest_dir / f"{source.stem}.pdf"
    powerpoint_error: str | None = None

    exporter = platforms.export_slides_with_powerpoint
    if exporter is not None and platforms.powerpoint_installed():
        ctx.report(Stage.RENDERING_SLIDES, f"Converting slides with PowerPoint: {file_label}")
        try:
            exporter(local, output, POWERPOINT_TIMEOUT_SEC, ctx.cancel)
            return output
        except Exception as exc:
            # Cancelled is an Exception too: a user cancel must stop the job,
            # not fall back to LibreOffice.
            if ctx.cancel.cancelled:
                raise
            powerpoint_error = str(exc)
            log.warning("PowerPoint couldn't convert %s; trying LibreOffice.", file_label)
            log.debug("PowerPoint error for %s:\n%s", file_label, powerpoint_error)

    ctx.check_cancel()
    ctx.report(Stage.RENDERING_SLIDES, f"Converting slides with LibreOffice: {file_label}")
    try:
        result = libreoffice_convert(local, dest_dir, "pdf:impress_pdf_Export", ".pdf", ctx)
    except ConversionError as exc:
        if powerpoint_error is None:
            raise  # LibreOffice missing and PowerPoint not available: renderer missing.
        details = f"PowerPoint: {powerpoint_error}\n\nLibreOffice: not installed."
        raise ConversionError(powerpoint_failed(file_label, details)) from exc
    except LibreOfficeError as exc:
        details = f"LibreOffice: {exc}"
        if powerpoint_error is not None:
            details = f"PowerPoint: {powerpoint_error}\n\n{details}"
        raise ConversionError(powerpoint_failed(file_label, details)) from exc

    if powerpoint_error is not None:
        ctx.warn(powerpoint_fallback(file_label, powerpoint_error))
    return result
