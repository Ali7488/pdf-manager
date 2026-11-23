/**
 * Test helper: renders the whole app against a fresh, fast mock backend.
 */
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { createMockApi, type MockOptions } from "../api/mock";
import type { InputFile } from "../api/types";
import type { AppState } from "../state/appReducer";

/** Sample files covering every kind. */
export const SAMPLE_FILES: InputFile[] = [
  { path: "C:\\in\\Report.pdf", name: "Report.pdf", kind: "pdf", sizeBytes: 1_000_000, pageCount: 10 },
  { path: "C:\\in\\Slides.pptx", name: "Slides.pptx", kind: "pptx", sizeBytes: 3_000_000, pageCount: null },
  { path: "C:\\in\\Photo.jpg", name: "Photo.jpg", kind: "image", sizeBytes: 500_000, pageCount: null },
  { path: "C:\\in\\Notes.pdf", name: "Notes.pdf", kind: "pdf", sizeBytes: 200_000, pageCount: 4 },
];

/** Options for {@link renderApp}. */
export interface RenderAppOptions {
  /** Mock backend options; put saved settings here (they replace `state.settings` on load). */
  mock?: MockOptions;
  /** Starting app state, e.g. `{ page, files }`. */
  state?: Partial<AppState>;
}

/**
 * Renders <App> with a mock whose steps take 1 ms, and waits for the saved
 * settings to load.
 *
 * @returns The mock (to inspect or spy on) and a userEvent instance.
 */
export async function renderApp({ mock: mockOptions, state }: RenderAppOptions = {}) {
  const mock = createMockApi({ tickMs: 1, ...mockOptions });
  const user = userEvent.setup();
  const result = render(<App api={mock} initialState={state} />);
  await screen.findByRole("navigation", { name: "Main" });
  // Let the mock's getSettings/getAppInfo (1 ms) resolve inside act().
  await act(() => new Promise((resolve) => setTimeout(resolve, 10)));
  return { mock, user, ...result };
}
