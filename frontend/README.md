# PDF Manager frontend

The React interface runs in a pywebview window in desktop mode and in the user's default browser in portable mode. Both use the same Python backend. Browser mode uses a local HTTP API on `127.0.0.1`. The contract is described in the [API guide](../docs/API.md) and [TypeScript types](src/api/types.ts).

Stack: Vite, React, TypeScript, CSS Modules, dnd-kit (drag to reorder), Segoe UI where Windows provides it, else bundled Open Sans (works offline), Vitest and React Testing Library.

## Commands

```bash
npm ci               # install the locked dependencies
npm run dev          # browser preview at http://localhost:5173 with the mock backend
npm test             # run the tests once (npm run test:watch to keep watching)
npm run lint         # ESLint
npm run typecheck    # TypeScript, no output files
npm run build        # type-check, then build dist/index.html
```

## The build is one self-contained file

The desktop app opens `dist/index.html` straight from disk as a `file://` URL (no web server). Chromium and WebView2 block module scripts and font downloads from `file://`, so `npm run build` produces a **single `dist/index.html` with nothing else next to it**:

- [`vite-plugin-singlefile`](https://github.com/richardtallent/vite-plugin-singlefile) inlines the JavaScript and CSS (no code-splitting).
- Font: Segoe UI is used where Windows provides it (it's proprietary, so it isn't bundled). The fallback is Open Sans (OFL), a variable font inlined as data URIs (see `src/styles/fonts.css`): woff2, Latin and Latin Extended only.
- The small inline script in `index.html` that picks light or dark before the first paint stays as it is.

Keep fonts, scripts, and other assets inside the build so both modes work offline.

To check a production build with the real service, run `uv run main.py --browser` from the repository root. The app serves the same HTML file over loopback and opens it in your default browser. See the [browser mode guide](../docs/BROWSER_MODE.md).

## Running with the mock

When `window.pywebview` is missing (a normal browser), `npm run dev` uses an in-memory mock of the Python backend (`src/api/mock.ts`), so every screen can be tried without Python:

- **Add files** and **Add images** return sample files (a browser can't give real paths).
- Dropping real files on the window turns them into fake entries in the list.
- Jobs show progress over a few seconds and can be cancelled.
- A file whose name contains `warn` produces a warning, to show how warnings are listed.
- LibreOffice starts as installed; `createMockApi({ tools: { libreoffice: false } })` shows the notice for PowerPoint files.
- A file whose name contains `fail` makes the job fail, to show the error popup.
- OCR starts as "not installed", so ticking **Use OCR** shows the missing-tool check. **Install OCR** then "installs" it.
- Start with `VITE_MOCK_PLATFORM=linux npm run dev` to act like Linux: **Install OCR** installs nothing and instead shows the command to copy and run (`sudo apt install tesseract-ocr tesseract-ocr-eng`, decision C16).
- Settings save normally. Start with `VITE_MOCK_SETTINGS_SAVE_FAILS=1 npm run dev` to make every settings save fail, which shows the "not saved" warning in Settings.

A production build never includes the mock. To use the real bridge during development (for example a pywebview window pointed at the dev server), start Vite with `VITE_API=bridge npm run dev`.

## Folder layout

```
src/
  api/          types.ts (contract), bridge.ts (desktop), http.ts (portable), mock.ts (dev)
  components/   shared components, each with its .module.css and tests
                (Button, InfoTip, FileList, Modal, Issue, Sidebar, DropOverlay, Field, ...)
  pages/        one folder per page: HomePage, ActionPage (+ ConvertModal), SettingsPage
  state/        app state (reducer + context), theme hook
  lib/          plain helpers: the action table, page ranges, formatting
  styles/       tokens.css, global.css and themes/ (one file per colour theme)
  test/         test setup and the renderApp helper
```

Feature folders keep a component, its styles and its tests together. Colours always come from the semantic tokens in `styles/themes/*.css` (for example `--color-primary`), never from hard-coded values, so all four themes work everywhere.
