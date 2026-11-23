/**
 * Sends settings changes to Python one at a time, so responses can never
 * arrive out of order (audit R5).
 *
 * - Only one `saveSettings` call is in flight. Changes made meanwhile are
 *   merged into one queued patch and sent when the current call returns, so
 *   the last value sent for every field is the user's latest choice.
 * - When a response arrives while newer changes are still queued, those
 *   changes are laid over the returned snapshot, so an older response never
 *   undoes a newer choice on screen.
 */
import type { Issue, SaveSettingsResult, Settings } from "../api/types";

/** What one finished save means for the app. */
export interface SettingsSaveOutcome {
  /**
   * Settings to show: Python's snapshot with any still-queued changes on top.
   * Null when the call itself failed, so the local values stay as they are.
   */
  settings: Settings | null;
  /** SETTINGS_SAVE_FAILED when the change isn't on disk; null when it was saved. */
  issue: Issue | null;
}

/** The queue returned by {@link createSettingsSaver}. */
export interface SettingsSaver {
  /**
   * Queues a change to save.
   *
   * @param patch - The fields that changed.
   * @returns A promise that resolves once the save carrying this change has finished.
   */
  save(patch: Partial<Settings>): Promise<void>;
  /** Changes not yet confirmed by Python (in flight or queued). */
  unconfirmed(): Partial<Settings>;
  /** True once any save has returned; an older `getSettings` snapshot is then stale. */
  hasAnswered(): boolean;
}

/**
 * Builds the issue shown when the `saveSettings` call itself fails (for example
 * the bridge throws), so the UI never claims a change was saved when it may not be.
 *
 * @param error - What the call threw.
 */
export function settingsCallFailedIssue(error: unknown): Issue {
  return {
    code: "SETTINGS_SAVE_FAILED",
    severity: "warning",
    title: "Your settings couldn't be saved",
    message: "The change works for now, but it may be lost when PDF Manager closes.",
    troubleshooting: [
      "Try changing the setting again.",
      "If it keeps happening, restart PDF Manager.",
      "If it still happens, open the logs folder and keep the latest log file.",
    ],
    details: error instanceof Error ? error.message : String(error),
    logFile: null,
    file: null,
  };
}

/**
 * Creates a settings save queue.
 *
 * @param save - Sends one patch to Python (usually `api.saveSettings`).
 * @param onResult - Called after every finished save, in order.
 * @returns A {@link SettingsSaver}.
 */
export function createSettingsSaver(
  save: (patch: Partial<Settings>) => Promise<SaveSettingsResult>,
  onResult: (outcome: SettingsSaveOutcome) => void,
): SettingsSaver {
  let queued: Partial<Settings> | null = null;
  let inFlight: Partial<Settings> | null = null;
  let waiters: Array<() => void> = [];
  let busy = false;
  let answered = false;
  // A function, so code after an `await` sees changes queued meanwhile.
  const stillQueued = (): Partial<Settings> => ({ ...queued });

  async function drain() {
    busy = true;
    while (queued) {
      const sending = queued;
      const batch = waiters;
      queued = null;
      waiters = [];
      inFlight = sending;
      let outcome: SettingsSaveOutcome;
      try {
        const result = await save(sending);
        outcome = { settings: { ...result.settings, ...stillQueued() }, issue: result.issue };
      } catch (error) {
        outcome = { settings: null, issue: settingsCallFailedIssue(error) };
      }
      inFlight = null;
      answered = true;
      onResult(outcome);
      batch.forEach((resolve) => resolve());
    }
    busy = false;
  }

  return {
    save(patch) {
      queued = { ...queued, ...patch };
      const done = new Promise<void>((resolve) => waiters.push(resolve));
      if (!busy) void drain();
      return done;
    },
    unconfirmed: () => ({ ...inFlight, ...stillQueued() }),
    hasAnswered: () => answered,
  };
}
