"""Tests for converter.compress: the three levels, never growing a file, and what is kept."""

from __future__ import annotations

import random
from pathlib import Path

import fitz
import pytest

from converter.common import CompressLevel, Stage
from converter.compress import LEVEL_IMAGES, compress_pdf
from converter.context import JobContext
from converter.issues import Cancelled, ConversionError, IssueCode

SAMPLE_TEXT = "Sample text for searching"

# Image placed on a 2 x 1.5 inch area: 800 x 600 pixels there is 400 DPI.
IMAGE_PX = (800, 600)
IMAGE_RECT = fitz.Rect(72, 150, 72 + 144, 150 + 108)


def _noise_pixmap(width: int, height: int, seed: int) -> fitz.Pixmap:
    """Build a photo-like (hard to compress) RGB image from random pixels.

    Args:
        width: Width in pixels.
        height: Height in pixels.
        seed: Random seed, so runs are repeatable.

    Returns:
        The pixmap.
    """
    samples = random.Random(seed).randbytes(width * height * 3)
    return fitz.Pixmap(fitz.csRGB, width, height, samples, False)


def _add_extras(doc: fitz.Document) -> None:
    """Add text, links and bookmarks that compression must keep.

    Args:
        doc: Document with at least two pages.
    """
    for number, page in enumerate(doc, 1):
        page.insert_text((72, 72), f"{SAMPLE_TEXT} {number}")
    doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(72, 80, 200, 95), "page": 1})
    web = {"kind": fitz.LINK_URI, "from": fitz.Rect(72, 100, 200, 115)}
    web["uri"] = "https://example.com/"
    doc[0].insert_link(web)
    doc.set_toc([[1, "First", 1], [2, "Second", 2]])


@pytest.fixture
def image_pdf(tmp_path: Path) -> Path:
    """Build a two-page PDF holding a large lossless image and a high-quality JPEG.

    Args:
        tmp_path: pytest's temporary folder.

    Returns:
        Path to the saved PDF.
    """
    path = tmp_path / "Pictures.pdf"
    with fitz.open() as doc:
        for _ in range(2):
            doc.new_page()
        # Page 1: lossless (PNG/Flate) image; page 2: JPEG at quality 95.
        doc[0].insert_image(IMAGE_RECT, pixmap=_noise_pixmap(*IMAGE_PX, seed=1))
        jpeg = _noise_pixmap(*IMAGE_PX, seed=2).tobytes("jpeg", jpg_quality=95)
        doc[1].insert_image(IMAGE_RECT, stream=jpeg)
        _add_extras(doc)
        doc.save(str(path), garbage=4, deflate=True)
    return path


@pytest.fixture
def text_pdf(tmp_path: Path) -> Path:
    """Build an already well-compressed, text-only PDF.

    Args:
        tmp_path: pytest's temporary folder.

    Returns:
        Path to the saved PDF.
    """
    path = tmp_path / "Text.pdf"
    with fitz.open() as doc:
        for _ in range(2):
            doc.new_page()
        _add_extras(doc)
        doc.save(str(path), garbage=4, deflate=True, use_objstms=1)
    return path


def _compress(source: Path, tmp_path: Path, level, ctx: JobContext | None = None) -> Path:
    """Compress ``source`` into ``tmp_path / "out" / "result.pdf"``.

    Args:
        source: PDF to compress.
        tmp_path: pytest's temporary folder.
        level: Compression level.
        ctx: Optional job context.

    Returns:
        The result path.
    """
    target = tmp_path / "out" / f"result-{level}.pdf"
    compress_pdf(source, target, level, ctx or JobContext())
    return target


def _check_kept(path: Path) -> None:
    """Assert pages, text, links and bookmarks survived.

    Args:
        path: Compressed PDF.
    """
    with fitz.open(str(path)) as doc:
        assert doc.page_count == 2
        assert SAMPLE_TEXT in doc[0].get_text()
        assert doc[1].search_for(f"{SAMPLE_TEXT} 2")  # Still searchable.
        kinds = sorted(link["kind"] for link in doc[0].get_links())
        assert kinds == sorted([fitz.LINK_GOTO, fitz.LINK_URI])
        goto = next(link for link in doc[0].get_links() if link["kind"] == fitz.LINK_GOTO)
        assert goto["page"] == 1
        assert doc.get_toc() == [[1, "First", 1], [2, "Second", 2]]


def _image_widths(path: Path) -> list[int]:
    """Return the pixel width of the image on each page.

    Args:
        path: PDF to inspect.

    Returns:
        One width per page.
    """
    with fitz.open(str(path)) as doc:
        return [page.get_images(full=True)[0][2] for page in doc]


# --- Levels ---------------------------------------------------------------------------


def test_level_settings_are_ordered():
    assert LEVEL_IMAGES[CompressLevel.LIGHT] is None
    balanced = LEVEL_IMAGES[CompressLevel.BALANCED]
    strong = LEVEL_IMAGES[CompressLevel.STRONG]
    assert strong.dpi_target < balanced.dpi_target
    assert strong.quality < balanced.quality
    for images in (balanced, strong):
        assert images.dpi_target < images.dpi_threshold  # Only sharper images are scaled.


def test_light_shrinks_uncompressed_pdf_losslessly(tmp_path):
    source = tmp_path / "Loose.pdf"
    with fitz.open() as doc:
        for _ in range(2):
            doc.new_page()
        _add_extras(doc)
        for page in doc:
            for line in range(40):  # Plenty of uncompressed page content.
                page.insert_text((72, 140 + line * 15), f"{SAMPLE_TEXT} line {line}")
        doc.save(str(source), deflate=False, garbage=0)
    result = _compress(source, tmp_path, CompressLevel.LIGHT)
    assert result.stat().st_size < source.stat().st_size * 0.8
    _check_kept(result)


@pytest.mark.parametrize("level", [CompressLevel.BALANCED, CompressLevel.STRONG])
def test_image_levels_shrink_image_heavy_pdf(image_pdf, tmp_path, level):
    result = _compress(image_pdf, tmp_path, level)
    assert result.stat().st_size < image_pdf.stat().st_size * 0.5
    _check_kept(result)


def test_images_scaled_to_level_resolution(image_pdf, tmp_path):
    # The images are shown at 400 DPI; each level scales them to its target.
    for level in (CompressLevel.BALANCED, CompressLevel.STRONG):
        expected = IMAGE_PX[0] * LEVEL_IMAGES[level].dpi_target / 400
        widths = _image_widths(_compress(image_pdf, tmp_path, level))
        assert widths == [pytest.approx(expected, abs=2)] * 2


def test_strong_is_smaller_than_balanced(image_pdf, tmp_path):
    balanced = _compress(image_pdf, tmp_path, CompressLevel.BALANCED).stat().st_size
    strong = _compress(image_pdf, tmp_path, CompressLevel.STRONG).stat().st_size
    assert strong < balanced


def test_light_keeps_images_unchanged(image_pdf, tmp_path):
    result = _compress(image_pdf, tmp_path, CompressLevel.LIGHT)
    assert _image_widths(result) == [IMAGE_PX[0]] * 2
    assert result.stat().st_size <= image_pdf.stat().st_size
    _check_kept(result)


@pytest.mark.parametrize("level", list(CompressLevel))
def test_text_only_pdf_never_grows(text_pdf, tmp_path, level):
    result = _compress(text_pdf, tmp_path, level)
    assert result.stat().st_size <= text_pdf.stat().st_size
    _check_kept(result)


def test_no_gain_returns_exact_copy(tmp_path):
    # A PDF this small and tidy can't be made smaller; the original bytes come back.
    source = tmp_path / "Tiny.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 72), SAMPLE_TEXT)
        doc.save(str(source), garbage=4, deflate=True, use_objstms=1)
    for level in CompressLevel:
        result = _compress(source, tmp_path, level)
        if result.stat().st_size == source.stat().st_size:
            assert result.read_bytes() == source.read_bytes()
        assert result.stat().st_size <= source.stat().st_size


def test_accepts_string_level(text_pdf, tmp_path):
    result = _compress(text_pdf, tmp_path, "strong")
    assert result.is_file()


def test_source_is_unchanged(image_pdf, tmp_path):
    before = image_pdf.read_bytes()
    _compress(image_pdf, tmp_path, CompressLevel.STRONG)
    assert image_pdf.read_bytes() == before


def test_refuses_to_overwrite_source(text_pdf):
    with pytest.raises(ValueError):
        compress_pdf(text_pdf, text_pdf, CompressLevel.LIGHT, JobContext())


# --- Progress, cancel and errors ------------------------------------------------------


def test_reports_progress(image_pdf, tmp_path):
    events = []
    _compress(image_pdf, tmp_path, CompressLevel.BALANCED, JobContext(progress=events.append))
    assert {event.stage for event in events} == {Stage.COMPRESSING}
    fractions = [event.fraction for event in events]
    assert fractions == sorted(fractions)
    assert fractions[0] == 0.0 and fractions[-1] == 1.0
    assert len(events) >= 3


def test_cancel_before_start(image_pdf, tmp_path):
    ctx = JobContext()
    ctx.cancel.cancel()
    with pytest.raises(Cancelled):
        _compress(image_pdf, tmp_path, CompressLevel.BALANCED, ctx)
    assert not (tmp_path / "out").exists()


def test_cancel_while_shrinking_images_stops_before_saving(image_pdf, tmp_path):
    ctx = JobContext()

    def cancel_when_shrinking(event):
        """Press Cancel once image re-encoding starts."""
        if "shrinking" in event.message:
            ctx.cancel.cancel()

    ctx.progress = cancel_when_shrinking
    with pytest.raises(Cancelled):
        _compress(image_pdf, tmp_path, CompressLevel.STRONG, ctx)
    assert not (tmp_path / "out" / "result-strong.pdf").exists()


def test_unreadable_file(tmp_path):
    broken = tmp_path / "Broken.pdf"
    broken.write_bytes(b"this is not a pdf")
    with pytest.raises(ConversionError) as info:
        _compress(broken, tmp_path, CompressLevel.LIGHT)
    assert info.value.issue.code == IssueCode.UNREADABLE_FILE
    assert info.value.issue.file == "Broken.pdf"


def test_password_protected(tmp_path):
    locked = tmp_path / "Locked.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(str(locked), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(ConversionError) as info:
        _compress(locked, tmp_path, CompressLevel.LIGHT)
    assert info.value.issue.code == IssueCode.PASSWORD_PROTECTED
