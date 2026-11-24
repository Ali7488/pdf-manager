"""Tests for slide rendering: LibreOffice Impress is the only renderer (decision C17).

LibreOffice is real where installed (those tests skip otherwise); its failures
are simulated by replacing the command it runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from pptx import Presentation

from converter import Action, ActionData, ActionSettings, check_tools, platforms
from converter.core.context import CancelToken, JobContext
from converter.core.issues import Cancelled, ConversionError, IssueCode
from converter.slides import render
from converter.slides.render import copy_for_rendering, render_slides

needs_libreoffice = pytest.mark.skipif(
    not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice not installed"
)


@pytest.fixture
def pptx(tmp_path):
    pres = Presentation()
    for text in ("Overview", "Details"):
        slide = pres.slides.add_slide(pres.slide_layouts[6])
        box = slide.shapes.add_textbox(1_000_000, 1_000_000, 7_000_000, 1_000_000)
        box.text_frame.text = text
    path = tmp_path / "Deck.pptx"
    pres.save(str(path))
    return path


def test_copy_for_rendering_leaves_original_untouched(tmp_path, pptx):
    before = pptx.read_bytes()
    copy = copy_for_rendering(pptx, tmp_path / "scratch")
    assert copy.read_bytes() == before and copy != pptx and pptx.read_bytes() == before


@needs_libreoffice
def test_libreoffice_renders_every_slide_without_warnings(tmp_path, pptx):
    ctx = JobContext()
    pdf = render_slides(pptx, tmp_path / "w", ctx, "Deck.pptx")
    with pymupdf.open(pdf) as doc:
        assert doc.page_count == 2
        assert "Overview" in doc[0].get_text() and "Details" in doc[1].get_text()
    assert ctx.warnings == []


def test_powerpoint_is_never_part_of_the_platform_interface():
    """Decision C17: no PowerPoint automation and no provenance-based routing remain."""
    for name in (
        "export_slides_with_powerpoint",
        "powerpoint_installed",
        "powerpoint_path",
        "is_untrusted",
        "mark_untrusted",
    ):
        assert not hasattr(platforms, name), name
    root = Path(render.__file__).resolve().parents[1]
    assert not (root / "platforms" / "windows_powerpoint.py").exists()


def test_the_same_path_for_every_file_whatever_its_origin(tmp_path, pptx, monkeypatch):
    """Dropped, uploaded or picked: render_slides takes no origin and always uses LibreOffice."""
    commands = []

    def fake_libreoffice(args, **kwargs):
        commands.append([str(a) for a in args])
        out = Path(args[args.index("--outdir") + 1]) / f"{Path(args[-1]).stem}.pdf"
        with pymupdf.open() as doc:
            doc.new_page()
            doc.save(out)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(render, "find_libreoffice", lambda: Path("/opt/lo/soffice"))
    monkeypatch.setattr(render, "run_command", fake_libreoffice)
    render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    [command] = commands
    assert command[0] == str(Path("/opt/lo/soffice"))
    assert "--headless" in command and "pdf:impress_pdf_Export" in command


def test_no_libreoffice_explains_what_to_install(tmp_path, pptx, monkeypatch):
    monkeypatch.setattr(render, "find_libreoffice", lambda: None)
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    issue = err.value.issue
    assert issue.code is IssueCode.SLIDE_RENDERER_MISSING
    assert "LibreOffice" in issue.title
    assert any("PowerPoint" in step and "PDF" in step for step in issue.troubleshooting)


def test_libreoffice_failure_carries_its_output(tmp_path, pptx, monkeypatch):
    monkeypatch.setattr(render, "find_libreoffice", lambda: Path(sys.executable))
    monkeypatch.setattr(
        render,
        "run_command",
        lambda args, **kwargs: subprocess.CompletedProcess(
            args, 1, "", "Error: source file broken"
        ),
    )
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    assert err.value.issue.code is IssueCode.POWERPOINT_CONVERSION_FAILED
    assert "source file broken" in err.value.issue.details


def test_a_leftover_file_is_never_taken_as_output(tmp_path, pptx, monkeypatch):
    """Audit R3: LibreOffice can exit 0 without writing; an old file must not pass for it."""
    work = tmp_path / "w"
    stale = work / "libreoffice"
    stale.mkdir(parents=True)
    (stale / "Deck.pdf").write_bytes(b"%PDF-1.7 left over from an earlier attempt")
    monkeypatch.setattr(render, "find_libreoffice", lambda: Path(sys.executable))
    monkeypatch.setattr(
        render, "run_command", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", "")
    )
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, work, JobContext(), "Deck.pptx")
    assert err.value.issue.code is IssueCode.POWERPOINT_CONVERSION_FAILED


def test_a_timeout_is_reported_as_a_failed_conversion(tmp_path, pptx, monkeypatch):
    def hang(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs.get("timeout", 0))

    monkeypatch.setattr(render, "find_libreoffice", lambda: Path(sys.executable))
    monkeypatch.setattr(render, "run_command", hang)
    with pytest.raises(ConversionError) as err:
        render_slides(pptx, tmp_path / "w", JobContext(), "Deck.pptx")
    assert "didn't finish" in err.value.issue.details


def test_a_cancelled_job_doesnt_start_libreoffice(tmp_path, pptx, monkeypatch):
    calls = []
    monkeypatch.setattr(render, "run_command", lambda *a, **k: calls.append(a))
    cancel = CancelToken()
    cancel.cancel()
    with pytest.raises(Cancelled):
        render_slides(pptx, tmp_path / "w", JobContext(cancel=cancel), "Deck.pptx")
    assert calls == []


# --- The Convert window's tool check ---


def test_tool_check_needs_libreoffice_only_for_presentations(tmp_path, pptx, monkeypatch):
    monkeypatch.setattr("converter.tools.check.find_libreoffice", lambda: None)
    pdf = tmp_path / "Report.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(pdf)
    pdf_only = check_tools(Action.MERGE, ActionSettings(), ActionData([pdf]))
    assert pdf_only.ok and pdf_only.libreoffice.required is False and pdf_only.issues == []
    with_slides = check_tools(Action.MERGE, ActionSettings(), ActionData([pdf, pptx]))
    assert not with_slides.ok and with_slides.libreoffice.required is True
    assert [i.code for i in with_slides.issues] == [IssueCode.SLIDE_RENDERER_MISSING]
    monkeypatch.setattr("converter.tools.check.find_libreoffice", lambda: Path("/lo/soffice"))
    found = check_tools(Action.MERGE, ActionSettings(), ActionData([pdf, pptx]))
    assert found.ok and found.libreoffice.present and found.libreoffice.path == Path("/lo/soffice")


def test_pdf_only_jobs_never_look_for_libreoffice(tmp_path, monkeypatch):
    def unexpected():
        raise AssertionError("a PDF-only job looked for LibreOffice")

    monkeypatch.setattr("converter.tools.check.find_libreoffice", unexpected)
    pdf = tmp_path / "a.pdf"
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(pdf)
    assert check_tools(Action.COMPRESS, ActionSettings(), ActionData([pdf])).ok
