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
  PdfManagerApi,
  PdfManagerEvents,
  SaveOptions,
  SaveOutcome,
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

/** Name of an event Python can send. */
export type EventName = keyof PdfManagerEvents;

/** Prefix of the DOM events Python dispatches on `window`. */
export const EVENT_PREFIX = "pdfmanager:";

/**
 * Subscribes to an event from Python.
 *
 * Python dispatches `pdfmanager:<name>` CustomEvents on `window` with the
 * payload in `event.detail`. The mock dispatches the same events, so this works
 * in both modes.
 *
 * @param name - Event name, e.g. `"jobProgress"`.
 * @param handler - Called with the event payload.
 * @returns A function that removes the listener.
 */
export function onEvent<K extends EventName>(
  name: K,
  handler: (payload: PdfManagerEvents[K]) => void,
): () => void {
  const listener = (event: Event) => {
    handler((event as CustomEvent<PdfManagerEvents[K]>).detail);
  };
  window.addEventListener(EVENT_PREFIX + name, listener);
  return () => window.removeEventListener(EVENT_PREFIX + name, listener);
}

/**
 * Dispatches an event the same way Python does. Used by the mock and tests.
 *
 * @param name - Event name.
 * @param payload - Event payload, delivered as `event.detail`.
 */
export function emitEvent<K extends EventName>(name: K, payload: PdfManagerEvents[K]): void {
  window.dispatchEvent(new CustomEvent(EVENT_PREFIX + name, { detail: payload }));
}

/** True if pywebview has injected its object into the page. */
export function isPywebviewPresent(): boolean {
  return typeof window !== "undefined" && window.pywebview !== undefined;
}

let readyPromise: Promise<PythonApi> | null = null;

/**
 * Resolves with the Python API once pywebview is ready: straight away if
 * `window.pywebview.api` already exists, otherwise on the `pywebviewready`
 * window event. The promise is created once and shared by every call.
 */
function whenPythonReady(): Promise<PythonApi> {
  if (!readyPromise) {
    readyPromise = new Promise((resolve) => {
      const existing = window.pywebview?.api;
      if (existing && typeof existing.get_settings === "function") {
        resolve(existing);
        return;
      }
      window.addEventListener(
        "pywebviewready",
        () => resolve(window.pywebview?.api ?? {}),
        { once: true },
      );
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
    getAppInfo: () => callPython<AppInfo>("get_app_info"),
    getSettings: () => callPython<Settings>("get_settings"),
    saveSettings: (patch: Partial<Settings>) => callPython<Settings>("save_settings", patch),
    pickFiles: (kind: "documents" | "images") => callPython<InputFile[]>("pick_files", kind),
    pickFolder: () => callPython<string | null>("pick_folder"),
    // start_job and check_tools take three positional arguments on the Python side.
    checkTools: (action: Action, settings: ActionSettings, data: ActionData) =>
      callPython<ToolCheckResult>("check_tools", action, settings, data),
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
