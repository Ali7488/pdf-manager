/**
 * Theme choice with a small colour preview for each option.
 */
import type { Theme } from "../../api/types";
import styles from "./SettingsPage.module.css";

const THEMES: readonly { value: Theme; label: string; hint: string }[] = [
  { value: "system", label: "System", hint: "Follows Windows light or dark" },
  { value: "light", label: "Light", hint: "Gold on white" },
  { value: "dark", label: "Dark", hint: "Gold on charcoal" },
  { value: "burgundy", label: "Burgundy", hint: "Burgundy and pink" },
  { value: "green", label: "Green", hint: "Forest green, cream and coral" },
];

/** Props for {@link ThemePicker}. */
export interface ThemePickerProps {
  value: Theme;
  onChange(theme: Theme): void;
}

/**
 * A radio group of themes. Each preview sets `data-theme` on itself, so it
 * shows that theme's real colours without repeating them here.
 */
export function ThemePicker({ value, onChange }: ThemePickerProps) {
  return (
    <fieldset className={styles.themeGroup}>
      <legend className={styles.legend}>Theme</legend>
      <div className={styles.themes}>
        {THEMES.map((theme) => (
          <label key={theme.value} className={`${styles.theme} ${value === theme.value ? styles.themeSelected : ""}`}>
            <input
              type="radio"
              name="theme"
              value={theme.value}
              checked={value === theme.value}
              onChange={() => onChange(theme.value)}
            />
            <span className={styles.previewRow} aria-hidden="true">
              {theme.value === "system" ? (
                <>
                  <Preview theme="light" half />
                  <Preview theme="dark" half />
                </>
              ) : (
                <Preview theme={theme.value} />
              )}
            </span>
            <span className={styles.themeLabel}>{theme.label}</span>
            <span className={styles.themeHint}>{theme.hint}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** A tiny mock window drawn in one theme's colours. */
function Preview({ theme, half = false }: { theme: Exclude<Theme, "system">; half?: boolean }) {
  return (
    <span data-theme={theme} className={`${styles.preview} ${half ? styles.previewHalf : ""}`}>
      <span className={styles.previewBar} />
      <span className={styles.previewLine} />
      <span className={styles.previewButton} />
    </span>
  );
}
