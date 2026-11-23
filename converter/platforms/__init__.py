"""Platform-specific functionality behind one minimal interface.

Shared code never checks the operating system itself; it calls these
functions, which come from ``windows.py`` on Windows and ``posix.py`` on Linux
(and macOS). See ``docs/PORTABILITY.md``.

Interface:
    popen_options() -> dict
        Extra ``subprocess.Popen`` options so external programs run without a
        console window and can be stopped as a whole process tree.
    kill_process_tree(process) -> None
        Stop a program and everything it started. Never raises.
    tesseract_candidates() -> list[Path]
        Places to look for Tesseract beyond ``PATH``.
    libreoffice_candidates() -> list[Path]
        Places to look for LibreOffice beyond ``PATH``.
    powerpoint_installed() -> bool
        Whether Microsoft PowerPoint can be automated (always False off Windows).
    powerpoint_path() -> Path | None
        Path of PowerPoint's executable, for display only.
"""

from __future__ import annotations

import os

if os.name == "nt":
    from .windows import (
        kill_process_tree,
        libreoffice_candidates,
        popen_options,
        powerpoint_installed,
        powerpoint_path,
        tesseract_candidates,
    )
else:
    from .posix import (
        kill_process_tree,
        libreoffice_candidates,
        popen_options,
        powerpoint_installed,
        powerpoint_path,
        tesseract_candidates,
    )

__all__ = [
    "kill_process_tree",
    "libreoffice_candidates",
    "popen_options",
    "powerpoint_installed",
    "powerpoint_path",
    "tesseract_candidates",
]
