import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { createMockApi, type MockApi } from "../api/mock";
import type { SaveSettingsResult, Settings } from "../api/types";
import { renderApp } from "../test/renderApp";

/**
 * Makes the mock's saveSettings answer late and on demand. Like Python, each
 * call is applied as soon as it arrives; only the reply is held back, so the
 * test can deliver replies in any order.
 */
function holdSettingsReplies(mock: MockApi) {
  const realSave = mock.saveSettings.bind(mock);
  const held: Array<() => void> = [];
  const sent: Array<Partial<Settings>> = [];
  let mostHeldAtOnce = 0;
  vi.spyOn(mock, "saveSettings").mockImplementation((patch) => {
    sent.push(patch);
    const applied = realSave(patch);
    return new Promise<SaveSettingsResult>((resolve) => {
      held.push(() => void applied.then(resolve));
      mostHeldAtOnce = Math.max(mostHeldAtOnce, held.length);
    });
  });

  /** Answers the newest waiting call first, then older ones, until none are left. */
  async function replyNewestFirst() {
    while (held.length > 0) {
      await act(async () => {
        held.pop()?.();
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
    }
  }

  return { sent, replyNewestFirst, mostHeldAtOnce: () => mostHeldAtOnce };
}

describe("AppProvider settings saves (audit R5)", () => {
  it("keeps the latest choice when replies come back in reverse order", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" } });
    const replies = holdSettingsReplies(mock);

    await user.click(screen.getByRole("radio", { name: /^Burgundy/ }));
    await user.click(screen.getByRole("radio", { name: /^Green/ }));
    await user.click(screen.getByRole("radio", { name: /^Dark/ }));
    // Shown straight away, before Python answers.
    expect(screen.getByRole("radio", { name: /^Dark/ })).toBeChecked();
    expect(document.documentElement.dataset.theme).toBe("dark");

    await replies.replyNewestFirst();

    expect(screen.getByRole("radio", { name: /^Dark/ })).toBeChecked();
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(replies.sent.at(-1)).toEqual({ theme: "dark" });
    expect((await mock.getSettings()).theme).toBe("dark");
    // Saves go one at a time, so an older reply can't land after a newer one.
    expect(replies.mostHeldAtOnce()).toBe(1);
  });

  it("keeps a newer change to one field when an older save of another field returns", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" } });
    const replies = holdSettingsReplies(mock);

    await user.click(screen.getByRole("radio", { name: /^Light/ }));
    const dpi = screen.getByRole("spinbutton", { name: "Resolution (DPI)" });
    await user.clear(dpi);
    await user.type(dpi, "300{Enter}");
    await user.click(screen.getByRole("radio", { name: /^Green/ }));

    await replies.replyNewestFirst();

    expect(screen.getByRole("radio", { name: /^Green/ })).toBeChecked();
    expect(screen.getByRole("spinbutton", { name: "Resolution (DPI)" })).toHaveValue(300);
    expect(await mock.getSettings()).toMatchObject({ theme: "green", dpi: 300 });
  });

  it("keeps a change made before the saved settings finished loading", async () => {
    const mock = createMockApi({ tickMs: 1, settings: { theme: "light", dpi: 250 } });
    let finishLoading = () => {};
    const realGet = mock.getSettings.bind(mock);
    vi.spyOn(mock, "getSettings").mockImplementationOnce(
      () => new Promise<Settings>((resolve) => (finishLoading = () => void realGet().then(resolve))),
    );
    const user = userEvent.setup();
    render(<App api={mock} initialState={{ page: "settings" }} />);

    await user.click(await screen.findByRole("radio", { name: /^Green/ }));
    await act(async () => {
      finishLoading();
      await new Promise((resolve) => setTimeout(resolve, 10));
    });

    expect(screen.getByRole("radio", { name: /^Green/ })).toBeChecked();
    expect(screen.getByRole("spinbutton", { name: "Resolution (DPI)" })).toHaveValue(250);
  });
});
