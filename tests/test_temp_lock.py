"""Regression tests for OCR PDF temporary-file WinError 32 cleanup bug.

Before the fix, `flatten_searchable()` unlinked the page_*.png and ocr_*.pdf
while the Windows PDF/file scan stack could still hold those outputs open.
This test simulates the Windows behavior by raising PermissionError if the
converter tries to unlink those temporary files inside the worker.
"""
from __future__ import annotations
import hashlib
import tempfile
from pathlib import Path
from unittest.mock import patch
import fitz
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from converter import FLATTEN, FLATTEN_MERGE, process_files, find_tesseract


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    assert find_tesseract(), 'Tesseract OCR must be available for this test'
    with tempfile.TemporaryDirectory() as d:
        work = Path(d)
        src = work / 'source.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page(width=420, height=280)
            page.insert_text((20, 80), 'Sample document: searchable text check', fontsize=18)
            pdf.save(str(src))
        original_checksum = checksum(src)
        real_unlink = Path.unlink
        def refuse_ocr_temp_unlink(self: Path, *args, **kwargs):
            if self.name.startswith(('ocr_', 'page_')):
                raise PermissionError(32, 'The process cannot access the file because it is being used by another process', str(self))
            return real_unlink(self, *args, **kwargs)

        with patch.object(Path, 'unlink', refuse_ocr_temp_unlink):
            for mode in (FLATTEN, FLATTEN_MERGE):
                results = process_files([src], mode, work / mode, lambda _: None)
                assert len(results) == 1
                output = results[0][1]
                assert output.is_file()
                with fitz.open(str(output)) as doc:
                    assert len(doc) == 1
                    assert 'searchable' in doc[0].get_text().lower()
                    assert len(doc[0].get_images()) > 0
                assert checksum(src) == original_checksum, 'Source was modified!'
        print('PASS: WinError 32 simulated OCR temp lock, OCR text, original preservation')

if __name__ == '__main__':
    main()
