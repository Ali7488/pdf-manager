# Packaging (Windows)

How PDF Manager becomes an installable Windows app: PyInstaller bundles the Python app and the built frontend into one folder, and Inno Setup wraps that folder in a simple install wizard (decisions F2, F17, F18, F19).

| File | What it does |
| --- | --- |
| `pdf-manager.spec` | PyInstaller spec: one-folder, windowed build of `main.py` into `dist\PDF Manager\`. |
| `installer.iss` | Inno Setup 6 script: the install wizard, `dist\installer\PDF-Manager-Setup-<version>.exe`. |
| `build.ps1` | Builds everything in order and stops at the first problem. |
| `../.github/workflows/build-windows.yml` | Runs `build.ps1` on GitHub Actions (manual trigger only). |

The version comes from `version` in `pyproject.toml`.

## Build on your own Windows PC

Install once:

- [uv](https://docs.astral.sh/uv/): `winget install --id astral-sh.uv -e`
- [Node.js 24 LTS](https://nodejs.org/): `winget install --id OpenJS.NodeJS.LTS -e`
- [Inno Setup 6.3 or newer](https://jrsoftware.org/isdl.php): `winget install --id JRSoftware.InnoSetup -e`

Then, from the repository folder:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

The script:

1. checks for uv, Node.js/npm and Inno Setup,
2. builds the frontend (`npm ci`, `npm run build`) into `frontend\dist`,
3. installs the locked Python dependencies (`uv sync --frozen --no-dev`),
4. runs PyInstaller (`uv run --with pyinstaller ...`; PyInstaller isn't a project dependency) into `dist\PDF Manager\`,
5. compiles the installer to `dist\installer\PDF-Manager-Setup-<version>.exe`.

To try the bundled app without installing it, run `dist\PDF Manager\PDF Manager.exe`.

## Build on GitHub Actions

The workflow runs only when started by hand (the repository is public, so standard runners are free; decision P24):

1. On GitHub, open **Actions** > **Build Windows installer**.
2. Click **Run workflow**, choose the branch, and click **Run workflow** again.
3. When it finishes (about 10 minutes), open the run and download **PDF-Manager-Setup** under **Artifacts**. It's a zip that contains the installer. Artifacts are kept for 14 days.

The run also checks licensing. `scripts/check_licenses.py` fails the build if any file in the bundle or in the installed app belongs to no component listed in `THIRD_PARTY_NOTICES.md`, or if the installed licence files differ from the repository's. A second job uploads **PDF-Manager-third-party-sources**, the third-party source code to attach to the release (see `LICENSING.md`). Nothing is published.

## The browser-mode ZIP

`packaging/build-browser.ps1` builds the portable browser-mode app (docs/BROWSER_MODE.md) as `dist\PDF-Manager-<version>-browser-windows-x64.zip`: the folder `PDF Manager (browser)` with `PDF Manager.exe`, its licences and `READ ME FIRST.txt`. It needs uv and Node.js; Inno Setup isn't needed.

- **Bundling:** `pdf-manager.spec` with `PDF_MANAGER_BUILD=browser`, from its own environment (`build\venv-browser`, `--no-group desktop`). Your `.venv` is left alone, and pywebview, pythonnet and the WebView2 SDK can't get in.
- **Checks:** `check_licenses.py bundle --build browser` checks the bundle. `stage_licenses.py --build browser` then adds exactly its licence texts, which `--installed --build browser` checks byte for byte.
- **No installer:** nothing checks for the Microsoft Visual C++ Redistributable, so `READ ME FIRST.txt` and the README say to install it first.
- **On GitHub:** the `browser-zip` job of `build-windows.yml` builds it, unzips it, checks the unzipped folder, and runs `tests/e2e` against the packaged exe with the runner's Edge. It uploads **PDF-Manager-browser-ZIP**, and the sources job uploads **PDF-Manager-browser-third-party-sources**.

## Releasing (only with the owner's approval)

1. Bump the version in `pyproject.toml`; regenerate the notices if dependencies changed (`uv run --with pip python scripts/collect_licenses.py`) and commit.
2. Tag the commit (`v<version>`) and run the workflow on the tag.
3. Create the GitHub pre-release from the tag and attach the installer, `SHA256SUMS.txt` (the installer's SHA-256) and the source bundle (as one archive).

## What the install wizard does

1. **Welcome.**
2. **Install location** (first install only). The default is `%LOCALAPPDATA%\Programs\PDF Manager`. The install is for the current user only, so no administrator rights are needed.
3. **Optional helper programs:**
   - **Tesseract OCR**: unchecked. OCR reads the words in scanned pages and pictures so they can be searched and copied.
   - **LibreOffice**: checked only if Microsoft PowerPoint isn't found; otherwise unchecked, with a note that PowerPoint was found and LibreOffice is only a backup.
   - Programs that are already installed are shown as such and greyed out.
   - Both are installed with **winget** after the app files. They install for everyone on the PC, so Windows may show a permission (UAC) prompt. If winget is missing or an install fails, setup still finishes and explains how to add them later (OCR from the app's Settings, LibreOffice from libreoffice.org).
4. **Desktop shortcut** (ticked by default). A Start menu shortcut is always added.
5. **Install**, then **Finish** with **Launch PDF Manager**.

Setup also checks for the **Microsoft Edge WebView2 Runtime**, which the app window needs. It ships with Windows 11. If it's missing, setup says so and offers Microsoft's download (`https://go.microsoft.com/fwlink/p/?LinkId=2124703`); the **Launch** box is hidden until it's installed.

### Microsoft Visual C++ Redistributable (prerequisite, not bundled)

The app doesn't ship Microsoft's Visual C++ runtime DLLs (decision P32). The Python runtime, PyMuPDF, pywin32 and cffi need `vcruntime140.dll`, `vcruntime140_1.dll` and `msvcp140.dll` (and pywin32's unused `win32ui` needs `mfc140u.dll`), so the app uses the system-wide **Microsoft Visual C++ Redistributable (x64), version 14.44 or newer**: Microsoft's recommended central deployment, serviced by Windows Update.

- **Detection.** Setup looks for those four DLLs in the 64-bit `System32` and reads their file versions; each must be 14.44 or newer (Microsoft requires the redistributable to be at least as new as the MSVC toolset that built the app; the newest toolset in the bundle is 14.44). The redistributable's registry entry (`HKLM\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64`, 32-bit view) is written to the setup log, but the files decide, because they are what Windows loads.
- **When it's missing or too old.** Setup explains, says installing it needs administrator permission, and offers to open Microsoft's permalink `https://aka.ms/vc14/vc_redist.x64.exe` in the browser; the welcome page mentions it too. Setup continues either way, asks again after installing, and hides the **Launch** box until it's there. Setup never downloads or runs the redistributable itself, and nothing Microsoft's goes into the installer.
- **If the app is started without it.** Windows can't load `python313.dll`, and PyInstaller's launcher shows "Failed to load Python DLL '…\_internal\python313.dll'" with a LoadLibrary error. Installing the redistributable fixes it.
- **Keeping it out.** `packaging/pdf-manager.spec` excludes every Visual C++ runtime DLL wherever PyInstaller collects it. `scripts/check_licenses.py bundle` fails if one is bundled again, reads every bundled binary's imports, and fails unless `installer.iss` checks for each runtime DLL they import (`VCRuntimeFiles`) and requires at least the newest linker version among them (`VCRuntimeMinMajor`/`VCRuntimeMinMinor`). Upgrades delete the old `_internal` folder first, so the DLLs an earlier build shipped don't survive an upgrade.
- **Testing.** GitHub's Windows runner already has the redistributable, so the workflow's smoke test only shows the app works with the system-wide copy. It also simulates a missing runtime with `/VCRUNTIMEDIR=<folder>` (a testing-only setup parameter that replaces `System32` in the detection) and checks that setup reports it. Neither is a clean PC: test the missing-runtime path in Windows Sandbox or on a Windows 11 PC without the redistributable (see below).

Upgrading: run a newer installer over the old one. It closes a running PDF Manager, replaces the program files and keeps settings and logs.

### "Windows protected your PC" (SmartScreen)

The installer isn't code-signed in v1 (decision F17), so Windows SmartScreen may block it the first time. Click **More info**, then **Run anyway**. Some browsers also warn when downloading an unsigned `.exe`; choose **Keep**.

## Where things are after installing

| What | Where |
| --- | --- |
| Program files | `%LOCALAPPDATA%\Programs\PDF Manager\` (`PDF Manager.exe` plus `_internal\`) |
| Logs | `%LOCALAPPDATA%\Programs\PDF Manager\logs\` (next to the app, decision C4) |
| Settings | `%LOCALAPPDATA%\PDFManager\` |
| Shortcuts | Start menu "PDF Manager", optional desktop "PDF Manager" |
| Uninstall | Settings > Apps > Installed apps > PDF Manager > Uninstall |
| Setup log | `%TEMP%\Setup Log <date> #<n>.txt` (useful when a component install fails) |

**Uninstalling** removes the program files, the shortcuts and the `logs` folder. It then asks whether to remove the settings as well (default **No**, so a reinstall keeps them). A silent uninstall keeps them.

## Testing an installed build

1. Install on a Windows 11 PC as a standard (non-admin) user. Confirm there's no UAC prompt for the app itself.
   - **Without the Visual C++ Redistributable** (Windows Sandbox starts without it; check *Installed apps* for "Microsoft Visual C++ v14 Redistributable (x64)" or "2015-2022 Redistributable (x64)"): setup must explain that it's missing, offer the download, and hide **Launch**; starting the app must show "Failed to load Python DLL". Then install `vc_redist.x64.exe` (administrator prompt), and the app must start.
   - **With it installed:** no message about it, and **Launch** is shown.
2. Open PDF Manager from the Start menu and the desktop shortcut. The window should open with no console window behind it.
3. Run each mode once (with and without OCR, with a PowerPoint file), then check `logs\` next to the app.
4. Use the "Open logs folder" button and confirm it opens the folder above.
5. Change a setting, close and reopen the app, and confirm it was kept.
6. Uninstall, answer the settings question both ways on separate runs, and check what's left.

## What the app must do for packaging to work

- Load the UI from `Path(sys._MEIPASS) / "frontend" / "dist" / "index.html"` when frozen (`getattr(sys, "frozen", False)`). In the one-folder build `sys._MEIPASS` is the `_internal` folder.
- Put the logs folder at `Path(sys.executable).parent / "logs"` when frozen, **not** under `sys._MEIPASS`.
- Keep settings in `%LOCALAPPDATA%\PDFManager` (the uninstaller asks about that folder).
- `pywebview` must be a dependency in `pyproject.toml` / `uv.lock`; `build.ps1` checks for it.
- The windowed exe has no console: `sys.stdout` and `sys.stderr` are `None`, so log to files, and start child processes with `CREATE_NO_WINDOW` (the converter's `run_command` already does).
