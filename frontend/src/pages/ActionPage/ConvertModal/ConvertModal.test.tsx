import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LINUX_OCR_INSTALL_COMMAND } from "../../../api/mock";
import { Action, type InputFile } from "../../../api/types";
import { renderApp, SAMPLE_FILES } from "../../../test/renderApp";

const FOLDER = "D:\\Results";
const pdfs = SAMPLE_FILES.filter((file) => file.kind === "pdf");
const dialog = () => screen.getByRole("dialog");

describe("ConvertModal", () => {
  it("checks tools, shows progress, then saves to a chosen folder", async () => {
    const { user, mock } = await renderApp({
      state: { page: Action.Flatten, files: SAMPLE_FILES },
      mock: { tickMs: 15, folderPicker: () => FOLDER },
    });
    const saveResults = vi.spyOn(mock, "saveResults");
    await user.click(screen.getByRole("button", { name: "Convert" }));

    // Tool check: only PowerPoint/LibreOffice rows (no OCR), with LibreOffice not needed.
    const tools = await screen.findByRole("list", { name: "Tools this job needs" });
    expect(within(tools).queryByText(/OCR/)).not.toBeInTheDocument();
    await within(dialog()).findByText("Not present (not needed)");

    // Progress.
    await screen.findByRole("progressbar", { name: "Conversion progress" });
    await within(dialog()).findByText(/File \d of 3/);

    // Finished: outputs, the PowerPoint warning, and Save.
    await screen.findByRole("heading", { name: "Done" }, { timeout: 3000 });
    expect(screen.getByText("Report - Flattened.pdf")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /Warning: PowerPoint had a problem/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save as one .zip" })).not.toBeInTheDocument();
    // Unsaved results can't be dismissed by accident.
    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(FOLDER)).toBeInTheDocument();
    expect(saveResults).toHaveBeenCalledWith(expect.any(String), { folder: null, asZip: false });

    const openFolder = vi.spyOn(mock, "openFolder");
    await user.click(screen.getByRole("button", { name: "Open folder" }));
    expect(openFolder).toHaveBeenCalledWith(FOLDER);
    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("saves to the default folder straight away when ticked", async () => {
    const { user, mock } = await renderApp({
      state: { page: Action.Merge, files: pdfs },
      mock: { settings: { defaultSaveFolder: FOLDER } },
    });
    const saveResults = vi.spyOn(mock, "saveResults");
    await screen.findByRole("checkbox", { name: "Save to default folder" });
    await user.click(screen.getByRole("button", { name: "Convert" }));

    await screen.findByRole("heading", { name: "Done" });
    expect(await within(dialog()).findByText(/^Saved to/)).toHaveTextContent(`Saved to ${FOLDER}`);
    expect(saveResults).toHaveBeenCalledWith(expect.any(String), { folder: FOLDER, asZip: false });
  });

  it("keeps the results when the folder picker is cancelled", async () => {
    const { user } = await renderApp({
      state: { page: Action.Compress, files: pdfs },
      mock: { folderPicker: () => null },
    });
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "Done" });
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/No folder was chosen. Your results are kept/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("asks before discarding results", async () => {
    const { user, mock } = await renderApp({ state: { page: Action.Compress, files: pdfs } });
    const discard = vi.spyOn(mock, "discardResults");
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "Done" });

    await user.click(screen.getByRole("button", { name: "Discard" }));
    await user.click(screen.getByRole("button", { name: "Keep them" }));
    expect(discard).not.toHaveBeenCalled();
    expect(dialog()).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Discard" }));
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(discard).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers Save as one .zip for Split", async () => {
    const { user, mock } = await renderApp({ state: { page: Action.Split, files: [SAMPLE_FILES[0]] } });
    const saveResults = vi.spyOn(mock, "saveResults");
    await user.click(screen.getByRole("radio", { name: /One file per page/ }));
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "Done" });
    expect(screen.getByText(/Your \d+ new files/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save as one .zip" }));
    await waitFor(() => expect(saveResults).toHaveBeenCalledWith(expect.any(String), { folder: null, asZip: true }));
  });

  it("cancels a running job", async () => {
    const { user } = await renderApp({ state: { page: Action.Flatten, files: pdfs }, mock: { tickMs: 30 } });
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("progressbar");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await screen.findByRole("heading", { name: "Cancelled" });
    expect(screen.getByText("The job was cancelled. Nothing was saved.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the error when the job fails", async () => {
    const broken: InputFile = { path: "C:\\in\\will fail.pdf", name: "will fail.pdf", kind: "pdf", sizeBytes: 10, pageCount: 1 };
    const { user } = await renderApp({ state: { page: Action.Merge, files: [pdfs[0], broken] } });
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "It didn't work" });
    const issue = screen.getByRole("region", { name: "Error: A file couldn't be read" });
    expect(within(issue).getAllByRole("listitem").length).toBeGreaterThan(0);

    // Technical details are hidden until asked for.
    expect(within(issue).queryByText(/Traceback/)).not.toBeInTheDocument();
    await user.click(within(issue).getByRole("button", { name: "Show details" }));
    expect(within(issue).getByText(/Traceback/)).toBeInTheDocument();
    expect(within(issue).getByRole("button", { name: "Open logs folder" })).toBeInTheDocument();
  });

  it("blocks when OCR is missing, then continues after installing it", async () => {
    const { user, mock } = await renderApp({ state: { page: Action.Merge, files: pdfs } });
    const startJob = vi.spyOn(mock, "startJob");
    await user.click(screen.getByRole("checkbox", { name: "Use OCR" }));
    await user.click(screen.getByRole("button", { name: "Convert" }));

    await screen.findByRole("heading", { name: "Something is missing" });
    expect(within(dialog()).getByText("Missing")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Error: OCR isn't installed" })).toBeInTheDocument();
    expect(startJob).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Install OCR" }));
    // After the install finishes, the check runs again and the job starts.
    await screen.findByRole("heading", { name: "Done" }, { timeout: 3000 });
    expect(startJob).toHaveBeenCalledWith(Action.Merge, expect.objectContaining({ useOcr: true }), {
      files: pdfs.map((file) => file.path),
    });
  });

  it("on Linux, shows the OCR install command inside the modal (C16)", async () => {
    const { user } = await renderApp({ state: { page: Action.Merge, files: pdfs }, mock: { platform: "linux" } });
    await user.click(screen.getByRole("checkbox", { name: "Use OCR" }));
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "Something is missing" });

    await user.click(screen.getByRole("button", { name: "Install OCR" }));
    const issue = await screen.findByRole("region", { name: "Warning: Install OCR with one command" }, { timeout: 3000 });
    expect(within(issue).getByText(LINUX_OCR_INSTALL_COMMAND)).toBeInTheDocument();
    expect(within(issue).getByRole("button", { name: "Copy command" })).toBeInTheDocument();
    // The OCR_MISSING issue above it has no command, so only one Copy button shows.
    expect(screen.getAllByRole("button", { name: "Copy command" })).toHaveLength(1);
  });

  it("explains when PowerPoint files can't be opened at all", async () => {
    const { user } = await renderApp({
      state: { page: Action.Flatten, files: [SAMPLE_FILES[1]] },
      mock: { tools: { powerpoint: false, libreoffice: false } },
    });
    await user.click(screen.getByRole("button", { name: "Convert" }));
    await screen.findByRole("heading", { name: "Something is missing" });
    expect(within(dialog()).getAllByText("Missing")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Error: PowerPoint files can't be opened" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
