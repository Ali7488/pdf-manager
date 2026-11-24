"""Mark-of-the-Web is never stripped from the working copy (audit R1).

Presentations are converted by LibreOffice whatever their origin (decision
C17), so the app no longer reads the marker; it only keeps it on the copies it
makes, so nothing it writes looks more trusted than the original.
"""

from __future__ import annotations

import sys

import pytest

from converter.platforms import posix, windows


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
@pytest.mark.parametrize("zone", [3, 4, 2, 0])
def test_windows_copy_keeps_the_zone_identifier(tmp_path, zone):
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"slides")
    marker = f"[ZoneTransfer]\nZoneId={zone}\nHostUrl=https://example.org/deck.pptx\n"
    with open(f"{source}:Zone.Identifier", "w", encoding="utf-8") as stream:
        stream.write(marker)
    copy = tmp_path / "copy.pptx"
    windows.copy_with_provenance(source, copy)
    assert copy.read_bytes() == b"slides"
    assert windows._read_zone_identifier(copy) == marker, "the copy must keep the provenance"


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
def test_windows_copy_of_a_local_file_gets_no_marker(tmp_path):
    local = tmp_path / "local.pptx"
    local.write_bytes(b"x")
    copy = tmp_path / "copy.pptx"
    windows.copy_with_provenance(local, copy)
    assert windows._read_zone_identifier(copy) is None


def test_posix_copy_is_a_plain_copy(tmp_path):
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"pptx")
    copy = tmp_path / "copy.pptx"
    posix.copy_with_provenance(source, copy)
    assert copy.read_bytes() == b"pptx" and source.read_bytes() == b"pptx"
