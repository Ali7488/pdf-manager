"""External programs: running them (``process``), finding them (``locate``) and the
tool check for the Convert modal (``check``)."""

from .locate import find_libreoffice, find_tesseract, tesseract_languages
from .process import kill_process_tree, run_command

__all__ = [
    "find_libreoffice",
    "find_tesseract",
    "kill_process_tree",
    "run_command",
    "tesseract_languages",
]
