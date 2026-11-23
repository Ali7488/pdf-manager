"""OCR with Tesseract: page rendering, page OCR and the text-layer-only mode."""

from .tesseract import add_text_layer, ocr_image_to_pdf, page_needs_ocr, render_page, require_ocr

__all__ = ["add_text_layer", "ocr_image_to_pdf", "page_needs_ocr", "render_page", "require_ocr"]
