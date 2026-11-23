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
