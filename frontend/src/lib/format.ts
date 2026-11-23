/**
 * Small formatting helpers for file details shown to the user.
 */
import type { FileKind } from "../api/types";

/**
 * Formats a byte count for people, e.g. "1.2 MB".
 *
 * @param bytes - Size in bytes.
 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

/**
 * Plain name for a file kind.
 *
 * @param kind - The detected kind.
 */
export function kindLabel(kind: FileKind): string {
  switch (kind) {
    case "pdf":
      return "PDF";
    case "pptx":
    case "ppt":
      return "PowerPoint";
    case "image":
      return "Image";
  }
}

/**
 * "1 page" / "12 pages".
 *
 * @param count - Number of pages.
 */
export function formatPages(count: number): string {
  return count === 1 ? "1 page" : `${count} pages`;
}

/** Display names for common Tesseract language codes. */
const LANGUAGE_NAMES: Record<string, string> = {
  eng: "English",
  deu: "German",
  fra: "French",
  spa: "Spanish",
  ita: "Italian",
  por: "Portuguese",
  nld: "Dutch",
  pol: "Polish",
  swe: "Swedish",
  dan: "Danish",
  nor: "Norwegian",
  fin: "Finnish",
  ces: "Czech",
  tur: "Turkish",
  rus: "Russian",
  ukr: "Ukrainian",
  ell: "Greek",
  ara: "Arabic",
  heb: "Hebrew",
  hin: "Hindi",
  jpn: "Japanese",
  kor: "Korean",
  chi_sim: "Chinese (Simplified)",
  chi_tra: "Chinese (Traditional)",
};

/**
 * Turns a Tesseract language code (or "eng+deu") into a readable name.
 *
 * @param code - Language code(s).
 */
export function languageName(code: string): string {
  return code
    .split("+")
    .map((part) => LANGUAGE_NAMES[part] ?? part)
    .join(" + ");
}
