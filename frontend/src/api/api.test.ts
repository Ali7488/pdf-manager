import { describe, expect, it, vi } from "vitest";
import { createBridgeApi, emitEvent, onEvent } from "./bridge";
import { createMockApi } from "./mock";
import { Action, type JobFinished, type JobProgress } from "./types";
import { defaultActionSettings } from "../lib/actions";

/** Resolves with the next jobFinished event. */
function nextFinished(): Promise<JobFinished> {
  return new Promise((resolve) => {
    const off = onEvent("jobFinished", (payload) => {
      off();
      resolve(payload);
    });
  });
}

describe("onEvent", () => {
  it("delivers pdfmanager:<name> payloads and unsubscribes", () => {
    const handler = vi.fn();
    const off = onEvent("ocrInstallProgress", handler);
    emitEvent("ocrInstallProgress", { message: "Downloading" });
    off();
    emitEvent("ocrInstallProgress", { message: "Ignored" });
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith({ message: "Downloading" });
  });
});

describe("bridge", () => {
  it("passes action, settings and data to Python as three arguments", async () => {
    const startJob = vi.fn().mockResolvedValue({ jobId: "j1" });
    window.pywebview = { api: { get_settings: vi.fn(), start_job: startJob } };
    try {
      const api = createBridgeApi();
      const settings = defaultActionSettings();
      const result = await api.startJob(Action.Merge, settings, { files: ["C:\\a.pdf"] });
      expect(result).toEqual({ jobId: "j1" });
      expect(startJob).toHaveBeenCalledWith("merge", settings, { files: ["C:\\a.pdf"] });
    } finally {
      delete window.pywebview;
    }
  });
});

describe("bridge mapping", () => {
  it("maps getOcrStatus to get_ocr_status and passes the pickFiles kind", async () => {
    const getOcrStatus = vi.fn().mockResolvedValue({ present: true, path: "C:\\t.exe" });
    const pickFiles = vi.fn().mockResolvedValue([]);
    window.pywebview = { api: { get_settings: vi.fn(), get_ocr_status: getOcrStatus, pick_files: pickFiles } };
    try {
      const api = createBridgeApi();
      expect(await api.getOcrStatus()).toEqual({ present: true, path: "C:\\t.exe" });
      await api.pickFiles("all");
      expect(pickFiles).toHaveBeenCalledWith("all");
    } finally {
      delete window.pywebview;
    }
  });
});

describe("mock API", () => {
  it("picks every kind with 'all' and reports OCR status", async () => {
    const api = createMockApi({ tickMs: 1 });
    const kinds = new Set((await api.pickFiles("all")).map((file) => file.kind));
    expect(kinds).toEqual(new Set(["pdf", "pptx", "image"]));
    expect(await api.getOcrStatus()).toEqual({ present: false, path: null });
    api.setTools({ ocr: true });
    expect((await api.getOcrStatus()).present).toBe(true);
  });

  it("uses the converting_images stage for Images to PDF", async () => {
    const api = createMockApi({ tickMs: 1 });
    const images = await api.pickFiles("images");
    const stages: string[] = [];
    const off = onEvent("jobProgress", (payload) => stages.push(payload.stage));
    const finished = nextFinished();
    await api.startJob(Action.ImagesToPdf, defaultActionSettings(), { files: images.map((file) => file.path) });
    await finished;
    off();
    expect(stages).toContain("converting_images");
  });

  it("applies the tool-check rules", async () => {
    const api = createMockApi({ tickMs: 1, tools: { ocr: false, powerpoint: true, libreoffice: false } });
    const files = await api.pickFiles("documents");
    const slides = files.filter((file) => file.kind === "pptx").map((file) => file.path);

    const noOcr = await api.checkTools(Action.Flatten, defaultActionSettings(), { files: slides });
    expect(noOcr.ok).toBe(true);
    expect(noOcr.ocr.required).toBe(false);
    expect(noOcr.powerpoint).toMatchObject({ required: true, present: true });
    expect(noOcr.libreoffice).toMatchObject({ required: false, present: false });

    const withOcr = await api.checkTools(
      Action.Flatten,
      { ...defaultActionSettings(), useOcr: true },
      { files: slides },
    );
    expect(withOcr.ok).toBe(false);
    expect(withOcr.issues.map((issue) => issue.code)).toContain("OCR_MISSING");

    const compress = await api.checkTools(
      Action.Compress,
      { ...defaultActionSettings(), useOcr: true },
      { files: [] },
    );
    expect(compress.ok).toBe(true);
    expect(compress.ocr.required).toBe(false);
  });

  it("runs a job with progress, warnings for PowerPoint files and outputs", async () => {
    const api = createMockApi({ tickMs: 1 });
    const files = await api.pickFiles("documents");
    const progress: JobProgress[] = [];
    const off = onEvent("jobProgress", (payload) => progress.push(payload));
    const finished = nextFinished();
    const started = await api.startJob(Action.Flatten, defaultActionSettings(), {
      files: files.map((file) => file.path),
    });
    const result = await finished;
    off();
    expect(result.jobId).toBe(started.jobId);
    expect(result.status).toBe("succeeded");
    expect(result.outputs).toHaveLength(3);
    expect(result.warnings.map((warning) => warning.code)).toEqual(["POWERPOINT_FALLBACK"]);
    expect(progress.length).toBeGreaterThan(3);
    expect(progress.every((p) => p.fraction > 0 && p.fraction < 1)).toBe(true);
  });

  it("fails when a file name contains 'fail', and supports cancel", async () => {
    const api = createMockApi({ tickMs: 1 });
    api.simulateDrop([new File(["x"], "will fail.pdf")]);
    const failed = nextFinished();
    await api.startJob(Action.Compress, defaultActionSettings(), { files: ["C:\\Dropped\\will fail.pdf"] });
    expect((await failed).error?.code).toBe("UNREADABLE_FILE");

    const cancelled = nextFinished();
    const started = await api.startJob(Action.Flatten, defaultActionSettings(), { files: ["C:\\x.pdf"] });
    await api.cancelJob(started.jobId!);
    expect((await cancelled).status).toBe("cancelled");
  });

  it("keeps results when the folder picker is cancelled", async () => {
    const api = createMockApi({ tickMs: 1, folderPicker: () => null });
    const finished = nextFinished();
    const started = await api.startJob(Action.Compress, defaultActionSettings(), { files: ["C:\\x.pdf"] });
    await finished;
    const outcome = await api.saveResults(started.jobId!, { folder: null, asZip: false });
    expect(outcome.cancelled).toBe(true);
    const saved = await api.saveResults(started.jobId!, { folder: "D:\\Out", asZip: false });
    expect(saved.savedPaths).toEqual(["D:\\Out\\x - Compressed.pdf"]);
  });
});
