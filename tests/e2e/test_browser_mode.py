"""Browser mode end to end: the production interface in a real browser, the real backend.

Starts ``main.py --browser --no-browser`` (server only: the browser's own file
chooser and downloads, no native pickers) with its own settings folder, and
drives it with Playwright in headless Chromium. Nothing is mocked: real
conversions on synthetic files, real uploads and downloads.

    uv sync --group e2e && uv run playwright install chromium
    uv run pytest tests/e2e

``PDF_MANAGER_E2E_BROWSER`` can point at another Chromium-family browser
(Edge, Chrome, Brave). ``PDF_MANAGER_E2E_APP`` runs the tests against a built
browser-mode app (``dist/PDF Manager (browser)/PDF Manager``) instead of the
source. The tests skip when Playwright or the built interface (``frontend/dist``)
is missing; the OCR and PowerPoint cases also need Tesseract and LibreOffice.
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import fitz
import pytest

from tests.helpers import scanned_pdf, text_pdf

playwright = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    not (ROOT / "frontend" / "dist" / "index.html").is_file(),
    reason="build the interface first (cd frontend && npm run build)",
)
DONE_TIMEOUT_MS = 120_000


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Server:
    """``main.py --browser --no-browser`` in a subprocess with its own settings."""

    def __init__(self, home: Path):
        self.home = home
        self.proc: subprocess.Popen | None = None
        self.url = ""

    def start(self) -> str:
        url_file = self.home / "url.txt"
        url_file.unlink(missing_ok=True)
        env = {**os.environ, "XDG_CONFIG_HOME": str(self.home), "LOCALAPPDATA": str(self.home)}
        # PDF_MANAGER_E2E_APP: a built browser-mode app (its PDF Manager executable) to
        # test instead of the source.
        built = os.environ.get("PDF_MANAGER_E2E_APP")
        start = [built] if built else [sys.executable, "main.py", "--browser"]
        self.proc = subprocess.Popen(
            [*start, "--no-browser", "--url-file", str(url_file)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not url_file.is_file():
            if self.proc.poll() is not None:
                raise RuntimeError("browser mode exited at start-up")
            time.sleep(0.1)
        self.url = url_file.read_text()
        return self.url

    @property
    def origin(self) -> str:
        return self.url.split("/?")[0]

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                self.proc.kill()


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        try:
            instance = p.chromium.launch(
                headless=True, executable_path=os.environ.get("PDF_MANAGER_E2E_BROWSER") or None
            )
        except Exception as exc:  # No browser installed for Playwright.
            pytest.skip(f"no browser for Playwright: {exc}")
        yield instance
        instance.close()


@pytest.fixture
def server(tmp_path):
    instance = Server(tmp_path / "home")
    instance.home.mkdir()
    instance.start()
    yield instance
    instance.stop()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(accept_downloads=True)
    tab = context.new_page()
    tab.requests = []
    tab.on("request", lambda request: tab.requests.append(request.url))
    tab.downloads = []
    tab.on("download", lambda download: tab.downloads.append(download))
    origin = server.origin
    tab.goto(server.url)
    tab.get_by_role("navigation", name="Main").wait_for()
    yield tab
    # No document, font or script ever came from anywhere but the app.
    outside = [u for u in tab.requests if not u.startswith((origin, "blob:", "data:"))]
    assert outside == []
    context.close()


@pytest.fixture
def inputs(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    files = {
        "a": text_pdf(folder / "Alpha.pdf", ["A1", "A2", "A3", "A4", "A5"], toc=[[1, "Start", 1]]),
        "b": text_pdf(folder / "Beta.pdf", ["B1", "B2"]),
    }
    for name, fmt in (("Photo.png", "png"), ("Picture.jpg", "jpeg")):
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), False)
        pix.clear_with(200)
        (folder / name).write_bytes(pix.tobytes(fmt))
        files[name] = folder / name
    hashes = {name: sha256(path) for name, path in files.items()}
    yield files
    assert {name: sha256(path) for name, path in files.items()} == hashes, "originals changed"


def go(page, label: str) -> None:
    page.get_by_role("navigation", name="Main").get_by_role(
        "button", name=label, exact=True
    ).click()


def add(page, *paths: Path) -> None:
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Add files").or_(
            page.get_by_role("button", name="Add images")
        ).first.click()
    chooser.value.set_files([str(p) for p in paths])
    for path in paths:
        page.get_by_text(path.name, exact=True).first.wait_for()


def convert(page) -> None:
    page.get_by_role("button", name="Convert").click()
    page.get_by_role("heading", name="Done").wait_for(timeout=DONE_TIMEOUT_MS)


def download(page, tmp_path: Path, button: str = "Download", count: int = 1) -> list[Path]:
    before = len(page.downloads)
    page.get_by_role("dialog").get_by_role("button", name=button, exact=True).click()
    deadline = time.monotonic() + 30
    while len(page.downloads) < before + count and time.monotonic() < deadline:
        page.wait_for_timeout(100)
    saved = []
    for item in page.downloads[before:]:
        target = tmp_path / "downloads" / item.suggested_filename
        item.save_as(target)
        saved.append(target)
    assert len(saved) == count
    return saved


def pages(path: Path) -> int:
    with fitz.open(path) as doc:
        return doc.page_count


def done(page) -> None:
    page.get_by_role("dialog").get_by_role("button", name="Done").click()
    page.get_by_role("dialog").wait_for(state="detached")


# ----- Start-up -----


def test_the_production_interface_runs_against_the_real_app(page, server):
    html = page.content()
    assert 'name="pdf-manager-mode"' in html and "data-native-dialogs" in html
    go(page, "Settings")
    page.get_by_text("Version 0.5.0", exact=False).or_(
        page.get_by_text("version 0.5.0")
    ).first.wait_for()
    page.get_by_role("button", name="Quit PDF Manager").wait_for()


def test_the_launch_link_works_only_once(browser, server, page):
    other = browser.new_context()
    tab = other.new_page()
    tab.goto(server.url)
    assert "already been used" in tab.content()
    other.close()


# ----- The six actions -----


def test_flatten_and_download(page, inputs, tmp_path):
    go(page, "Flatten")
    add(page, inputs["a"])
    convert(page)
    (result,) = download(page, tmp_path)
    assert result.name == "Alpha - Flattened.pdf" and pages(result) == 5
    with fitz.open(result) as doc:
        assert doc[0].get_text().strip() == ""  # Pages became images.
    done(page)


def test_flatten_merge_keeps_the_list_order(page, inputs, tmp_path):
    go(page, "Flatten + Merge")
    add(page, inputs["b"], inputs["a"])
    convert(page)
    (result,) = download(page, tmp_path)
    assert pages(result) == 7


def test_merge_keeps_text_and_bookmarks(page, inputs, tmp_path):
    go(page, "Merge")
    add(page, inputs["a"], inputs["b"])
    convert(page)
    (result,) = download(page, tmp_path)
    with fitz.open(result) as doc:
        assert doc.page_count == 7 and "A1" in doc[0].get_text() and "B1" in doc[5].get_text()
        assert any(entry[1] == "Start" for entry in doc.get_toc())


def test_split_by_ranges_as_one_zip(page, inputs, tmp_path):
    go(page, "Split")
    add(page, inputs["a"])
    page.get_by_label("Pages", exact=True).fill("1-2, 4")
    convert(page)
    (archive,) = download(page, tmp_path, "Download as one .zip")
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist()) == 2


def test_split_every_few_pages_as_files(page, inputs, tmp_path):
    go(page, "Split")
    add(page, inputs["a"])
    page.get_by_text("Every few pages", exact=True).click()
    page.get_by_label("Pages in each file").fill("2")
    convert(page)
    results = download(page, tmp_path, count=3)
    assert sorted(pages(p) for p in results) == [1, 2, 2]


def test_images_to_pdf(page, inputs, tmp_path):
    go(page, "Images to PDF")
    add(page, inputs["Photo.png"], inputs["Picture.jpg"])
    convert(page)
    (result,) = download(page, tmp_path)
    assert pages(result) == 2


def test_compress(page, inputs, tmp_path):
    go(page, "Compress")
    add(page, inputs["a"])
    page.get_by_text("Strong").click()
    convert(page)
    (result,) = download(page, tmp_path)
    assert pages(result) == 5


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="needs Tesseract")
def test_flatten_with_ocr_is_searchable(page, tmp_path):
    scan = scanned_pdf(tmp_path / "Scan.pdf", ["Hello searchable world"])
    go(page, "Flatten")
    add(page, scan)
    page.get_by_text("Use OCR").click()
    convert(page)
    (result,) = download(page, tmp_path)
    with fitz.open(result) as doc:
        assert "searchable" in doc[0].get_text().lower()


@pytest.mark.skipif(
    shutil.which("soffice") is None and shutil.which("libreoffice") is None,
    reason="needs LibreOffice",
)
def test_a_dropped_presentation_is_converted(page, tmp_path):
    from pptx import Presentation

    deck = Presentation()
    for title in ("One", "Two"):
        deck.slides.add_slide(deck.slide_layouts[0]).shapes.title.text = title
    path = tmp_path / "Deck.pptx"
    deck.save(path)
    go(page, "Flatten")
    drop(page, path)
    convert(page)
    (result,) = download(page, tmp_path)
    assert pages(result) == 2


# ----- Files, the job's life, settings and the app -----


def drop(page, path: Path) -> None:
    """Drop a file onto the window, as dragging it from the desktop does."""
    page.evaluate(
        """async ({ name, data }) => {
            const bytes = Uint8Array.from(atob(data), (c) => c.charCodeAt(0));
            const transfer = new DataTransfer();
            transfer.items.add(new File([bytes], name));
            for (const type of ["dragenter", "dragover", "drop"]) {
                const init = { dataTransfer: transfer, bubbles: true, cancelable: true };
                window.dispatchEvent(new DragEvent(type, init));
            }
        }""",
        {"name": path.name, "data": base64.b64encode(path.read_bytes()).decode()},
    )
    page.get_by_text(path.name, exact=True).first.wait_for()


def test_dropped_and_chosen_files_share_one_list(page, inputs, tmp_path):
    go(page, "Merge")
    drop(page, inputs["b"])
    add(page, inputs["a"])
    # Dropping the same file again is a new upload with its own ID (decision P34).
    drop(page, inputs["b"])
    page.get_by_text("Beta.pdf", exact=True).nth(1).wait_for()
    assert page.get_by_text("Beta.pdf", exact=True).count() == 2
    convert(page)
    (result,) = download(page, tmp_path)
    with fitz.open(result) as doc:
        first_pages = [sheet.get_text() for sheet in doc]
    beta, alpha = pages(inputs["b"]), pages(inputs["a"])
    assert len(first_pages) == 2 * beta + alpha
    assert "B1" in first_pages[0] and "B1" in first_pages[beta + alpha]  # The list's order.


def long_pdf(tmp_path: Path) -> Path:
    return text_pdf(tmp_path / "Long.pdf", [f"Page {n}" for n in range(1, 241)])


def test_cancel_a_running_job(page, tmp_path):
    go(page, "Flatten")
    add(page, long_pdf(tmp_path))
    page.get_by_role("button", name="Convert").click()
    page.get_by_role("progressbar", name="Conversion progress").wait_for()
    page.get_by_role("button", name="Cancel").click()
    page.get_by_role("heading", name="Cancelled").wait_for(timeout=DONE_TIMEOUT_MS)


def test_a_reload_during_a_job_shows_it_again(page, tmp_path):
    go(page, "Flatten")
    add(page, long_pdf(tmp_path))
    page.get_by_role("button", name="Convert").click()
    page.get_by_role("progressbar", name="Conversion progress").wait_for()
    page.reload()
    page.get_by_role("heading", name="Converting").or_(
        page.get_by_role("heading", name="Done")
    ).first.wait_for()
    page.get_by_role("heading", name="Done").wait_for(timeout=DONE_TIMEOUT_MS)
    (result,) = download(page, tmp_path)
    assert pages(result) == 240


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def test_settings_survive_a_restart(browser, server, page):
    go(page, "Settings")
    page.get_by_text("Dark", exact=True).click()
    settings = server.home / "pdf-manager" / "settings.json"
    if not settings.parent.is_dir():  # Windows: %LOCALAPPDATA%\PDFManager.
        settings = server.home / "PDFManager" / "settings.json"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and '"dark"' not in _text(settings):
        page.wait_for_timeout(100)
    assert '"dark"' in _text(settings), "the setting wasn't saved"
    server.stop()
    server.start()
    tab = browser.new_page()
    tab.goto(server.url)
    tab.get_by_role("navigation", name="Main").get_by_role("button", name="Settings").click()
    assert tab.get_by_role("radio", name="Dark").is_checked()
    tab.close()


def test_a_lost_connection_is_reported(page, server):
    server.stop()
    go(page, "Settings")  # Settings asks the app for the OCR status, which fails.
    page.get_by_role("heading", name="Lost contact with PDF Manager").wait_for(timeout=30_000)


def test_quit_closes_the_app(page, server):
    go(page, "Settings")
    page.get_by_role("button", name="Quit PDF Manager").click()
    page.get_by_role("heading", name="PDF Manager has closed").wait_for()
    assert server.proc.wait(15) == 0
