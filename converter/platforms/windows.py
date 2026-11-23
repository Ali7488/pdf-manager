"""Windows implementation of the platform interface.

Windows-only modules (``winreg``) are imported inside functions, so this
module can still be imported, and its pure logic tested, on other systems.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# Registry keys the Tesseract installer is known to write.
_TESSERACT_KEYS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\tesseract.exe",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Tesseract-OCR_is1",
    r"SOFTWARE\Tesseract-OCR",
)
# "" is a key's default value (App Paths stores the full exe path there). The
# others hold an install folder or an icon path pointing at the exe.
_TESSERACT_VALUES = ("InstallLocation", "Path", "DisplayIcon", "")


def popen_options() -> dict:
    """Start external programs without a console window flashing up."""
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def kill_process_tree(process: subprocess.Popen) -> None:
    """Stop a program and every program it started. Never raises.

    LibreOffice's ``soffice.exe`` launches ``soffice.bin``, so killing only the
    parent would leave the real worker running. ``taskkill /T`` stops the
    whole tree and ``/F`` forces it.
    """
    if process.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(process.pid)],
            capture_output=True,
            **popen_options(),
        )
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        process.kill()
    except OSError:
        pass


def exe_from_registry_value(value: str, exe_name: str = "tesseract.exe") -> Path:
    """Turn a registry value into the path of an executable.

    Installers store paths in several shapes; all of these give
    ``C:\\Tools\\tesseract.exe``:

    * ``C:\\Tools\\tesseract.exe`` (plain path)
    * ``"C:\\Tools\\tesseract.exe",0`` (quoted, with an icon index)
    * ``C:\\Tools\\tesseract.exe,0`` (unquoted, with an icon index)
    * ``C:\\Tools`` (a folder: ``exe_name`` is appended)

    Environment variables such as ``%ProgramFiles%`` are expanded.
    """
    text = os.path.expandvars(value.strip())
    if text.startswith('"'):
        # Quoted: the path is everything up to the closing quote.
        text = text[1:].split('"', 1)[0]
    else:
        # Unquoted: drop a trailing icon index such as ",0" or ",-101".
        text = re.sub(r",\s*-?\d+$", "", text)
    path = Path(text)
    return path if path.suffix.lower() == ".exe" else path / exe_name


def _install_roots() -> list[Path]:
    """Program Files (64- and 32-bit) and LocalAppData, where installers put programs."""
    names = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
    return [Path(value) for value in map(os.getenv, names) if value]


def _registry_strings(keys: tuple[str, ...], values: tuple[str, ...]) -> list[str]:
    """Read string values from registry keys in the machine-wide and per-user hives."""
    try:
        import winreg
    except ImportError:
        return []
    found: list[str] = []
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for key_name in keys:
            try:
                with winreg.OpenKey(hive, key_name) as key:
                    for value_name in values:
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if isinstance(value, str) and value.strip():
                            found.append(value)
            except OSError:
                continue  # Key doesn't exist on this machine.
    return found


def tesseract_candidates() -> list[Path]:
    """Standard install folders, then paths the Tesseract installer recorded in the registry.

    These matter because a fresh ``winget`` install can be per-user and isn't
    on ``PATH`` until a new session starts.
    """
    candidates = []
    for root in _install_roots():
        candidates += [
            root / "Tesseract-OCR" / "tesseract.exe",
            root / "Programs" / "Tesseract-OCR" / "tesseract.exe",
        ]
    candidates += [
        exe_from_registry_value(value)
        for value in _registry_strings(_TESSERACT_KEYS, _TESSERACT_VALUES)
    ]
    return candidates


def libreoffice_candidates() -> list[Path]:
    """Standard LibreOffice install folders."""
    candidates = []
    for root in _install_roots():
        candidates += [
            root / "LibreOffice" / "program" / "soffice.exe",
            root / "Programs" / "LibreOffice" / "program" / "soffice.exe",
        ]
    return candidates


def _read_zone_identifier(path: Path) -> str | None:
    """Contents of ``path``'s Zone.Identifier stream (Mark-of-the-Web), or None if it has none."""
    try:
        with open(f"{path}:Zone.Identifier", encoding="utf-8", errors="replace") as stream:
            return stream.read()
    except OSError:
        return None


def copy_with_provenance(source: Path, target: Path) -> None:
    """Copy a file **including** its Mark-of-the-Web, so the copy is exactly as trusted.

    The provenance is never stripped (audit R1): the Zone.Identifier stream is
    copied explicitly instead of relying on how a particular copy API treats
    alternate data streams.
    """
    shutil.copyfile(source, target)
    text = _read_zone_identifier(source)
    if text is not None:
        with open(f"{target}:Zone.Identifier", "w", encoding="utf-8") as stream:
            stream.write(text)


def os_family() -> str:
    """Which operating system family this is, for choosing user-facing wording."""
    return "windows"
