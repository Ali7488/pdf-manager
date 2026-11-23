"""Enforce the portability rule (docs/PORTABILITY.md, decision P15) for the API layer.

Shared API code has no OS checks and no platform-specific commands; those live
only in ``api/platforms/``. The service layer has the same check in
``tests/test_portability.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

API = Path(__file__).resolve().parents[2] / "api"
FORBIDDEN = re.compile(
    r"\bos\.name\b|\bsys\.platform\b|\bplatform\.system\b|\bstartfile\b|\bwinget\b"
    r"|xdg-open|\bwinreg\b|\bwin32com\b|\bpythoncom\b|\btaskkill\b|CREATE_NO_WINDOW"
    r"|\bon_windows\b"
)


def test_forbidden_pattern_catches_platform_checks():
    """The pattern really matches the checks it is meant to keep out."""
    for sample in (
        'if os.name == "nt":',
        'sys.platform == "darwin"',
        "os.startfile(folder)",
        'run(["winget", "install"])',
        'Popen(["xdg-open", folder])',
        "paths.on_windows()",
    ):
        assert FORBIDDEN.search(sample), sample


def test_shared_api_code_has_no_platform_checks():
    """Only api/platforms/ may contain OS checks or platform-specific commands."""
    offenders = []
    for path in sorted(API.rglob("*.py")):
        if "platforms" in path.relative_to(API).parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if FORBIDDEN.search(code):
                offenders.append(f"{path.relative_to(API.parent)}:{number}: {line.strip()}")
    assert not offenders, "Move platform-specific code into api/platforms/:\n" + "\n".join(
        offenders
    )


def test_platform_modules_exist():
    """The scan is meaningful only while the platform modules are where it expects."""
    for name in ("__init__.py", "windows.py", "linux.py", "mac.py"):
        assert (API / "platforms" / name).is_file(), name
