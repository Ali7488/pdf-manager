# Windows redistribution: Microsoft runtime and WebView2 resolution

**Date:** 2026-11-23  
**Application:** PDF Manager 0.5 (Windows)  
**Status:** Research and implementation plan; **no public distribution approval**.

## Decision

Keep the existing MIT grant for original project files, preserve the GNU AGPL-3.0 route for the combined application with PyMuPDF/MuPDF, and avoid a premature rewrite of the PDF converter.

Resolve the independent Windows issues separately:

1. **Visual C++ runtime: remove app-local Microsoft runtime DLLs and depend on a separately installed Microsoft Visual C++ Redistributable (x64).** The prerequisite must be explicit and the app must fail gracefully when missing.
2. **WebView2: leave the current Windows backend unchanged for private testing while seeking authoritative clarification.** The matching SDK package grants BSD-style binary redistribution with notices; that does **not** conclusively establish the combined AGPL application's Corresponding Source treatment. If a defensible interpretation or appropriate written permission cannot be obtained, **use the Qt/PySide6 backend on Windows** as an independently testable alternative, with complete Qt/Chromium compliance work.
3. **Release:** Do not publish until the owner approves the chosen solution and validates the artifact on a real Windows machine. A green runner smoke test alone is not sign-off.

This document records what the vendor/license sources say and what still requires a legal determination. It does not grant a license or purport to resolve legal ambiguity by description.

## Windows Visual C++ runtime: practical fix

**Current app:** the packaging spec keeps `vcruntime140.dll`, `vcruntime140_1.dll` and `MSVCP140.dll` inside the PyInstaller application. The build's native-file license check maps these to the Visual C++ runtime entry. The Microsoft UCRT and unused MFC DLLs were already excluded.

**Microsoft's policy:** its deployment documentation recommends *central deployment* of the Visual C++ Redistributable rather than app-local runtime DLLs, using a system-wide install in `%windir%\system32`. This requires administrator rights. It also states that redistribution of Microsoft runtime packages and individual binaries is limited by Visual Studio license rights. GNU's GPL FAQ explicitly distinguishes a Visual C++ runtime installed as a System Library from DLLs bundled with a GPL program. The exception's applicability to a given binary remains a legal matter.

**Recommended implementation on an isolated branch:**

- Modify `packaging/pdf-manager.spec` to exclude app-local `vcruntime140*.dll`, `msvcp140*.dll`, and any other Microsoft Visual C++ DLLs unexpectedly collected anywhere under the app folder. Do **not** remove `python313.dll` or application-owned PyMuPDF binaries.
- Update `scripts/check_licenses.py` to **fail** if the excluded Microsoft runtime DLLs are found anywhere in the output, including nested locations. Exclude them from the packaged runtime inventory rather than leaving a false claim that PDF Manager bundles them.
- In `packaging/installer.iss`, check the **x64 Visual C++ 2015-2022/v14 runtime** or otherwise perform a reliable DLL availability check before the user launches the application. A registry check for installed redistributable is useful but must account for application compatibility and versions. When missing, explain the prerequisite and open Microsoft's official [latest supported redistributable downloads](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/) page. Do not download an unknown third-party DLL or bundle `vc_redist.x64.exe` without separately verifying the distributor's Microsoft licensing rights.
- Preserve the per-user PDF Manager installer, but **explain that first-time installation of the system-wide Microsoft prerequisite may require administrator permission**. Do not silently claim the complete installation is admin-free in that case.
- Update user-facing notices, the dependency inventory, install troubleshooting and Windows pre-release notes to distinguish a separately installed prerequisite from files actually packaged by the application.
- Test the installer on a Windows virtual machine *without* the redistributable, a machine *with* the supported version and a real Windows 11 device. Verify the post-prerequisite app works and that app updates do not copy the runtime files back in.
- Re-run Windows packaging, installed-notice checks and smoke tests. GitHub-hosted runners often have redistributables already installed; a successful runner alone does not demonstrate the missing-prerequisite path.

**Source references:**
- [Microsoft, Redistribute Visual C++ files](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
- [Microsoft, Choose a deployment method](https://learn.microsoft.com/en-us/cpp/windows/choosing-a-deployment-method)
- [Microsoft, Latest supported Visual C++ Redistributable downloads](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist/)
- [GNU GPL FAQ, Visual C++ runtime/System Libraries question](https://www.gnu.org/licenses/gpl-faq.html#WindowsRuntimeAndGPL)

## WebView2: precise blocker and resolution choices

**Current app:** `pywebview` on Windows uses the WinForms/EdgeChromium backend and `pythonnet`. The installer includes `Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll` and three architecture-specific `WebView2Loader.dll` files. The repository matches these bytes to Microsoft's `Microsoft.Web.WebView2` NuGet package version `1.0.3856.49`; the matching license and NOTICE are already included. The separate Evergreen *runtime* is installed by Windows or obtained from Microsoft, but is not shipped as part of PDF Manager.

**What is established:** the [official NuGet license](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49/License) allows binary redistribution under BSD-3-Clause-like attribution conditions. [Microsoft's distribution documentation](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution) explicitly calls for the SDK loader and managed WinForms/Core assemblies alongside a managed application. Installing the Evergreen Runtime does not replace them.

**What is not established:** source code for those exact SDK assemblies is not published with the NuGet package, and no official source archive for the identical binaries was verified. Their inclusion in a combined AGPL-3.0 application may create a Corresponding Source/System Libraries question. A permissive binary redistribution license is not proof that the System Libraries exception applies.

**Route A: preserve the lightweight WinForms backend (least code churn).**

Request specific, written clarification from the relevant rights holders or a qualified open-source licensing lawyer. Send the precise file/version list, the AGPL grant, PyInstaller bundling method, the fact that the SDK files sit *inside* the package, and the intended public GitHub release with sources. Ask whether bundling the three SDK component types is permissible without source for the Microsoft SDK; whether a documented linking exception is required; and whether the proposed distribution satisfies the relevant licensors. An informal response from one rights holder may be insufficient if other parties own relevant rights. Do not turn a general product FAQ or vendor sales reply into a made-up exception.

Contact: [Artifex contact](https://artifex.com/contact), [PyMuPDF licensing](https://pymupdf.io/licensing). This route keeps the small installer and WebView2's Windows integration, but it cannot be called legally resolved until the actual question is answered.

**Route B: replace only the Windows window renderer with Qt/PySide6 (technical fallback).**

- pywebview's own [installation documentation](https://pywebview.idepy.com/en/guide/installation) confirms Qt is supported on Windows; [web engine configuration](https://pywebview.idepy.com/en/guide/web_engine) documents `gui='qt'` / `PYWEBVIEW_GUI=qt`.
- PDF Manager already uses `pywebview[pyside6]` on Linux. Build a **separate Windows proof of concept** by enabling the Qt backend, adding Windows PySide6/Qt dependencies and switching the GUI selection. Keep the existing React frontend, Python converter and bridge API, subject to real GUI/file-dialog verification.
- In the Windows PyInstaller spec, collect the required QtWebEngine/Qt resources and helper process. Exclude the WinForms/EdgeChromium backend, `pythonnet`, `clr-loader`, Microsoft WebView2 SDK files and legacy WebBrowserInterop DLLs *only after verifying they are not used by other Windows code paths*. Do not remove `pywin32` while Office COM automation still uses it.
- Install complete Qt/PySide6 LGPL notices, the exact Qt/Chromium third-party license inventory and source archives for components **actually shipped**, plus the user ability and instructions to replace/relink modified LGPL libraries. Under [Qt's requirements](https://www.qt.io/faq/qt-open-source-licensing), linking to its website alone is not sufficient to fulfill a source-delivery obligation; the source must be under the distributor's control or an applicable offer made.
- [Qt WebEngine licensing](https://doc.qt.io/qt-6/qtwebengine-licensing.html) and [third-party Qt components](https://doc.qt.io/qt-6/licenses-used-in-qt.html) require a version-specific manifest; verify the exact PySide6 wheel's Qt version and the bundled modules rather than blindly licensing every module in a generic Qt catalog.
- Rework the Windows bundle/license/source checks to match the **actual Qt artifact**. Test bridge communication, native file dialogs, PowerPoint COM conversion, drag/drop, OCR, file save, accessibility, Windows DPI/scaling, update/uninstall and Windows Sandbox. Publish nothing until it passes.
- **Cost:** QtWebEngine bundles a Chromium-based renderer and is significantly heavier than using the Windows Evergreen WebView2 Runtime. Measure the actual installer size and memory impact; do not invent a size or assume the backend change is flawless.

**Not a clean workaround:** extracting or downloading the same Microsoft SDK DLLs into a separate app folder during installation merely changes when they are copied, not the licensing analysis. Likewise using a static WebView2 loader may eliminate the separate loader file but does not remove the proprietary Microsoft implementation. Running the entire UI in an external browser is a different architecture and violates the currently specified in-process pywebview window design. Replacing PyMuPDF would unnecessarily remove an approved dependency without fixing Microsoft runtime distribution.

## Comparison and recommendation

| Strategy | Primary advantage | Main cost/risk | Conclusion |
| --- | --- | --- | --- |
| Existing WebView2 + written licensing determination | Preserves current tested Windows build and small installer | Legal clarification or exception may not be obtainable | Preferred only if properly cleared |
| Qt/PySide6 on Windows + external MSVC runtime | Reuses already planned Linux technology; avoids Microsoft SDK binaries | Larger installer; Qt/Chromium/LGPL source, replacement and notice work | Preferred technical fallback and strongest route to auditable source compliance |
| Keep WebView2 but remove only bundled MSVC runtime | Smaller legal surface and easy implementation | **WebView2 question remains** | Useful interim improvement, not complete resolution |
| Drop PyMuPDF | Avoids Artifex AGPL obligations | Core redesign; contrary to current requirements; unrelated SDK issue persists | Not recommended |

**Priority:** (1) remove app-local VC++ DLLs behind tested prerequisite handling, (2) request the specific WebView2 licensing determination, (3) prepare Qt Windows proof-of-concept in parallel if the lightweight WebView2 route cannot be cleared, (4) complete Windows acceptance and source artifacts before releasing.

## Final release requirements

- [ ] Visual C++ runtime absent from the packaged files and present as a documented, separately installed prerequisite; missing-runtime test completed.
- [ ] Either documented legal permission/determination for the precise bundled WebView2 SDK, **or** a Windows Qt bundle that contains none of the WebView2 SDK DLLs and is audited against LGPL/Chromium terms.
- [ ] `LICENSE`, AGPL, notices and complete Corresponding Source available alongside the **same** release revision; exact source package contents verified.
- [ ] Original app icon and preview provenance documented or replaced with an original asset.
- [ ] Owner-approved release tag and verified SHA-256 for the installer.
- [ ] CI/package tests **and** real-machine Windows tests passed; no unverified claim of complete compliance.

No Windows artifact was modified or rebuilt as part of this research entry. The changes listed here are a proposed implementation, not tested or released functionality.
