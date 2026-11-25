# Licensing

PDF Manager is free, open-source software. This page explains which licence applies to what. It's a plain-language summary, not legal advice; the licence texts themselves are what count.

| What | Licence |
| --- | --- |
| The original source code in this repository (© 2026 Mohannad Ali) | [MIT License](LICENSE) |
| The distributed application (the Windows installer and portable ZIP), which combines that code with PyMuPDF and other components | [GNU Affero General Public License v3.0](LICENSE-AGPL-3.0.txt) (AGPL-3.0) |
| Each bundled third-party component | Its own licence: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the [`licenses/`](licenses) folder |

For a component-by-component list of dependency uses, upstream license websites, verified source packages, and unresolved redistribution questions, see the [dependency license review](docs/DEPENDENCY_LICENSE_REVIEW_2026-11-23.md). The original license texts remain in the installed `licenses/` folder.

## Why the app is AGPL-3.0

PDF Manager uses [PyMuPDF](https://pymupdf.readthedocs.io/) for all PDF work. PyMuPDF is available under the AGPL-3.0 or a commercial licence from Artifex; PDF Manager uses the **AGPL-3.0 open-source route**. A program that includes PyMuPDF and is distributed to others must be distributed under the AGPL-3.0's terms, so **the distributed application as a whole is licensed under the AGPL-3.0**. It is not MIT-only.

The original code stays available under the MIT License as well: MIT is compatible with the AGPL-3.0, so anyone may reuse the original files under MIT on their own (for example in a project that doesn't include PyMuPDF). When they are part of the distributed application, the AGPL-3.0 governs that combination.

## Your rights with the app

You may use, study, share and change PDF Manager. If you distribute it, or a modified version, you must do so under the AGPL-3.0: keep the copyright and licence notices, and make the complete corresponding source code available to the people you give it to. PDF Manager comes with **absolutely no warranty**, to the extent permitted by law (sections 15 and 16 of the AGPL-3.0).

## Sources supplied with the Windows builds

The RC1 source bundles contain the following material. The open questions below describe the remaining source and redistribution review.

- **This repository at the release's tag** (for example `v0.5.0`) at <https://github.com/Ali7488/pdf-manager>: the app's own code, the user interface source, the build scripts (`packaging/`, `scripts/`), and the lockfiles that pin every third-party version: [`uv.lock`](uv.lock) (Python packages) and [`frontend/package-lock.json`](frontend/package-lock.json) (interface packages). The Python runtime, PyInstaller and Inno Setup versions are pinned in `scripts/collect_licenses.py`, `packaging/build.ps1` and `.github/workflows/build-windows.yml`.
- **The third-party source bundle attached to the release** (`PDF-Manager-third-party-sources`), made by `scripts/collect_sources.py` from those exact versions, with `SOURCES.md` and `SHA256SUMS`:
  - the source distribution of every bundled Python package (pywin32's GitHub source archive, as it publishes none);
  - **MuPDF's source release**, because PyMuPDF's own source distribution doesn't contain MuPDF (it downloads it at build time);
  - the CPython source of the bundled Python runtime, plus the libraries the python.org Windows build compiles in or ships as DLLs from outside that tarball: OpenSSL 3.5.9, libffi 3.4.4, bzip2 1.0.8, xz 5.2.5, mpdecimal 4.0.0 and zlib 1.3.1, from the `python/cpython-source-deps` tags CPython's `PCbuild/get_externals.bat` names;
  - the PyInstaller source (its bootloader is in the app's `.exe`);
  - the app's own source as a `git archive` of the exact commit the build was made from (`app/`, with `SOURCE_REVISION`);
  - the npm package of every interface package inlined into the app;
  - the editable React, React DOM and Scheduler source archives, pinned by upstream
    Git revision from the corresponding npm release metadata and verified by SHA-256.

The bundles record upstream download locations and hashes. The npm tarballs are the exact frontend build inputs. The extra upstream archives cover the React packages whose npm tarballs contain distribution builds without the editable source. These archives are planned for the next build. The published v0.5.0-rc.1 source bundles predate this addition.

## Building it yourself

See [`packaging/README.md`](packaging/README.md). In short, on Windows with uv, Node.js and Inno Setup 6 installed:

```powershell
./packaging/build.ps1
```

This builds the interface, installs the locked Python dependencies, bundles the app with PyInstaller and compiles the installer.

## The browser-mode ZIP

The browser-mode ZIP ([docs/BROWSER_MODE.md](docs/BROWSER_MODE.md)) is the same app without the desktop window's toolkit (pywebview, pythonnet, Qt, the WebView2 SDK) and without the installer. It is also distributed under the AGPL-3.0.

- **Notices:** [`THIRD_PARTY_NOTICES-browser.md`](THIRD_PARTY_NOTICES-browser.md), shipped as `THIRD_PARTY_NOTICES.md`, with exactly the licence texts of what the ZIP contains. Its build fails if a desktop-only file is bundled, or a licence text is missing or extra.
- **Sources:** its third-party sources are gathered with `scripts/collect_sources.py --platform windows --build browser`.
- **The browser:** it runs in the user's own browser, which is never shipped.
- **AGPL-3.0 section 13:** the server listens on 127.0.0.1 only, so the only user is the person running the app, who already has the source. Settings → About also links to the source of exactly the running version. A version modified to serve other people over a network (for example a future Docker image) must offer those users its own corresponding source.

**Development and test tools aren't distributed:** pytest, python-pptx, Playwright and the browser it drives, PyInstaller's build-time packages, and the frontend's build tools. Playwright (Apache-2.0) and its greenlet dependency (MIT AND Python-2.0) are in the separate `e2e` group, so they never enter a build. The PyInstaller bootloader that *is* bundled is listed in the notices.

## Notices shipped with the app

The installer puts these next to the app: `LICENSE.txt` (MIT, the original code), `LICENSE-AGPL-3.0.txt`, this file, `THIRD_PARTY_NOTICES.md` and the `licenses/` folder. In the app, **Settings → About** shows the copyright, the licence, the no-warranty notice and where to get the source, and **Open licences folder** opens these files.

`THIRD_PARTY_NOTICES.md` and `licenses/` are generated by `scripts/collect_licenses.py`. `scripts/check_licenses.py` fails the test suite when they no longer match the lockfiles, and fails the Windows build when any file in the built or installed app belongs to no listed component or the installed licence files differ from the repository's.

## Open questions

These aren't settled, and this page doesn't claim they are:

1. **WebView2 SDK and legacy interop in the desktop installer.** The desktop app carries Microsoft WebView2 SDK binaries and their license and notice. The desktop source bundle does not include the SDK source. The pywebview source archive also carries prebuilt legacy WebBrowserInterop DLLs whose matching source has not been established.
2. **Microsoft CRT in both Windows launchers.** Windows installs the Visual C++ Redistributable separately (P32). PyInstaller's MSVC bootloader statically links Microsoft CRT code into the launcher. Document the redistribution and corresponding-source treatment for that code under decision O1 before publishing stable Windows binaries.

Details and options: [`docs/LICENSING_AUDIT_2026-11-23.md`](docs/LICENSING_AUDIT_2026-11-23.md).

## About GitHub's licence label

GitHub detects `LICENSE` and labels the repository "MIT". That's accurate for the original source code; the distributed app is under the AGPL-3.0, as explained above.

## Contributing

Contributions are accepted under the MIT License, like the original code, so they can be distributed in the AGPL-3.0 application.
