"""Tests for slide rendering: renderer order, fallback warnings and failure issues.

PowerPoint itself can't run here, so it is replaced by fakes. LibreOffice is
real (skipped if not installed).
"""

from __future__ import annotations

import shutil
import threading
import time

import fitz
import pytest
from pptx import Presentation

from converter import platforms
from converter.context import CancelToken, JobContext
from converter.issues import Cancelled, ConversionError, IssueCode
from converter.platforms import windows_powerpoint
from converter.powerpoint import copy_for_rendering, render_slides

needs_libreoffice = pytest.mark.skipif(
    not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice not installed"
)


@pytest.fixture
def pptx(tmp_path):
    pres = Presentation()
    slide = pres.slides.add_slide(pres.slide_layouts[6])
    slide.shapes.add_textbox(
        1_000_000, 1_000_000, 7_000_000, 1_000_000
    ).text_frame.text = "Overview"
    path = tmp_path / "Deck.pptx"
    pres.save(str(path))
    return path


def use_fake_powerpoint(monkeypatch, exporter):
    monkeypatch.setattr(platforms, "export_slides_with_powerpoint", exporter)
    monkeypatch.setattr(platforms, "powerpoint_installed", lambda: True)


def test_copy_for_rendering_leaves_original_untouched(tmp_path, pptx):
    before = pptx.read_bytes()
    copy = copy_for_rendering(pptx, tmp_path / "scratch")
    assert copy.read_bytes() == before and copy != pptx and pptx.read_bytes() == before


def test_powerpoint_used_when_it_works(tmp_path, pptx, monkeypatch):
    def fake_export(source, output, timeout, cancel):
        with fitz.open() as doc:
            doc.new_page()
            doc.save(str(output))

    use_fake_powerpoint(monkeypatch, fake_export)
    ctx = JobContext()
    pdf = render_slides(pptx, tmp_path / "w", ctx, "Deck.pptx")
    assert pdf.is_file() and ctx.warnings == []


@needs_libreoffice
def test_powerpoint_failure_falls_back_with_real_error(tmp_path, pptx, monkeypatch):
    def broken(*_):
        raise RuntimeError("Protected View blocked the file")

    use_fake_powerpoint(monkeypatch, broken)
    ctx = JobContext()
    pdf = render_slides(pptx, tmp_path / "w", ctx, "Deck.pptx")
    assert pdf.is_file()
    [warning] = ctx.warnings
    assert warning.code is IssueCode.POWERPOINT_FALLBACK
    assert "Protected View" in warning.details


def test_both_renderers_failing_reports_both(tmp_path, pptx, monkeypatch):
    use_fake_powerpoint(monkeypatch, lambda *_: (_ for _ in ()).throw(RuntimeError("PP broke")))
    monkeypatch.setattr("converter.powerpoint.find_libreoffice", lambda: None)
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    assert err.value.issue.code is IssueCode.POWERPOINT_CONVERSION_FAILED
    assert "PP broke" in err.value.issue.details


def test_no_renderer_at_all(tmp_path, pptx, monkeypatch):
    monkeypatch.setattr(platforms, "export_slides_with_powerpoint", None)
    monkeypatch.setattr("converter.powerpoint.find_libreoffice", lambda: None)
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    assert err.value.issue.code is IssueCode.SLIDE_RENDERER_MISSING


def test_cancel_during_powerpoint_does_not_fall_back(tmp_path, pptx, monkeypatch):
    def cancelled(source, output, timeout, cancel):
        cancel.cancel()
        raise Cancelled()

    use_fake_powerpoint(monkeypatch, cancelled)
    with pytest.raises(Cancelled):
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")


# --- The COM renderer's thread, timeout and kill rules, with a fake export. ---


def fake_hanging_export(was_running, pid):
    def body(source, output, state):
        state["was_running"] = was_running
        if pid:
            state["pid"] = pid
        time.sleep(5)

    return body


@pytest.mark.parametrize("was_running,pid,should_kill", [(False, 4242, True), (True, None, False)])
def test_timeout_kills_only_a_powerpoint_we_started(
    tmp_path, monkeypatch, was_running, pid, should_kill
):
    killed = []
    monkeypatch.setattr(windows_powerpoint, "_export", fake_hanging_export(was_running, pid))
    monkeypatch.setattr(windows_powerpoint, "_kill", killed.append)
    started = time.monotonic()
    with pytest.raises(windows_powerpoint.PowerPointExportError) as err:
        windows_powerpoint.export_slides(
            tmp_path / "a.pptx", tmp_path / "a.pdf", 0.5, CancelToken()
        )
    assert time.monotonic() - started < 3
    assert killed == ([4242] if should_kill else [])
    assert ("left running" in str(err.value)) is (not should_kill)


def test_cancel_stops_the_com_export(tmp_path, monkeypatch):
    monkeypatch.setattr(windows_powerpoint, "_export", fake_hanging_export(False, 99))
    monkeypatch.setattr(windows_powerpoint, "_kill", lambda pid: None)
    token = CancelToken()
    threading.Timer(0.3, token.cancel).start()
    with pytest.raises(Cancelled):
        windows_powerpoint.export_slides(tmp_path / "a.pptx", tmp_path / "a.pdf", 60, token)


def test_export_error_carries_details(tmp_path, monkeypatch):
    def failing(source, output, state):
        state["was_running"] = False
        state["error"] = RuntimeError("Presentations.Open failed")
        state["traceback"] = "Traceback ..."

    monkeypatch.setattr(windows_powerpoint, "_export", failing)
    with pytest.raises(windows_powerpoint.PowerPointExportError, match="Presentations.Open failed"):
        windows_powerpoint.export_slides(tmp_path / "a.pptx", tmp_path / "a.pdf", 10, CancelToken())
