/**
 * App-wide state and its reducer: the current page, the shared file list,
 * saved settings, and each action tab's own choices (kept while switching tabs).
 */
import { arrayMove } from "@dnd-kit/sortable";
import { Action, type ActionSettings, type AppInfo, type InputFile, type Settings } from "../api/types";
import { defaultActionSettings } from "../lib/actions";

/** A sidebar destination. */
export type Page = "home" | "settings" | Action;

/** Settings used until the saved ones arrive from Python. */
export const DEFAULT_SETTINGS: Settings = {
  theme: "system",
  defaultSaveFolder: null,
  dpi: 200,
  ocrLanguage: "eng",
  ocrPageTimeoutSec: 120,
  tesseractPath: null,
};

/** Everything the app keeps in memory. */
export interface AppState {
  page: Page;
  /** Shared across all tabs, in display order (the order used for merges). */
  files: InputFile[];
  settings: Settings;
  settingsLoaded: boolean;
  appInfo: AppInfo | null;
  /** Each tab's options, so they survive switching tabs. */
  actionSettings: Record<Action, ActionSettings>;
  /** Each tab's "Save to default folder" box. Starts ticked (F32). */
  saveToDefault: Record<Action, boolean>;
}

/** Everything that can change the state. */
export type AppEvent =
  | { type: "navigate"; page: Page }
  | { type: "filesAdded"; files: InputFile[] }
  | { type: "fileRemoved"; path: string }
  | { type: "filesCleared" }
  | { type: "fileMoved"; fromPath: string; toPath: string }
  | { type: "settingsLoaded"; settings: Settings }
  | { type: "settingsPatched"; patch: Partial<Settings> }
  /** A save finished; `settings` is null when the call failed and local values stay. */
  | { type: "settingsSaved"; settings: Settings | null }
  | { type: "appInfoLoaded"; appInfo: AppInfo }
  | { type: "actionSettingsChanged"; action: Action; patch: Partial<ActionSettings> }
  | { type: "saveToDefaultChanged"; action: Action; value: boolean };

const ALL_ACTIONS = Object.values(Action);

/** Builds a record with one value per action. */
function perAction<T>(make: () => T): Record<Action, T> {
  return Object.fromEntries(ALL_ACTIONS.map((action) => [action, make()])) as Record<Action, T>;
}

/** The state the app starts with. */
export function initialAppState(): AppState {
  return {
    page: "home",
    files: [],
    settings: DEFAULT_SETTINGS,
    settingsLoaded: false,
    appInfo: null,
    actionSettings: perAction(defaultActionSettings),
    saveToDefault: perAction(() => true),
  };
}

/**
 * Applies one event to the state. Pure, so it's easy to test.
 *
 * - `filesAdded` appends files in order and skips paths already in the list.
 * - `fileMoved` moves a file to where another file is (drag to reorder).
 *
 * @param state - Current state.
 * @param event - What happened.
 * @returns The next state.
 */
export function appReducer(state: AppState, event: AppEvent): AppState {
  switch (event.type) {
    case "navigate":
      return { ...state, page: event.page };
    case "filesAdded": {
      const seen = new Set(state.files.map((file) => file.path));
      const fresh: InputFile[] = [];
      for (const file of event.files) {
        if (seen.has(file.path)) continue;
        seen.add(file.path);
        fresh.push(file);
      }
      return fresh.length === 0 ? state : { ...state, files: [...state.files, ...fresh] };
    }
    case "fileRemoved":
      return { ...state, files: state.files.filter((file) => file.path !== event.path) };
    case "filesCleared":
      return { ...state, files: [] };
    case "fileMoved": {
      const from = state.files.findIndex((file) => file.path === event.fromPath);
      const to = state.files.findIndex((file) => file.path === event.toPath);
      if (from < 0 || to < 0 || from === to) return state;
      return { ...state, files: arrayMove(state.files, from, to) };
    }
    case "settingsLoaded":
      return { ...state, settings: event.settings, settingsLoaded: true };
    case "settingsPatched":
      return { ...state, settings: { ...state.settings, ...event.patch } };
    case "settingsSaved":
      return event.settings ? { ...state, settings: event.settings, settingsLoaded: true } : state;
    case "appInfoLoaded":
      return { ...state, appInfo: event.appInfo };
    case "actionSettingsChanged":
      return {
        ...state,
        actionSettings: {
          ...state.actionSettings,
          [event.action]: { ...state.actionSettings[event.action], ...event.patch },
        },
      };
    case "saveToDefaultChanged":
      return { ...state, saveToDefault: { ...state.saveToDefault, [event.action]: event.value } };
  }
}
