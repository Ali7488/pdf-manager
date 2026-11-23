"""SlideStitch: local PDF/PPT/PPTX conversion, image flattening, OCR and merge.

The original inputs are never modified.  Results are staged in a temporary folder
and only copied to the chosen destination after all requested conversion is done.
"""

from __future__ import annotations

import html
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

import fitz
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

DPI = 200
ALLOWED = {".pdf", ".pptx", ".ppt"}
FLATTEN = "flatten"
FLATTEN_MERGE = "flatten_merge"
MERGE = "merge"
MODES = {FLATTEN, FLATTEN_MERGE, MERGE}
Progress = Callable[[str], None]


def _run(cmd: Sequence[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    options = {"capture_output": True, "text": True, "timeout": timeout}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(list(map(str, cmd)), **options)


def find_tesseract(configured: str | Path | None = None) -> Path | None:
    """Find Tesseract in PATH, known Windows folders and installer registry entries.

    Installed WinGet packages can be per-user and may not be in PATH in an
    already-running session, so path detection alone was unreliable in v1.0.
    """
    possible: list[Path] = []
    if configured:
        possible.append(Path(configured).expanduser())
    located = shutil.which("tesseract")
    if located:
        possible.append(Path(located))
    if os.name == "nt":
        roots = [
            os.getenv("ProgramFiles"),
            os.getenv("ProgramFiles(x86)"),
            os.getenv("LOCALAPPDATA"),
        ]
        for root in filter(None, roots):
            base = Path(root)
            possible.extend(
                (
                    base / "Tesseract-OCR" / "tesseract.exe",
                    base / "Programs" / "Tesseract-OCR" / "tesseract.exe",
                )
            )
        try:
            import winreg

            hives = (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER)
            keys = (
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tesseract.exe",
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
                r"SOFTWARE\Tesseract-OCR",
            )
            for hive in hives:
                for keyname in keys:
                    try:
                        with winreg.OpenKey(hive, keyname) as key:
                            for value_name in ("InstallLocation", "Path", "DisplayIcon", ""):
                                try:
                                    value, _ = winreg.QueryValueEx(key, value_name)
                                except OSError:
                                    continue
                                if not isinstance(value, str) or not value.strip():
                                    continue
                                cleaned = os.path.expandvars(
                                    value.strip().strip('"').split('",')[0]
                                )
                                path = Path(cleaned)
                                possible.append(
                                    path
                                    if path.suffix.lower() == ".exe"
                                    else path / "tesseract.exe"
                                )
                    except OSError:
                        continue
        except ImportError:
            pass
    seen = set()
    for path in possible:
        normalized = str(path).casefold()
        if normalized not in seen and path.is_file():
            return path
        seen.add(normalized)
    return None


def require_tesseract(configured: str | Path | None = None) -> Path:
    engine = find_tesseract(configured)
    if engine is None:
        raise RuntimeError(
            "OCR engine missing. Click 'Install OCR' or 'Find OCR' in the dashboard, then retry."
        )
    return engine


def find_libreoffice() -> Path | None:
    for name in ("soffice", "libreoffice"):
        value = shutil.which(name)
        if value:
            return Path(value)
    if os.name == "nt":
        for root in (
            os.getenv("ProgramFiles"),
            os.getenv("ProgramFiles(x86)"),
            os.getenv("LOCALAPPDATA"),
        ):
            if root:
                for sub in (
                    "LibreOffice/program/soffice.exe",
                    "Programs/LibreOffice/program/soffice.exe",
                ):
                    value = Path(root) / sub
                    if value.is_file():
                        return value
    return None


def _lo_convert(source: Path, dest_dir: Path, filter_spec: str, extension: str) -> Path:
    office = find_libreoffice()
    if office is None:
        raise RuntimeError("PowerPoint conversion requires Microsoft PowerPoint or LibreOffice.")
    with tempfile.TemporaryDirectory(prefix="slidestitch-lo-") as profile:
        proc = _run(
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
    return _lo_convert(source, dest_dir, "pdf:impress_pdf_Export", ".pdf")


def _pptx_notes(source: Path) -> list[tuple[int, str]]:
    from pptx import Presentation

    pres = Presentation(str(source))
    notes: list[tuple[int, str]] = []
    for number, slide in enumerate(pres.slides, 1):
        if not slide.has_notes_slide:
            continue
        frame = slide.notes_slide.notes_text_frame
        text = frame.text.strip() if frame is not None else ""
        if text and text not in {str(number), f"Slide {number}"}:
            notes.append((number, text))
    return notes


def speaker_notes(source: Path, work: Path, report: Progress) -> list[tuple[int, str]]:
    if source.suffix.lower() == ".pptx":
        try:
            return _pptx_notes(source)
        except Exception as exc:
            raise RuntimeError(f"Speaker notes could not be extracted: {exc}") from exc
    if source.suffix.lower() == ".ppt":
        # Legacy PPT is converted temporarily to PPTX to recover author notes.
        try:
            report("Checking speaker notes in older PowerPoint...")
            converted = _lo_convert(source, work, "pptx:Impress MS PowerPoint 2007 XML", ".pptx")
            return _pptx_notes(converted)
        except Exception as exc:
            report(f"Warning: could not extract notes from legacy PPT ({type(exc).__name__}).")
            return []
    return []


def notes_pdf(notes: list[tuple[int, str]], target: Path) -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "NoteTitle",
        parent=styles["Heading1"],
        fontSize=17,
        leading=22,
        alignment=TA_CENTER,
        spaceAfter=14,
    )
    heading = ParagraphStyle(
        "SlideHeading",
        parent=styles["Heading2"],
        fontSize=12,
        leading=16,
        spaceBefore=12,
        spaceAfter=6,
    )
    body = ParagraphStyle(
        "NoteBody",
        parent=styles["BodyText"],
        fontSize=10.5,
        leading=15,
        spaceAfter=12,
        textColor=colors.black,
    )
    story = [
        Paragraph("Speaker Notes Appendix", title),
        Paragraph("Notes are labeled with their original slide number.", body),
        Spacer(1, 10),
    ]
    for slide_number, content in notes:
        story.append(Paragraph(f"Slide {slide_number}", heading))
        safe = html.escape(content).replace("\n", "<br/>")
        for para in safe.split("<br/><br/>"):
            story.append(Paragraph(para or " ", body))
    doc = SimpleDocTemplate(
        str(target),
        pagesize=(8.5 * inch, 11 * inch),
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.7 * inch,
    )
    doc.build(story)


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


def flatten_searchable(
    source: Path,
    target: Path,
    work: Path,
    report: Progress,
    engine: str | Path | None = None,
    dpi: int = DPI,
) -> None:
    """Rasterize all visible content, then add Tesseract English OCR text per page."""
    tess = require_tesseract(engine)
    work.mkdir(parents=True, exist_ok=True)
    with fitz.open(str(source)) as original:
        if original.needs_pass:
            raise ValueError("Password-protected PDFs are not supported.")
        if len(original) == 0:
            raise ValueError("PDF has no pages.")
        with fitz.open() as finished:
            for page_no, page in enumerate(original, 1):
                report(f"Flattening and OCR: page {page_no} / {len(original)}")
                pix = page.get_pixmap(
                    matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=fitz.csRGB, alpha=False
                )
                img = work / f"page_{page_no:05d}.png"
                pix.save(str(img))
                ocr_base = work / f"ocr_{page_no:05d}"
                proc = _run(
                    [str(tess), str(img), str(ocr_base), "-l", "eng", "--dpi", str(dpi), "pdf"],
                    timeout=300,
                )
                if proc.returncode:
                    raise RuntimeError(f"OCR failed on page {page_no}: {proc.stderr.strip()[:400]}")
                ocr_pdf = Path(str(ocr_base) + ".pdf")
                if not ocr_pdf.is_file():
                    raise RuntimeError(f"OCR did not generate a PDF for page {page_no}.")
                with fitz.open(str(ocr_pdf)) as scanned:
                    output = finished.new_page(width=page.rect.width, height=page.rect.height)
                    output.show_pdf_page(output.rect, scanned, 0, keep_proportion=False)
                # Intentionally keep page images and OCR PDFs in the dedicated
                # scratch folder until the *entire* finished document is saved
                # and closed. Immediate unlink can raise WinError 32 on Windows
                # because the OCR PDF may still be locked by a PDF renderer or
                # real-time scanner. The app cleans scratch only after final
                # results have been copied to the user-selected save folder.
            finished.save(str(target), garbage=4, deflate=True)

    with fitz.open(str(target)) as check:
        if not any(page.get_images() for page in check):
            raise RuntimeError("Flattening failed: no image-backed pages found.")


def merge_pdfs(sources: Sequence[Path], target: Path, report: Progress) -> None:
    if not sources:
        raise ValueError("No PDF inputs available to merge.")
    with fitz.open() as output:
        expected = 0
        for i, source in enumerate(sources, 1):
            report(f"Merging {i} / {len(sources)}: {source.name}")
            with fitz.open(str(source)) as part:
                if part.needs_pass:
                    raise ValueError(f"Password-protected PDF: {source.name}")
                if len(part) == 0:
                    raise ValueError(f"Empty PDF: {source.name}")
                expected += len(part)
                output.insert_pdf(part, links=True, annots=True)
        output.save(str(target), garbage=4, deflate=True)
    with fitz.open(str(target)) as result:
        if len(result) != expected:
            raise RuntimeError("Merge verification failed: page counts do not match.")


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


def safe_destination(folder: Path, proposed: str, reserved: set[str] | None = None) -> Path:
    """Never overwrite existing files or collide with another result in this batch."""
    reserved = set() if reserved is None else reserved
    requested = Path(proposed)
    for i in range(1, 100000):
        filename = f"{requested.stem}{f' ({i})' if i > 1 else ''}{requested.suffix}"
        target = folder / filename
        if not target.exists() and filename.casefold() not in reserved:
            reserved.add(filename.casefold())
            return target
    raise RuntimeError("Could not choose a unique output filename.")
