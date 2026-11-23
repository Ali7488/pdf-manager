import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Action } from "../../api/types";
import { renderApp, SAMPLE_FILES } from "../../test/renderApp";
import { CONTENTS_TIP, OCR_TIP } from "./ActionOptions";

const FOLDER = "D:\\Results";
const convertButton = () => screen.getByRole("button", { name: "Convert" });

describe("ActionPage option defaults", () => {
  it.each([Action.Flatten, Action.FlattenMerge, Action.Merge, Action.Split, Action.ImagesToPdf])(
    "%s offers Use OCR, unchecked",
    async (action) => {
      await renderApp({ state: { page: action } });
      expect(screen.getByRole("checkbox", { name: "Use OCR" })).not.toBeChecked();
    },
  );

  it("Compress has no OCR option and starts on Balanced", async () => {
    await renderApp({ state: { page: Action.Compress } });
    expect(screen.queryByRole("checkbox", { name: "Use OCR" })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Balanced/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "About Light" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "About Strong" })).toBeInTheDocument();
  });

  it.each([Action.Merge, Action.FlattenMerge])("%s offers a contents page, off by default", async (action) => {
    const { user } = await renderApp({ state: { page: action } });
    expect(screen.getByRole("checkbox", { name: "Add a contents page" })).not.toBeChecked();
    await user.hover(screen.getByRole("button", { name: "About Add a contents page" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent(CONTENTS_TIP);
  });

  it("Flatten has no contents page option", async () => {
    await renderApp({ state: { page: Action.Flatten } });
    expect(screen.queryByRole("checkbox", { name: "Add a contents page" })).not.toBeInTheDocument();
  });

  it("explains OCR in a tooltip", async () => {
    const { user } = await renderApp({ state: { page: Action.Flatten } });
    await user.hover(screen.getByRole("button", { name: "About Use OCR" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent(OCR_TIP);
  });

  it("Images to PDF starts on one PDF with all images", async () => {
    await renderApp({ state: { page: Action.ImagesToPdf } });
    expect(screen.getByRole("radio", { name: /One PDF with all images/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /One PDF per image/ })).not.toBeChecked();
  });

  it("ticks Save to default folder when a default folder is set", async () => {
    const { user } = await renderApp({ state: { page: Action.Merge }, mock: { settings: { defaultSaveFolder: FOLDER } } });
    expect(await screen.findByRole("checkbox", { name: "Save to default folder" })).toBeChecked();
    expect(screen.getByText(FOLDER)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Change default folder" }));
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("links to Settings when no default folder is set", async () => {
    const { user } = await renderApp({ state: { page: Action.Merge } });
    expect(screen.queryByRole("checkbox", { name: "Save to default folder" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Set a default folder" }));
    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
  });

  it("keeps a tab's options when switching away and back", async () => {
    const { user } = await renderApp({ state: { page: Action.Merge } });
    await user.click(screen.getByRole("checkbox", { name: "Add a contents page" }));
    await user.click(screen.getByRole("button", { name: "Home" }));
    await user.click(screen.getByRole("button", { name: "Merge" }));
    expect(screen.getByRole("checkbox", { name: "Add a contents page" })).toBeChecked();
  });
});

describe("Convert button", () => {
  it("is disabled when no file fits the mode", async () => {
    await renderApp({ state: { page: Action.ImagesToPdf, files: [SAMPLE_FILES[0]] } });
    expect(convertButton()).toBeDisabled();
    expect(screen.getByText("Add an image (PNG or JPG) to start.")).toBeInTheDocument();
  });

  it("sends only the accepted files, in list order", async () => {
    const { user, mock } = await renderApp({ state: { page: Action.Compress, files: SAMPLE_FILES } });
    const startJob = vi.spyOn(mock, "startJob");
    await user.click(convertButton());
    await screen.findByRole("heading", { name: "Done" });
    expect(startJob).toHaveBeenCalledWith(
      Action.Compress,
      expect.objectContaining({ compressLevel: "balanced", useOcr: false }),
      { files: ["C:\\in\\Report.pdf", "C:\\in\\Notes.pdf"] },
    );
  });
});

describe("Split options", () => {
  it("validates custom page ranges with a friendly message", async () => {
    const { user } = await renderApp({ state: { page: Action.Split, files: SAMPLE_FILES } });
    const input = screen.getByRole("textbox", { name: "Pages" });
    expect(convertButton()).toBeDisabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.type(input, "5-2");
    expect(screen.getByRole("alert")).toHaveTextContent("goes backwards");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(convertButton()).toBeDisabled();

    await user.clear(input);
    await user.type(input, "1-3, 5, 8-10");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(convertButton()).toBeEnabled();
    // Notes.pdf has 4 pages, which the ranges go past.
    expect(screen.getByText(/"Notes.pdf" has only 4 pages/)).toBeInTheDocument();
  });

  it("checks the every-N number and allows one file per page", async () => {
    const { user } = await renderApp({ state: { page: Action.Split, files: SAMPLE_FILES } });
    await user.click(screen.getByRole("radio", { name: /Every few pages/ }));
    const input = screen.getByRole("spinbutton", { name: "Pages in each file" });
    expect(input).toHaveValue(5);
    expect(convertButton()).toBeEnabled();
    await user.clear(input);
    expect(screen.getByRole("alert")).toHaveTextContent("whole number");
    expect(convertButton()).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: /One file per page/ }));
    expect(convertButton()).toBeEnabled();
  });

  it("explains that each range becomes its own file", async () => {
    const { user } = await renderApp({ state: { page: Action.Split } });
    const group = screen.getByRole("group", { name: /How to split/ });
    await user.hover(within(group).getByRole("button", { name: "About How to split" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Each range becomes its own PDF file");
  });
});
