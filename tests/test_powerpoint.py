"""Tests for slide rendering: renderer order, fallback warnings and failure issues.

PowerPoint itself can't run here, so it is replaced by fakes. LibreOffice is
real (skipped if not installed).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pymupdf
import pytest
from pptx import Presentation

from converter import platforms
from converter.core.context import CancelToken, JobContext
from converter.core.issues import Cancelled, ConversionError, IssueCode
from converter.platforms import windows_powerpoint
from converter.slides.render import copy_for_rendering, render_slides

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
        with pymupdf.open() as doc:
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
    monkeypatch.setattr("converter.slides.render.find_libreoffice", lambda: None)
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    assert err.value.issue.code is IssueCode.POWERPOINT_CONVERSION_FAILED
    assert "PP broke" in err.value.issue.details


def test_no_renderer_at_all(tmp_path, pptx, monkeypatch):
    monkeypatch.setattr(platforms, "export_slides_with_powerpoint", None)
    monkeypatch.setattr("converter.slides.render.find_libreoffice", lambda: None)
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


# --- Audit R3: a leftover from a failed PowerPoint export is never taken as output. ---


def test_partial_powerpoint_output_is_not_accepted_when_libreoffice_fails(
    tmp_path, pptx, monkeypatch
):
    def partial_then_fail(source, output, timeout, cancel):
        output.write_bytes(b"%PDF-1.7 partial garbage")  # Non-empty leftover.
        raise RuntimeError("PowerPoint crashed mid-export")

    use_fake_powerpoint(monkeypatch, partial_then_fail)
    # A "LibreOffice" that reports success (exit code 0) but writes nothing, which
    # real LibreOffice does. Before the fix, the leftover partial PowerPoint PDF had
    # the same path as LibreOffice's expected output and was accepted as the result.
    monkeypatch.setattr("converter.slides.render.find_libreoffice", lambda: Path(sys.executable))
    monkeypatch.setattr(
        "converter.slides.render.run_command",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""),
    )
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    assert err.value.issue.code is IssueCode.POWERPOINT_CONVERSION_FAILED
    assert "crashed mid-export" in err.value.issue.details


# --- Audit R1 / decision C14: downloaded presentations never go to PowerPoint. ---


def test_untrusted_presentation_skips_powerpoint(tmp_path, pptx, monkeypatch):
    calls = []
    use_fake_powerpoint(monkeypatch, lambda *args: calls.append(args))
    monkeypatch.setattr(platforms, "is_untrusted", lambda path: True)
    if not (shutil.which("soffice") or shutil.which("libreoffice")):
        pytest.skip("LibreOffice not installed")
    ctx = JobContext()
    pdf = render_slides(pptx, tmp_path / "w", ctx, "Deck.pptx")
    assert pdf.is_file() and calls == [], "PowerPoint must not be automated"
    [warning] = ctx.warnings
    assert warning.code is IssueCode.UNTRUSTED_PRESENTATION


def test_untrusted_presentation_without_libreoffice_explains_why(tmp_path, pptx, monkeypatch):
    use_fake_powerpoint(monkeypatch, lambda *args: None)
    monkeypatch.setattr(platforms, "is_untrusted", lambda path: True)
    monkeypatch.setattr("converter.slides.render.find_libreoffice", lambda: None)
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    assert err.value.issue.code is IssueCode.SLIDE_RENDERER_MISSING
    assert "internet" in err.value.issue.message


def test_tool_check_requires_libreoffice_for_untrusted_files(tmp_path, pptx, monkeypatch):
    from converter import Action, ActionData, ActionSettings, check_tools

    monkeypatch.setattr("converter.tools.check.powerpoint_installed", lambda: True)
    monkeypatch.setattr("converter.tools.check.find_libreoffice", lambda: None)
    monkeypatch.setattr(platforms, "is_untrusted", lambda path: False)
    assert check_tools(Action.FLATTEN, ActionSettings(), ActionData([pptx])).ok
    monkeypatch.setattr(platforms, "is_untrusted", lambda path: True)
    result = check_tools(Action.FLATTEN, ActionSettings(), ActionData([pptx]))
    assert not result.ok and "internet" in result.issues[0].message


# --- Audit R2: only a provably owned PowerPoint process may be stopped. ---


@pytest.mark.parametrize(
    "was_running,before,after,window_pid,expected",
    [
        (False, set(), {500}, 500, 500),  # We started the only PowerPoint: ours.
        (True, set(), {500}, 500, None),  # Automation object already existed.
        (False, {100}, {100, 500}, 500, None),  # The user already had PowerPoint open.
        (False, set(), {500, 600}, 500, None),  # Two new processes: ambiguous.
        (False, set(), {600}, 500, None),  # Window belongs to another process.
        (False, None, {500}, 500, None),  # Process list unavailable before.
        (False, set(), None, 500, None),  # Process list unavailable after.
        (False, set(), {500}, None, None),  # Window process unknown.
    ],
)
def test_owned_pid_requires_proof(was_running, before, after, window_pid, expected):
    assert windows_powerpoint.owned_pid(was_running, before, after, window_pid) == expected


def test_parse_tasklist_pids():
    output = (
        '"POWERPNT.EXE","4242","Console","1","250,000 K"\r\n'
        '"POWERPNT.EXE","77","Console","1","90,000 K"\r\n'
    )
    assert windows_powerpoint.parse_tasklist_pids(output) == {4242, 77}
    assert (
        windows_powerpoint.parse_tasklist_pids(
            "INFO: No tasks are running which match the specified criteria."
        )
        == set()
    )
