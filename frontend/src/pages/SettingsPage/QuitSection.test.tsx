import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "../../App";
import { createMockApi } from "../../api/mock";
import type { PdfManagerApi } from "../../api/types";
import { quitWarning } from "../../lib/quit";

async function renderSettings(api: PdfManagerApi) {
  const user = userEvent.setup();
  render(<App api={api} initialState={{ page: "settings" }} />);
  await screen.findByRole("navigation", { name: "Main" });
  await act(() => new Promise((resolve) => setTimeout(resolve, 10)));
  return user;
}

describe("Quit PDF Manager (browser mode)", () => {
  it("quits straight away when nothing would be lost", async () => {
    const api: PdfManagerApi = { ...createMockApi(), mode: "browser" };
    const quit = vi.spyOn(api, "quit");
    const user = await renderSettings(api);
    await user.click(screen.getByRole("button", { name: "Quit PDF Manager" }));
    expect(quit).toHaveBeenCalledWith({ discardUnsaved: false });
    expect(await screen.findByRole("heading", { name: "PDF Manager has closed" })).toBeInTheDocument();
  });

  it("asks before deleting unsaved results, and can keep the app open", async () => {
    const api: PdfManagerApi = { ...createMockApi(), mode: "browser" };
    const quit = vi
      .spyOn(api, "quit")
      .mockResolvedValueOnce({ quit: false, running: false, unsavedResults: 2 })
      .mockResolvedValueOnce({ quit: false, running: false, unsavedResults: 2 })
      .mockResolvedValueOnce({ quit: true, running: false, unsavedResults: 2 });
    const user = await renderSettings(api);
    await user.click(screen.getByRole("button", { name: "Quit PDF Manager" }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("2 finished results aren't saved yet. Quitting now deletes them.")).toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Keep PDF Manager open" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "PDF Manager has closed" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Quit PDF Manager" }));
    await user.click(within(await screen.findByRole("alert")).getByRole("button", { name: "Quit anyway" }));
    expect(quit).toHaveBeenLastCalledWith({ discardUnsaved: true });
    expect(await screen.findByRole("heading", { name: "PDF Manager has closed" })).toBeInTheDocument();
  });

  it("words each case plainly", () => {
    expect(quitWarning({ quit: false, running: false, unsavedResults: 1 })).toBe(
      "One finished result isn't saved yet. Quitting now deletes it.",
    );
    expect(quitWarning({ quit: false, running: true, unsavedResults: 0 })).toBe(
      "A conversion is still running. Quitting now stops it.",
    );
    expect(quitWarning({ quit: false, running: true, unsavedResults: 1 })).toMatch(
      /still running, and one finished result isn't saved yet\. Quitting now stops the conversion/,
    );
  });
});
