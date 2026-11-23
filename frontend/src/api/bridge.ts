/**
 * pywebview bridge: the real `PdfManagerApi`, backed by the Python object that
 * pywebview exposes as `window.pywebview.api`, plus the typed event helpers.
 *
 * See docs/API.md for the transport rules.
 */
import type {
  Action,
  ActionData,
  ActionSettings,
  AppInfo,
  InputFile,
  OcrSearchResult,
  OcrStatus,
  PdfManagerApi,
  SaveOptions,
  SaveOutcome,
  SaveSettingsResult,
  Settings,
  StartJobResult,
  ToolCheckResult,
} from "./types";

/** Shape of the Python API object: snake_case methods returning promises. */
type PythonApi = Record<string, ((...args: unknown[]) => Promise<unknown>) | undefined>;

declare global {
  interface Window {
    /** Injected by pywebview. Absent in a plain browser (dev mode and tests). */
    pywebview?: { api?: PythonApi };
  }
}

export { EVENT_PREFIX, emitEvent, onEvent, type EventName } from "./events";

/** True if pywebview has injected its object into the page. */
export function isPywebviewPresent(): boolean {
  return typeof window !== "undefined" && window.pywebview !== undefined;
}

let readyPromise: Promise<PythonApi> | null = null;

/**
 * Resolves with the Python API once pywebview is ready: straight away if
 * `window.pywebview.api` already exists, otherwise on the `pywebviewready`
 * window event. Only the waiting promise is shared; once the API exists, the
 * live object is always used.
 */
function whenPythonReady(): Promise<PythonApi> {
  const existing = window.pywebview?.api;
  if (existing && typeof existing.get_settings === "function") {
    return Promise.resolve(existing);
  }
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      window.addEventListener("pywebviewready", () => resolve(window.pywebview?.api ?? {}), { once: true });
    });
  }
  return readyPromise;
}

/**
 * Calls one Python method after pywebview is ready.
 *
 * @param method - snake_case method name on `window.pywebview.api`.
 * @param args - Positional arguments, passed through unchanged.
 * @returns The method's result.
 * @throws Error if the method doesn't exist (a bug, not an expected failure).
 */
async function callPython<T>(method: string, ...args: unknown[]): Promise<T> {
  const python = await whenPythonReady();
  const fn = python[method];
  if (typeof fn !== "function") {
    throw new Error(`The Python API has no method "${method}".`);
  }
  return (await fn(...args)) as T;
}

/**
 * Creates the real API client. Every method maps 1:1 onto the snake_case
 * Python method of the same name (see the table in docs/API.md).
 */
export function createBridgeApi(): PdfManagerApi {
  return {
    mode: "desktop",
    saveMode: "folder",
    // Python reads dropped files' real paths itself and sends `filesAdded`.
    addDroppedFiles: () => Promise.resolve([]),
    latestJob: () => Promise.resolve(null),
    // Python sends job events by itself.
    watchJob: () => undefined,
    // The window's close button quits the desktop app.
    quit: () => Promise.resolve(),
    getAppInfo: () => callPython<AppInfo>("get_app_info"),
    getSettings: () => callPython<Settings>("get_settings"),
    saveSettings: (patch: Partial<Settings>) => callPython<SaveSettingsResult>("save_settings", patch),
    pickFiles: (kind: "all" | "documents" | "images") => callPython<InputFile[]>("pick_files", kind),
    pickFolder: () => callPython<string | null>("pick_folder"),
    // start_job and check_tools take three positional arguments on the Python side.
    checkTools: (action: Action, settings: ActionSettings, data: ActionData) =>
      callPython<ToolCheckResult>("check_tools", action, settings, data),
    getOcrStatus: () => callPython<OcrStatus>("get_ocr_status"),
    getOcrLanguages: () => callPython<string[]>("get_ocr_languages"),
    searchOcr: () => callPython<OcrSearchResult>("search_ocr"),
    installOcr: () => callPython<void>("install_ocr"),
    startJob: (action: Action, settings: ActionSettings, data: ActionData) =>
      callPython<StartJobResult>("start_job", action, settings, data),
    cancelJob: (jobId: string) => callPython<void>("cancel_job", jobId),
    saveResults: (jobId: string, options: SaveOptions) =>
      callPython<SaveOutcome>("save_results", jobId, options),
    discardResults: (jobId: string) => callPython<void>("discard_results", jobId),
    openFolder: (path: string) => callPython<void>("open_folder", path),
    openLogsFolder: () => callPython<void>("open_logs_folder"),
  };
}
