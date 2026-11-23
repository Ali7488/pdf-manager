/**
 * What each action (sidebar tab) is called, what it does in plain words, and
 * which files it accepts. Mirrors the table in docs/API.md.
 */
import { Action, type ActionSettings, type FileKind, type InputFile } from "../api/types";
import type { IconName } from "../components/Icon/Icon";

/** Display and behaviour details for one action. */
export interface ActionInfo {
  action: Action;
  /** Sidebar and heading label. */
  label: string;
  /** A short paragraph at the top of the tab. */
  description: string;
  /** File kinds this action works on. */
  accepts: readonly FileKind[];
  /** Whether the "Use OCR" checkbox is offered. */
  offersOcr: boolean;
  /** Whether the output joins files (order matters; contents page offered). */
  merges: boolean;
  /** Which native file picker the "Add files" button opens on this tab. */
  pickKind: "documents" | "images";
  /** Sidebar and Home icon. */
  icon: IconName;
}

const DOCUMENTS: readonly FileKind[] = ["pdf", "pptx", "ppt"];

/** Every action, in sidebar order. */
export const ACTIONS: readonly ActionInfo[] = [
  {
    action: Action.Flatten,
    label: "Flatten",
    description:
      "Turns every page into a picture, so the PDF opens cleanly in apps that struggle with complex files, such as note-taking apps on tablets. You get one new PDF for each file.",
    accepts: DOCUMENTS,
    offersOcr: true,
    merges: false,
    pickKind: "documents",
    icon: "flatten",
  },
  {
    action: Action.FlattenMerge,
    label: "Flatten + Merge",
    description:
      "Flattens every file, then joins them into one PDF in the order shown in the list.",
    accepts: DOCUMENTS,
    offersOcr: true,
    merges: true,
    pickKind: "documents",
    icon: "flattenMerge",
  },
  {
    action: Action.Merge,
    label: "Merge",
    description:
      "Joins your files into one PDF in the order shown in the list. Text stays as it is, and bookmarks are kept.",
    accepts: DOCUMENTS,
    offersOcr: true,
    merges: true,
    pickKind: "documents",
    icon: "merge",
  },
  {
    action: Action.Split,
    label: "Split",
    description:
      "Splits each file into separate PDFs: by the pages you choose, every few pages, or one file per page.",
    accepts: DOCUMENTS,
    offersOcr: true,
    merges: false,
    pickKind: "documents",
    icon: "split",
  },
  {
    action: Action.ImagesToPdf,
    label: "Images to PDF",
    description:
      "Puts your pictures into a PDF, one picture per page. You can make one PDF with all of them, or one PDF for each picture.",
    accepts: ["image"],
    offersOcr: true,
    merges: false,
    pickKind: "images",
    icon: "image",
  },
  {
    action: Action.Compress,
    label: "Compress",
    description:
      "Makes each PDF smaller so it's quicker to send and takes less space. You get one new PDF for each file.",
    accepts: ["pdf"],
    offersOcr: false,
    merges: false,
    pickKind: "documents",
    icon: "compress",
  },
];

/**
 * Looks up an action's details.
 *
 * @param action - The action.
 * @returns Its entry in {@link ACTIONS}.
 */
export function getActionInfo(action: Action): ActionInfo {
  const info = ACTIONS.find((entry) => entry.action === action);
  if (!info) throw new Error(`Unknown action: ${action}`);
  return info;
}

/**
 * Whether an action works on a file.
 *
 * @param action - The action of the current tab.
 * @param file - A file from the shared list.
 */
export function actionAcceptsFile(action: Action, file: InputFile): boolean {
  return getActionInfo(action).accepts.includes(file.kind);
}

/** True for PowerPoint files, which LibreOffice Impress converts (decision C17). */
export function isSlides(kind: FileKind): boolean {
  return kind === "pptx" || kind === "ppt";
}

/**
 * Settings every tab starts with: OCR unchecked, contents page off,
 * custom page ranges for Split, one combined PDF for images, Balanced compression.
 */
export function defaultActionSettings(): ActionSettings {
  return {
    useOcr: false,
    contentsPage: false,
    split: { method: "ranges", ranges: "", everyN: 5 },
    combineImages: true,
    compressLevel: "balanced",
  };
}
