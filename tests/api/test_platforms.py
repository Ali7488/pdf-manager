"""Tests for api.platforms: module selection and each platform's behaviour.

Every platform module is importable everywhere, so the Windows and Linux
logic is tested on any system with the OS calls replaced. Real Explorer,
winget and xdg-open are never started.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from api import dto, platforms
from api.platforms import linux, mac, windows
from api.service import IssueCode, Severity

MODULES = (windows, linux, mac)


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A fake home folder, with the XDG variables unset."""
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    return tmp_path / "home"


# ----- Selection and interface -----


def test_the_current_system_selects_its_module():
    """The package exposes exactly one module's functions, chosen by the running OS."""
    if os.name == "nt":
        expected = windows
    elif sys.platform == "darwin":
        expected = mac
    else:
        expected = linux
    for name in platforms.__all__:
        assert getattr(platforms, name) is getattr(expected, name), name


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_module_implements_the_interface(module):
    """Each platform module provides every interface function."""
    for name in platforms.__all__:
        assert callable(getattr(module, name, None)), f"{module.__name__}.{name}"


def test_platform_names_match_the_contract():
    """AppInfo.platform is one of the contract's values."""
    assert [m.platform_name() for m in MODULES] == ["windows", "linux", "mac"]


def test_picker_filters_are_the_same_everywhere():
    """pywebview's filter format works on every backend (Qt turns ';' into spaces)."""
    for module in MODULES:
        assert module.file_filters() == {
            "all": ("Supported files (*.pdf;*.pptx;*.ppt;*.png;*.jpg;*.jpeg)",),
            "documents": ("PDF and PowerPoint files (*.pdf;*.pptx;*.ppt)",),
            "images": ("Images (*.png;*.jpg;*.jpeg)",),
        }


# ----- Windows -----


def test_windows_gui_is_pywebview_default():
    """Windows doesn't force a GUI: pywebview uses Edge WebView2 as before."""
    assert windows.prepare_gui() is None


def test_windows_open_folder_uses_startfile(monkeypatch, tmp_path):
    """Folders open in Explorer through os.startfile."""
    opened = []
    monkeypatch.setattr(windows.os, "startfile", opened.append, raising=False)
    windows.open_folder(tmp_path)
    assert opened == [str(tmp_path)]


def test_windows_tesseract_picker():
    """On Windows the user picks tesseract.exe from programs."""
    assert windows.program_filters() == ("Programs (*.exe)",)
    assert windows.tesseract_file_name() == "tesseract.exe"


def test_windows_settings_dir(monkeypatch, tmp_path, home):
    """Settings live under %LOCALAPPDATA%\\PDFManager, with a fallback below home."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert windows.settings_dir() == tmp_path / "local" / "PDFManager"
    monkeypatch.delenv("LOCALAPPDATA")
    assert windows.settings_dir() == home / "AppData" / "Local" / "PDFManager"


def test_windows_logs_next_to_the_app(tmp_path):
    """The installed app logs next to itself (C4)."""
    assert windows.installed_logs_dir(tmp_path) == tmp_path / "logs"


def test_windows_install_available_with_winget(monkeypatch):
    """With winget present the app installs OCR itself."""
    monkeypatch.setattr(windows.shutil, "which", lambda name: "C:\\winget.exe")
    assert windows.ocr_install_unavailable() is None


def test_windows_install_unavailable_without_winget(monkeypatch):
    """Without winget, the issue explains the manual install."""
    monkeypatch.setattr(windows.shutil, "which", lambda name: None)
    issue = windows.ocr_install_unavailable()
    assert issue.code == IssueCode.OCR_INSTALL_FAILED
    assert "winget" in issue.details and "Search for OCR" in issue.details
    assert issue.command is None


def test_windows_run_install_reports_output(monkeypatch):
    """run_ocr_install runs winget with a 20-minute timeout and returns its output."""
    calls = []

    def fake_run(cmd, timeout=0, cancel=None):
        calls.append((list(cmd), timeout))
        return subprocess.CompletedProcess(cmd, 5, "out text", "No network")

    monkeypatch.setattr(windows.service, "run_command", fake_run)
    details = windows.run_ocr_install()
    assert calls[0][0][:4] == ["winget", "install", "--id", "UB-Mannheim.TesseractOCR"]
    assert "--silent" in calls[0][0] and calls[0][1] == 20 * 60
    assert "exit code 5" in details and "out text" in details and "No network" in details


@pytest.mark.parametrize(
    "error, needle",
    [
        (subprocess.TimeoutExpired("winget", 1), "didn't finish within 20 minutes"),
        (FileNotFoundError("winget"), "Couldn't run winget"),
    ],
)
def test_windows_run_install_failures(monkeypatch, error, needle):
    """A timeout or a missing winget becomes details text, never an exception."""

    def fake_run(cmd, timeout=0, cancel=None):
        raise error

    monkeypatch.setattr(windows.service, "run_command", fake_run)
    assert needle in windows.run_ocr_install()


# ----- Linux -----


def test_linux_gui_is_qt_with_pyside6(monkeypatch):
    """Linux asks pywebview for Qt and forces QtPy onto PySide6 (P18, P19), never PyQt6."""
    monkeypatch.setenv("QT_API", "pyqt6")
    assert linux.prepare_gui() == "qt"
    assert os.environ["QT_API"] == "pyside6"


def test_linux_open_folder_uses_xdg_open(monkeypatch, tmp_path):
    """Folders open with xdg-open, detached from the app."""
    calls = []
    monkeypatch.setattr(linux.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    linux.open_folder(tmp_path)
    args, kwargs = calls[0]
    assert args == ["xdg-open", str(tmp_path)]
    assert kwargs["start_new_session"] is True


def test_linux_tesseract_picker():
    """Linux programs have no extension, so the picker has no filter."""
    assert linux.program_filters() == ()
    assert linux.tesseract_file_name() == "tesseract"


def test_linux_settings_dir(monkeypatch, tmp_path, home):
    """Settings follow $XDG_CONFIG_HOME; relative values are ignored (XDG spec)."""
    assert linux.settings_dir() == home / ".config" / "pdf-manager"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert linux.settings_dir() == tmp_path / "config" / "pdf-manager"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
    assert linux.settings_dir() == home / ".config" / "pdf-manager"


def test_linux_installed_logs_in_xdg_state(monkeypatch, tmp_path, home):
    """The installed app logs to $XDG_STATE_HOME/pdf-manager/logs (C15), never the app folder."""
    app_dir = tmp_path / "opt" / "pdf-manager"
    assert linux.installed_logs_dir(app_dir) == home / ".local" / "state" / "pdf-manager" / "logs"
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert linux.installed_logs_dir(app_dir) == tmp_path / "state" / "pdf-manager" / "logs"
    monkeypatch.setenv("XDG_STATE_HOME", "state")
    assert linux.installed_logs_dir(app_dir) == home / ".local" / "state" / "pdf-manager" / "logs"


@pytest.mark.parametrize(
    "os_release, family",
    [
        ({"ID": "ubuntu", "ID_LIKE": "debian"}, "debian"),
        ({"ID": "debian"}, "debian"),
        ({"ID": "linuxmint", "ID_LIKE": "ubuntu debian"}, "debian"),
        ({"ID": "pop", "ID_LIKE": "ubuntu debian"}, "debian"),
        ({"ID": "arch"}, "arch"),
        ({"ID": "cachyos", "ID_LIKE": "arch"}, "arch"),
        ({"ID": "manjaro", "ID_LIKE": "arch"}, "arch"),
        ({"ID": "endeavouros", "ID_LIKE": "arch"}, "arch"),
        ({"ID": "Ubuntu"}, "debian"),
        ({"ID": "fedora"}, None),
        ({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}, None),
        ({}, None),
    ],
)
def test_linux_distribution_family(os_release, family):
    """ID, then ID_LIKE, decide the package family."""
    assert linux.distribution_family(os_release) == family


def test_linux_install_commands_are_exactly_c16():
    """The commands are exactly the ones in decision C16."""
    debian = linux.ocr_install_command({"ID": "ubuntu", "ID_LIKE": "debian"})
    arch = linux.ocr_install_command({"ID": "arch"})
    assert debian == "sudo apt install tesseract-ocr tesseract-ocr-eng"
    assert arch == "sudo pacman -S tesseract tesseract-data-eng"
    assert linux.ocr_install_command({"ID": "fedora"}) is None


@pytest.mark.parametrize(
    "os_release, command",
    [
        ({"ID": "debian"}, "sudo apt install tesseract-ocr tesseract-ocr-eng"),
        ({"ID": "cachyos", "ID_LIKE": "arch"}, "sudo pacman -S tesseract tesseract-data-eng"),
    ],
)
def test_linux_install_issue_with_command(os_release, command):
    """A known distribution gets the exact command and plain steps ending in Search for OCR."""
    issue = linux.ocr_install_issue(os_release)
    assert issue.code == IssueCode.OCR_INSTALL_FAILED
    assert issue.severity == Severity.ERROR
    assert issue.command == command
    assert "Search for OCR" in issue.troubleshooting[-1]
    assert any("Copy" in step for step in issue.troubleshooting)
    assert "sudo" not in issue.message  # The command is shown by itself, with a Copy button.
    assert os_release["ID"] in issue.details
    assert dto.issue_to_json(issue)["command"] == command


def test_linux_install_issue_unknown_distribution():
    """An unknown distribution gets no command, only the software-manager step."""
    issue = linux.ocr_install_issue({"ID": "fedora"})
    assert issue.code == IssueCode.OCR_INSTALL_FAILED
    assert issue.command is None
    assert "software manager" in issue.troubleshooting[0]
    assert "Search for OCR" in issue.troubleshooting[-1]
    assert dto.issue_to_json(issue)["command"] is None


def test_linux_install_unavailable_reads_os_release(monkeypatch):
    """ocr_install_unavailable always answers with an issue built from os-release."""
    monkeypatch.setattr(linux, "read_os_release", lambda: {"ID": "manjaro", "ID_LIKE": "arch"})
    assert linux.ocr_install_unavailable().command == "sudo pacman -S tesseract tesseract-data-eng"


def test_linux_read_os_release_missing(monkeypatch):
    """Without an os-release file the result is empty (and so: no command)."""

    def missing():
        raise OSError("no os-release")

    monkeypatch.setattr(linux.platform, "freedesktop_os_release", missing)
    assert linux.read_os_release() == {}


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Needs a real Linux system")
def test_linux_read_os_release_on_this_system():
    """On a real Linux system os-release is readable and has an ID."""
    assert linux.read_os_release().get("ID")


def test_linux_never_runs_an_install():
    """The app never runs package installs or sudo on Linux (C16)."""
    with pytest.raises(RuntimeError):
        linux.run_ocr_install()


# ----- macOS fallback -----


def test_mac_fallback(monkeypatch, tmp_path):
    """macOS opens folders with `open` and has no in-app OCR install."""
    calls = []
    monkeypatch.setattr(mac.subprocess, "Popen", lambda args, **kw: calls.append(args))
    mac.open_folder(tmp_path)
    assert calls == [["open", str(tmp_path)]]
    assert mac.prepare_gui() is None
    assert mac.installed_logs_dir(tmp_path) == tmp_path / "logs"
    assert mac.ocr_install_unavailable().code == IssueCode.OCR_INSTALL_FAILED
    with pytest.raises(RuntimeError):
        mac.run_ocr_install()


# ----- Browser mode: default browser and native pickers -----


@pytest.mark.parametrize("module", MODULES)
def test_every_platform_offers_the_browser_mode_functions(module):
    for name in (
        "default_browser",
        "open_url",
        "start_browser",
        "dialogs_available",
        "ask_files",
        "ask_folder",
    ):
        assert callable(getattr(module, name))


@pytest.mark.parametrize(
    ("progid", "expected"),
    [
        ("MSEdgeHTM", "edge"),
        ("MSEdgeBHTML", "edge"),
        ("ChromeHTML", "chrome"),
        ("BraveHTML", "brave"),
        ("ChromiumHTM", "chromium"),
        ("FirefoxURL-308046B0AF4A39CB", None),
        ("IE.HTTP", None),
        ("", None),
    ],
)
def test_windows_progids_map_to_app_mode_browsers(progid, expected):
    assert windows.classify_progid(progid) == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            '"C:\\Program Files\\Google\\Chrome\\chrome.exe" --single-argument %1',
            "C:\\Program Files\\Google\\Chrome\\chrome.exe",
        ),
        ("C:\\Chromium\\chrome.exe -- %1", "C:\\Chromium\\chrome.exe"),
        ("", None),
    ],
)
def test_windows_open_command_executable(command, expected):
    assert windows.command_executable(command) == expected


@pytest.mark.parametrize(
    ("desktop_id", "expected"),
    [
        ("microsoft-edge.desktop", "edge"),
        ("google-chrome.desktop", "chrome"),
        ("brave-browser.desktop", "brave"),
        ("com.brave.Browser.desktop", "brave"),
        ("chromium.desktop", "chromium"),
        ("chromium-browser.desktop", "chromium"),
        ("firefox.desktop", None),
        ("org.kde.falkon.desktop", None),
    ],
)
def test_linux_desktop_files_map_to_app_mode_browsers(desktop_id, expected):
    assert linux.classify_desktop_id(desktop_id) == expected


def test_linux_exec_lines_lose_their_field_codes():
    flatpak = (
        "/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=brave "
        "--file-forwarding com.brave.Browser @@u %U @@"
    )
    assert linux.desktop_exec_command(flatpak)[-1] == "com.brave.Browser"
    assert linux.desktop_exec_command("/snap/bin/chromium %U") == ("/snap/bin/chromium",)
    assert linux.desktop_exec_command('"unterminated') is None


def test_linux_default_browser_reads_the_desktop_file(monkeypatch, tmp_path):
    apps = tmp_path / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / "brave-browser.desktop").write_text(
        "[Desktop Entry]\nExec=/usr/bin/brave-browser-stable %U\n"
        "[Desktop Action new-window]\nExec=/usr/bin/brave-browser-stable --new-window\n"
    )
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(
        linux.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "brave-browser.desktop\n", ""),
    )
    browser = linux.default_browser()
    assert browser.name == "Brave" and browser.app_command == ("/usr/bin/brave-browser-stable",)


def test_linux_firefox_default_has_no_app_mode(monkeypatch):
    monkeypatch.setattr(
        linux.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, "firefox.desktop\n", ""),
    )
    assert linux.default_browser().app_command is None


def test_windows_open_dialog_results_become_paths():
    assert windows.split_open_result("C:\\a\\One.pdf") == [Path("C:\\a\\One.pdf")]
    assert windows.split_open_result("C:\\a\x00One.pdf\x00Two.pptx\x00") == [
        Path("C:\\a") / "One.pdf",
        Path("C:\\a") / "Two.pptx",
    ]
    assert windows.split_open_result("") == []


def test_windows_filter_spec():
    spec = windows.open_filter_spec(platforms.file_filters()["images"])
    assert spec == "Images\x00*.png;*.jpg;*.jpeg\x00"
    assert windows.open_filter_spec(()) is None


def test_linux_picker_commands():
    filters = platforms.file_filters()["documents"]
    zenity = linux.files_command("zenity", "/usr/bin/zenity", filters, True)
    assert (
        "--multiple" in zenity
        and "--file-filter=PDF and PowerPoint files | *.pdf *.pptx *.ppt" in zenity
    )
    kdialog = linux.files_command("kdialog", "/usr/bin/kdialog", filters, False)
    assert "*.pdf *.pptx *.ppt|PDF and PowerPoint files" in kdialog and "--multiple" not in kdialog
    assert linux.folder_command("zenity", "z", "/data")[-1] == "--filename=/data/"
    assert linux.folder_command("kdialog", "k", "/data")[-1] == "/data"


def test_linux_pickers_report_cancel_as_nothing_chosen(monkeypatch):
    monkeypatch.setattr(
        linux.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "zenity" else None
    )
    results = iter(
        [
            subprocess.CompletedProcess([], 0, "/a/One.pdf\n/a/Two.pdf\n", ""),
            subprocess.CompletedProcess([], 1, "", ""),
            subprocess.CompletedProcess([], 0, "/data/out\n", ""),
        ]
    )
    monkeypatch.setattr(linux.subprocess, "run", lambda *a, **k: next(results))
    assert linux.ask_files(("Docs (*.pdf)",), True) == [Path("/a/One.pdf"), Path("/a/Two.pdf")]
    assert linux.ask_files(("Docs (*.pdf)",), True) == []
    assert linux.ask_folder("") == Path("/data/out")


def test_linux_without_a_picker_program(monkeypatch):
    monkeypatch.setattr(linux.shutil, "which", lambda name: None)
    assert linux.dialogs_available() is False
    assert linux.ask_files(("Docs (*.pdf)",), True) == [] and linux.ask_folder("") is None


def test_filter_parsing():
    from api.platforms._common import parse_filter

    assert parse_filter("Images (*.png;*.jpg)") == ("Images", ["*.png", "*.jpg"])
    assert parse_filter("Programs") == ("Programs", ["*"])
