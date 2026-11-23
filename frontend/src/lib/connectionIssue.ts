/**
 * The issue shown when PDF Manager didn't answer a request (browser mode: the
 * app was closed, or the connection to it failed). Built here because Python
 * can't send it.
 */
import type { Issue } from "../api/types";

/**
 * @param error - What the request failed with, for "Show details".
 * @returns An `UNEXPECTED_ERROR` issue in plain language.
 */
export function connectionIssue(error: unknown): Issue {
  return {
    code: "UNEXPECTED_ERROR",
    severity: "error",
    title: "PDF Manager isn't answering",
    message: "This page lost contact with PDF Manager. Your original files haven't been changed.",
    troubleshooting: [
      "Click Try again.",
      "If PDF Manager was closed, start it again from its shortcut. It opens a new window.",
    ],
    details: error instanceof Error ? error.message : String(error),
    logFile: null,
    command: null,
    file: null,
  };
}
