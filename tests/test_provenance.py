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


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS alternate data streams")
def test_mark_untrusted_treats_a_copy_as_downloaded(tmp_path):
    """Browser-mode uploads get the Internet zone, so PowerPoint never opens them (C14)."""
    upload = tmp_path / "Dropped.pptx"
    upload.write_bytes(b"pptx")
    assert windows.is_untrusted(upload) is False
    windows.mark_untrusted(upload)
    assert windows.is_untrusted(upload) is True


def test_mark_untrusted_is_a_no_op_without_mark_of_the_web(tmp_path):
    """Off Windows there is no provenance marker; the file is left as it is."""
    from converter.platforms import posix

    upload = tmp_path / "Dropped.pptx"
    upload.write_bytes(b"pptx")
    posix.mark_untrusted(upload)
    assert upload.read_bytes() == b"pptx" and posix.is_untrusted(upload) is False
