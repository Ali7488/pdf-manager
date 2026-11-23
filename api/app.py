"""The desktop window: create it, show the built UI and shut down cleanly.

``main()`` is the app's entry point (see the root ``main.py``). It sets up
logging, loads the settings, creates the pywebview window with
:class:`api.bridge.Api` as its ``js_api`` and runs the GUI loop until the
window closes. Afterwards a running job is cancelled and every scratch
folder is deleted.

The GUI backend comes from the platform module: pywebview's default (Edge
WebView2) on Windows, Qt WebEngine through PySide6 on Linux (decisions P18,
P19). With ``PDF_MANAGER_SMOKE_TEST=1`` the same start-up runs, the page is
checked and the window closes again (:mod:`api.smoke`, used by CI).
"""

from __future__ import annotations

import html
import logging
import os
from pathlib import Path

import webview

from . import paths, platforms, smoke
from .bridge import Api
from .logging_setup import configure_logging, dev_mode
from .settings_store import SettingsStore

log = logging.getLogger(__name__)

WINDOW_TITLE = "PDF Manager"
WINDOW_SIZE = (1200, 800)  # Comfortable on a 1080p screen; users can resize it.
MIN_SIZE = (960, 640)  # Below this the sidebar and file list get cramped.
# Development only: load the UI from a dev server (e.g. Vite) instead of the built files.
UI_URL_ENV = "PDF_MANAGER_UI_URL"


def missing_ui_page(index: Path) -> str:
    """A simple page shown instead of a blank window when the built UI is missing.

    Args:
        index: Where the UI was expected.

    Returns:
        A self-contained HTML document.
    """
    hint = (
        "<p>Development: build the interface with <code>npm run build</code> in "
        "<code>frontend/</code>, or set <code>PDF_MANAGER_UI_URL</code> to a dev server.</p>"
        if dev_mode()
        else "<p>Please reinstall PDF Manager. Your files have not been changed.</p>"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>PDF Manager</title>"
        "<style>body{font-family:'Segoe UI',system-ui,sans-serif;margin:48px;color:#222}"
        "code{background:#f1f1f1;padding:2px 4px;border-radius:4px}</style></head><body>"
        "<h1>PDF Manager can't start</h1>"
        "<p>The app's interface files are missing.</p>"
        f"{hint}"
        f"<p><small>Expected at: <code>{html.escape(str(index))}</code></small></p>"
        "</body></html>"
    )


def ui_source() -> tuple[str | None, str | None]:
    """Decide what the window shows.

    In development mode, ``PDF_MANAGER_UI_URL`` (an ``http(s)://`` address,
    such as the Vite dev server) takes precedence. Otherwise the built UI is
    loaded straight from disk as a ``file://`` URL, so no local web server is
    started (docs/API.md, decision F18). If it's missing, a short explanation
    page is shown instead of a blank window.

    Returns:
        ``(url, None)`` to load a URL, or ``(None, html)`` for the fallback page.
    """
    override = os.environ.get(UI_URL_ENV, "").strip()
    if override:
        if not dev_mode():
            log.warning("%s is ignored outside development mode", UI_URL_ENV)
        elif override.startswith(("http://", "https://")):
            log.info("Loading the interface from %s", override)
            return override, None
        else:
            log.warning("%s must start with http:// or https://; ignoring it", UI_URL_ENV)
    index = paths.ui_index()
    if index.is_file():
        # A file:// URL: pywebview would start its own HTTP server for a plain path.
        return index.resolve().as_uri(), None
    log.error("Built interface not found at %s", index)
    return None, missing_ui_page(index)


def main() -> int:
    """Run PDF Manager until its window is closed.

    Returns:
        Process exit code: 0 after a normal close, 1 after a startup failure.
        In smoke-test mode, 0 if the check passed and non-zero otherwise.
    """
    configure_logging()
    api: Api | None = None
    try:
        store = SettingsStore(paths.settings_path())
        store.load()
        api = Api(store)
        url, page = ui_source()
        window = webview.create_window(
            WINDOW_TITLE,
            url=url,
            html=page,
            js_api=api,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=MIN_SIZE,
            # Let the UI's CSS decide what is selectable (pywebview disables
            # selection everywhere by default, which blocks copying error details).
            text_select=True,
        )
        api._bind_window(window)
        gui = platforms.prepare_gui()
        log.info("Starting the window (GUI: %s)", gui or "pywebview default")
        if smoke.enabled():
            check = smoke.SmokeCheck(window)
            check.arm()
            try:
                # No devtools: they would open a second window.
                webview.start(check.run, gui=gui, debug=False)
            finally:
                check.disarm()
            log.info("Smoke test finished with exit code %d", check.exit_code)
            return check.exit_code
        # debug=True enables the browser devtools (development mode only).
        webview.start(debug=dev_mode(), gui=gui)
        log.info("Window closed")
        return 0
    except Exception:
        log.exception("PDF Manager stopped because of an unexpected error")
        return 1
    finally:
        if api is not None:
            api._shutdown()  # Cancel a running job and delete scratch folders.
        # Log files are flushed and closed by logging's own exit handler.
