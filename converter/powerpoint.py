"""Rendering PowerPoint files (PPT/PPTX) to PDF via Microsoft PowerPoint or LibreOffice."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .common import Progress
from .tools import find_libreoffice, run_command


def libreoffice_convert(source: Path, dest_dir: Path, filter_spec: str, extension: str) -> Path:
    """Convert a document with LibreOffice running headless (no window).

    Args:
        source: The file to convert.
        dest_dir: Folder where LibreOffice writes the result.
        filter_spec: LibreOffice's ``--convert-to`` value, e.g.
            ``"pdf:impress_pdf_Export"`` for slides to PDF.
        extension: Extension of the expected output, e.g. ``".pdf"``. Used to
            find the file LibreOffice wrote (it is named after the source).

    Returns:
        Path to the converted file, ``dest_dir / (source stem + extension)``.

    Raises:
        RuntimeError: LibreOffice isn't installed, or the conversion failed or
            produced an empty file. The message includes LibreOffice's output.
    """
    office = find_libreoffice()
    if office is None:
        raise RuntimeError("PowerPoint conversion requires Microsoft PowerPoint or LibreOffice.")
    # A throwaway LibreOffice profile for this one run. Without it, if the user
    # already has LibreOffice open, the command hands the job to that running
    # instance and exits without converting anything.
    with tempfile.TemporaryDirectory(prefix="pdf-manager-lo-") as profile:
        proc = run_command(
            [
                str(office),
                f"-env:UserInstallation={Path(profile).as_uri()}",
                "--headless",
                "--convert-to",
                filter_spec,
                "--outdir",
                str(dest_dir),
                str(source),
            ],
            timeout=300,
        )
    # LibreOffice often exits with code 0 even when it failed, so also check
    # that the output file exists and isn't empty.
    target = dest_dir / f"{source.stem}{extension}"
    if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(
            f"LibreOffice conversion failed: {(proc.stderr or proc.stdout).strip()[:350]}"
        )
    return target


def powerpoint_to_pdf(source: Path, dest_dir: Path, report: Progress) -> Path:
    """Render a PowerPoint file to PDF, one page per slide.

    On Windows, Microsoft PowerPoint is tried first because it renders slides
    most faithfully. It is driven through COM automation (pywin32): the file is
    opened read-only in a hidden window and exported with "Save As PDF". If
    PowerPoint is missing or anything fails, LibreOffice is used instead. On
    other systems only LibreOffice is used.

    Args:
        source: The ``.ppt`` or ``.pptx`` file. It is never modified.
        dest_dir: Folder to write ``<source stem>.pdf`` into.
        report: Progress callback for status messages.

    Returns:
        Path to the rendered PDF.

    Raises:
        RuntimeError: Both PowerPoint and LibreOffice failed (or are missing).

    Known issues:
        * PowerPoint runs as a single instance, so ``DispatchEx`` may attach to
          a PowerPoint the user already has open, and ``app.Quit()`` below can
          then close it.
        * The PowerPoint error is discarded; only the LibreOffice error is
          reported if the fallback also fails.
    """
    output = dest_dir / f"{source.stem}.pdf"
    if os.name == "nt":
        try:
            import pythoncom
            import win32com.client

            # COM must be initialised on each thread that uses it; conversions
            # run on a background worker thread.
            pythoncom.CoInitialize()
            app = None
            pres = None
            try:
                report("Rendering PowerPoint slides...")
                app = win32com.client.DispatchEx("PowerPoint.Application")
                # Open(FileName, ReadOnly=True, Untitled=False, WithWindow=False)
                pres = app.Presentations.Open(str(source.resolve()), True, False, False)
                pres.SaveAs(str(output.resolve()), 32)  # 32 = ppSaveAsPDF
                if output.is_file() and output.stat().st_size:
                    return output
                # An empty or missing PDF falls through to LibreOffice below.
            finally:
                # Always close the file and PowerPoint, even after an error,
                # so no hidden PowerPoint process is left running.
                if pres is not None:
                    try:
                        pres.Close()
                    except Exception:
                        pass
                if app is not None:
                    try:
                        app.Quit()
                    except Exception:
                        pass
                pythoncom.CoUninitialize()
        except Exception:
            # Covers pywin32 not installed, PowerPoint not installed, and any
            # error while opening or exporting.
            report("Using LibreOffice to render the slides...")
    return libreoffice_convert(source, dest_dir, "pdf:impress_pdf_Export", ".pdf")
