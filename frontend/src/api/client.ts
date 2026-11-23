/**
 * The API the app uses, picked once at startup:
 *
 * - Inside the desktop app (pywebview present), the real bridge to Python.
 * - In development (`npm run dev`) and tests without pywebview, the in-memory
 *   mock, so the UI works in a plain browser.
 *
 * A production build always uses the bridge; the bridge waits for
 * `pywebviewready` if pywebview injects itself after the page loads.
 * Set `VITE_API=bridge` to force the bridge in development (for example when
 * a pywebview window points at the Vite dev server).
 */
import { createBridgeApi, isPywebviewPresent, onEvent } from "./bridge";
import { createMockApi } from "./mock";
import type { PdfManagerApi } from "./types";

// Statically false in production builds, so the mock is tree-shaken away.
const mockAllowed =
  (import.meta.env.DEV || import.meta.env.MODE === "test") && import.meta.env.VITE_API !== "bridge";

/** True when the in-memory mock is in use. */
export const usingMock: boolean = mockAllowed && !isPywebviewPresent();

/** The API client for the whole app. */
export const api: PdfManagerApi = usingMock ? createMockApi() : createBridgeApi();

export { onEvent };
