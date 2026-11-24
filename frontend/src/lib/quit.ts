/** Wording for Settings → Quit PDF Manager when quitting would lose work (decision P35). */
import type { QuitResult } from "../api/types";

/** What would be lost, in plain words. */
export function quitWarning(held: QuitResult): string {
  const results =
    held.unsavedResults === 1 ? "one finished result isn't saved yet" : `${held.unsavedResults} finished results aren't saved yet`;
  if (held.running && held.unsavedResults > 0)
    return `A conversion is still running, and ${results}. Quitting now stops the conversion and deletes the unsaved results.`;
  if (held.running) return "A conversion is still running. Quitting now stops it.";
  const lost = held.unsavedResults === 1 ? "it" : "them";
  return `${results.charAt(0).toUpperCase()}${results.slice(1)}. Quitting now deletes ${lost}.`;
}
