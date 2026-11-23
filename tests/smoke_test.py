"""End-to-end offline conversion tests (run where LibreOffice and Tesseract are installed)."""
from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

import fitz
from pptx import Presentation
from reportlab.pdfgen.canvas import Canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from converter import (FLATTEN, FLATTEN_MERGE, MERGE, find_tesseract,
                       process_files, safe_destination)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_pdf(path):
    c = Canvas(str(path), pagesize=(480, 300))
    c.setFont("Helvetica", 24)
    c.drawString(30, 220, "Quarterly summary document")
    c.save()


def make_pptx(path):
    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    tb = slide.shapes.add_textbox(1_000_000, 1_000_000, 7_000_000, 1_000_000)
    tb.text_frame.text = "Project overview and timeline"
    slide.notes_slide.notes_text_frame.text = "Presenter notes: review the timeline first."
    pres.save(str(path))


def inspect(path):
    with fitz.open(str(path)) as doc:
        return len(doc), [p.get_text() for p in doc], [bool(p.get_images()) for p in doc]


def main():
    assert find_tesseract(), "Tesseract is required for the flatten tests."
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        pdf = root / "Document A.pdf"
        pptx = root / "Document B.pptx"
        make_pdf(pdf)
        make_pptx(pptx)
        originals = {p: sha(p) for p in (pdf, pptx)}
        report = lambda message: None

        each = process_files([pdf, pptx], FLATTEN, root / "work1", report)
        assert len(each) == 2
        n1, words1, images1 = inspect(each[0][1])
        n2, words2, images2 = inspect(each[1][1])
        assert n1 == 1 and n2 == 2, (n1, n2)
        assert all(images1) and all(images2)
        assert "Quarterly" in " ".join(words1)
        assert "Presenter notes" in " ".join(words2), words2

        combined = process_files([pptx, pdf], FLATTEN_MERGE, root / "work2", report)
        assert len(combined) == 1
        pages, texts, images = inspect(combined[0][1])
        assert pages == 3 and all(images)
        assert "Presenter notes" in " ".join(texts)
        assert "Quarterly" in texts[-1]

        merged = process_files([pdf, pptx], MERGE, root / "work3", report)
        assert len(merged) == 1
        pages, texts, images = inspect(merged[0][1])
        assert pages == 3
        assert not images[0], "Merge should not rasterize the source PDF."
        assert "Quarterly" in texts[0]
        assert "Presenter notes" in texts[-1]

        safe1 = safe_destination(root, "Sample.pdf")
        safe1.write_text("existing", encoding="utf-8")
        assert safe_destination(root, "Sample.pdf").name == "Sample (2).pdf"
        assert all(sha(p) == digest for p, digest in originals.items()), "Inputs changed!"
        print("PASS: flatten (separate), flatten+merge, merge, notes, OCR, order, overwrite safety, source preservation")


if __name__ == "__main__":
    main()
