import { act, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { emitEvent } from "../../api/bridge";
import { Action } from "../../api/types";
import { renderApp, SAMPLE_FILES } from "../../test/renderApp";

const rows = () => screen.getAllByTestId("file-row");
const names = () => rows().map((row) => within(row).getByTitle(/C:\\/).textContent);

describe("FileList", () => {
  it("adds files from the filesAdded event and skips duplicates", async () => {
    await renderApp();
    expect(screen.getByText(/No files yet/)).toBeInTheDocument();

    act(() => emitEvent("filesAdded", { files: SAMPLE_FILES.slice(0, 2) }));
    act(() => emitEvent("filesAdded", { files: SAMPLE_FILES.slice(1, 3) }));

    expect(names()).toEqual(["Report.pdf", "Slides.pptx", "Photo.jpg"]);
    expect(screen.getByText("PDF · 977 KB · 10 pages")).toBeInTheDocument();
    expect(screen.getByText("PowerPoint · 2.9 MB")).toBeInTheDocument();
  });

  it("removes one file and clears all", async () => {
    const { user } = await renderApp({ state: { files: SAMPLE_FILES } });
    await user.click(screen.getByRole("button", { name: "Remove Slides.pptx" }));
    expect(names()).toEqual(["Report.pdf", "Photo.jpg", "Notes.pdf"]);

    await user.click(screen.getByRole("button", { name: "Clear all" }));
    expect(screen.queryAllByTestId("file-row")).toHaveLength(0);
    expect(screen.getByText(/No files yet/)).toBeInTheDocument();
  });

  it("greys out files the current mode doesn't use", async () => {
    await renderApp({ state: { files: SAMPLE_FILES, page: Action.Compress } });
    const [report, slides, photo, notes] = rows();
    expect(report).toHaveAttribute("data-applicable", "true");
    expect(notes).toHaveAttribute("data-applicable", "true");
    for (const row of [slides, photo]) {
      expect(row).toHaveAttribute("data-applicable", "false");
      expect(within(row).getByText(/Not used in this mode/)).toBeInTheDocument();
    }
    expect(screen.getByText("2 of 4 used here")).toBeInTheDocument();
  });

  it("keeps the list when switching tabs", async () => {
    const { user } = await renderApp({ state: { files: SAMPLE_FILES } });
    await user.click(screen.getByRole("button", { name: "Merge" }));
    expect(screen.getByRole("heading", { level: 1, name: "Merge" })).toBeInTheDocument();
    expect(rows()).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: "Images to PDF" }));
    expect(rows()).toHaveLength(4);
    expect(rows()[2]).toHaveAttribute("data-applicable", "true");
  });

  it("gives every row a keyboard-reachable drag handle", async () => {
    await renderApp({ state: { files: SAMPLE_FILES } });
    const handle = screen.getByRole("button", { name: "Move Report.pdf (position 1)" });
    expect(handle).toHaveAttribute("aria-roledescription", "sortable");
  });
});
