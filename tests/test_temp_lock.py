"""Regression test for the Windows "file in use" (WinError 32) bug during OCR.

An early version deleted each page image and OCR PDF right after using it,
while Windows (a PDF renderer or real-time virus scanner) could still hold them
open, which crashed the conversion. Temporary files are now kept until the
whole job is done. This simulates the Windows behaviour by making any attempt
to delete those files raise PermissionError.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from converter import Action, ActionData, ActionSettings, run_action
from tests.helpers import text_pdf

pytestmark = pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
REAL_UNLINK = Path.unlink


def refuse_temp_unlink(self: Path, *args, **kwargs):
    if self.name.startswith(("ocr_", "page_")):
        raise PermissionError(
            32, "The process cannot access the file because it is being used", str(self)
        )
    return REAL_UNLINK(self, *args, **kwargs)


@pytest.mark.parametrize("action", [Action.FLATTEN, Action.FLATTEN_MERGE])
def test_locked_temp_files_do_not_break_flattening(tmp_path, action):
    src = text_pdf(tmp_path / "source.pdf", ["Sample document searchable text check"], (420, 280))
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    with patch.object(Path, "unlink", refuse_temp_unlink):
        result = run_action(
            action, ActionSettings(use_ocr=True), ActionData([src]), scratch=tmp_path / "w"
        )
    [output] = result.outputs
    with fitz.open(str(output.path)) as doc:
        assert len(doc) == 1
        assert "searchable" in doc[0].get_text().lower()
        assert doc[0].get_images()
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
