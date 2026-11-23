"""PowerPoint slides to PDF: optional Microsoft PowerPoint, LibreOffice as the fallback."""

from .render import LibreOfficeError, copy_for_rendering, libreoffice_convert, render_slides

__all__ = ["LibreOfficeError", "copy_for_rendering", "libreoffice_convert", "render_slides"]
