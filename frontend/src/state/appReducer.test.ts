import { describe, expect, it } from "vitest";
import { Action } from "../api/types";
import { SAMPLE_FILES } from "../test/renderApp";
import { appReducer, initialAppState } from "./appReducer";

const [report, slides, photo, notes] = SAMPLE_FILES;

describe("appReducer", () => {
  it("adds files in order and skips paths already in the list", () => {
    let state = appReducer(initialAppState(), { type: "filesAdded", files: [report, slides] });
    state = appReducer(state, { type: "filesAdded", files: [slides, photo, { ...report, name: "Copy.pdf" }] });
    expect(state.files.map((file) => file.name)).toEqual(["Report.pdf", "Slides.pptx", "Photo.jpg"]);
  });

  it("returns the same state when nothing new is added", () => {
    const state = appReducer(initialAppState(), { type: "filesAdded", files: [report] });
    expect(appReducer(state, { type: "filesAdded", files: [report] })).toBe(state);
  });

  it("moves a file to another file's position", () => {
    const state = appReducer(initialAppState(), { type: "filesAdded", files: [report, slides, photo, notes] });
    const down = appReducer(state, { type: "fileMoved", fromPath: report.path, toPath: photo.path });
    expect(down.files.map((file) => file.name)).toEqual(["Slides.pptx", "Photo.jpg", "Report.pdf", "Notes.pdf"]);
    const up = appReducer(down, { type: "fileMoved", fromPath: notes.path, toPath: slides.path });
    expect(up.files.map((file) => file.name)).toEqual(["Notes.pdf", "Slides.pptx", "Photo.jpg", "Report.pdf"]);
  });

  it("removes one file or clears them all", () => {
    const state = appReducer(initialAppState(), { type: "filesAdded", files: [report, slides] });
    expect(appReducer(state, { type: "fileRemoved", path: report.path }).files).toEqual([slides]);
    expect(appReducer(state, { type: "filesCleared" }).files).toEqual([]);
  });

  it("starts every tab with OCR off, contents page off and save-to-default ticked", () => {
    const state = initialAppState();
    for (const action of Object.values(Action)) {
      expect(state.actionSettings[action].useOcr).toBe(false);
      expect(state.actionSettings[action].contentsPage).toBe(false);
      expect(state.saveToDefault[action]).toBe(true);
    }
  });

  it("keeps each tab's options separate", () => {
    const state = appReducer(initialAppState(), {
      type: "actionSettingsChanged",
      action: Action.Merge,
      patch: { contentsPage: true },
    });
    expect(state.actionSettings[Action.Merge].contentsPage).toBe(true);
    expect(state.actionSettings[Action.FlattenMerge].contentsPage).toBe(false);
  });
});
