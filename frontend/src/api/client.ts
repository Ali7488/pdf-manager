/**
 * The API the app uses, picked once at startup:
 *
 * - Browser mode (the app served this page, with its bootstrap tag): the local
 *   HTTP client (`http.ts`).
 * - Inside the desktop app (pywebview present), the real bridge to Python.
 * - In development (`npm run dev`) and tests without either, the in-memory
 *   mock, so the UI works in a plain browser.
 *
 * A production build never uses the mock: without browser mode's tag it uses
 * the bridge, which waits for `pywebviewready` if pywebview injects itself
 * after the page loads.
 * Set `VITE_API=bridge` to force the bridge in development (for example when
 * a pywebview window points at the Vite dev server).
 * Set `VITE_MOCK_SETTINGS_SAVE_FAILS=1` to make the mock's settings saves fail,
 * to try the "not saved" state in Settings.
 * Set `VITE_MOCK_PLATFORM=linux` (or `mac`) to make the mock act like that
 * system; on Linux, Install OCR then shows the command to copy and run.
 */
import { createBridgeApi, isPywebviewPresent, onEvent } from "./bridge";
import { createHttpApi, readBrowserBootstrap } from "./http";
import { createMockApi } from "./mock";
import type { AppInfo, PdfManagerApi } from "./types";

// Statically false in production builds, so the mock is tree-shaken away.
const mockAllowed =
  (import.meta.env.DEV || import.meta.env.MODE === "test") && import.meta.env.VITE_API !== "bridge";

/** Reads `VITE_MOCK_PLATFORM`; anything unknown means the default (Windows). */
function mockPlatform(value: string | undefined): AppInfo["platform"] | undefined {
  return value === "windows" || value === "linux" || value === "mac" ? value : undefined;
}

const browserMode = readBrowserBootstrap();

/** True when the in-memory mock is in use. */
export const usingMock: boolean = mockAllowed && browserMode === null && !isPywebviewPresent();

/** The API client for the whole app. */
export const api: PdfManagerApi = browserMode
  ? createHttpApi(browserMode)
  : usingMock
    ? createMockApi({
        settingsSaveFails: import.meta.env.VITE_MOCK_SETTINGS_SAVE_FAILS === "1",
        platform: mockPlatform(import.meta.env.VITE_MOCK_PLATFORM),
      })
    : createBridgeApi();

export { onEvent };
