"""Rendering PowerPoint files (PPT/PPTX) to PDF via Microsoft PowerPoint or LibreOffice."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .common import Progress
from .tools import find_libreoffice, run_command


def libreoffice_convert(source: Path, dest_dir: Path, filter_spec: str, extension: str) -> Path:
    office = find_libreoffice()
    if office is None:
        raise RuntimeError("PowerPoint conversion requires Microsoft PowerPoint or LibreOffice.")
    with tempfile.TemporaryDirectory(prefix="slidestitch-lo-") as profile:
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
    target = dest_dir / f"{source.stem}{extension}"
    if proc.returncode != 0 or not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(
            f"LibreOffice conversion failed: {(proc.stderr or proc.stdout).strip()[:350]}"
        )
    return target


def powerpoint_to_pdf(source: Path, dest_dir: Path, report: Progress) -> Path:
    """Prefer PowerPoint rendering on Windows; use LibreOffice as fallback."""
    output = dest_dir / f"{source.stem}.pdf"
    if os.name == "nt":
        try:
            import pythoncom
            import win32com.client

            pythoncom.CoInitialize()
            app = None
            pres = None
            try:
                report("Rendering PowerPoint slides...")
                app = win32com.client.DispatchEx("PowerPoint.Application")
                pres = app.Presentations.Open(str(source.resolve()), True, False, False)
                pres.SaveAs(str(output.resolve()), 32)
                if output.is_file() and output.stat().st_size:
                    return output
            finally:
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
            report("Using LibreOffice to render the slides...")
    return libreoffice_convert(source, dest_dir, "pdf:impress_pdf_Export", ".pdf")
