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
import { createSettingsSaver } from "./settingsSaver";

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
 * and then saved with `saveSettings`, one call at a time (see
 * `settingsSaver.ts`), so a late response from an older change can't undo a
 * newer one. The settings Python returns replace the local copy, except for
 * fields the user has changed again since.
 */
export function AppProvider({ children, api = defaultApi, onEvent = defaultOnEvent, initialState }: AppProviderProps) {
  const [state, dispatch] = useReducer(appReducer, undefined, () => ({ ...initialAppState(), ...initialState }));
  const [ocrInstall, setOcrInstall] = useState<OcrInstallState>({ status: "idle", message: "", issue: null });
  const [ocrVersion, setOcrVersion] = useState(0);

  const saver = useMemo(
    () =>
      createSettingsSaver(
        (patch) => api.saveSettings(patch),
        ({ settings, issue }) => dispatch({ type: "settingsSaved", settings, issue }),
      ),
    [api],
  );

  // Load saved settings and app info once.
  useEffect(() => {
    let active = true;
    void api.getSettings().then((settings) => {
      // A save that has already returned carries newer settings than this load.
      if (!active || saver.hasAnswered()) return;
      // Keep changes the user made while the load was on its way.
      dispatch({ type: "settingsLoaded", settings: { ...settings, ...saver.unconfirmed() } });
    });
    void api.getAppInfo().then((appInfo) => {
      if (active) dispatch({ type: "appInfoLoaded", appInfo });
    });
    return () => {
      active = false;
    };
  }, [api, saver]);

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
    (patch: Partial<Settings>) => {
      dispatch({ type: "settingsPatched", patch });
      return saver.save(patch);
    },
    [saver],
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
