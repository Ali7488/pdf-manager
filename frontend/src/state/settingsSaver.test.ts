import { describe, expect, it } from "vitest";
import type { SaveSettingsResult, Settings } from "../api/types";
import { DEFAULT_SETTINGS } from "./appReducer";
import { createSettingsSaver, type SettingsSaveOutcome } from "./settingsSaver";

/** A fake saveSettings whose calls stay open until the test answers them. */
function heldSave() {
  const calls: Array<{ patch: Partial<Settings>; answer(result: SaveSettingsResult | Error): void }> = [];
  const save = (patch: Partial<Settings>) =>
    new Promise<SaveSettingsResult>((resolve, reject) => {
      calls.push({ patch, answer: (result) => (result instanceof Error ? reject(result) : resolve(result)) });
    });
  return { calls, save };
}

const saved = (patch: Partial<Settings>): SaveSettingsResult => ({
  settings: { ...DEFAULT_SETTINGS, ...patch },
  issue: null,
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe("createSettingsSaver", () => {
  it("sends one call at a time and merges changes made meanwhile", async () => {
    const { calls, save } = heldSave();
    const outcomes: SettingsSaveOutcome[] = [];
    const saver = createSettingsSaver(save, (outcome) => outcomes.push(outcome));

    void saver.save({ theme: "burgundy" });
    void saver.save({ theme: "green" });
    void saver.save({ dpi: 300 });
    void saver.save({ theme: "dark" });
    expect(calls.map((call) => call.patch)).toEqual([{ theme: "burgundy" }]);
    expect(saver.unconfirmed()).toEqual({ theme: "dark", dpi: 300 });

    // The first answer comes back with the old theme; the newer queued choice stays on top.
    calls[0].answer(saved({ theme: "burgundy" }));
    await flush();
    expect(outcomes[0].settings?.theme).toBe("dark");
    expect(outcomes[0].settings?.dpi).toBe(300);
    expect(calls.map((call) => call.patch)).toEqual([{ theme: "burgundy" }, { theme: "dark", dpi: 300 }]);

    calls[1].answer(saved({ theme: "dark", dpi: 300 }));
    await flush();
    expect(outcomes).toHaveLength(2);
    expect(outcomes[1].settings).toMatchObject({ theme: "dark", dpi: 300 });
    expect(saver.unconfirmed()).toEqual({});
  });

  it("resolves each change once the save carrying it has finished", async () => {
    const { calls, save } = heldSave();
    const saver = createSettingsSaver(save, () => {});
    const done: string[] = [];
    void saver.save({ theme: "light" }).then(() => done.push("first"));
    void saver.save({ theme: "dark" }).then(() => done.push("second"));

    calls[0].answer(saved({ theme: "light" }));
    await flush();
    expect(done).toEqual(["first"]);
    calls[1].answer(saved({ theme: "dark" }));
    await flush();
    expect(done).toEqual(["first", "second"]);
  });

  it("passes on Python's issue and turns a failed call into one", async () => {
    const { calls, save } = heldSave();
    const outcomes: SettingsSaveOutcome[] = [];
    const saver = createSettingsSaver(save, (outcome) => outcomes.push(outcome));
    expect(saver.hasAnswered()).toBe(false);

    void saver.save({ dpi: 250 });
    calls[0].answer(new Error("bridge went away"));
    await flush();
    expect(outcomes[0].settings).toBeNull();
    expect(outcomes[0].issue).toMatchObject({ code: "SETTINGS_SAVE_FAILED", details: "bridge went away" });
    expect(saver.hasAnswered()).toBe(true);

    // The queue keeps working after a failed call.
    void saver.save({ dpi: 260 });
    expect(calls).toHaveLength(2);
    calls[1].answer(saved({ dpi: 260 }));
    await flush();
    expect(outcomes[1]).toEqual({ settings: { ...DEFAULT_SETTINGS, dpi: 260 }, issue: null });
  });
});
