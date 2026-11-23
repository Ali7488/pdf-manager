/**
 * React context that gives every component the app state, the API client and
 * a few shared operations. Provided by {@link AppProvider}.
 */
import { createContext, useContext, type Dispatch } from "react";
import type { onEvent } from "../api/bridge";
import type { Issue, PdfManagerApi, Settings } from "../api/types";
import type { AppEvent, AppState } from "./appReducer";

/** State of an OCR install started from Settings or the Convert modal. */
export interface OcrInstallState {
  status: "idle" | "running" | "succeeded" | "failed";
  /** Latest progress line from Python. */
  message: string;
  issue: Issue | null;
}

/** What {@link useApp} returns. */
export interface AppContextValue {
  state: AppState;
  dispatch: Dispatch<AppEvent>;
  api: PdfManagerApi;
  onEvent: typeof onEvent;
  /**
   * Applies a settings change straight away and saves it through Python.
   * Saves run one at a time and the latest choice always wins; resolves once
   * the save carrying this change has finished.
   */
  updateSettings(patch: Partial<Settings>): Promise<void>;
  ocrInstall: OcrInstallState;
  /** Starts installing OCR; progress and result arrive in `ocrInstall`. */
  startOcrInstall(): Promise<void>;
  /** Increases whenever OCR may have become available (install or search). */
  ocrVersion: number;
  /** Tells listeners that OCR may have become available. */
  bumpOcrVersion(): void;
}

export const AppContext = createContext<AppContextValue | null>(null);

/**
 * Reads the app context.
 *
 * @throws Error if used outside {@link AppProvider}.
 */
export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside <AppProvider>.");
  return value;
}
