"""Enforce the portability rule (docs/PORTABILITY.md): shared service code has no OS checks.

Platform-specific code may only live in converter/platforms/.
"""

from __future__ import annotations

import re
from pathlib import Path

CONVERTER = Path(__file__).resolve().parents[1] / "converter"
FORBIDDEN = re.compile(
    r"\bos\.name\b|\bsys\.platform\b|\bplatform\.system\b|\bwinreg\b|\bwin32com\b"
    r"|\bpythoncom\b|\bstartfile\b|\btaskkill\b|CREATE_NO_WINDOW"
)


def test_shared_service_code_has_no_platform_checks():
    offenders = []
    for path in CONVERTER.rglob("*.py"):
        if "platforms" in path.relative_to(CONVERTER).parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if FORBIDDEN.search(code):
                offenders.append(f"{path.relative_to(CONVERTER.parent)}:{number}: {line.strip()}")
    assert not offenders, "Move platform-specific code into converter/platforms/:\n" + "\n".join(
        offenders
    )
