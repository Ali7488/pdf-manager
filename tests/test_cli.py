"""Tests for the command-line front end (cli.py) and the sample generator.

Every sample is generated once per test session; each CLI command is run
against it the way a tester would. Tests needing Tesseract or LibreOffice skip
when those aren't installed.
"""

from __future__ import annotations

import json
import shutil
import zipfile

import pymupdf
import pytest

import cli
from scripts import make_samples

needs_ocr = pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract not installed")
needs_lo = pytest.mark.skipif(
    not (shutil.which("soffice") or shutil.which("libreoffice")), reason="LibreOffice not installed"
)


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    folder = tmp_path_factory.mktemp("samples")
    make_samples.make_all(folder)
    return folder


def run(capsys, *argv):
    code = cli.main([*map(str, argv)])
    return code, capsys.readouterr().out


def test_generator_makes_every_portable_sample(samples):
    names = {p.name for p in samples.iterdir()}
    expected = set(make_samples.SAMPLES) - {"06-slides-legacy.ppt"}
    assert expected <= names
    assert (samples / "README.txt").read_text(encoding="utf-8").count(".pdf") >= 8
    with pymupdf.open(str(samples / "13-long-document.pdf")) as doc:
        assert len(doc) == 40 and len(doc.get_toc()) == 4
    with pymupdf.open(str(samples / "10-password-protected.pdf")) as doc:
        assert doc.needs_pass
    with pymupdf.open(str(samples / "02-scanned-pages.pdf")) as doc:
        assert not doc[0].get_text().strip(), "scans must have no text layer"


def test_info_describes_files(samples, capsys):
    code, out = run(capsys, "info", samples / "13-long-document.pdf", samples / "08-diagram.png")
    assert code == 0
    assert "13-long-document.pdf: pdf" in out and "pages: 40" in out and "image" in out


def test_info_reports_unsupported(tmp_path, capsys):
    other = tmp_path / "notes.txt"
    other.write_text("x")
    code, out = run(capsys, "info", other)
    assert code == 2 and "not supported" in out


def test_flatten_without_ocr(samples, tmp_path, capsys):
    code, out = run(capsys, "flatten", samples / "01-text-report.pdf", "--out", tmp_path, "-q")
    assert code == 0
    [saved] = list(tmp_path.glob("*.pdf"))
    assert saved.name == "01-text-report - Flattened.pdf"
    with pymupdf.open(str(saved)) as doc:
        assert len(doc) == 3 and all(page.get_images() for page in doc)


@needs_ocr
def test_flatten_with_ocr_json(samples, tmp_path, capsys):
    code, out = run(
        capsys,
        "flatten",
        samples / "02-scanned-pages.pdf",
        "--ocr",
        "--json",
        "--out",
        tmp_path,
        "-q",
    )
    assert code == 0
    summary = json.loads(out)
    assert summary["outputs"][0]["name"] == "02-scanned-pages - Flattened Searchable.pdf"
    with pymupdf.open(summary["saved"][0]) as doc:
        assert "Scanned" in doc[0].get_text()


def test_never_overwrites(samples, tmp_path, capsys):
    args = ["compress", samples / "09-image-heavy.pdf", "--out", tmp_path, "-q"]
    assert run(capsys, *args)[0] == 0
    assert run(capsys, *args)[0] == 0
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["09-image-heavy - Compressed (2).pdf", "09-image-heavy - Compressed.pdf"]


@needs_lo
def test_merge_with_contents(samples, tmp_path, capsys):
    code, _ = run(
        capsys,
        "merge",
        samples / "01-text-report.pdf",
        samples / "05-slides.pptx",
        samples / "12-ملف-unicode-name.pdf",
        "--contents",
        "--out",
        tmp_path,
        "-q",
    )
    assert code == 0
    [saved] = list(tmp_path.glob("*.pdf"))
    with pymupdf.open(str(saved)) as doc:
        text = doc[0].get_text()
        assert "Contents" in text and "unicode-name" in text
        all_text = "".join(page.get_text() for page in doc)
        assert "PRESENTER NOTES" not in all_text


def test_split_ranges_to_zip(samples, tmp_path, capsys):
    code, _ = run(
        capsys,
        "split",
        samples / "13-long-document.pdf",
        "--ranges",
        "1-3, 5",
        "--zip",
        "--out",
        tmp_path,
        "-q",
    )
    assert code == 0
    [archive] = list(tmp_path.glob("*.zip"))
    with zipfile.ZipFile(archive) as z:
        assert sorted(z.namelist()) == [
            "13-long-document - page 5.pdf",
            "13-long-document - pages 1-3.pdf",
        ]


@pytest.mark.parametrize("option,count", [(("--every", "10"), 4), (("--per-page",), 40)])
def test_split_every_n_and_per_page(samples, tmp_path, capsys, option, count):
    code, _ = run(
        capsys, "split", samples / "13-long-document.pdf", *option, "--out", tmp_path, "-q"
    )
    assert code == 0 and len(list(tmp_path.glob("*.pdf"))) == count


def test_split_bad_ranges_is_explained(samples, tmp_path, capsys):
    code, out = run(
        capsys, "split", samples / "13-long-document.pdf", "--ranges", "50", "--out", tmp_path, "-q"
    )
    assert code == 1 and "INVALID_PAGE_RANGES" in out and "40 pages" in out


def test_images_separate_and_upright(samples, tmp_path, capsys):
    code, _ = run(
        capsys,
        "images",
        samples / "07-photo-portrait.jpg",
        samples / "08-diagram.png",
        "--separate",
        "--out",
        tmp_path,
        "-q",
    )
    assert code == 0
    photo = tmp_path / "07-photo-portrait.pdf"
    with pymupdf.open(str(photo)) as doc:
        rect = doc[0].rect
        assert rect.width > rect.height, "EXIF rotation must make the sideways photo upright"
    assert (tmp_path / "08-diagram.pdf").is_file()


@pytest.mark.parametrize(
    "name,code_name", [("10-password-protected.pdf", "PASSWORD_PROTECTED"), ("11-damaged.pdf", "")]
)
def test_error_samples_give_clear_issues(samples, tmp_path, capsys, name, code_name):
    code, out = run(capsys, "merge", samples / name, "--out", tmp_path, "-q")
    assert code == 1 and "[ERROR]" in out and "1. " in out
    assert code_name in out
    assert not list(tmp_path.glob("*.pdf")), "nothing is saved when a job fails"


def test_tools_reports_requirements(samples, capsys):
    code, out = run(capsys, "tools", "compress", samples / "09-image-heavy.pdf")
    assert code == 0 and "OK: the job can start." in out
    assert "ocr          not needed" in out


def test_tools_blocks_when_ocr_missing(samples, capsys, monkeypatch):
    monkeypatch.setattr("converter.tools.check.find_tesseract", lambda configured=None: None)
    code, out = run(capsys, "tools", "flatten", samples / "01-text-report.pdf", "--ocr")
    assert code == 2 and "OCR_MISSING" in out and "BLOCKED" in out


def test_usage_errors_exit_2(capsys):
    with pytest.raises(SystemExit) as err:
        cli.main(["compress", "x.pdf", "--level", "extreme"])
    assert err.value.code == 2


@pytest.mark.parametrize(
    "option",
    [("--dpi", "0"), ("--dpi", "601"), ("--ocr-timeout", "5"), ("--every", "0"), ("--dpi", "x")],
)
def test_out_of_range_numbers_are_usage_errors(samples, tmp_path, capsys, option):
    with pytest.raises(SystemExit) as err:
        cli.main(["split", str(samples / "13-long-document.pdf"), *option, "--out", str(tmp_path)])
    assert err.value.code == 2
    message = capsys.readouterr().err
    assert "must be" in message or "whole number" in message
