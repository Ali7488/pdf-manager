"""Images to PDF: turn PNG/JPG images into PDF pages.

``pipeline.run_action`` calls :func:`images_to_pdf`.

Each image becomes one page that is exactly the image's shape (no margins).
MuPDF reads the image, applies its camera orientation (EXIF rotation and
mirroring) and sizes it from the resolution stored in the file, or 96 DPI when
there is none. Pages whose longer side would exceed an A4 page's longer side are
scaled down to that size, so phone photos (which usually claim 72 DPI and are
thousands of pixels wide) don't become metre-wide pages. Smaller images keep
their natural size. JPEG data is embedded as it is, without re-compressing.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path

import fitz

from .common import OutputFile, Stage
from .context import JobContext
from .issues import ConversionError, unreadable_file

log = logging.getLogger(__name__)

# Longest page side allowed, in points (1/72 inch): the long side of A4, 297 mm.
# Bigger images are scaled down to this; the image's pixels are unchanged.
MAX_PAGE_SIDE_PT = 842.0


def _image_as_pdf(image: Path) -> fitz.Document:
    """Turn one image file into a one-page PDF held in memory.

    MuPDF applies the EXIF orientation while converting, so the page shows the
    image the way the camera meant it to be seen.

    Args:
        image: PNG or JPG file; only read.

    Returns:
        An open PDF document with the image on its first page, sized from the
        image's own resolution. The caller closes it.

    Raises:
        ConversionError: The file is missing, damaged or not an image
            (``unreadable_file``).
    """
    try:
        with fitz.open(str(image)) as picture:
            # MuPDF opens images lazily: a damaged file only fails here.
            data = picture.convert_to_pdf()
        pdf = fitz.open("pdf", data)
    except Exception as exc:  # MuPDF raises several error types for unusable files.
        raise ConversionError(unreadable_file(image.name, str(exc))) from exc
    if pdf.page_count < 1:
        pdf.close()
        raise ConversionError(unreadable_file(image.name, "No image found in the file."))
    return pdf


def _page_size(natural: fitz.Rect) -> tuple[float, float]:
    """Choose the page size for an image.

    Args:
        natural: The image's size at its stored resolution, in points.

    Returns:
        ``(width, height)`` in points: the natural size, scaled down (keeping
        the shape) so the longer side is at most :data:`MAX_PAGE_SIDE_PT`.
    """
    longest = max(natural.width, natural.height)
    scale = min(1.0, MAX_PAGE_SIDE_PT / longest) if longest > 0 else 1.0
    return natural.width * scale, natural.height * scale


def _add_image_page(output: fitz.Document, image: Path) -> None:
    """Append one image as a new page at the end of ``output``.

    Args:
        output: PDF being built.
        image: Image file to add.

    Raises:
        ConversionError: The image can't be read.
    """
    with _image_as_pdf(image) as single:
        natural = single[0].rect
        width, height = _page_size(natural)
        page = output.new_page(width=width, height=height)
        # Draw the image's page onto the new page; the image data is shared, not
        # re-encoded, so JPEG photos keep their exact bytes.
        page.show_pdf_page(page.rect, single, 0)
    log.debug(
        "Added %s: natural %.0fx%.0f pt, page %.0fx%.0f pt",
        image.name,
        natural.width,
        natural.height,
        width,
        height,
    )


def _save(doc: fitz.Document, target: Path) -> int:
    """Save a finished PDF and return its size.

    Args:
        doc: PDF to save.
        target: Where to write it.

    Returns:
        The file size in bytes.
    """
    # garbage=4 also merges identical objects, such as the colour profile each image carries.
    doc.save(str(target), garbage=4, deflate=True)
    return target.stat().st_size


def _combined_name(images: Sequence[Path]) -> str:
    """Return the suggested name for the combined PDF.

    Args:
        images: The input images, in order (at least one).

    Returns:
        ``"<first name> - Images.pdf"`` or ``"<first name> + N more - Images.pdf"``.
    """
    stem = Path(images[0]).stem
    prefix = f"{stem} + {len(images) - 1} more" if len(images) > 1 else stem
    return f"{prefix} - Images.pdf"


def images_to_pdf(
    images: Sequence[Path], out_dir: Path, combine: bool, ctx: JobContext
) -> list[OutputFile]:
    """Convert images to PDF, either into one combined PDF or one PDF per image.

    Images keep their order and their camera orientation (EXIF rotation).
    Combined output is named ``"<first name> - Images.pdf"`` (one image) or
    ``"<first name> + N more - Images.pdf"``; per-image output is
    ``"<image name>.pdf"``. OCR is not done here (the pipeline adds it when
    requested). Reports progress and checks for cancel between images.

    Page size: see the module docstring (natural size, capped at A4's long side).
    Files are written in ``out_dir`` as ``images.pdf`` (combined) or
    ``image_001.pdf``, ``image_002.pdf``... (per image), so images with the same
    name never overwrite each other; the suggested name is in
    :attr:`OutputFile.name`.

    Args:
        images: PNG/JPG files, in output order; only read.
        out_dir: Scratch folder for the results; created if needed.
        combine: True for one PDF with a page per image, False for one PDF per image.
        ctx: Job context for progress and cancel.

    Returns:
        One :class:`OutputFile` (combined) or one per image, in input order.

    Raises:
        ConversionError: An image can't be read (``unreadable_file``).
        Cancelled: The user pressed Cancel.
        ValueError: ``images`` is empty.
    """
    if not images:
        raise ValueError("No images to convert.")
    images = [Path(image) for image in images]
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(images)
    log.debug("Converting %d image(s) to PDF, combine=%s", total, combine)
    outputs: list[OutputFile] = []

    def step(index: int, image: Path) -> None:
        """Check for cancel and report progress before image ``index`` (1-based)."""
        ctx.check_cancel()
        ctx.report(
            Stage.PREPARING,
            f"Adding image {index} of {total}: {image.name}",
            within_file=(index - 1) / total,
        )

    if combine:
        with fitz.open() as output:
            for index, image in enumerate(images, 1):
                step(index, image)
                _add_image_page(output, image)
            ctx.check_cancel()  # Don't spend time saving if the user just cancelled.
            target = out_dir / "images.pdf"
            size = _save(output, target)
        outputs.append(OutputFile(_combined_name(images), target, total, size))
    else:
        for index, image in enumerate(images, 1):
            step(index, image)
            target = out_dir / f"image_{index:03d}.pdf"
            with fitz.open() as output:
                _add_image_page(output, image)
                size = _save(output, target)
            outputs.append(OutputFile(f"{image.stem}.pdf", target, 1, size))
    ctx.report(Stage.PREPARING, "Images converted", within_file=1.0)
    log.debug(
        "Images to PDF done in %.2f s: %s",
        time.perf_counter() - started,
        [(o.name, o.size_bytes) for o in outputs],
    )
    return outputs
