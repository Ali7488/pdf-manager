import { screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Action } from "../../api/types";
import { renderApp } from "../../test/renderApp";

describe("HomePage", () => {
  it("shows the drop zone and adds every kind of file with one button", async () => {
    const { user, mock } = await renderApp();
    const pickFiles = vi.spyOn(mock, "pickFiles");
    expect(screen.getByText("Drop files here, or click Add files")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add images" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add files" }));
    expect(pickFiles).toHaveBeenCalledWith("all");
    expect(await screen.findByText("Sample report.pdf")).toBeInTheDocument();
    expect(screen.getByText("Photo 1.jpg")).toBeInTheDocument();
    expect(screen.getAllByTestId("file-row")).toHaveLength(5);
  });

  it("asks for images only on the Images to PDF tab", async () => {
    const { user, mock } = await renderApp({ state: { page: Action.ImagesToPdf } });
    const pickFiles = vi.spyOn(mock, "pickFiles");
    await user.click(screen.getByRole("button", { name: "Add images" }));
    expect(pickFiles).toHaveBeenCalledWith("images");
  });

  it("opens a mode tab from its button", async () => {
    const { user } = await renderApp();
    await user.click(screen.getByRole("button", { name: "Open Split" }));
    expect(screen.getByRole("heading", { level: 1, name: "Split" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Split" })).toHaveAttribute("aria-current", "page");
  });
});
