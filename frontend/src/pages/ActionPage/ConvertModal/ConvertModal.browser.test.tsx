/**
 * Convert window behaviour that only browser mode reaches: requests the app
 * doesn't answer, a lost connection during a job, a job resumed after a page
 * reload, and saving through the browser's downloads.
 */
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "../../../App";
import { emitEvent } from "../../../api/events";
import { createMockApi } from "../../../api/mock";
import { Action, type PdfManagerApi } from "../../../api/types";
import type { AppState } from "../../../state/appReducer";
import { SAMPLE_FILES } from "../../../test/renderApp";

const pdfs = SAMPLE_FILES.filter((file) => file.kind === "pdf");
const dialog = () => screen.getByRole("dialog");

async function renderWith(api: PdfManagerApi, state: Partial<AppState>) {
  const user = userEvent.setup();
  render(<App api={api} initialState={state} />);
  await screen.findByRole("navigation", { name: "Main" });
  await act(() => new Promise((resolve) => setTimeout(resolve, 10)));
  return user;
}

describe("ConvertModal in browser mode", () => {
  it("explains a start the app didn't answer, instead of hanging", async () => {
    const api = createMockApi({ tickMs: 1 });
    vi.spyOn(api, "checkTools").mockRejectedValue(new Error("PDF Manager didn't answer"));
    const user = await renderWith(api, { page: Action.Merge, files: pdfs });
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "The job couldn't start" });
    expect(within(dialog()).getByText("PDF Manager isn't answering")).toBeInTheDocument();
    await user.click(within(dialog()).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers Try again after losing contact during a job, and follows the job again", async () => {
    const api = createMockApi({ tickMs: 200 });
    const watch = vi.spyOn(api, "watchJob");
    const user = await renderWith(api, { page: Action.Merge, files: pdfs });
    const started = vi.spyOn(api, "startJob");
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("progressbar", { name: "Conversion progress" });
    const { jobId } = (await started.mock.results[0].value) as { jobId: string };
    act(() => emitEvent("connectionLost", { jobId }));
    await screen.findByRole("heading", { name: "Lost contact with PDF Manager" });
    await user.click(within(dialog()).getByRole("button", { name: "Try again" }));
    expect(watch).toHaveBeenCalledWith(jobId);
    await screen.findByRole("heading", { name: "Done" }, { timeout: 5000 });
  });

  it("shows a job found after a reload without starting a new one", async () => {
    const api = createMockApi({ tickMs: 1 });
    const watch = vi.spyOn(api, "watchJob");
    const start = vi.spyOn(api, "startJob");
    const jobId = "f".repeat(32);
    vi.spyOn(api, "latestJob").mockResolvedValue({
      jobId,
      action: Action.Split,
      progress: null,
      finished: null,
      saved: null,
      savedAsZip: false,
    });
    await renderWith(api, { page: "home" });
    await screen.findByRole("heading", { name: "Converting" });
    expect(watch).toHaveBeenCalledWith(jobId);
    expect(start).not.toHaveBeenCalled();
    act(() =>
      emitEvent("jobFinished", {
        jobId,
        status: "succeeded",
        outputs: [{ name: "Report - Split.pdf", sizeBytes: 10, pageCount: 1 }],
        warnings: [],
        error: null,
      }),
    );
    await screen.findByRole("heading", { name: "Done" });
    expect(screen.getByText("Report - Split.pdf")).toBeInTheDocument();
  });

  it("without a folder picker, saves through the browser's downloads", async () => {
    const mock = createMockApi({ tickMs: 1 });
    const api: PdfManagerApi = { ...mock, mode: "browser", saveMode: "download" };
    const save = vi.spyOn(api, "saveResults").mockResolvedValue({
      cancelled: false,
      savedPaths: ["Report - Merged.pdf"],
      folder: null,
      issue: null,
      downloaded: true,
    });
    const user = await renderWith(api, { page: Action.Merge, files: pdfs });
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "Done" });
    await user.click(within(dialog()).getByRole("button", { name: "Download" }));
    expect(await within(dialog()).findByText(/Sent to your browser's downloads/)).toBeInTheDocument();
    await user.click(within(dialog()).getByRole("button", { name: "Download again" }));
    expect(save).toHaveBeenCalledTimes(2);
  });

  const finished = (jobId: string) => ({
    jobId,
    status: "succeeded" as const,
    outputs: [{ name: "Report - Merged.pdf", sizeBytes: 10, pageCount: 1 }],
    warnings: [],
    error: null,
  });

  it("after a reload, a job already saved to a folder shows where it went and never offers Save", async () => {
    const api: PdfManagerApi = { ...createMockApi({ tickMs: 1 }), mode: "browser", saveMode: "folder" };
    const jobId = "a".repeat(32);
    const outcome = { cancelled: false, savedPaths: ["/out/Report - Merged.pdf"], folder: "/out", issue: null };
    vi.spyOn(api, "latestJob").mockResolvedValue({
      jobId,
      action: Action.Merge,
      progress: null,
      finished: finished(jobId),
      saved: outcome,
      savedAsZip: false,
    });
    const save = vi.spyOn(api, "saveResults");
    const discard = vi.spyOn(api, "discardResults");
    const user = await renderWith(api, { page: "home" });
    act(() => emitEvent("jobFinished", finished(jobId)));
    await screen.findByRole("heading", { name: "Done" });
    expect(within(dialog()).getByText("/out")).toBeInTheDocument();
    expect(within(dialog()).queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "Open folder" })).toBeInTheDocument();
    await user.click(within(dialog()).getByRole("button", { name: "Done" }));
    expect(save).not.toHaveBeenCalled();
    expect(discard).toHaveBeenCalledWith(jobId);
  });

  it("after a reload, a downloaded job keeps Download again (as one .zip) until Done", async () => {
    const mock = createMockApi({ tickMs: 1 });
    const api: PdfManagerApi = { ...mock, mode: "browser", saveMode: "download" };
    const jobId = "b".repeat(32);
    const outcome = { cancelled: false, savedPaths: ["Report - Split.zip"], folder: null, issue: null, downloaded: true };
    vi.spyOn(api, "latestJob").mockResolvedValue({
      jobId,
      action: Action.Split,
      progress: null,
      finished: finished(jobId),
      saved: outcome,
      savedAsZip: true,
    });
    const save = vi.spyOn(api, "saveResults").mockResolvedValue(outcome);
    const user = await renderWith(api, { page: "home" });
    act(() => emitEvent("jobFinished", finished(jobId)));
    await screen.findByRole("heading", { name: "Done" });
    expect(within(dialog()).getByText(/Sent to your browser's downloads/)).toBeInTheDocument();
    await user.click(within(dialog()).getByRole("button", { name: "Download again" }));
    expect(save).toHaveBeenCalledWith(jobId, { folder: null, asZip: true });
    expect(within(dialog()).getByRole("button", { name: "Done" })).toBeInTheDocument();
  });

  it("explains a pending result and opens it again for Save or Discard", async () => {
    const api: PdfManagerApi = { ...createMockApi({ tickMs: 1 }), mode: "browser", saveMode: "download" };
    const jobId = "c".repeat(32);
    vi.spyOn(api, "startJob").mockResolvedValue({
      issue: {
        code: "RESULT_PENDING",
        severity: "error",
        title: "Your last results aren't saved yet",
        message: "PDF Manager keeps one finished result at a time. Save or discard it before starting a new conversion.",
        troubleshooting: ["Click Show the results to open them again."],
        details: null,
        logFile: null,
        command: null,
        file: null,
      },
    });
    const user = await renderWith(api, { page: Action.Merge, files: pdfs });
    // The pending result belongs to a Split job; recovery finds it through latestJob.
    vi.spyOn(api, "latestJob").mockResolvedValue({
      jobId,
      action: Action.Split,
      progress: null,
      finished: finished(jobId),
      saved: null,
      savedAsZip: false,
    });
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "The job couldn't start" });
    expect(within(dialog()).getByText("Your last results aren't saved yet")).toBeInTheDocument();
    await user.click(within(dialog()).getByRole("button", { name: "Show the results" }));
    act(() => emitEvent("jobFinished", finished(jobId)));
    await screen.findByRole("heading", { name: "Done" });
    expect(screen.getByRole("heading", { level: 1, name: "Split" })).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(within(dialog()).getByRole("button", { name: "Discard" })).toBeInTheDocument();
  });
});
