/**
 * Copying text to the clipboard in every window the app runs in.
 *
 * The desktop app loads the page from `file://` inside WebView2 or Qt
 * WebEngine, where `navigator.clipboard` can be missing or can reject (it
 * normally needs a secure origin). So the copy falls back to selecting the
 * text on screen and trying the older `document.execCommand("copy")`. If that
 * fails too, the text stays selected so the user only has to press Ctrl+C.
 */

/**
 * How a copy attempt ended.
 *
 * - `"copied"`: the text is on the clipboard.
 * - `"selected"`: copying wasn't possible, but the text is selected on screen,
 *   ready for Ctrl+C.
 */
export type CopyResult = "copied" | "selected";

/**
 * Selects all the text inside an element, replacing the current selection.
 *
 * @param element - The element whose text to select.
 */
export function selectElementText(element: HTMLElement): void {
  const selection = window.getSelection();
  if (!selection) return;
  const range = document.createRange();
  range.selectNodeContents(element);
  selection.removeAllRanges();
  selection.addRange(range);
}

/**
 * Copies text to the clipboard, falling back to selecting it on screen.
 *
 * Tries `navigator.clipboard.writeText` first. If that is missing or rejects,
 * selects the text in `fallbackElement` and tries `document.execCommand("copy")`.
 * Never throws.
 *
 * @param text - The text to copy.
 * @param fallbackElement - The element showing the same text, selected when
 *   the clipboard API can't be used.
 * @returns `"copied"`, or `"selected"` when the user has to press Ctrl+C.
 */
export async function copyText(text: string, fallbackElement: HTMLElement | null): Promise<CopyResult> {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return "copied";
    }
  } catch {
    // Blocked or unsupported here (for example a file:// page); use the fallback.
  }

  if (fallbackElement) selectElementText(fallbackElement);
  try {
    // execCommand is deprecated but still the only copy that works in some embedded browsers.
    if (fallbackElement && typeof document.execCommand === "function" && document.execCommand("copy")) {
      return "copied";
    }
  } catch {
    // Not allowed; the text stays selected for Ctrl+C.
  }
  return "selected";
}
