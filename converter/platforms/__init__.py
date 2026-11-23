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
    os_family() -> str
        "windows", "linux" or "mac", for choosing user-facing wording.
    copy_with_provenance(source, target) -> None
        Copy a file keeping its provenance marker (Windows Mark-of-the-Web;
        never strip it, audit R1). A plain copy where there's no such marker.

Presentations are converted by LibreOffice on every platform (decision C17),
so nothing here depends on Microsoft PowerPoint or on where a file came from.
"""

from __future__ import annotations

import os

if os.name == "nt":
    from .windows import (
        copy_with_provenance,
        kill_process_tree,
        libreoffice_candidates,
        os_family,
        popen_options,
        tesseract_candidates,
    )
else:
    from .posix import (
        copy_with_provenance,
        kill_process_tree,
        libreoffice_candidates,
        os_family,
        popen_options,
        tesseract_candidates,
    )

__all__ = [
    "copy_with_provenance",
    "os_family",
    "kill_process_tree",
    "libreoffice_candidates",
    "popen_options",
    "tesseract_candidates",
]
