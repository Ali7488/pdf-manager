"""Tests for converter.images: PNG/JPG to PDF, order, naming, page size and EXIF orientation."""

from __future__ import annotations

import struct
from pathlib import Path

import fitz
import pytest

from converter.common import Stage
from converter.context import JobContext
from converter.images import MAX_PAGE_SIDE_PT, images_to_pdf
from converter.issues import Cancelled, ConversionError, IssueCode

RED = (255, 0, 0)
BLUE = (0, 0, 255)
GREEN = (0, 160, 0)


def _two_tone(width: int, height: int, left=RED, right=BLUE) -> fitz.Pixmap:
    """Build an RGB image whose left half is one colour and right half another.

    Args:
        width: Width in pixels.
        height: Height in pixels.
        left: Colour of the left half.
        right: Colour of the right half.

    Returns:
        The pixmap.
    """
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pix.set_rect(fitz.IRect(0, 0, width // 2, height), left)
    pix.set_rect(fitz.IRect(width // 2, 0, width, height), right)
    return pix


def _png(path: Path, width: int, height: int, dpi: int | None = None, **colours) -> Path:
    """Write a two-tone PNG, optionally with a stored resolution.

    Args:
        path: Where to write it.
        width: Width in pixels.
        height: Height in pixels.
        dpi: Resolution to store in the file, or None for MuPDF's default.
        **colours: ``left``/``right`` colours passed to :func:`_two_tone`.

    Returns:
        ``path``.
    """
    pix = _two_tone(width, height, **colours)
    if dpi:
        pix.set_dpi(dpi, dpi)
    path.write_bytes(pix.tobytes("png"))
    return path


def _exif_segment(orientation: int) -> bytes:
    """Build a JPEG APP1 (EXIF) segment holding only an Orientation tag.

    Layout: marker FFE1, segment length, "Exif\\0\\0", then a big-endian TIFF
    header and one IFD with a single entry: tag 0x0112 (Orientation), type 3
    (SHORT), count 1, the value padded to 4 bytes, and no next IFD.

    Args:
        orientation: EXIF orientation value, 1 to 8.

    Returns:
        The segment bytes, ready to insert after the JPEG's SOI marker.
    """
    tiff = b"MM\x00\x2a" + struct.pack(">I", 8)  # Byte order, magic 42, first IFD at offset 8.
    tiff += struct.pack(">H", 1)  # One entry in the IFD.
    tiff += struct.pack(">HHIHH", 0x0112, 3, 1, orientation, 0)
    tiff += struct.pack(">I", 0)  # No further IFDs.
    payload = b"Exif\x00\x00" + tiff
    # The length field counts itself (2 bytes) plus the payload, not the marker.
    return b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload


def _jpeg(path: Path, width: int, height: int, orientation: int | None = None) -> Path:
    """Write a red-left, blue-right JPEG, optionally tagged with an EXIF orientation.

    Args:
        path: Where to write it.
        width: Stored width in pixels.
        height: Stored height in pixels.
        orientation: EXIF orientation to add, or None for no EXIF data.

    Returns:
        ``path``.
    """
    data = _two_tone(width, height).tobytes("jpeg", jpg_quality=95)
    if orientation is not None:
        data = data[:2] + _exif_segment(orientation) + data[2:]  # Right after SOI (FFD8).
    path.write_bytes(data)
    return path


def _colour_at(page: fitz.Page, fx: float, fy: float) -> tuple[int, int, int]:
    """Render a page and return the colour at a relative position.

    Args:
        page: Page to render.
        fx: Horizontal position, 0 (left) to 1 (right).
        fy: Vertical position, 0 (top) to 1 (bottom).

    Returns:
        The RGB colour there.
    """
    pix = page.get_pixmap()
    return pix.pixel(int(fx * (pix.width - 1)), int(fy * (pix.height - 1)))


def _close(actual, expected, tolerance: int = 40) -> bool:
    """Compare colours loosely, allowing for JPEG artefacts.

    Args:
        actual: Rendered colour.
        expected: Wanted colour.
        tolerance: Largest allowed difference per channel.

    Returns:
        True when every channel is within ``tolerance``.
    """
    return all(abs(a - e) <= tolerance for a, e in zip(actual, expected))


def _convert(images, tmp_path: Path, combine: bool, ctx: JobContext | None = None):
    """Run images_to_pdf into ``tmp_path / "out"`` with a default context.

    Args:
        images: Image paths.
        tmp_path: pytest's temporary folder.
        combine: Combined or per-image output.
        ctx: Optional job context.

    Returns:
        The list of OutputFile entries.
    """
    return images_to_pdf(images, tmp_path / "out", combine, ctx or JobContext())


# --- Naming, order and page counts ----------------------------------------------------


def test_combined_keeps_order_and_names_after_first(tmp_path):
    images = [
        _png(tmp_path / "first.png", 40, 20, left=RED, right=RED),
        _jpeg(tmp_path / "second.jpg", 40, 20),
        _png(tmp_path / "third.png", 20, 40, left=GREEN, right=GREEN),
    ]
    (output,) = _convert(images, tmp_path, combine=True)
    assert output.name == "first + 2 more - Images.pdf"
    assert output.page_count == 3
    assert output.size_bytes == output.path.stat().st_size
    with fitz.open(str(output.path)) as doc:
        assert doc.page_count == 3
        assert _close(_colour_at(doc[0], 0.9, 0.5), RED)
        assert _close(_colour_at(doc[1], 0.9, 0.5), BLUE)
        assert _close(_colour_at(doc[2], 0.5, 0.5), GREEN)
        assert doc[2].rect.height > doc[2].rect.width  # Third image is portrait.


def test_combined_single_image_name(tmp_path):
    (output,) = _convert([_png(tmp_path / "only.png", 10, 10)], tmp_path, combine=True)
    assert output.name == "only - Images.pdf"
    assert output.page_count == 1


def test_per_image_outputs(tmp_path):
    images = [_png(tmp_path / "one.png", 10, 10), _jpeg(tmp_path / "two.jpeg", 10, 10)]
    outputs = _convert(images, tmp_path, combine=False)
    assert [o.name for o in outputs] == ["one.pdf", "two.pdf"]
    for output in outputs:
        assert output.page_count == 1
        assert output.size_bytes == output.path.stat().st_size
        with fitz.open(str(output.path)) as doc:
            assert doc.page_count == 1


def test_per_image_same_stem_gets_separate_files(tmp_path):
    images = [_png(tmp_path / "photo.png", 10, 10), _jpeg(tmp_path / "photo.jpg", 10, 10)]
    outputs = _convert(images, tmp_path, combine=False)
    assert [o.name for o in outputs] == ["photo.pdf", "photo.pdf"]
    assert outputs[0].path != outputs[1].path
    assert all(o.path.is_file() for o in outputs)


def test_accepts_string_paths_and_leaves_inputs_unchanged(tmp_path):
    image = _png(tmp_path / "keep.png", 30, 30)
    before = image.read_bytes()
    (output,) = _convert([str(image)], tmp_path, combine=True)
    assert output.name == "keep - Images.pdf"
    assert image.read_bytes() == before


def test_empty_list_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        _convert([], tmp_path, combine=True)


# --- Page size ------------------------------------------------------------------------


def _page_rect(output) -> fitz.Rect:
    """Return the first page's rectangle of an output PDF.

    Args:
        output: An OutputFile.

    Returns:
        The page rectangle in points.
    """
    with fitz.open(str(output.path)) as doc:
        return doc[0].rect


def test_page_uses_stored_resolution(tmp_path):
    # 600 x 300 pixels at 300 DPI is 2 x 1 inches: 144 x 72 points.
    (output,) = _convert([_png(tmp_path / "a.png", 600, 300, dpi=300)], tmp_path, True)
    rect = _page_rect(output)
    assert rect.width == pytest.approx(144, abs=0.5)
    assert rect.height == pytest.approx(72, abs=0.5)


def test_page_without_resolution_uses_96_dpi(tmp_path):
    # MuPDF assumes 96 DPI when a file stores none: 192 x 96 pixels is 144 x 72 points.
    (output,) = _convert([_png(tmp_path / "a.png", 192, 96)], tmp_path, True)
    rect = _page_rect(output)
    assert rect.width == pytest.approx(144, abs=0.5)
    assert rect.height == pytest.approx(72, abs=0.5)


def test_large_photo_is_capped_at_a4_long_side(tmp_path):
    # Like a phone photo: 2000 x 1500 pixels claiming 72 DPI would be a 70 cm
    # wide page; it is scaled down to A4's long side, keeping its shape.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 2000, 1500), False)
    pix.clear_with(200)  # Plain grey; much faster than set_rect at this size.
    pix.set_dpi(72, 72)
    photo = tmp_path / "photo.jpg"
    photo.write_bytes(pix.tobytes("jpeg"))
    (output,) = _convert([photo], tmp_path, True)
    rect = _page_rect(output)
    assert rect.width == pytest.approx(MAX_PAGE_SIDE_PT, abs=0.5)
    assert rect.height == pytest.approx(MAX_PAGE_SIDE_PT * 0.75, abs=0.5)


def test_jpeg_is_embedded_without_recompression(tmp_path):
    image = _jpeg(tmp_path / "photo.jpg", 200, 100)
    (output,) = _convert([image], tmp_path, True)
    with fitz.open(str(output.path)) as doc:
        ((xref, *_),) = doc[0].get_images(full=True)
        extracted = doc.extract_image(xref)
    assert extracted["ext"] == "jpeg"
    assert extracted["image"] == image.read_bytes()


def test_png_with_transparency(tmp_path):
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), True)  # With alpha.
    pix.set_rect(pix.irect, (0, 0, 255, 255))
    path = tmp_path / "clear.png"
    path.write_bytes(pix.tobytes("png"))
    (output,) = _convert([path], tmp_path, True)
    assert output.page_count == 1


# --- EXIF orientation -----------------------------------------------------------------

# Stored image: 40 x 20 pixels, red on the left, blue on the right. For each
# EXIF orientation: whether the upright page is portrait, and the colours
# expected at (top or left) and (bottom or right).
ORIENTATIONS = {
    1: (False, RED, BLUE),  # Upright already.
    2: (False, BLUE, RED),  # Mirrored left to right.
    3: (False, BLUE, RED),  # Upside down.
    6: (True, RED, BLUE),  # Phone held upright: rotate 90 degrees clockwise to view.
    8: (True, BLUE, RED),  # Rotate 90 degrees anticlockwise to view.
}


@pytest.mark.parametrize("orientation", sorted(ORIENTATIONS))
def test_exif_orientation_is_applied(tmp_path, orientation):
    portrait, first, second = ORIENTATIONS[orientation]
    image = _jpeg(tmp_path / f"photo{orientation}.jpg", 40, 20, orientation=orientation)
    (output,) = _convert([image], tmp_path, True)
    with fitz.open(str(output.path)) as doc:
        page = doc[0]
        assert (page.rect.height > page.rect.width) == portrait
        if portrait:
            assert page.rect.height == pytest.approx(2 * page.rect.width, rel=0.01)
            top, bottom = _colour_at(page, 0.5, 0.1), _colour_at(page, 0.5, 0.9)
            assert _close(top, first) and _close(bottom, second)
        else:
            left, right = _colour_at(page, 0.1, 0.5), _colour_at(page, 0.9, 0.5)
            assert _close(left, first) and _close(right, second)


def test_exif_orientation_per_image_mode(tmp_path):
    image = _jpeg(tmp_path / "upright.jpg", 40, 20, orientation=6)
    (output,) = _convert([image], tmp_path, combine=False)
    rect = _page_rect(output)
    assert rect.height > rect.width


# --- Errors, progress and cancel ------------------------------------------------------


def test_unreadable_image(tmp_path):
    good = _png(tmp_path / "good.png", 10, 10)
    bad = tmp_path / "damaged.png"
    bad.write_bytes(b"this is not an image")
    with pytest.raises(ConversionError) as info:
        _convert([good, bad], tmp_path, combine=True)
    assert info.value.issue.code == IssueCode.UNREADABLE_FILE
    assert info.value.issue.file == "damaged.png"
    assert info.value.issue.details  # MuPDF's message is kept for "Show details".


def test_missing_image(tmp_path):
    with pytest.raises(ConversionError) as info:
        _convert([tmp_path / "gone.jpg"], tmp_path, combine=False)
    assert info.value.issue.code == IssueCode.UNREADABLE_FILE
    assert info.value.issue.file == "gone.jpg"


def test_reports_progress(tmp_path):
    images = [_png(tmp_path / f"p{i}.png", 10, 10) for i in range(3)]
    events = []
    _convert(images, tmp_path, True, JobContext(progress=events.append))
    assert {event.stage for event in events} == {Stage.PREPARING}
    assert events[0].message == "Adding image 1 of 3: p0.png"
    fractions = [event.fraction for event in events]
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0


def _cancelling_context() -> JobContext:
    """Return a context that presses Cancel on its first progress report.

    Returns:
        The job context.
    """
    ctx = JobContext()

    def cancel(event):
        """Press Cancel."""
        ctx.cancel.cancel()

    ctx.progress = cancel
    return ctx


def test_cancel_between_images_per_image(tmp_path):
    images = [_png(tmp_path / f"p{i}.png", 10, 10) for i in range(3)]
    with pytest.raises(Cancelled):
        _convert(images, tmp_path, False, _cancelling_context())
    # The image in progress finishes; the next one is never started.
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["image_001.pdf"]


def test_cancel_combined_saves_nothing(tmp_path):
    images = [_png(tmp_path / f"p{i}.png", 10, 10) for i in range(3)]
    with pytest.raises(Cancelled):
        _convert(images, tmp_path, True, _cancelling_context())
    assert list((tmp_path / "out").iterdir()) == []
