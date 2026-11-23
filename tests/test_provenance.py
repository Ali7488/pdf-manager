"""Mark-of-the-Web handling (audit R1): read it correctly and never strip it."""

from __future__ import annotations

import sys

import pytest

from converter.platforms import windows


@pytest.mark.parametrize(
    "text,zone",
    [
        ("[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=https://example.org/\r\n", 3),
        ("[ZoneTransfer]\nZoneId = 4\n", 4),
        ("[ZoneTransfer]\nZoneId=0\n", 0),
        ("[ZoneTransfer]\nHostUrl=about:internet\n", None),
        ("", None),
    ],
)
def test_zone_parsing(text, zone):
    assert windows.zone_from_identifier(text) == zone


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
@pytest.mark.parametrize("zone,untrusted", [(3, True), (4, True), (2, False), (0, False)])
def test_windows_zone_detection_and_copy_keeps_it(tmp_path, zone, untrusted):
    source = tmp_path / "deck.pptx"
    source.write_bytes(b"slides")
    with open(f"{source}:Zone.Identifier", "w", encoding="utf-8") as stream:
        stream.write(f"[ZoneTransfer]\nZoneId={zone}\n")
    assert windows.is_untrusted(source) is untrusted
    copy = tmp_path / "copy.pptx"
    windows.copy_with_provenance(source, copy)
    assert copy.read_bytes() == b"slides"
    assert windows.is_untrusted(copy) is untrusted, "the copy must keep the provenance"


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
def test_windows_file_without_marker_is_trusted(tmp_path):
    local = tmp_path / "local.pptx"
    local.write_bytes(b"x")
    assert windows.is_untrusted(local) is False
