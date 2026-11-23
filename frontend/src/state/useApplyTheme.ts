/**
 * Applies the chosen colour theme by setting `data-theme` on <html>.
 */
import { useEffect, useState } from "react";
import type { Theme } from "../api/types";

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Theme names that have a stylesheet ("system" resolves to light or dark). */
export type ResolvedTheme = Exclude<Theme, "system">;

/**
 * Sets `data-theme` on the document root. "system" follows the Windows
 * light/dark setting (via `prefers-color-scheme`) and updates live when it
 * changes.
 *
 * @param theme - The saved theme.
 * @returns The theme actually applied.
 */
export function useApplyTheme(theme: Theme): ResolvedTheme {
  const [systemDark, setSystemDark] = useState(() => window.matchMedia(DARK_QUERY).matches);

  useEffect(() => {
    const query = window.matchMedia(DARK_QUERY);
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  const resolved: ResolvedTheme = theme === "system" ? (systemDark ? "dark" : "light") : theme;

  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  return resolved;
}
