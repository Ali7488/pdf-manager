# Licensing

PDF Manager is free, open-source software. This page explains which licence applies to what. It's a plain-language summary, not legal advice; the licence texts themselves are what count.

| What | Licence |
| --- | --- |
| The original source code in this repository (© 2026 Mohannad Ali) | [MIT License](LICENSE) |
| The distributed application (the Windows installer, and the Linux packages from v0.75), which combines that code with PyMuPDF and other components | [GNU Affero General Public License v3.0](LICENSE-AGPL-3.0.txt) (AGPL-3.0) |
| Each bundled third-party component | Its own licence: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and the [`licenses/`](licenses) folder |

## Why the app is AGPL-3.0

PDF Manager uses [PyMuPDF](https://pymupdf.readthedocs.io/) for all PDF work. PyMuPDF is available under the AGPL-3.0 or a commercial licence from Artifex; PDF Manager uses the **AGPL-3.0 open-source route**. A program that includes PyMuPDF and is distributed to others must be distributed under the AGPL-3.0's terms, so **the distributed application as a whole is licensed under the AGPL-3.0**. It is not MIT-only.

The original code stays available under the MIT License as well: MIT is compatible with the AGPL-3.0, so anyone may reuse the original files under MIT on their own (for example in a project that doesn't include PyMuPDF). When they are part of the distributed application, the AGPL-3.0 governs that combination.

## Your rights with the app

You may use, study, share and change PDF Manager. If you distribute it, or a modified version, you must do so under the AGPL-3.0: keep the copyright and licence notices, and make the complete corresponding source code available to the people you give it to. PDF Manager comes with **absolutely no warranty**, to the extent permitted by law (sections 15 and 16 of the AGPL-3.0).

## Complete corresponding source

For each release, the complete corresponding source is:

- **This repository at the release's tag** (for example `v0.5.0`) at <https://github.com/Ali7488/pdf-manager>: the app's own code, the user interface source, the build scripts (`packaging/`), and the lockfiles.
- **The exact third-party versions**, pinned by [`uv.lock`](uv.lock) (Python packages) and [`frontend/package-lock.json`](frontend/package-lock.json) (interface packages), with the PyInstaller version pinned in [`packaging/build.ps1`](packaging/build.ps1). Their source is published by their projects on PyPI and npm; PyMuPDF's source distribution is also attached to each GitHub release.

## Building it yourself

See [`packaging/README.md`](packaging/README.md). In short, on Windows with uv, Node.js and Inno Setup 6 installed:

```powershell
./packaging/build.ps1
```

This builds the interface, installs the locked Python dependencies, bundles the app with PyInstaller and compiles the installer.

## Notices shipped with the app

The installer puts these next to the app: `LICENSE.txt` (MIT, the original code), `LICENSE-AGPL-3.0.txt`, this file, `THIRD_PARTY_NOTICES.md` and the `licenses/` folder. In the app, **Settings → About** shows the copyright, the licence, the no-warranty notice and where to get the source, and **Open licences folder** opens these files.

## Contributing

Contributions are accepted under the MIT License, like the original code, so they can be distributed in the AGPL-3.0 application.
