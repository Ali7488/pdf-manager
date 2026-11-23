"""Linux (and macOS) implementation of the platform interface.

Distribution packages put Tesseract and LibreOffice on ``PATH``, so no extra
search locations are needed. LibreOffice converts presentations here, as on
every platform (decision C17).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def popen_options() -> dict:
    """Start external programs in their own session (and so their own process group).

    The group id then equals the program's pid, which lets
    :func:`kill_process_tree` stop the program and every child it started.
    """
    return {"start_new_session": True}


def kill_process_tree(process: subprocess.Popen) -> None:
    """Stop a program and all its children by killing its process group. Never raises."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.kill()
    except OSError:
        pass


def tesseract_candidates() -> list[Path]:
    """No locations beyond ``PATH``: packages install Tesseract to ``/usr/bin``."""
    return []


def libreoffice_candidates() -> list[Path]:
    """No locations beyond ``PATH`` (``soffice`` / ``libreoffice``)."""
    return []


def copy_with_provenance(source: Path, target: Path) -> None:
    """Plain copy: there's no Windows provenance stream to keep."""
    shutil.copyfile(source, target)


def os_family() -> str:
    """Which operating system family this is, for choosing user-facing wording."""
    return "mac" if sys.platform == "darwin" else "linux"
