/**
 * Checks the Split options before a job can start.
 */
import type { ActionSettings, InputFile } from "../../api/types";
import { formatPages } from "../../lib/format";
import { highestPage, parsePageRanges } from "../../lib/pageRanges";

/**
 * Finds what's wrong with the Split options, if anything.
 *
 * @param split - The Split settings.
 * @returns A friendly message, or null when the options are fine.
 */
export function splitProblem(split: ActionSettings["split"]): string | null {
  switch (split.method) {
    case "ranges": {
      const parsed = parsePageRanges(split.ranges);
      return parsed.ok ? null : parsed.message;
    }
    case "every_n":
      return Number.isInteger(split.everyN) && split.everyN >= 1 ? null : "Enter a whole number of 1 or more.";
    case "per_page":
      return null;
  }
}

/**
 * A gentle note when the chosen ranges go past the end of a PDF whose page
 * count is known. It doesn't block the job: other files may be longer.
 *
 * @param split - The Split settings.
 * @param files - The files the job will use.
 * @returns The note, or null.
 */
export function splitPageNote(split: ActionSettings["split"], files: InputFile[]): string | null {
  if (split.method !== "ranges") return null;
  const parsed = parsePageRanges(split.ranges);
  if (!parsed.ok) return null;
  const highest = highestPage(parsed.ranges);
  const short = files.find((file) => file.pageCount !== null && file.pageCount < highest);
  if (!short || short.pageCount === null) return null;
  return `Note: "${short.name}" has only ${formatPages(short.pageCount)}, so it won't have page ${highest}.`;
}
