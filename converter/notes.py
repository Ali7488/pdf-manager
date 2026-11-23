"""Extracting PowerPoint speaker notes and rendering them as a PDF appendix."""

from __future__ import annotations

import html
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from .common import Progress
from .powerpoint import libreoffice_convert


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
            converted = libreoffice_convert(
                source, work, "pptx:Impress MS PowerPoint 2007 XML", ".pptx"
            )
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
