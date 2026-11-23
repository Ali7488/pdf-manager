/**
 * A group of radio buttons drawn as selectable cards.
 */
import { useId, type ReactNode } from "react";
import { InfoTip } from "../InfoTip/InfoTip";
import styles from "./Field.module.css";

/** One choice in a {@link RadioCards} group. */
export interface RadioOption<T extends string> {
  value: T;
  label: string;
  /** Optional short plain explanation under the label. */
  hint?: string;
  /** Optional (?) explanation. */
  tip?: string;
}

/** Props for {@link RadioCards}. */
export interface RadioCardsProps<T extends string> {
  /** Group title (rendered as the fieldset legend). */
  legend: string;
  /** Optional (?) explanation for the whole group. */
  legendTip?: string;
  options: readonly RadioOption<T>[];
  value: T;
  onChange(value: T): void;
  /** Content shown under the group, e.g. the input for the chosen option. */
  children?: ReactNode;
}

/**
 * A <fieldset> of native radio inputs; arrow keys move between choices as usual.
 */
export function RadioCards<T extends string>({
  legend,
  legendTip,
  options,
  value,
  onChange,
  children,
}: RadioCardsProps<T>) {
  const name = useId();
  return (
    <fieldset className={styles.fieldset}>
      <legend className={styles.legend}>
        {legend}
        {legendTip && <InfoTip label={legend} text={legendTip} />}
      </legend>
      <div className={styles.cards}>
        {options.map((option) => (
          <div key={option.value} className={styles.cardWrap}>
            <label className={`${styles.card} ${option.value === value ? styles.cardSelected : ""}`}>
              <input
                type="radio"
                name={name}
                value={option.value}
                checked={option.value === value}
                onChange={() => onChange(option.value)}
              />
              <span className={styles.cardText}>
                <span className={styles.cardLabel}>{option.label}</span>
                {option.hint && <span className={styles.cardHint}>{option.hint}</span>}
              </span>
            </label>
            {option.tip && (
              <span className={styles.cardTip}>
                <InfoTip label={option.label} text={option.tip} />
              </span>
            )}
          </div>
        ))}
      </div>
      {children}
    </fieldset>
  );
}
