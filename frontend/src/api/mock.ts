/**
 * In-memory mock of the Python backend, used when `window.pywebview` is absent
 * (`npm run dev` in a browser, and tests). It follows the contract in
 * docs/API.md closely enough to exercise every screen:
 *
 * - `pickFiles` returns sample files (a browser can't give real paths).
 * - Files dropped in the browser become fake `InputFile`s via `simulateDrop`.
 * - Jobs emit realistic `jobProgress` events over a few seconds, honour
 *   `cancelJob`, warn about PowerPoint files (POWERPOINT_FALLBACK), and fail
 *   when an input's name contains "fail".
 * - `checkTools` applies the contract's rules to a configurable set of tools.
 */
import { emitEvent } from "./bridge";
import {
  Action,
  type ActionData,
  type ActionSettings,
  type AppInfo,
  type FileKind,
  type InputFile,
  type Issue,
  type IssueCode,
  type JobFinished,
  type JobProgress,
  type JobStage,
  type OcrSearchResult,
  type OutputFile,
  type PdfManagerApi,
  type SaveOptions,
  type SaveOutcome,
  type Settings,
  type StartJobResult,
  type ToolCheckResult,
} from "./types";
import { parsePageRanges } from "../lib/pageRanges";

/** Which external tools the mock pretends are installed. */
export interface MockTools {
  ocr: boolean;
  powerpoint: boolean;
  libreoffice: boolean;
}

/** Options for {@link createMockApi}. */
export interface MockOptions {
  /** Milliseconds between simulated steps. Default 300 (a job takes a few seconds). */
  tickMs?: number;
  /** Installed tools. Default: PowerPoint only (no OCR, no LibreOffice). */
  tools?: Partial<MockTools>;
  /** Initial saved settings. */
  settings?: Partial<Settings>;
  /** What the native folder picker returns; null means the user cancelled. */
  folderPicker?: () => string | null;
  /** Make "Install OCR" fail. */
  ocrInstallFails?: boolean;
}

/** Extra controls only the mock has. */
export interface MockControls {
  /** Marks this object as the mock. */
  readonly isMock: true;
  /** Turns files dropped in a browser into fake InputFiles and emits `filesAdded`. */
  simulateDrop(files: ArrayLike<File>): void;
  /** Changes which tools are "installed". */
  setTools(tools: Partial<MockTools>): void;
}

/** The mock API: the full contract plus {@link MockControls}. */
export type MockApi = PdfManagerApi & MockControls;

/**
 * True if an API object is the mock (so dev-only features such as browser
 * drops can be enabled).
 *
 * @param api - Any API implementation.
 */
export function isMockApi(api: PdfManagerApi): api is MockApi {
  return (api as Partial<MockControls>).isMock === true;
}

const SAMPLE_FOLDER = "C:\\Users\\Public\\Documents";
const TESSERACT_PATH = "C:\\Program Files\\Tesseract-OCR\\tesseract.exe";

const DEFAULT_SETTINGS: Settings = {
  theme: "system",
  defaultSaveFolder: null,
  dpi: 200,
  ocrLanguage: "eng",
  ocrPageTimeoutSec: 120,
  tesseractPath: null,
};

/** Builds an Issue with the contract's shape. */
function makeIssue(
  code: IssueCode,
  severity: Issue["severity"],
  title: string,
  message: string,
  troubleshooting: string[],
  extra: Partial<Pick<Issue, "details" | "file">> = {},
): Issue {
  return {
    code,
    severity,
    title,
    message,
    troubleshooting,
    details: extra.details ?? null,
    logFile: "C:\\Users\\Public\\PDF Manager\\logs\\pdf-manager.log",
    file: extra.file ?? null,
  };
}

const OCR_MISSING = (): Issue =>
  makeIssue(
    "OCR_MISSING",
    "error",
    "OCR isn't installed",
    "Reading text from page images needs Tesseract OCR, which wasn't found on this computer.",
    [
      "Click Install OCR to install it now.",
      "If it's already installed, click Search for OCR and pick tesseract.exe.",
      "Or untick Use OCR and try again.",
    ],
  );

/** Detects a file kind from its name, as Python does. */
function kindFromName(name: string): FileKind | null {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (ext === "pdf") return "pdf";
  if (ext === "pptx") return "pptx";
  if (ext === "ppt") return "ppt";
  if (["png", "jpg", "jpeg"].includes(ext)) return "image";
  return null;
}

/** File name without its folder or extension. */
function baseName(path: string): string {
  const name = path.split(/[\\/]/).pop() ?? path;
  return name.replace(/\.[^.]+$/, "");
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** One planned step of a simulated job. */
type Step =
  | { kind: "progress"; progress: Omit<JobProgress, "jobId" | "fraction"> }
  | { kind: "fail"; issue: Issue };

interface MockJob {
  id: string;
  cancelRequested: boolean;
  finished: JobFinished | null;
  saved: boolean;
}

/**
 * Creates an in-memory mock of the Python API.
 *
 * @param options - Speed, installed tools and starting settings.
 * @returns A {@link MockApi}.
 */
export function createMockApi(options: MockOptions = {}): MockApi {
  const tickMs = options.tickMs ?? 300;
  const tools: MockTools = { ocr: false, powerpoint: true, libreoffice: false, ...options.tools };
  let settings: Settings = { ...DEFAULT_SETTINGS, ...options.settings };
  const folderPicker = options.folderPicker ?? (() => `${SAMPLE_FOLDER}\\PDF Manager results`);
  const knownFiles = new Map<string, InputFile>();
  const jobs = new Map<string, MockJob>();
  let runningJob: MockJob | null = null;
  let jobCounter = 0;
  let pickCounter = 0;

  /** Short delay so calls feel like a real round trip. */
  const latency = () => wait(Math.max(1, Math.round(tickMs / 3)));

  const remember = (file: InputFile) => {
    knownFiles.set(file.path, file);
    return file;
  };

  const kindOfPath = (path: string): FileKind | null =>
    knownFiles.get(path)?.kind ?? kindFromName(path);

  /** Page count for planning; PowerPoints and unknowns get a plausible number. */
  const pagesOf = (path: string): number => {
    const file = knownFiles.get(path);
    if (file?.pageCount) return file.pageCount;
    if (kindOfPath(path) === "image") return 1;
    return 8;
  };

  /** Makes the list of steps and the outputs for a job. */
  function planJob(action: Action, jobSettings: ActionSettings, data: ActionData) {
    const steps: Step[] = [];
    const outputs: OutputFile[] = [];
    const warnings: Issue[] = [];
    const fileCount = data.files.length;
    const ocr = jobSettings.useOcr && action !== Action.Compress;
    const progress = (
      stage: JobStage,
      fileIndex: number,
      message: string,
      page: number | null = null,
      pageCount: number | null = null,
    ) => steps.push({ kind: "progress", progress: { stage, fileIndex, fileCount, page, pageCount, message } });

    progress("preparing", 1, "Getting ready");

    if (action === Action.Split && jobSettings.split.method === "ranges") {
      const parsed = parsePageRanges(jobSettings.split.ranges);
      if (!parsed.ok) {
        steps.push({
          kind: "fail",
          issue: makeIssue("INVALID_PAGE_RANGES", "error", "The page ranges can't be read", parsed.message, [
            "Use numbers and ranges separated by commas, for example 1-3, 5, 8-10.",
          ]),
        });
        return { steps, outputs, warnings };
      }
    }

    let totalPages = 0;
    data.files.forEach((path, index) => {
      const i = index + 1;
      const name = path.split(/[\\/]/).pop() ?? path;
      const base = baseName(path);
      const kind = kindOfPath(path);
      const pages = pagesOf(path);
      totalPages += pages;

      if (kind === "pptx" || kind === "ppt") {
        progress("rendering_slides", i, `Turning slides into pages: ${name}`);
        warnings.push(
          makeIssue(
            "POWERPOINT_FALLBACK",
            "warning",
            "PowerPoint had a problem, so LibreOffice was used",
            `"${name}" was converted with LibreOffice instead. The layout may look slightly different.`,
            [
              "Open the result and check that the slides look right.",
              "If they don't, close PowerPoint completely and try again.",
              "Restarting the computer can also help if PowerPoint is stuck.",
            ],
            { details: "COM error 0x80048240: PowerPoint could not export the presentation.", file: path },
          ),
        );
      }

      if (name.toLowerCase().includes("fail")) {
        steps.push({
          kind: "fail",
          issue: makeIssue(
            "UNREADABLE_FILE",
            "error",
            "A file couldn't be read",
            `"${name}" seems to be damaged or isn't a real ${kind === "image" ? "image" : "PDF"}.`,
            [
              "Open the file in another app to check that it works.",
              "If it opens, save a new copy of it and add that copy instead.",
              "Remove this file from the list to convert the others.",
            ],
            { details: `Traceback (most recent call last):\n  ...\nFileDataError: cannot open broken document: ${path}`, file: path },
          ),
        });
        return;
      }

      // A handful of page steps per file keeps a job to a few seconds.
      const pageSteps = Math.min(pages, 4);
      const pageAt = (n: number) => Math.max(1, Math.round((n / pageSteps) * pages));
      switch (action) {
        case Action.Flatten:
        case Action.FlattenMerge:
          for (let n = 1; n <= pageSteps; n++) {
            progress("flattening", i, `Flattening ${name}: page ${pageAt(n)} of ${pages}`, pageAt(n), pages);
          }
          break;
        case Action.Merge:
          progress("merging", i, `Adding ${name}`);
          break;
        case Action.Split:
          progress("splitting", i, `Splitting ${name}`);
          break;
        case Action.ImagesToPdf:
          progress("preparing", i, `Placing ${name} on a page`);
          break;
        case Action.Compress:
          progress("compressing", i, `Making ${name} smaller`, null, null);
          progress("compressing", i, `Making ${name} smaller: almost done`, null, null);
          break;
      }
      if (ocr) {
        for (let n = 1; n <= pageSteps; n++) {
          progress("ocr", i, `Reading text in ${name}: page ${pageAt(n)} of ${pages}`, pageAt(n), pages);
        }
      }

      const size = knownFiles.get(path)?.sizeBytes ?? 500_000;
      if (action === Action.Flatten) {
        outputs.push({ name: `${base} - Flattened.pdf`, sizeBytes: Math.round(size * 1.6), pageCount: pages });
      } else if (action === Action.Compress) {
        outputs.push({ name: `${base} - Compressed.pdf`, sizeBytes: Math.round(size * 0.4), pageCount: pages });
      } else if (action === Action.ImagesToPdf && !jobSettings.combineImages) {
        outputs.push({ name: `${base}.pdf`, sizeBytes: size, pageCount: 1 });
      } else if (action === Action.Split) {
        outputs.push(...splitOutputs(base, pages, size, jobSettings.split));
      }
    });

    if (steps.some((step) => step.kind === "fail")) {
      return { steps, outputs, warnings };
    }

    const first = data.files[0] ? baseName(data.files[0]) : "Files";
    if (action === Action.FlattenMerge || action === Action.Merge) {
      progress("merging", fileCount, "Joining the files into one PDF");
      if (jobSettings.contentsPage) progress("merging", fileCount, "Adding the contents page");
      const contents = jobSettings.contentsPage ? 1 : 0;
      outputs.push({
        name: `${first} - Merged.pdf`,
        sizeBytes: 750_000 * fileCount,
        pageCount: totalPages + contents,
      });
    } else if (action === Action.ImagesToPdf && jobSettings.combineImages) {
      outputs.push({ name: `${first} - Images.pdf`, sizeBytes: 400_000 * fileCount, pageCount: fileCount });
    }
    progress("finishing", fileCount, "Finishing up");
    return { steps, outputs, warnings };
  }

  /** Output files a Split job would make. */
  function splitOutputs(base: string, pages: number, size: number, split: ActionSettings["split"]): OutputFile[] {
    const ranges: Array<[number, number]> = [];
    if (split.method === "per_page") {
      for (let p = 1; p <= pages; p++) ranges.push([p, p]);
    } else if (split.method === "every_n") {
      const n = Math.max(1, Math.floor(split.everyN));
      for (let p = 1; p <= pages; p += n) ranges.push([p, Math.min(pages, p + n - 1)]);
    } else {
      const parsed = parsePageRanges(split.ranges);
      if (parsed.ok) {
        for (const range of parsed.ranges) {
          if (range.start <= pages) ranges.push([range.start, Math.min(range.end, pages)]);
        }
      }
    }
    return ranges.map(([start, end]) => ({
      name: start === end ? `${base} - page ${start}.pdf` : `${base} - pages ${start}-${end}.pdf`,
      sizeBytes: Math.round((size / pages) * (end - start + 1)),
      pageCount: end - start + 1,
    }));
  }

  /** Runs a planned job one step per tick, emitting events like Python would. */
  function runJob(job: MockJob, plan: ReturnType<typeof planJob>) {
    const total = plan.steps.length;
    let index = 0;
    const finish = (finished: Omit<JobFinished, "jobId">) => {
      job.finished = { jobId: job.id, ...finished };
      runningJob = null;
      emitEvent("jobFinished", job.finished);
    };
    const tick = () => {
      if (job.cancelRequested) {
        finish({ status: "cancelled", outputs: [], warnings: [], error: null });
        return;
      }
      const step = plan.steps[index];
      if (!step) {
        finish({ status: "succeeded", outputs: plan.outputs, warnings: plan.warnings, error: null });
        return;
      }
      if (step.kind === "fail") {
        finish({ status: "failed", outputs: [], warnings: plan.warnings, error: step.issue });
        return;
      }
      index += 1;
      emitEvent("jobProgress", { jobId: job.id, fraction: index / (total + 1), ...step.progress });
      setTimeout(tick, tickMs);
    };
    setTimeout(tick, tickMs);
  }

  return {
    isMock: true,

    simulateDrop(files: ArrayLike<File>) {
      const added: InputFile[] = [];
      for (const file of Array.from(files)) {
        const kind = kindFromName(file.name);
        if (!kind) continue; // Python would skip unsupported files too.
        added.push(
          remember({
            path: `C:\\Dropped\\${file.name}`,
            name: file.name,
            kind,
            sizeBytes: file.size,
            pageCount: kind === "pdf" ? Math.min(200, Math.max(1, Math.round(file.size / 100_000))) : null,
          }),
        );
      }
      if (added.length > 0) emitEvent("filesAdded", { files: added });
    },

    setTools(next: Partial<MockTools>) {
      Object.assign(tools, next);
    },

    async getAppInfo(): Promise<AppInfo> {
      await latency();
      return { version: "1.0.0 (preview)", logsDir: "C:\\Users\\Public\\PDF Manager\\logs", platform: "windows" };
    },

    async getSettings() {
      await latency();
      return { ...settings };
    },

    async saveSettings(patch: Partial<Settings>) {
      await latency();
      settings = { ...settings, ...patch };
      return { ...settings };
    },

    async pickFiles(kind: "documents" | "images") {
      await latency();
      pickCounter += 1;
      const extra = pickCounter > 1 ? pickCounter : null;
      const docs: InputFile[] = [
        { path: `${SAMPLE_FOLDER}\\Sample report.pdf`, name: "Sample report.pdf", kind: "pdf", sizeBytes: 1_240_000, pageCount: 12 },
        { path: `${SAMPLE_FOLDER}\\Slides overview.pptx`, name: "Slides overview.pptx", kind: "pptx", sizeBytes: 4_800_000, pageCount: null },
        { path: `${SAMPLE_FOLDER}\\Scanned pages.pdf`, name: "Scanned pages.pdf", kind: "pdf", sizeBytes: 8_400_000, pageCount: 6 },
      ];
      const images: InputFile[] = [
        { path: `${SAMPLE_FOLDER}\\Photo 1.jpg`, name: "Photo 1.jpg", kind: "image", sizeBytes: 2_100_000, pageCount: null },
        { path: `${SAMPLE_FOLDER}\\Diagram.png`, name: "Diagram.png", kind: "image", sizeBytes: 310_000, pageCount: null },
      ];
      const list = kind === "images" ? images : docs;
      // Later picks add one new file, so the list can grow while dedupe still shows.
      if (extra) {
        list.push(
          kind === "images"
            ? { path: `${SAMPLE_FOLDER}\\Photo ${extra}.png`, name: `Photo ${extra}.png`, kind: "image", sizeBytes: 900_000, pageCount: null }
            : { path: `${SAMPLE_FOLDER}\\Document ${extra}.pdf`, name: `Document ${extra}.pdf`, kind: "pdf", sizeBytes: 640_000, pageCount: 3 + extra },
        );
      }
      return list.map(remember);
    },

    async pickFolder() {
      await latency();
      return folderPicker();
    },

    async checkTools(action: Action, jobSettings: ActionSettings, data: ActionData): Promise<ToolCheckResult> {
      await wait(tickMs * 2);
      const ocrRequired = jobSettings.useOcr && action !== Action.Compress;
      const hasSlides = data.files.some((path) => {
        const kind = kindOfPath(path);
        return kind === "pptx" || kind === "ppt";
      });
      const issues: Issue[] = [];
      if (ocrRequired && !tools.ocr) issues.push(OCR_MISSING());
      if (hasSlides && !tools.powerpoint && !tools.libreoffice) {
        issues.push(
          makeIssue(
            "SLIDE_RENDERER_MISSING",
            "error",
            "PowerPoint files can't be opened",
            "Converting PowerPoint files needs Microsoft PowerPoint or LibreOffice, and neither was found.",
            [
              "Install Microsoft PowerPoint, or install LibreOffice (free).",
              "Or remove the PowerPoint files from the list and try again.",
            ],
          ),
        );
      }
      if (hasSlides && tools.powerpoint && !tools.libreoffice) {
        issues.push(
          makeIssue("SLIDE_RENDERER_MISSING", "warning", "LibreOffice not present", "PowerPoint will be used. LibreOffice is only a backup.", []),
        );
      }
      return {
        ok: !issues.some((issue) => issue.severity === "error"),
        ocr: { required: ocrRequired, present: tools.ocr, path: tools.ocr ? (settings.tesseractPath ?? TESSERACT_PATH) : null },
        powerpoint: {
          required: hasSlides,
          present: tools.powerpoint,
          path: tools.powerpoint ? "C:\\Program Files\\Microsoft Office\\root\\Office16\\POWERPNT.EXE" : null,
        },
        libreoffice: {
          required: hasSlides && !tools.powerpoint,
          present: tools.libreoffice,
          path: tools.libreoffice ? "C:\\Program Files\\LibreOffice\\program\\soffice.exe" : null,
        },
        issues,
      };
    },

    async getOcrLanguages() {
      await latency();
      return tools.ocr ? ["eng", "deu", "fra", "spa", "osd"] : [];
    },

    async searchOcr(): Promise<OcrSearchResult> {
      await wait(tickMs * 2);
      if (tools.ocr) {
        settings = { ...settings, tesseractPath: TESSERACT_PATH };
        return { found: true, path: TESSERACT_PATH, issue: null };
      }
      return {
        found: false,
        path: null,
        issue: makeIssue(
          "OCR_MISSING",
          "error",
          "OCR wasn't found",
          "Tesseract OCR isn't in any of the usual places, and no tesseract.exe was chosen.",
          ["Click Install OCR to install it.", "If you installed it somewhere else, search again and pick tesseract.exe."],
        ),
      };
    },

    async installOcr() {
      await latency();
      const messages = ["Downloading Tesseract OCR", "Installing", "Adding languages", "Checking the installation"];
      messages.forEach((message, index) => {
        setTimeout(() => emitEvent("ocrInstallProgress", { message }), tickMs * (index + 1) * 2);
      });
      setTimeout(() => {
        if (options.ocrInstallFails) {
          emitEvent("ocrInstallFinished", {
            ok: false,
            issue: makeIssue(
              "OCR_INSTALL_FAILED",
              "error",
              "OCR couldn't be installed",
              "The installer stopped before it finished.",
              ["Check your internet connection.", "Try again, or install Tesseract OCR yourself and use Search for OCR."],
              { details: "winget exited with code 0x8A15000F" },
            ),
          });
          return;
        }
        tools.ocr = true;
        settings = { ...settings, tesseractPath: TESSERACT_PATH };
        emitEvent("ocrInstallFinished", { ok: true, issue: null });
      }, tickMs * (messages.length + 1) * 2);
    },

    async startJob(action: Action, jobSettings: ActionSettings, data: ActionData): Promise<StartJobResult> {
      await latency();
      if (runningJob) {
        return {
          issue: makeIssue("JOB_ALREADY_RUNNING", "error", "Another job is still running", "Only one job can run at a time.", [
            "Wait for the current job to finish, or cancel it.",
          ]),
        };
      }
      jobCounter += 1;
      const job: MockJob = { id: `job-${jobCounter}`, cancelRequested: false, finished: null, saved: false };
      jobs.set(job.id, job);
      runningJob = job;
      runJob(job, planJob(action, jobSettings, data));
      return { jobId: job.id };
    },

    async cancelJob(jobId: string) {
      await latency();
      const job = jobs.get(jobId);
      if (job && !job.finished) job.cancelRequested = true;
    },

    async saveResults(jobId: string, saveOptions: SaveOptions): Promise<SaveOutcome> {
      await latency();
      const job = jobs.get(jobId);
      if (!job?.finished || job.finished.status !== "succeeded") {
        return {
          cancelled: false,
          savedPaths: [],
          folder: null,
          issue: makeIssue("SAVE_FAILED", "error", "The results couldn't be saved", "These results are no longer available.", [
            "Run the job again.",
          ]),
        };
      }
      const folder = saveOptions.folder ?? folderPicker();
      if (folder === null) return { cancelled: true, savedPaths: [], folder: null, issue: null };
      job.saved = true;
      const outputs = job.finished.outputs;
      const savedPaths = saveOptions.asZip
        ? [`${folder}\\${baseName(outputs[0]?.name ?? "Results")} - split.zip`]
        : outputs.map((output) => `${folder}\\${output.name}`);
      return { cancelled: false, savedPaths, folder, issue: null };
    },

    async discardResults(jobId: string) {
      await latency();
      jobs.delete(jobId);
    },

    async openFolder(path: string) {
      await latency();
      console.info(`[mock] Would open folder: ${path}`);
    },

    async openLogsFolder() {
      await latency();
      console.info("[mock] Would open the logs folder");
    },
  };
}
