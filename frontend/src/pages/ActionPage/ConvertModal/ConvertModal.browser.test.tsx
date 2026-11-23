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
    vi.spyOn(api, "latestJob").mockResolvedValue({ jobId, action: Action.Split, progress: null, finished: null });
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
});
