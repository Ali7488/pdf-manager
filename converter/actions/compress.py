"""Compress PDF: make a PDF smaller at one of three levels.

``pipeline.run_action`` calls :func:`compress_pdf`.

Every level saves the document with PyMuPDF's lossless clean-up (unused and
duplicate objects removed, streams compressed, small objects packed into
object streams). The Balanced and Strong levels first re-encode images that are
sharper than needed as JPEG, using MuPDF's image rewriter. Pages, text, fonts,
links, annotations and bookmarks are not touched.
"""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from ..core.context import JobContext
from ..core.issues import ConversionError, empty_pdf, password_protected, unreadable_file
from ..core.types import CompressLevel, Stage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ImageSettings:
    """How images are re-encoded at one compression level.

    Attributes:
        dpi_threshold: Images shown sharper than this (pixels per inch at
            their size on the page) are scaled down.
        dpi_target: Resolution those images are scaled down to.
        quality: JPEG quality, 0 to 100, used when re-encoding images.
    """

    dpi_threshold: int
    dpi_target: int
    quality: int


# Image handling per level. None means images are left exactly as they are.
#
# * Balanced: 150 DPI keeps text in scanned pages and slide screenshots crisp on
#   screen and fine for everyday printing; JPEG quality 75 is visually close to
#   the original. Only images above 200 DPI are scaled, so pictures that are
#   already near 150 DPI aren't resampled for a tiny gain.
# * Strong: 96 DPI (a typical screen resolution) and quality 50 give the
#   smallest files that are still readable on screen; fine print in scans may
#   blur and printouts look soft. Images above 120 DPI are scaled.
LEVEL_IMAGES: dict[CompressLevel, ImageSettings | None] = {
    CompressLevel.LIGHT: None,
    CompressLevel.BALANCED: ImageSettings(dpi_threshold=200, dpi_target=150, quality=75),
    CompressLevel.STRONG: ImageSettings(dpi_threshold=120, dpi_target=96, quality=50),
}


def _open_source(source: Path) -> pymupdf.Document:
    """Open the PDF to compress, turning low-level failures into user-facing errors.

    Args:
        source: PDF to open; only read.

    Returns:
        The open document. The caller closes it.

    Raises:
        ConversionError: The file can't be read, needs a password, or has no pages.
    """
    try:
        doc = pymupdf.open(str(source))
    except Exception as exc:  # MuPDF raises several types for damaged or missing files.
        raise ConversionError(unreadable_file(source.name, str(exc))) from exc
    if doc.needs_pass:
        doc.close()
        raise ConversionError(password_protected(source.name))
    if doc.page_count < 1:
        doc.close()
        raise ConversionError(empty_pdf(source.name))
    return doc


def _rewriter_options(images: ImageSettings) -> pymupdf.mupdf.PdfImageRewriterOptions:
    """Build MuPDF image-rewriter options for one level.

    ``Document.rewrite_images`` is given these options instead of its simple
    arguments because the simple form scales images by averaging, which only
    divides the size by whole powers of two: a 299 DPI image wouldn't be
    scaled to 150 DPI at all, and 400 DPI would only drop to 200. Bicubic
    scaling reaches the target resolution exactly and looks smoother.

    Colour and grey images, lossless (PNG-like) and lossy (JPEG) alike, are
    re-encoded as JPEG. Black-and-white images (fax-style scans) are left alone:
    they are already tiny, and JPEG or scaling would blur their text.

    Args:
        images: Resolution and quality to use.

    Returns:
        The options object for ``rewrite_images(options=...)``.
    """
    mupdf = pymupdf.mupdf
    opts = mupdf.PdfImageRewriterOptions()
    for kind in ("color_lossless", "color_lossy", "gray_lossless", "gray_lossy"):
        setattr(opts, f"{kind}_image_recompress_method", mupdf.FZ_RECOMPRESS_JPEG)
        setattr(opts, f"{kind}_image_recompress_quality", str(images.quality))
        setattr(opts, f"{kind}_image_subsample_method", mupdf.FZ_SUBSAMPLE_BICUBIC)
        setattr(opts, f"{kind}_image_subsample_threshold", images.dpi_threshold)
        setattr(opts, f"{kind}_image_subsample_to", images.dpi_target)
    # Keep an image's original data whenever re-encoding wouldn't make it smaller
    # (MuPDF's default, set explicitly so it can't change under us).
    opts.recompress_when = mupdf.FZ_RECOMPRESS_WHEN_SMALLER
    return opts


def _shrink_images(doc: pymupdf.Document, images: ImageSettings) -> None:
    """Re-encode the document's images in memory at the given settings.

    If MuPDF can't rewrite the images (for example an unusual image type), the
    problem is logged and the document is still saved with lossless clean-up.

    Args:
        doc: Open document; modified in memory only.
        images: Resolution and quality to use.
    """
    try:
        doc.rewrite_images(options=_rewriter_options(images))
    except Exception:
        # Known limitation: a failure here means images stay as they were, so
        # the file may shrink less than expected. It is not worth failing the job.
        log.warning("Image re-encoding failed; continuing with lossless clean-up", exc_info=True)


def compress_pdf(source: Path, target: Path, level: CompressLevel, ctx: JobContext) -> None:
    """Write a smaller copy of ``source`` to ``target``.

    * ``LIGHT``: lossless clean-up only (remove unused objects, compress streams).
    * ``BALANCED``: also re-encode large images at a moderate resolution and quality.
    * ``STRONG``: lower image resolution and quality for the smallest files.

    Text, links and bookmarks are kept. The result is never bigger than the
    input: if compression doesn't help, the input is copied unchanged.
    Reports progress (``Stage.COMPRESSING``) and checks for cancel.

    The exact image settings per level are in :data:`LEVEL_IMAGES`.

    Args:
        source: PDF to compress; only read.
        target: Where to write the result (its folder is created if needed).
            Must not be ``source``.
        level: How hard to compress.
        ctx: Job context for progress and cancel.

    Raises:
        ConversionError: The source can't be read, needs a password, or has no pages.
        Cancelled: The user pressed Cancel.
        ValueError: ``target`` is the source file, or ``level`` is unknown.
    """
    level = CompressLevel(level)  # Also accepts the plain string value.
    if target.resolve() == source.resolve():
        raise ValueError("Compress must write to a new file; originals are never modified.")
    started = time.perf_counter()
    images = LEVEL_IMAGES[level]
    ctx.check_cancel()
    ctx.report(Stage.COMPRESSING, "Compressing: reading the file", within_file=0.0)
    original_size = source.stat().st_size if source.is_file() else 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with _open_source(source) as doc:
        log.debug(
            "Compressing %s (%d pages, %d bytes) at level %s: %s",
            source.name,
            doc.page_count,
            original_size,
            level,
            images,
        )
        if images is not None:
            ctx.report(Stage.COMPRESSING, "Compressing: shrinking images", within_file=0.1)
            _shrink_images(doc, images)
        ctx.check_cancel()
        ctx.report(Stage.COMPRESSING, "Compressing: saving", within_file=0.7)
        doc.save(
            str(target),
            garbage=4,  # Remove unused objects and merge duplicates.
            deflate=True,  # Compress uncompressed streams...
            deflate_images=True,  # ...including image data...
            deflate_fonts=True,  # ...and embedded fonts.
            use_objstms=1,  # Pack small objects together; often saves several percent.
        )
    compressed_size = target.stat().st_size
    if compressed_size >= original_size:
        # Compression didn't help (already optimised, or re-encoding grew it):
        # hand back the original bytes instead.
        shutil.copyfile(source, target)
        log.debug(
            "Compressed copy was %d bytes, not smaller than %d; kept the original",
            compressed_size,
            original_size,
        )
    else:
        log.debug(
            "Compressed %s: %d -> %d bytes (%.0f%% of original)",
            source.name,
            original_size,
            compressed_size,
            100 * compressed_size / original_size,
        )
    ctx.report(Stage.COMPRESSING, "Compressing: done", within_file=1.0)
    log.debug("Compress finished in %.2f s", time.perf_counter() - started)
