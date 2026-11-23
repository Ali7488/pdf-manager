/**
 * Holds the app state and connects it to the Python API: loads settings and
 * app info, adds files from `filesAdded` events, saves settings, and tracks
 * OCR installs.
 */
import { useCallback, useEffect, useMemo, useReducer, useState, type ReactNode } from "react";
import { api as defaultApi, onEvent as defaultOnEvent } from "../api/client";
import type { PdfManagerApi, Settings } from "../api/types";
import { AppContext, type AppContextValue, type OcrInstallState } from "./AppContext";
import { appReducer, initialAppState, type AppState } from "./appReducer";

/** Props for {@link AppProvider}. */
export interface AppProviderProps {
  children: ReactNode;
  /** API implementation; defaults to the one picked by `api/client.ts`. Tests pass a mock. */
  api?: PdfManagerApi;
  /** Event subscription; defaults to the window-event `onEvent`. */
  onEvent?: typeof defaultOnEvent;
  /** Starting state overrides, for tests. */
  initialState?: Partial<AppState>;
}

/**
 * Provides {@link AppContext} to the app.
 *
 * Settings changes are applied in memory first (so a theme switch is instant)
 * and then saved with `saveSettings`; the full settings Python returns replace
 * the local copy.
 */
export function AppProvider({ children, api = defaultApi, onEvent = defaultOnEvent, initialState }: AppProviderProps) {
  const [state, dispatch] = useReducer(appReducer, undefined, () => ({ ...initialAppState(), ...initialState }));
  const [ocrInstall, setOcrInstall] = useState<OcrInstallState>({ status: "idle", message: "", issue: null });
  const [ocrVersion, setOcrVersion] = useState(0);

  // Load saved settings and app info once.
  useEffect(() => {
    let active = true;
    void api.getSettings().then((settings) => {
      if (active) dispatch({ type: "settingsLoaded", settings });
    });
    void api.getAppInfo().then((appInfo) => {
      if (active) dispatch({ type: "appInfoLoaded", appInfo });
    });
    return () => {
      active = false;
    };
  }, [api]);

  // Files dropped onto the window arrive from Python as filesAdded.
  useEffect(() => onEvent("filesAdded", ({ files }) => dispatch({ type: "filesAdded", files })), [onEvent]);

  // OCR install progress and result.
  useEffect(() => {
    const offProgress = onEvent("ocrInstallProgress", ({ message }) =>
      setOcrInstall((current) => ({ ...current, status: "running", message })),
    );
    const offFinished = onEvent("ocrInstallFinished", ({ ok, issue }) => {
      setOcrInstall({ status: ok ? "succeeded" : "failed", message: "", issue });
      if (ok) setOcrVersion((version) => version + 1);
    });
    return () => {
      offProgress();
      offFinished();
    };
  }, [onEvent]);

  const updateSettings = useCallback(
    async (patch: Partial<Settings>) => {
      dispatch({ type: "settingsPatched", patch });
      const saved = await api.saveSettings(patch);
      dispatch({ type: "settingsLoaded", settings: saved.settings });
    },
    [api],
  );

  const startOcrInstall = useCallback(async () => {
    setOcrInstall({ status: "running", message: "Starting the installer", issue: null });
    await api.installOcr();
  }, [api]);

  const bumpOcrVersion = useCallback(() => setOcrVersion((version) => version + 1), []);

  const value = useMemo<AppContextValue>(
    () => ({ state, dispatch, api, onEvent, updateSettings, ocrInstall, startOcrInstall, ocrVersion, bumpOcrVersion }),
    [state, api, onEvent, updateSettings, ocrInstall, startOcrInstall, ocrVersion, bumpOcrVersion],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}
