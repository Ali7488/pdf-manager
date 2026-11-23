import { describe, expect, it } from "vitest";
import { highestPage, parsePageRanges } from "./pageRanges";

describe("parsePageRanges", () => {
  it("reads single pages and ranges", () => {
    expect(parsePageRanges("1-3, 5, 8-10")).toEqual({
      ok: true,
      ranges: [
        { start: 1, end: 3 },
        { start: 5, end: 5 },
        { start: 8, end: 10 },
      ],
    });
  });

  it("ignores spaces and accepts an en dash", () => {
    expect(parsePageRanges(" 2 – 4 ,7 ")).toEqual({
      ok: true,
      ranges: [
        { start: 2, end: 4 },
        { start: 7, end: 7 },
      ],
    });
  });

  it.each([
    ["", "Type the pages"],
    ["1-3,", "extra comma"],
    ["abc", "isn't a page or a range"],
    ["0-2", "Pages start at 1"],
    ["5-2", "goes backwards"],
    ["1-2-3", "isn't a page or a range"],
  ])("rejects %j with a friendly message", (input, fragment) => {
    const result = parsePageRanges(input);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.message).toContain(fragment);
  });

  it("finds the highest page", () => {
    const result = parsePageRanges("3, 9-12, 4");
    expect(result.ok && highestPage(result.ranges)).toBe(12);
  });
});
