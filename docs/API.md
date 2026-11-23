# UI ↔ Python contract (v1)

How the React frontend and the Python backend talk to each other inside the desktop app. The TypeScript source of truth is [`frontend/src/api/types.ts`](../frontend/src/api/types.ts); this document explains it. Change both together.

## Transport

The app is a **pywebview** window (Edge WebView2 on Windows 11) showing the built React app. There is **no local web server**.

- **UI → Python (calls):** pywebview exposes a Python object as `window.pywebview.api`. Each method returns a `Promise`. Python method names are `snake_case`; the frontend wraps them in a typed `camelCase` client (`src/api/client.ts`).
- **Python → UI (events):** Python dispatches DOM events on `window`, named `pdfmanager:<eventName>`, with the payload in `event.detail`.
- **Readiness:** pywebview fires `pywebviewready` on `window` once `window.pywebview.api` is usable. The client waits for it.
- **Dev mode:** when `window.pywebview` is missing (plain `npm run dev` in a browser), the client uses an in-memory **mock** with the same interface, so the UI can be built and tested without Python.
- **JSON keys are `camelCase`** in both directions. Python converts at the boundary.
- **Errors:** a call never rejects for expected failures. It resolves with a result that carries an `Issue`. A rejected promise means a bug.

## Files and drag and drop

A web page can't see real file paths, so dropped files are handled on the Python side:

1. The UI shows the drop highlight on `dragenter`/`dragover` and calls `preventDefault()` on `dragover` and `drop` so the window doesn't navigate.
2. Python listens to the document `drop` event, reads the full paths, inspects each file and emits **`filesAdded`** with `InputFile[]`.
3. The UI appends them to the shared file list (shared across all tabs), skipping paths already in the list.

`pick_files` opens the native Windows file picker and returns `InputFile[]` the same way.

## Calls

| Python method | Client method | Purpose |
| --- | --- | --- |
| `get_app_info()` | `getAppInfo()` | Version, logs folder path, platform. |
| `get_settings()` | `getSettings()` | Saved settings. |
| `save_settings(patch)` | `saveSettings(patch)` | Merge and persist a partial settings object. Returns `{ settings, issue }`: the settings now in effect, and a `SETTINGS_SAVE_FAILED` issue if they couldn't be written to disk (they then apply only until the app closes). Calls are applied in the order received; the UI must not let an older response overwrite a newer choice. |
| `pick_files(kind)` | `pickFiles(kind)` | Native file picker. `kind`: `"all"` (every supported type), `"documents"` (PDF/PPTX/PPT) or `"images"` (PNG/JPG). Returns `InputFile[]` (empty if cancelled). |
| `pick_folder()` | `pickFolder()` | Native folder picker. Returns a path or `null`. |
| `check_tools(action, settings, data)` | `checkTools(action, settings, data)` | Tool check for the Convert modal. Same arguments as `start_job`. Checks **only what this job needs** (see below). Returns `ToolCheckResult`. |
| `get_ocr_status()` | `getOcrStatus()` | `{ present, path }`: whether Tesseract is installed (for Settings). |
| `get_ocr_languages()` | `getOcrLanguages()` | Installed Tesseract languages, e.g. `["eng", "deu"]`. Empty if OCR isn't found. |
| `search_ocr()` | `searchOcr()` | Settings → "Search for OCR": search the usual places; if not found, open a picker for `tesseract.exe`. Saves the path. Returns `OcrSearchResult`. |
| `install_ocr()` | `installOcr()` | Start installing Tesseract (winget). Progress via `ocrInstallProgress`, end via `ocrInstallFinished`. Returns immediately. |
| `start_job(action, settings, data)` | `startJob(action, settings, data)` | **The single entry point for every conversion** (see below). Returns `{ jobId }`, or `{ issue }` if it can't start (for example a job is already running). Only one job runs at a time. |
| `cancel_job(job_id)` | `cancelJob(jobId)` | Request cancellation. The job ends with status `"cancelled"`. |
| `save_results(job_id, options)` | `saveResults(jobId, options)` | Copy results out of the scratch folder. Never overwrites (adds ` (2)` and so on). Returns `SaveOutcome`. |
| `discard_results(job_id)` | `discardResults(jobId)` | Delete a finished job's scratch folder. Safe to call more than once, and after saving (the UI calls it when the user is done). |
| `open_folder(path)` | `openFolder(path)` | Open a folder in File Explorer. |
| `open_logs_folder()` | `openLogsFolder()` | Open the logs folder (next to the installed app) in File Explorer. |

## Events

| Event | Payload | When |
| --- | --- | --- |
| `filesAdded` | `{ files: InputFile[] }` | Files were dropped onto the window. |
| `jobProgress` | `JobProgress` | Regularly while a job runs (at least once per page and per file). |
| `jobFinished` | `JobFinished` | A job succeeded, failed or was cancelled. Results stay in scratch until `saveResults` or `discardResults`. |
| `ocrInstallProgress` | `{ message: string }` | During an OCR install. |
| `ocrInstallFinished` | `{ ok: boolean, issue: Issue \| null }` | OCR install ended. |

## One function for all actions

Every conversion (Flatten, Merge, Split and so on) goes through **one function**:

```ts
startJob(action: Action, settings: ActionSettings, data: ActionData)
```

- `action`: an enum value (`Action.Flatten`, `Action.FlattenMerge`, `Action.Merge`, `Action.Split`, `Action.ImagesToPdf`, `Action.Compress`) that decides what the job does.
- `settings`: one `ActionSettings` object. Each action reads only the fields relevant to it (for example `split` for Split, `compressLevel` for Compress).
- `data`: what the job works on: `{ files }`, the accepted file paths in display order.

The Python side mirrors this: `converter.run_action(action, settings, data, ...)` with an `Action` string enum, and the bridge's `start_job(action, settings, data)` simply forwards to it.

## Actions and what each accepts

| Action | Accepts | Output | OCR option |
| --- | --- | --- | --- |
| `flatten` | PDF, PPTX, PPT | One flattened PDF per input | Yes |
| `flatten_merge` | PDF, PPTX, PPT | One flattened, merged PDF | Yes |
| `merge` | PDF, PPTX, PPT | One merged PDF (original text kept) | Yes |
| `split` | PDF, PPTX, PPT | One PDF per range, per input | Yes |
| `images_to_pdf` | PNG, JPG | One combined PDF, or one PDF per image | Yes |
| `compress` | PDF | One smaller PDF per input | No |

The file list is shared, so it can hold files a mode doesn't accept. The UI shows those as not applicable on that tab and leaves them out; `data.files` only contains accepted files, in display order.

"Use OCR" is unchecked by default. For non-flatten actions, OCR adds a searchable text layer to pages that have no text (image-based pages), leaving pages that already have text alone.

## Tool check

`check_tools(action, settings, data)` decides what the job needs:

- **OCR (Tesseract)** is required only if `settings.useOcr` is true (never for Compress).
- **PowerPoint or LibreOffice** is needed only if `data.files` contains PPT/PPTX files. Microsoft PowerPoint is preferred. If PowerPoint is present, a missing LibreOffice is reported as `"not present"` but **doesn't block**. If neither is present, the check fails.

The Convert modal runs this on **every Convert** and only starts the job if `ok` is true. Otherwise it shows the returned issues.

## Issues (errors and warnings)

Every problem the user should see is an `Issue`:

- `severity`: `"error"` (the job or action failed) or `"warning"` (it succeeded, but something needs attention, for example PowerPoint failed and LibreOffice was used instead).
- `title` and `message`: short, plain language for non-technical users.
- `troubleshooting`: a few simple steps for the likely cause. Written by the backend so the wording lives in one place.
- `details`: technical text (raw error output) for an optional "Show details" section.
- `logFile`: path of the log file holding the full record, if one was written.

Every issue is also written to the logs folder.

## Saving

`save_results(jobId, { folder, asZip })`:

- `folder: null` opens the native folder picker. If the user cancels, `cancelled` is true and **nothing is lost**: results stay until saved or discarded.
- `asZip: true` (Split only) saves all outputs as one `.zip`.
- When a default save folder is set and the page's "Save to default folder" box is ticked (it starts ticked), the UI calls `saveResults` with that folder straight away, without asking.
