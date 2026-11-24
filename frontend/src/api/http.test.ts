import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { onEvent } from "./events";
import { ConnectionError, createHttpApi, readBrowserBootstrap } from "./http";
import { Action, type JobFinished, type JobProgress } from "./types";
import { defaultActionSettings } from "../lib/actions";

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>;

const json = (result: unknown, status = 200) =>
  new Response(JSON.stringify({ result }), { status, headers: { "Content-Type": "application/json" } });

let handler: Handler;
const calls: { url: string; init: RequestInit }[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      return Promise.resolve(handler(url, init));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  document.head.querySelector('meta[name="pdf-manager-mode"]')?.remove();
});

const progress: JobProgress = {
  jobId: "a".repeat(32),
  stage: "preparing",
  fileIndex: 1,
  fileCount: 1,
  page: null,
  pageCount: null,
  fraction: 0.5,
  message: "Halfway",
};
const finished: JobFinished = { jobId: "a".repeat(32), status: "succeeded", outputs: [], warnings: [], error: null };

describe("readBrowserBootstrap", () => {
  it("reads the app's tag, and nothing without it", () => {
    expect(readBrowserBootstrap()).toBeNull();
    const tag = document.createElement("meta");
    tag.name = "pdf-manager-mode";
    tag.content = "browser";
    tag.setAttribute("data-native-dialogs", "true");
    document.head.appendChild(tag);
    expect(readBrowserBootstrap()).toEqual({ nativeDialogs: true });
    tag.setAttribute("data-native-dialogs", "false");
    expect(readBrowserBootstrap()).toEqual({ nativeDialogs: false });
  });
});

describe("createHttpApi", () => {
  it("sends same-origin requests with the app's header and JSON bodies", async () => {
    handler = () => json({ settings: {}, issue: null });
    const api = createHttpApi({ nativeDialogs: true });
    expect(api.mode).toBe("browser");
    await api.saveSettings({ theme: "dark" });
    const { url, init } = calls[0];
    expect(url).toBe("/api/settings");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect(init.headers).toMatchObject({ "X-PDF-Manager": "1", "Content-Type": "application/json" });
    expect(JSON.parse(init.body as string)).toEqual({ theme: "dark" });
  });

  it("polls a started job and dispatches its progress and result once", async () => {
    let polls = 0;
    handler = (url) => {
      if (url === "/api/jobs") return json({ jobId: "a".repeat(32) });
      polls += 1;
      return json({ jobId: "a".repeat(32), progress, finished: polls >= 3 ? finished : null });
    };
    const seen: string[] = [];
    const offProgress = onEvent("jobProgress", (p) => seen.push(`progress ${p.message}`));
    const done = new Promise<void>((resolve) => {
      const off = onEvent("jobFinished", (f) => {
        seen.push(`finished ${f.status}`);
        off();
        resolve();
      });
    });
    const api = createHttpApi({ nativeDialogs: true });
    await api.startJob(Action.Merge, defaultActionSettings(), { files: ["f-1"] });
    await done;
    offProgress();
    expect(seen).toEqual(["progress Halfway", "finished succeeded"]);
    const body = JSON.parse(calls[0].init.body as string);
    expect(body).toMatchObject({ action: "merge", data: { files: ["f-1"] } });
    expect(typeof body.requestId).toBe("string");
  });

  it("retries a start the app didn't answer with the same request ID", async () => {
    let attempts = 0;
    handler = (url) => {
      if (url === "/api/jobs") {
        attempts += 1;
        if (attempts === 1) throw new TypeError("Failed to fetch");
        return json({ issue: null, jobId: "b".repeat(32) });
      }
      return json({ jobId: "b".repeat(32), progress: null, finished });
    };
    const api = createHttpApi({ nativeDialogs: true });
    const started = await api.startJob(Action.Merge, defaultActionSettings(), { files: ["f-1"] });
    expect(started.jobId).toBe("b".repeat(32));
    const ids = calls.filter((c) => c.url === "/api/jobs").map((c) => JSON.parse(c.init.body as string).requestId);
    expect(ids).toHaveLength(2);
    expect(ids[0]).toBe(ids[1]);
  });

  it("reports a lost connection when polling keeps failing", async () => {
    vi.useFakeTimers();
    handler = () => {
      throw new TypeError("Failed to fetch");
    };
    const lost = vi.fn();
    const off = onEvent("connectionLost", lost);
    const api = createHttpApi({ nativeDialogs: true });
    api.watchJob("c".repeat(32));
    await vi.advanceTimersByTimeAsync(16_000);
    off();
    expect(lost).toHaveBeenCalledWith({ jobId: "c".repeat(32) });
  });

  it("rejects with ConnectionError when the app is gone, and says so", async () => {
    handler = () => {
      throw new TypeError("Failed to fetch");
    };
    const lost = vi.fn();
    const off = onEvent("connectionLost", lost);
    const api = createHttpApi({ nativeDialogs: true });
    await expect(api.getSettings()).rejects.toBeInstanceOf(ConnectionError);
    off();
    expect(lost).toHaveBeenCalledWith({ jobId: null });
  });

  it("uploads dropped files as raw bytes and returns their IDs", async () => {
    handler = (url) =>
      json([{ path: "f-x", name: decodeURIComponent(url.split("name=")[1].split("&")[0]), kind: "pdf", sizeBytes: 1, pageCount: 1 }]);
    const api = createHttpApi({ nativeDialogs: false });
    const files = await api.addDroppedFiles([new File(["%PDF"], "Report 1.pdf", { lastModified: 5 })]);
    expect(files.map((f) => f.path)).toEqual(["f-x"]);
    expect(calls[0].url).toBe("/api/files/upload?name=Report%201.pdf");
    expect(calls[0].init.headers).toMatchObject({ "Content-Type": "application/octet-stream" });
  });

  it("without native pickers, saving sends the results to the browser's downloads", async () => {
    handler = (url) => {
      if (url.endsWith("/download")) return json({ downloads: [{ id: "x-1", name: "Result.pdf" }], issue: null });
      return new Response(new Blob(["%PDF"]), { status: 200 });
    };
    const created = vi.fn(() => "blob:result");
    vi.stubGlobal("URL", Object.assign(Object.create(URL), { createObjectURL: created, revokeObjectURL: vi.fn() }));
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const api = createHttpApi({ nativeDialogs: false });
    expect(api.saveMode).toBe("download");
    const outcome = await api.saveResults("d".repeat(32), { folder: null, asZip: false });
    expect(outcome).toMatchObject({ downloaded: true, savedPaths: ["Result.pdf"], folder: null, issue: null });
    expect(calls.map((c) => c.url)).toEqual([`/api/jobs/${"d".repeat(32)}/download`, "/api/downloads/x-1"]);
    expect(clicked).toHaveBeenCalledOnce();
    clicked.mockRestore();
  });

  it("with native pickers, saving asks the app (which shows the folder picker)", async () => {
    handler = () => json({ cancelled: false, savedPaths: ["D:\\out\\a.pdf"], folder: "D:\\out", issue: null });
    const api = createHttpApi({ nativeDialogs: true });
    expect(api.saveMode).toBe("folder");
    await api.saveResults("e".repeat(32), { folder: null, asZip: true });
    expect(calls[0].url).toBe(`/api/jobs/${"e".repeat(32)}/save`);
    expect(JSON.parse(calls[0].init.body as string)).toEqual({ folder: null, asZip: true });
  });
});
