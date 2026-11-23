"""Generate synthetic test documents for every PDF Manager function (Windows and Linux).

All content is neutral sample text created here; no real documents are used.

    uv run scripts/make_samples.py            # writes into ./samples (Git-ignored)
    uv run scripts/make_samples.py some/dir   # or anywhere else

Each file's purpose is listed in ``SAMPLES`` and written to ``samples/README.txt``.
The legacy ``.ppt`` is only made when LibreOffice is installed. On Windows, a
"downloaded" copy of the slides is also made (it carries the Mark-of-the-Web, to
test the untrusted-file rule).
"""

from __future__ import annotations

import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

# File name → what to use it for. Kept in one place so README.txt matches the files.
SAMPLES: dict[str, str] = {
    "01-text-report.pdf": "3 pages of real text, bookmarks and a link. Flatten, Merge, Split.",
    "02-scanned-pages.pdf": "2 pages that are only images of text (no text layer). OCR.",
    "03-rotated-scan.pdf": "An image-only page rotated 90 degrees. OCR alignment.",
    "04-mixed-text-and-scan.pdf": "Page 1 real text, page 2 image only. OCR only adds to page 2.",
    "05-slides.pptx": "3 slides with presenter notes (notes must NOT appear). PowerPoint.",
    "06-slides-legacy.ppt": "Old PowerPoint format (only made if LibreOffice is installed).",
    "07-photo-portrait.jpg": "Photo stored sideways with an EXIF rotation tag. Images to PDF.",
    "08-diagram.png": "A PNG image with text. Images to PDF (+ OCR).",
    "09-image-heavy.pdf": "Large high-resolution images. Compress (compare levels).",
    "10-password-protected.pdf": "Needs a password (it's 'test'). Must give a clear error.",
    "11-damaged.pdf": "A truncated, broken PDF. Must give a clear error.",
    "12-ملف-unicode-name.pdf": "Non-Latin file name. Merge with --contents (title rendering).",
    "13-long-document.pdf": "40 numbered pages. Split by ranges / every N / per page.",
    "14-downloaded-slides.pptx": "Windows only: carries the Mark-of-the-Web (ZoneId=3).",
}

PAGE = (595, 842)  # A4 portrait, in points.
SLIDE = (720, 405)  # 16:9 slide, in points.


def _text_page(doc: pymupdf.Document, lines: list[str], size=PAGE) -> pymupdf.Page:
    """Add a page with each line of real, extractable text."""
    page = doc.new_page(width=size[0], height=size[1])
    for n, line in enumerate(lines):
        page.insert_text((60, 100 + n * 36), line, fontsize=22 if n == 0 else 14)
    return page


def _image_of_text(lines: list[str], size=PAGE, dpi: int = 150) -> bytes:
    """PNG bytes of a page showing ``lines`` (an image, like a scan)."""
    with pymupdf.open() as tmp:
        _text_page(tmp, lines, size)
        return tmp[0].get_pixmap(dpi=dpi).tobytes("png")


def text_report(path: Path) -> None:
    with pymupdf.open() as doc:
        for n in range(1, 4):
            _text_page(
                doc,
                [
                    f"Sample report, section {n}",
                    "Quarterly summary of the project.",
                    "This text is real and can be searched and copied.",
                ],
            )
        doc[0].insert_link(
            {
                "kind": pymupdf.LINK_GOTO,
                "from": pymupdf.Rect(60, 80, 400, 105),
                "page": 2,
                "to": pymupdf.Point(0, 0),
            }
        )
        doc.set_toc([[1, "Section 1", 1], [2, "Details", 2], [1, "Section 3", 3]])
        doc.save(str(path))


def scanned(path: Path, pages: list[list[str]], rotation: int = 0) -> None:
    with pymupdf.open() as doc:
        for lines in pages:
            page = doc.new_page(width=PAGE[0], height=PAGE[1])
            page.insert_image(page.rect, stream=_image_of_text(lines))
            if rotation:
                page.set_rotation(rotation)
        doc.save(str(path))


def mixed(path: Path) -> None:
    with pymupdf.open() as doc:
        _text_page(doc, ["Page with real text", "Already searchable."])
        page = doc.new_page(width=PAGE[0], height=PAGE[1])
        page.insert_image(page.rect, stream=_image_of_text(["Scanned second page", "Needs OCR."]))
        doc.save(str(path))


def slides(path: Path) -> None:
    from pptx import Presentation  # Dev dependency.
    from pptx.util import Pt

    pres = Presentation()
    for n in range(1, 4):
        slide = pres.slides.add_slide(pres.slide_layouts[1])
        slide.shapes.title.text = f"Sample slide {n}"
        slide.placeholders[1].text_frame.text = "Overview of the project timeline."
        slide.placeholders[1].text_frame.paragraphs[0].runs[0].font.size = Pt(24)
        slide.notes_slide.notes_text_frame.text = "PRESENTER NOTES: must not appear in output."
    pres.save(str(path))


def legacy_ppt(pptx: Path, path: Path) -> bool:
    """Convert the .pptx to .ppt with LibreOffice, if installed."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from converter.tools import find_libreoffice

    office = find_libreoffice()
    if office is None:
        return False
    with tempfile.TemporaryDirectory() as profile, tempfile.TemporaryDirectory() as out:
        subprocess.run(
            [
                str(office),
                f"-env:UserInstallation={Path(profile).as_uri()}",
                "--headless",
                "--convert-to",
                "ppt",
                "--outdir",
                out,
                str(pptx),
            ],
            capture_output=True,
            timeout=300,
        )
        made = Path(out) / f"{pptx.stem}.ppt"
        if not made.is_file():
            return False
        path.write_bytes(made.read_bytes())
    return True


def _exif_orientation_segment(orientation: int) -> bytes:
    """A JPEG APP1 (EXIF) segment holding only the Orientation tag."""
    tiff = b"II*\x00" + struct.pack("<I", 8)  # Little-endian TIFF header, IFD at offset 8.
    tiff += struct.pack("<H", 1)  # One IFD entry:
    tiff += struct.pack("<HHIHH", 0x0112, 3, 1, orientation, 0)  # Orientation, SHORT, 1 value.
    tiff += struct.pack("<I", 0)  # No next IFD.
    payload = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def rotated_photo(path: Path) -> None:
    """A JPEG stored sideways with EXIF orientation 6 (viewers rotate it upright)."""
    with pymupdf.open() as tmp:
        page = tmp.new_page(width=600, height=400)
        page.insert_text((40, 200), "UPRIGHT when shown correctly", fontsize=28)
        # Store the pixels rotated 90 degrees counter-clockwise; orientation 6 undoes it.
        # Rotation goes in the matrix (get_pixmap ignores `matrix` when `dpi` is given).
        jpeg = page.get_pixmap(matrix=pymupdf.Matrix(1, 1).prerotate(-90)).tobytes("jpeg")
    path.write_bytes(jpeg[:2] + _exif_orientation_segment(6) + jpeg[2:])


def diagram(path: Path) -> None:
    with pymupdf.open() as tmp:
        page = tmp.new_page(width=600, height=300)
        page.draw_rect(pymupdf.Rect(40, 40, 560, 260), color=(0, 0, 1), width=3)
        page.insert_text((70, 160), "Diagram: input to output", fontsize=26)
        page.get_pixmap(dpi=150).save(str(path))


def image_heavy(path: Path) -> None:
    with pymupdf.open() as doc:
        for n in range(3):
            page = doc.new_page(width=PAGE[0], height=PAGE[1])
            page.insert_image(
                page.rect, stream=_image_of_text([f"High-resolution page {n + 1}"], dpi=300)
            )
        doc.save(str(path))


def password_protected(path: Path) -> None:
    with pymupdf.open() as doc:
        _text_page(doc, ["Locked sample"])
        doc.save(
            str(path), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="test", owner_pw="owner"
        )


def damaged(path: Path, source: Path) -> None:
    data = source.read_bytes()
    path.write_bytes(data[: len(data) // 3])  # Cut off the end, including the xref table.


def unicode_named(path: Path) -> None:
    with pymupdf.open() as doc:
        _text_page(doc, ["Sample with a non-Latin file name"])
        doc.save(str(path))


def long_document(path: Path) -> None:
    with pymupdf.open() as doc:
        for n in range(1, 41):
            _text_page(doc, [f"Page {n} of 40"])
        doc.set_toc([[1, f"Part {k}", (k - 1) * 10 + 1] for k in range(1, 5)])
        doc.save(str(path))


def mark_as_downloaded(path: Path) -> bool:
    """Windows only: add the Mark-of-the-Web (Internet zone) to ``path``."""
    if sys.platform != "win32":
        return False
    with open(f"{path}:Zone.Identifier", "w", encoding="utf-8") as stream:
        stream.write("[ZoneTransfer]\nZoneId=3\nHostUrl=https://example.org/slides.pptx\n")
    return True


def make_all(out: Path) -> list[Path]:
    """Create every sample in ``out``; returns the files made."""
    out.mkdir(parents=True, exist_ok=True)
    f = {name: out / name for name in SAMPLES}
    text_report(f["01-text-report.pdf"])
    scanned(
        f["02-scanned-pages.pdf"],
        [["Scanned page one", "Searchable after OCR."], ["Scanned page two", "Also an image."]],
    )
    scanned(f["03-rotated-scan.pdf"], [["Rotated scanned page"]], rotation=90)
    mixed(f["04-mixed-text-and-scan.pdf"])
    slides(f["05-slides.pptx"])
    legacy_ppt(f["05-slides.pptx"], f["06-slides-legacy.ppt"])
    rotated_photo(f["07-photo-portrait.jpg"])
    diagram(f["08-diagram.png"])
    image_heavy(f["09-image-heavy.pdf"])
    password_protected(f["10-password-protected.pdf"])
    damaged(f["11-damaged.pdf"], f["01-text-report.pdf"])
    unicode_named(f["12-ملف-unicode-name.pdf"])
    long_document(f["13-long-document.pdf"])
    downloaded = f["14-downloaded-slides.pptx"]
    downloaded.write_bytes(f["05-slides.pptx"].read_bytes())
    if not mark_as_downloaded(downloaded):
        downloaded.unlink()
    made = [p for p in f.values() if p.exists()]
    readme = ["PDF Manager test documents (synthetic). What each file is for:", ""]
    readme += [f"{p.name}: {SAMPLES[p.name]}" for p in made]
    (out / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")
    return made


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1] / "samples"
    made = make_all(out)
    print(f"Wrote {len(made)} sample files to {out}:")
    for path in made:
        print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
