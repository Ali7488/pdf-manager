import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { InfoTip } from "./InfoTip";

describe("InfoTip", () => {
  it("shows the explanation on hover and hides it when the pointer leaves", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="OCR" text="Reads the text in page images." />);
    const trigger = screen.getByRole("button", { name: "About OCR" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.hover(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Reads the text in page images.");
    expect(trigger).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);

    await user.unhover(trigger);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("shows on keyboard focus and hides on Escape", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="DPI" text="Higher is sharper but bigger." />);
    await user.tab();
    expect(screen.getByRole("button", { name: "About DPI" })).toHaveFocus();
    expect(screen.getByRole("tooltip")).toHaveTextContent("Higher is sharper but bigger.");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
