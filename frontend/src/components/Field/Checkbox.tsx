/**
 * A labelled native checkbox with an optional (?) explanation.
 */
import type { ReactNode } from "react";
import { InfoTip } from "../InfoTip/InfoTip";
import styles from "./Field.module.css";

/** Props for {@link Checkbox}. */
export interface CheckboxProps {
  label: string;
  checked: boolean;
  onChange(checked: boolean): void;
  /** Explanation shown by a (?) next to the label. */
  tip?: string;
  disabled?: boolean;
  /** Extra content after the label row (for example a related button). */
  children?: ReactNode;
}

/**
 * A real <input type="checkbox"> inside its <label>. The (?) sits outside the
 * label so clicking it doesn't toggle the box.
 */
export function Checkbox({ label, checked, onChange, tip, disabled, children }: CheckboxProps) {
  return (
    <div className={styles.checkRow}>
      <label className={styles.check}>
        <input
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{label}</span>
      </label>
      {tip && <InfoTip label={label} text={tip} />}
      {children}
    </div>
  );
}
