"""User-facing wording matches the platform (no Windows-only steps on Linux)."""

from __future__ import annotations

import pytest

from converter import platforms
from converter.core import issues

WINDOWS_ONLY = ("Microsoft Print to PDF", "UB-Mannheim", "AppData", "Microsoft PowerPoint")


def all_text(issue):
    return " ".join([issue.title, issue.message, *issue.troubleshooting])


def linux_issues():
    return [
        issues.ocr_install_failed(None),
        issues.powerpoint_failed("Deck.pptx", None),
        issues.slide_renderer_missing(),
        issues.settings_save_failed(None),
    ]


def test_linux_wording_has_no_windows_only_steps(monkeypatch):
    monkeypatch.setattr(platforms, "os_family", lambda: "linux")
    for issue in linux_issues():
        text = all_text(issue)
        assert not any(term in text for term in WINDOWS_ONLY), (issue.code, text)
    assert "libreoffice-impress" in all_text(issues.slide_renderer_missing())


@pytest.mark.parametrize(
    "factory,expected",
    [
        (lambda: issues.ocr_install_failed(None), "UB-Mannheim"),
        (lambda: issues.powerpoint_failed("Deck.pptx", None), "Microsoft PowerPoint"),
        (lambda: issues.slide_renderer_missing(), "libreoffice.org"),
        (lambda: issues.settings_save_failed(None), "AppData"),
    ],
)
def test_windows_wording(monkeypatch, factory, expected):
    monkeypatch.setattr(platforms, "os_family", lambda: "windows")
    assert expected in all_text(factory())
