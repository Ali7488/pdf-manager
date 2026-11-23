"""PowerPoint slides to PDF with LibreOffice Impress (decision C17)."""

from .render import LibreOfficeError, copy_for_rendering, libreoffice_convert, render_slides

__all__ = ["LibreOfficeError", "copy_for_rendering", "libreoffice_convert", "render_slides"]
