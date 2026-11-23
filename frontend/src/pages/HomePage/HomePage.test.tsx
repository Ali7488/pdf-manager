import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderApp } from "../../test/renderApp";

describe("HomePage", () => {
  it("shows the drop zone and adds picked files", async () => {
    const { user } = await renderApp();
    expect(screen.getByText("Drop PDFs, PowerPoints or images here")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add files" }));
    expect(await screen.findByText("Sample report.pdf")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add images" }));
    expect(await screen.findByText("Photo 1.jpg")).toBeInTheDocument();
    expect(screen.getAllByTestId("file-row")).toHaveLength(5);
  });

  it("opens a mode tab from its button", async () => {
    const { user } = await renderApp();
    await user.click(screen.getByRole("button", { name: /Split\s*Break a file/ }));
    expect(screen.getByRole("heading", { level: 1, name: "Split" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Split" })).toHaveAttribute("aria-current", "page");
  });
});
