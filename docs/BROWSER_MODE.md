# Browser mode

PDF Manager can run in the user's own web browser instead of its desktop window (decision P33). It uses the same interface, the same conversion engine, and the same jobs, settings and safe saving (`api/workflow.py`), reached through a small HTTP API on `127.0.0.1` instead of pywebview. The desktop window (`uv run main.py`) is unchanged and stays available for comparison.

## Which window it opens in

PDF Manager opens in the **default browser**. It never installs, chooses or forces another one.

| Default browser | What opens |
| --- | --- |
| **Microsoft Edge, Google Chrome, Brave or Chromium** | Its own window with no tabs or address bar (**app mode**, `--app=<url>`). |
| **Any other browser** (Firefox, Safari, Vivaldi, Opera, …), or a Chromium browser whose program can't be found | A **normal tab** at a local address, `http://127.0.0.1:<port>/`. Everything still stays on the computer. |

So app mode **expects Edge or a Chromium-based browser as the default**. With any other default, PDF Manager is a normal localhost tab.

- **Windows:** the default comes from the `https` (then `http`) link association, recognised by its ProgId: `MSEdgeHTM`, `ChromeHTML`, `BraveHTML`, `ChromiumHTM` and their beta/dev variants.
- **Linux:** the default comes from `xdg-settings get default-web-browser` and that browser's `.desktop` file (Flatpak and Snap launchers included).
- **macOS:** always a tab.

## Running it

| Who | Command |
| --- | --- |
| Development | `uv run main.py --browser` (build the interface first: `cd frontend && npm run build`) |
| Server only (tests, headless) | `uv run main.py --browser --no-browser`; prints a single-use link (`--url-file <path>` writes it to a private file) |
| End users (Windows) | Unzip `PDF-Manager-<version>-browser-windows-x64.zip` and double-click `PDF Manager.exe`. `READ ME FIRST.txt` explains the Visual C++ Redistributable prerequisite. |

- Browser mode needs only PyMuPDF (and pywin32 on Windows): `uv sync --no-group desktop`. It never imports pywebview, Qt or pythonnet (a test enforces this).
- **One instance per profile (decision P41):** each start first takes an exclusive lock (`browser-mode.lock` next to the settings; `flock` on Linux, `msvcrt.locking` on Windows). Starting it again, even twice at the same moment, opens a new window onto the one running instance. The system releases the lock when an instance dies, so after a crash or a killed process the next start simply runs a new one.
- **Quitting:** use **Settings → Quit PDF Manager**, Ctrl+C or a termination signal. If a conversion is running or a finished result isn't saved yet, Quit says so and asks before deleting it (decision P35).
- **Idle shutdown:** it quits by itself after an hour without requests, but only while nothing is running and no finished result is unsaved. A result saved to a folder no longer counts once its files are written. A result sent to the browser's downloads stays unsaved until **Done** or **Discard** (decision P39), because the app can't know the browser saved it. The loop is `launch.wait_for_stop`.
- **One result at a time (decision P40):** while a finished result is unsaved, a new conversion is refused with `RESULT_PENDING`; the Convert window explains why and offers **Show the results**, which opens it (in its own tab) for Save, Download or Discard. The job manager's one pending result is what a reload shows, what idle shutdown waits for and what Quit asks about. Done or Discard also deletes the job's download copies, fetched or not.
- **Closing the window doesn't quit it.** A browser may hand the window to an already running process, or keep running itself, so the app doesn't rely on the browser exiting.

## Files, saving and Office

| | With native pickers | Without (macOS, Linux without zenity/kdialog, `--no-native-dialogs`, `--no-browser`) |
| --- | --- | --- |
| **Add files** | The system's Open dialog (pywin32 on Windows; zenity or kdialog on Linux). The app keeps the original paths. | The browser's file chooser. Files are uploaded as working copies. |
| **Drag and drop** | Uploaded as working copies (browsers never reveal a file's path). | The same. |
| **Save** | The system's folder picker, or the default save folder, never overwriting. | **Download**: results go to the browser's downloads. They stay in the app for **Download again** until the user clicks Done. |

- **Uploads** are staged in a private temporary folder that is deleted on quit. Originals are never touched.
- **One UUID per upload (decision P34).** Every upload gets a fresh, server-generated UUID. It names its private folder (`uploads/<uuid>/<name>`) and is its ID (`f-<uuid>`), so two uploads never share a copy or an ID. That holds even for the same file sent twice, or different files with the same name, size and date. The original name is kept for display and output names. The body goes to a hidden partial file, is renamed into place and checked; only then is the ID published. A failed upload's folder is deleted, and a retry is a new upload. A file already in the list keeps its ID for every later conversion.
- **Presentations always use LibreOffice Impress (decision C17)**, whether dropped, uploaded or picked with **Add files**. No provenance marker is added or read to choose a renderer.
- **Reloads (decision P36).** The page asks for the newest job not yet closed with **Done**, including how its results were saved. A job saved to a folder comes back as saved (**Open folder**, **Done**), never with a Save button whose results are gone. A download keeps **Download again** (as one .zip if it was) until **Done**.

## Security

The page can only call the operations listed in `api/web/server.py` (`ROUTES`). Each one checks its input in `api/web/operations.py`:

- **Loopback only:** the server listens on `127.0.0.1`, on a port the system picks. Every request must use exactly that `Host`, which defeats DNS rebinding.
- **Session:** the app opens a **single-use launch link**, which sets an HttpOnly, SameSite=Strict session cookie and redirects to `/`. The session secret never appears in a URL, a log or a referrer.
- **Same origin only:** API requests also need the `X-PDF-Manager: 1` header (no CORS is ever approved), an `Origin` equal to the app's for POSTs, and `Sec-Fetch-Site: same-origin` when the browser sends it.
- **No host paths from the page:**
  - files are opaque IDs from a pick or an upload;
  - saving goes only to a folder the user picked, or the saved default folder;
  - "open folder" only opens folders the app showed for that purpose;
  - the Tesseract path and other programs are never taken from the page.
- **Limits:**
  - at most 24 requests at once;
  - 30 s socket reads;
  - JSON bodies up to 256 KiB, uploads up to 2 GiB;
  - no changes accepted while closing;
  - an unread request body closes the connection, so it can't be read as the next request.
- **The page itself:** a CSP of `'self'` only, with `frame-ancestors 'none'` and no external requests (the browser tests check this).

## Status and errors

Python's job status is the source of truth.

- **Polling:** while a job or an OCR install runs, the page polls it (`GET /api/jobs/<id>`) and dispatches the same events the desktop window gets.
- **Retries:** a start that gets no answer is retried with the same request ID, so it can't start twice.
- **Reload:** after a reload, the page finds the newest job not yet discarded and shows it again.
- **Connection loss:** if the app stops answering, the Convert window offers **Try again**, and the rest of the page explains how to restart it.

## Testing

| What | Where | Command |
| --- | --- | --- |
| Server, session, security, uploads, jobs, launch | `tests/api/test_web.py` | `uv run pytest tests/api/test_web.py` |
| Default browser and pickers | `tests/api/test_platforms.py` | part of `uv run pytest` |
| HTTP client and Convert window | `frontend/src/api/http.test.ts`, `ConvertModal.browser.test.tsx` | `npm test` |
| Real browser to real backend, all six actions, no mock | `tests/e2e/` | `uv sync --group e2e && uv run playwright install chromium && uv run pytest tests/e2e` |
| The packaged ZIP, end to end with Edge | `.github/workflows/build-windows.yml` (`browser-zip`) | manual workflow |

Set `PDF_MANAGER_E2E_BROWSER` to use an installed Chromium-family browser, and `PDF_MANAGER_E2E_APP` to test a built app instead of the source.

The owner reported passing PDF workflows on a Windows 11 VM using RC1. The report did not enumerate individual scenarios. These checks remain without a recorded result for the exact release candidate:

- **Default browser and app mode:** a real app-mode launch from the user's default browser (Edge, Chrome, Brave), a cold and an already running browser, and a Firefox default (a tab). Also whether a firewall prompt appears; none is expected for loopback.
- **Native pickers:** whether they come to the front of the browser window, cancel cleanly and return focus.
- **Presentations:** conversion with LibreOffice installed (dropped and picked with **Add files**), and the explanation shown when it is missing (as soon as a presentation is added, and in the Convert window). Run `scripts/check_slide_fidelity.py` there too (docs/PRESENTATION_FIDELITY.md).
- **OCR:** install Tesseract and confirm that the text from a scanned PDF is searchable and selectable.
- **The ZIP on a clean PC:** without the Visual C++ Redistributable, run as a standard user.
- **Not tested at all:** Linux desktops other than this development PC (KDE/kdialog, Ubuntu/zenity), and macOS.

## Packaging and licences

- **The build:** `packaging/build-browser.ps1` builds the portable ZIP. It uses `pdf-manager.spec` with `PDF_MANAGER_BUILD=browser`, from an environment without the desktop group.
- **What the ZIP leaves out:** pywebview, pythonnet, clr-loader, Qt/PySide6, the WebView2 SDK files and the installer. The browser itself stays outside the app.
- **Its licences:** it ships `THIRD_PARTY_NOTICES-browser.md` (as `THIRD_PARTY_NOTICES.md`) and exactly the licence texts of what it contains. `scripts/check_licenses.py bundle --build browser` fails otherwise.
- **Its sources:** `scripts/collect_sources.py --build browser` gathers the corresponding third-party source.
- **The AGPL:** PyMuPDF/MuPDF keep the app under the AGPL-3.0 (P31); see LICENSING.md. Settings → About links to the source of exactly the running version.
- **No Linux ZIP yet:** the Linux build's Python runtime source isn't pinned, so a Linux ZIP couldn't be shipped with its corresponding source.

**Later, not in this version:** a Docker image using the same server, headless with no native pickers, Office or host browser, and with explicit writable volumes.
