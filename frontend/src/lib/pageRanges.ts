/**
 * Parsing and validation of Split page ranges such as "1-3, 5, 8-10".
 */

/** One inclusive page range, 1-based. */
export interface PageRange {
  start: number;
  end: number;
}

/** Result of parsing: either the ranges, or a friendly message saying what's wrong. */
export type PageRangeParse = { ok: true; ranges: PageRange[] } | { ok: false; message: string };

/**
 * Parses a list of page ranges.
 *
 * Accepts single pages ("5") and ranges ("1-3"), separated by commas. Spaces
 * are ignored, and an en dash ("1–3") counts as a hyphen. Each range becomes
 * its own output file, so overlapping ranges are allowed.
 *
 * @param text - What the user typed.
 * @returns The ranges, or a plain-language message for the first problem found.
 */
export function parsePageRanges(text: string): PageRangeParse {
  const trimmed = text.trim();
  if (trimmed === "") {
    return { ok: false, message: "Type the pages you want, for example 1-3, 5, 8-10." };
  }
  const ranges: PageRange[] = [];
  for (const rawPart of trimmed.split(",")) {
    const part = rawPart.replace(/\s+/g, "").replace(/–/g, "-");
    if (part === "") {
      return { ok: false, message: "There's an extra comma. Remove it, or add a page after it." };
    }
    const match = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!match) {
      return {
        ok: false,
        message: `"${rawPart.trim()}" isn't a page or a range. Use numbers like 5 or 1-3.`,
      };
    }
    const start = Number(match[1]);
    const end = match[2] === undefined ? start : Number(match[2]);
    if (start < 1 || end < 1) {
      return { ok: false, message: "Pages start at 1." };
    }
    if (end < start) {
      return {
        ok: false,
        message: `"${part}" goes backwards. Put the lower page first, like ${end}-${start}.`,
      };
    }
    ranges.push({ start, end });
  }
  return { ok: true, ranges };
}

/**
 * Finds the highest page mentioned in a list of ranges.
 *
 * @param ranges - Parsed ranges.
 * @returns The largest end page, or 0 for an empty list.
 */
export function highestPage(ranges: PageRange[]): number {
  return ranges.reduce((max, range) => Math.max(max, range.end), 0);
}
