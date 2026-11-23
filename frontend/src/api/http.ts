/**
 * Browser mode's client: the real `PdfManagerApi` over PDF Manager's local
 * HTTP API on 127.0.0.1 (api/web/ in Python).
 *
 * - Selected only when the app serves the page: the server adds a
 *   `<meta name="pdf-manager-mode" content="browser">` tag (see client.ts).
 * - Same-origin requests with the `X-PDF-Manager: 1` header; the session is
 *   an HttpOnly cookie the browser already has. The page never sees a host
 *   path it could send back: files and picked folders are opaque IDs.
 * - Python's job and OCR-install status is the source of truth. While one is
 *   active this client polls it and dispatches the same `jobProgress`,
 *   `jobFinished`, `ocrInstallProgress` and `ocrInstallFinished` events the
 *   desktop window gets, so the UI code is the same in both modes.
 * - When the app stops answering, `connectionLost` is dispatched.
 */
import { emitEvent } from "./events";
import type {
  Action,
  ActionData,
  ActionSettings,
  AppInfo,
  InputFile,
  JobFinished,
  JobProgress,
  OcrSearchResult,
  OcrStatus,
  PdfManagerApi,
  RecoveredJob,
  SaveOptions,
  SaveOutcome,
  SaveSettingsResult,
  Settings,
  StartJobResult,
  ToolCheckResult,
} from "./types";

/** What the server's bootstrap tag says. */
export interface BrowserBootstrap {
  /** Whether the app can show native file and folder pickers on this computer. */
  nativeDialogs: boolean;
}

/** Reads the bootstrap tag the app adds to the page, or null when the app didn't serve it. */
export function readBrowserBootstrap(doc: Document | undefined = globalThis.document): BrowserBootstrap | null {
  const tag = doc?.querySelector('meta[name="pdf-manager-mode"]');
  if (!tag || tag.getAttribute("content") !== "browser") return null;
  return { nativeDialogs: tag.getAttribute("data-native-dialogs") === "true" };
}

/** The app didn't answer (it was closed, or the connection failed). */
export class ConnectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConnectionError";
  }
}

const POLL_MS = 300;
/** Polls may fail for this long (a busy computer, a sleeping laptop) before the connection counts as lost. */
const LOST_AFTER_MS = 15_000;
/** Requests that don't wait for the user time out after this. */
const TIMEOUT_MS = 30_000;

const ACCEPT: Record<"all" | "documents" | "images", string> = {
  all: ".pdf,.pptx,.ppt,.png,.jpg,.jpeg",
  documents: ".pdf,.pptx,.ppt",
  images: ".png,.jpg,.jpeg",
};

interface JobStatus {
  jobId: string;
  progress: JobProgress | null;
  finished: JobFinished | null;
}

interface OcrInstallStatus {
  running: boolean;
  messages: string[];
  finished: { ok: boolean; issue: SaveOutcome["issue"] } | null;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** A random ID for idempotent requests (a retried start returns the same job). */
function requestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * Sends one request. Resolves with the response's `result`.
 *
 * @param timeoutMs - null for requests that wait for the user (pickers) or carry big files.
 * @throws ConnectionError if the app didn't answer; Error for a refused request (a bug).
 */
async function call<T>(method: "GET" | "POST", path: string, body?: unknown, timeoutMs: number | null = TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = timeoutMs === null ? undefined : setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      credentials: "same-origin",
      headers: method === "POST" ? { "X-PDF-Manager": "1", "Content-Type": "application/json" } : { "X-PDF-Manager": "1" },
      body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    throw new ConnectionError(`PDF Manager didn't answer (${method} ${path}): ${String(error)}`);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
  if (response.status === 503) throw new ConnectionError("PDF Manager is closing.");
  if (!response.ok) throw new Error(`PDF Manager refused ${method} ${path} (${response.status}).`);
  const payload = (await response.json()) as { result: T };
  return payload.result;
}

/** Sends one file's bytes to the app, which keeps a private working copy. */
async function uploadOne(file: File): Promise<InputFile[]> {
  const query = `name=${encodeURIComponent(file.name)}&modified=${encodeURIComponent(String(file.lastModified))}`;
  let response: Response;
  try {
    response = await fetch(`/api/files/upload?${query}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-PDF-Manager": "1", "Content-Type": "application/octet-stream" },
      body: file,
    });
  } catch (error) {
    throw new ConnectionError(`Couldn't send ${file.name} to PDF Manager: ${String(error)}`);
  }
  if (!response.ok) return []; // Too large or refused: like an unsupported file, it isn't added.
  return ((await response.json()) as { result: InputFile[] }).result;
}

/** Saves one prepared result through the browser's downloads. */
async function download(id: string, name: string): Promise<void> {
  const response = await fetch(`/api/downloads/${encodeURIComponent(id)}`, {
    credentials: "same-origin",
    headers: { "X-PDF-Manager": "1" },
  });
  if (!response.ok) throw new Error(`The download of ${name} wasn't available (${response.status}).`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Give the browser time to start the download before freeing the data.
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/**
 * Lets the user choose files with the browser's own file chooser (when the
 * app can't show a native one). Must be called straight from a click.
 */
function chooseWithBrowser(kind: "all" | "documents" | "images"): Promise<File[]> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ACCEPT[kind];
    input.addEventListener("change", () => resolve(Array.from(input.files ?? [])), { once: true });
    input.addEventListener("cancel", () => resolve([]), { once: true });
    input.click();
  });
}

/** Creates browser mode's API client. */
export function createHttpApi(bootstrap: BrowserBootstrap): PdfManagerApi {
  const watched = new Set<string>();
  let watchingOcr = false;

  const lost = (jobId: string | null) => emitEvent("connectionLost", { jobId });

  /** Polls a job until it finishes, dispatching its progress and result. */
  async function pollJob(jobId: string) {
    let lastProgress = "";
    let failingSince: number | null = null;
    while (watched.has(jobId)) {
      try {
        const status = await call<JobStatus>("GET", `/api/jobs/${jobId}`);
        failingSince = null;
        const progress = JSON.stringify(status.progress);
        if (status.progress && progress !== lastProgress) {
          lastProgress = progress;
          emitEvent("jobProgress", status.progress);
        }
        if (status.finished) {
          watched.delete(jobId);
          emitEvent("jobFinished", status.finished);
          return;
        }
      } catch (error) {
        if (!(error instanceof ConnectionError)) {
          watched.delete(jobId); // The app doesn't know this job (it was restarted).
          lost(jobId);
          return;
        }
        failingSince ??= Date.now();
        if (Date.now() - failingSince > LOST_AFTER_MS) {
          watched.delete(jobId);
          lost(jobId);
          return;
        }
      }
      await sleep(POLL_MS);
    }
  }

  /** Polls the OCR install until it ends, dispatching its messages and result. */
  async function pollOcrInstall() {
    if (watchingOcr) return;
    watchingOcr = true;
    let seen = 0;
    let failingSince: number | null = null;
    try {
      for (;;) {
        try {
          const status = await call<OcrInstallStatus>("GET", "/api/ocr/install");
          failingSince = null;
          for (const message of status.messages.slice(seen)) emitEvent("ocrInstallProgress", { message });
          seen = status.messages.length;
          if (status.finished && !status.running) {
            emitEvent("ocrInstallFinished", status.finished);
            return;
          }
        } catch {
          failingSince ??= Date.now();
          if (Date.now() - failingSince > LOST_AFTER_MS) {
            lost(null);
            return;
          }
        }
        await sleep(POLL_MS * 2);
      }
    } finally {
      watchingOcr = false;
    }
  }

  /** Any call: a ConnectionError also tells the page the app is gone. */
  async function request<T>(method: "GET" | "POST", path: string, body?: unknown, timeoutMs?: number | null): Promise<T> {
    try {
      return await call<T>(method, path, body, timeoutMs);
    } catch (error) {
      if (error instanceof ConnectionError) lost(null);
      throw error;
    }
  }

  const addDroppedFiles = async (files: File[]): Promise<InputFile[]> => {
    const added: InputFile[] = [];
    for (const file of files) {
      try {
        added.push(...(await uploadOne(file)));
      } catch (error) {
        lost(null);
        throw error;
      }
    }
    return added;
  };

  const watchJob = (jobId: string) => {
    if (watched.has(jobId)) return;
    watched.add(jobId);
    void pollJob(jobId);
  };

  return {
    mode: "browser",
    saveMode: bootstrap.nativeDialogs ? "folder" : "download",
    addDroppedFiles,
    latestJob: async () => (await request<{ job: RecoveredJob | null }>("GET", "/api/jobs/latest")).job,
    watchJob,
    quit: () => request<void>("POST", "/api/quit"),

    getAppInfo: () => request<AppInfo>("GET", "/api/app-info"),
    getSettings: () => request<Settings>("GET", "/api/settings"),
    saveSettings: (patch: Partial<Settings>) => request<SaveSettingsResult>("POST", "/api/settings", patch),
    pickFiles: async (kind) => {
      if (!bootstrap.nativeDialogs) return addDroppedFiles(await chooseWithBrowser(kind));
      return request<InputFile[]>("POST", "/api/files/pick", { kind }, null);
    },
    pickFolder: () =>
      bootstrap.nativeDialogs ? request<string | null>("POST", "/api/folders/pick", {}, null) : Promise.resolve(null),
    checkTools: (action: Action, settings: ActionSettings, data: ActionData) =>
      request<ToolCheckResult>("POST", "/api/tools/check", { action, settings, data }),
    getOcrStatus: () => request<OcrStatus>("GET", "/api/ocr/status"),
    getOcrLanguages: () => request<string[]>("GET", "/api/ocr/languages"),
    searchOcr: () => request<OcrSearchResult>("POST", "/api/ocr/search", {}, null),
    installOcr: async () => {
      await request<void>("POST", "/api/ocr/install");
      void pollOcrInstall();
    },
    startJob: async (action: Action, settings: ActionSettings, data: ActionData) => {
      const body = { action, settings, data, requestId: requestId() };
      let started: StartJobResult;
      try {
        started = await call<StartJobResult>("POST", "/api/jobs", body);
      } catch (error) {
        if (!(error instanceof ConnectionError)) throw error;
        // The same requestId: if the first attempt did start a job, this returns that job.
        started = await request<StartJobResult>("POST", "/api/jobs", body);
      }
      if (started.jobId) watchJob(started.jobId);
      return started;
    },
    cancelJob: (jobId: string) => request<void>("POST", `/api/jobs/${jobId}/cancel`),
    saveResults: async (jobId: string, options: SaveOptions): Promise<SaveOutcome> => {
      if (options.folder === null && !bootstrap.nativeDialogs) {
        const prepared = await request<{ downloads: { id: string; name: string }[]; issue: SaveOutcome["issue"] }>(
          "POST",
          `/api/jobs/${jobId}/download`,
          { asZip: options.asZip },
        );
        if (prepared.issue) return { cancelled: false, savedPaths: [], folder: null, issue: prepared.issue };
        for (const item of prepared.downloads) await download(item.id, item.name);
        return { cancelled: false, savedPaths: prepared.downloads.map((d) => d.name), folder: null, issue: null, downloaded: true };
      }
      return request<SaveOutcome>("POST", `/api/jobs/${jobId}/save`, options, null);
    },
    discardResults: (jobId: string) => {
      watched.delete(jobId);
      return request<void>("POST", `/api/jobs/${jobId}/discard`);
    },
    openFolder: (path: string) => request<void>("POST", "/api/folders/open", { folder: path }),
    openLogsFolder: () => request<void>("POST", "/api/logs/open"),
  };
}
