# PDF Manager frontend

The React user interface of PDF Manager. In the desktop app it runs inside a pywebview window and talks to the Python backend directly (no web server). The contract between the two is in [`../docs/API.md`](../docs/API.md) and [`src/api/types.ts`](src/api/types.ts).

Stack: Vite, React, TypeScript, CSS Modules, dnd-kit (drag to reorder), IBM Plex Sans (bundled, works offline), Vitest and React Testing Library.

## Commands

```bash
npm install          # once
npm run dev          # browser preview at http://localhost:5173 with the mock backend
npm test             # run the tests once (npm run test:watch to keep watching)
npm run lint         # ESLint
npm run typecheck    # TypeScript, no output files
npm run build        # type-check, then build to dist/
```

`npm run build` writes `dist/index.html` with relative asset paths, so pywebview can load it straight from disk.

## Running with the mock

When `window.pywebview` is missing (a normal browser), `npm run dev` uses an in-memory mock of the Python backend (`src/api/mock.ts`), so every screen can be tried without Python:

- **Add files** and **Add images** return sample files (a browser can't give real paths).
- Dropping real files on the window turns them into fake entries in the list.
- Jobs show progress over a few seconds and can be cancelled.
- PowerPoint files produce a "LibreOffice was used" warning.
- A file whose name contains `fail` makes the job fail, to show the error popup.
- OCR starts as "not installed", so ticking **Use OCR** shows the missing-tool check. **Install OCR** then "installs" it.

A production build never includes the mock. To use the real bridge during development (for example a pywebview window pointed at the dev server), start Vite with `VITE_API=bridge npm run dev`.

## Folder layout

```
src/
  api/          types.ts (the contract), bridge.ts (pywebview), mock.ts (dev mock), client.ts (picks one)
  components/   shared components, each with its .module.css and tests
                (Button, InfoTip, FileList, Modal, Issue, Sidebar, DropOverlay, Field, ...)
  pages/        one folder per page: HomePage, ActionPage (+ ConvertModal), SettingsPage
  state/        app state (reducer + context), theme hook
  lib/          plain helpers: the action table, page ranges, formatting
  styles/       tokens.css, global.css and themes/ (one file per colour theme)
  test/         test setup and the renderApp helper
```

Feature folders keep a component, its styles and its tests together. Colours always come from the semantic tokens in `styles/themes/*.css` (for example `--color-primary`), never from hard-coded values, so all four themes work everywhere.
