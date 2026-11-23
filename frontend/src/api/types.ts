/**
 * UI <-> Python contract (v1). Source of truth for both sides; see docs/API.md.
 * JSON keys are camelCase in both directions.
 */

/**
 * The action a job performs. Every conversion goes through one function,
 * `startJob(action, settings, data)`; this enum decides what it does.
 * Each action is its own sidebar tab.
 *
 * (A const object rather than a TS `enum`, so it works with erasable-syntax-only builds.)
 */
export const Action = {
  Flatten: "flatten",
  FlattenMerge: "flatten_merge",
  Merge: "merge",
  Split: "split",
  ImagesToPdf: "images_to_pdf",
  Compress: "compress",
} as const;
export type Action = (typeof Action)[keyof typeof Action];

/** Kind of input file, detected by Python from the extension. */
export type FileKind = "pdf" | "pptx" | "ppt" | "image";

/** A file in the shared file list. */
export interface InputFile {
  /**
   * Unique key for the list. The desktop window gets the full path on disk;
   * browser mode gets an opaque file ID instead (the page never sees or sends paths).
   */
  path: string;
  /** File name shown to the user, e.g. "Report.pdf". */
  name: string;
  kind: FileKind;
  sizeBytes: number;
  /** Page count for PDFs; null for PowerPoints (unknown until rendered) and images. */
  pageCount: number | null;
}

/** Colour scheme. "system" follows the Windows light/dark setting. */
export type Theme = "system" | "light" | "dark" | "burgundy" | "green";

/** Persisted settings. */
export interface Settings {
  theme: Theme;
  /** Default save folder, or null if none is set. */
  defaultSaveFolder: string | null;
  /** Render resolution for flattening and OCR. Default 200. */
  dpi: number;
  /** Tesseract language code(s), e.g. "eng" or "eng+deu". Default "eng". */
  ocrLanguage: string;
  /** Give up on a page whose OCR takes longer than this. Default 120. */
  ocrPageTimeoutSec: number;
  /** User-chosen path to tesseract.exe, or null to auto-detect. */
  tesseractPath: string | null;
}

export type SplitMethod = "ranges" | "every_n" | "per_page";
export type CompressLevel = "light" | "balanced" | "strong";

/** Settings for one job. Only the fields relevant to the action are used. */
export interface ActionSettings {
  /** Add a searchable OCR text layer. Unchecked by default. Ignored for "compress". */
  useOcr: boolean;
  /** Merge actions only: clickable contents page at the start. Off by default. */
  contentsPage: boolean;
  /** Split only. */
  split: {
    method: SplitMethod;
    /** For "ranges": e.g. "1-3, 5, 8-10". Each range becomes its own file. */
    ranges: string;
    /** For "every_n": pages per output file. */
    everyN: number;
  };
  /** Images to PDF only: true = one combined PDF, false = one PDF per image. */
  combineImages: boolean;
  /** Compress only. */
  compressLevel: CompressLevel;
}

/** The data a job works on. */
export interface ActionData {
  /** Absolute paths of the files this action accepts, in display order. */
  files: string[];
}

/** Problem shown to the user in a simple popup. */
export interface Issue {
  /** Stable code for the frontend to branch on if needed, e.g. "OCR_MISSING". */
  code: IssueCode;
  severity: "error" | "warning";
  /** Short, plain-language title. */
  title: string;
  /** One or two plain-language sentences. */
  message: string;
  /** Simple steps for the likely cause. */
  troubleshooting: string[];
  /** Technical details (raw error text) for an optional "Show details" section. */
  details: string | null;
  /** Log file with the full record, if written. */
  logFile: string | null;
  /**
   * A command the user can copy and run themselves (for example the Linux package
   * install for Tesseract), shown with a Copy button; null when there is none.
   */
  command: string | null;
  /** The input file this is about, if any. */
  file: string | null;
}

export type IssueCode =
  | "OCR_MISSING"
  | "OCR_FAILED"
  | "OCR_TIMEOUT"
  | "OCR_INSTALL_FAILED"
  | "POWERPOINT_CONVERSION_FAILED"
  | "SLIDE_RENDERER_MISSING"
  | "PASSWORD_PROTECTED"
  | "EMPTY_PDF"
  | "UNREADABLE_FILE"
  | "UNSUPPORTED_FILE"
  | "INVALID_PAGE_RANGES"
  | "FLATTEN_CHECK_FAILED"
  | "MERGE_FAILED"
  | "SAVE_FAILED"
  | "SETTINGS_SAVE_FAILED"
  | "JOB_ALREADY_RUNNING"
  | "UNEXPECTED_ERROR";

/** One row of the tool-check modal. */
export interface ToolStatus {
  /** Whether this job needs the tool. Rows with required=false are hidden or shown as "not needed". */
  required: boolean;
  present: boolean;
  /** Path if found. */
  path: string | null;
}

export interface ToolCheckResult {
  /** True if the job can start. */
  ok: boolean;
  ocr: ToolStatus;
  /** LibreOffice Impress: required whenever the job has PowerPoint files (decision C17). */
  libreoffice: ToolStatus;
  /** Why ok is false (errors), or notes such as "LibreOffice not present" (warnings). */
  issues: Issue[];
}

export interface SaveSettingsResult {
  /** Settings now in effect (in memory), including the patch. */
  settings: Settings;
  /** Set when the settings couldn't be saved to disk; null when saved. */
  issue: Issue | null;
}

export interface OcrStatus {
  present: boolean;
  path: string | null;
}

export interface OcrSearchResult {
  found: boolean;
  path: string | null;
  /** Set if not found or the chosen file isn't Tesseract. */
  issue: Issue | null;
}

export interface AppInfo {
  version: string;
  logsDir: string;
  /** Folder with the licence texts (LICENSING.md, THIRD_PARTY_NOTICES.md, licenses/). */
  licensesDir: string;
  platform: "windows" | "linux" | "mac";
  /** The exact Git commit this copy was built from (40 hex digits), or null if unknown. */
  sourceRevision: string | null;
  /** True if it was built with local changes not in that commit (development builds only). */
  sourceModified: boolean;
}

export type JobStage =
  | "preparing"
  | "rendering_slides"
  | "flattening"
  | "ocr"
  | "merging"
  | "splitting"
  | "compressing"
  | "converting_images"
  | "finishing";

export interface JobProgress {
  jobId: string;
  stage: JobStage;
  /** 1-based index of the current input file, and how many there are. */
  fileIndex: number;
  fileCount: number;
  /** Current page within the file, if the stage works page by page. */
  page: number | null;
  pageCount: number | null;
  /** Overall progress 0..1, best estimate. */
  fraction: number;
  /** Plain-language status line, e.g. "Reading text: page 3 of 12". */
  message: string;
}

export interface OutputFile {
  /** Suggested file name, e.g. "Report - Flattened.pdf". */
  name: string;
  sizeBytes: number;
  pageCount: number;
}

export interface JobFinished {
  jobId: string;
  status: "succeeded" | "failed" | "cancelled";
  /** Empty unless succeeded. */
  outputs: OutputFile[];
  /** Non-fatal problems; shown even on success. */
  warnings: Issue[];
  /** Set when status is "failed". */
  error: Issue | null;
}

export interface SaveOptions {
  /** Target folder, or null to open the native folder picker. */
  folder: string | null;
  /** Split only: save all outputs as one .zip. */
  asZip: boolean;
}

export interface SaveOutcome {
  /** Browser mode without a folder picker: the files went to the browser's downloads. */
  downloaded?: boolean;
  /** True if the user closed the folder picker; results are kept. */
  cancelled: boolean;
  /** Full paths written. */
  savedPaths: string[];
  /** Folder the files were saved in. */
  folder: string | null;
  issue: Issue | null;
}

export type StartJobResult = { jobId: string; issue?: undefined } | { jobId?: undefined; issue: Issue };

/** A job found after the page was reloaded (browser mode only). */
export interface RecoveredJob {
  jobId: string;
  action: Action | null;
  progress: JobProgress | null;
  finished: JobFinished | null;
  /**
   * How its results were already saved (to a folder, or sent to the browser's downloads), or
   * null if they weren't. A job saved to a folder no longer has results to save again.
   */
  saved: SaveOutcome | null;
  /** Whether that save was one .zip (so Download again does the same). */
  savedAsZip: boolean;
}

/** What `quit` did. */
export interface QuitResult {
  /** True if the app is closing. */
  quit: boolean;
  /** A conversion was running (it is cancelled if the quit goes ahead). */
  running: boolean;
  /** Finished results that aren't saved yet (deleted if the quit goes ahead). */
  unsavedResults: number;
}

/**
 * Typed client used by the UI. Implemented by the pywebview bridge (desktop),
 * the local HTTP client (browser mode) and the dev mock.
 */
export interface PdfManagerApi {
  /** Which front end this is. */
  readonly mode: "desktop" | "browser" | "mock";
  /** How results are saved: into a folder (a picker or the default folder) or as browser downloads. */
  readonly saveMode: "folder" | "download";
  /**
   * Files dropped on the page: browser mode uploads them to the app and returns them. The
   * desktop window gets drops from Python (the `filesAdded` event) and returns nothing here.
   */
  addDroppedFiles(files: File[]): Promise<InputFile[]>;
  /** Browser mode, after a reload: the newest job whose results weren't discarded. Null elsewhere. */
  latestJob(): Promise<RecoveredJob | null>;
  /** Start (again) delivering `jobProgress`/`jobFinished` for a job. Browser mode polls; a no-op elsewhere. */
  watchJob(jobId: string): void;
  /**
   * Browser mode: quit the app. It doesn't quit while a job runs or results are unsaved
   * (`quit: false` says why) unless `discardUnsaved` confirms that. A no-op elsewhere (the
   * window's close button quits).
   */
  quit(options?: { discardUnsaved?: boolean }): Promise<QuitResult>;
  getAppInfo(): Promise<AppInfo>;
  getSettings(): Promise<Settings>;
  /**
   * Merge and persist a partial settings object. Always returns the settings now in effect;
   * `issue` is set (SETTINGS_SAVE_FAILED) if they couldn't be written to disk, so the UI can
   * show that the change applies only until the app closes.
   */
  saveSettings(patch: Partial<Settings>): Promise<SaveSettingsResult>;
  /** Native file picker. "all" accepts every supported type (PDF, PPTX, PPT, PNG, JPG). */
  pickFiles(kind: "all" | "documents" | "images"): Promise<InputFile[]>;
  pickFolder(): Promise<string | null>;
  /** Tool check for the Convert modal; checks only what this action needs. */
  checkTools(action: Action, settings: ActionSettings, data: ActionData): Promise<ToolCheckResult>;
  /** Whether Tesseract OCR is installed, and where (for Settings). */
  getOcrStatus(): Promise<OcrStatus>;
  getOcrLanguages(): Promise<string[]>;
  searchOcr(): Promise<OcrSearchResult>;
  installOcr(): Promise<void>;
  /** The single entry point for every conversion action. */
  startJob(action: Action, settings: ActionSettings, data: ActionData): Promise<StartJobResult>;
  cancelJob(jobId: string): Promise<void>;
  saveResults(jobId: string, options: SaveOptions): Promise<SaveOutcome>;
  discardResults(jobId: string): Promise<void>;
  openFolder(path: string): Promise<void>;
  openLogsFolder(): Promise<void>;
}

/** Events Python dispatches on window as `pdfmanager:<name>`. */
export interface PdfManagerEvents {
  filesAdded: { files: InputFile[] };
  jobProgress: JobProgress;
  jobFinished: JobFinished;
  ocrInstallProgress: { message: string };
  ocrInstallFinished: { ok: boolean; issue: Issue | null };
  /** Browser mode: the app stopped answering (`jobId` while a job was being watched). */
  connectionLost: { jobId: string | null };
}
