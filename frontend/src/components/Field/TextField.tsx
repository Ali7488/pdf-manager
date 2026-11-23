/**
 * A labelled text or number input with an optional (?), help text and an
 * inline error message.
 */
import { useId, type InputHTMLAttributes, type ReactNode } from "react";
import { InfoTip } from "../InfoTip/InfoTip";
import styles from "./Field.module.css";

/** Props for {@link TextField}. */
export interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  tip?: string;
  /** Shown under the input when there's no error. */
  help?: ReactNode;
  /** A friendly message; marks the input invalid when set. */
  error?: string | null;
  /** Text after the input, such as a unit ("minutes"). */
  suffix?: string;
}

/**
 * Renders <label>, <input> and the message, wired together with
 * `aria-describedby` and `aria-invalid` for screen readers.
 */
export function TextField({ label, tip, help, error, suffix, className, ...inputProps }: TextFieldProps) {
  const id = useId();
  const messageId = `${id}-message`;
  const hasMessage = Boolean(error) || Boolean(help);
  return (
    <div className={`${styles.field} ${className ?? ""}`}>
      <div className={styles.labelRow}>
        <label htmlFor={id} className={styles.label}>
          {label}
        </label>
        {tip && <InfoTip label={label} text={tip} />}
      </div>
      <div className={styles.inputRow}>
        <input
          id={id}
          className={`${styles.input} ${error ? styles.inputInvalid : ""}`}
          aria-invalid={error ? true : undefined}
          aria-describedby={hasMessage ? messageId : undefined}
          {...inputProps}
        />
        {suffix && <span className={styles.suffix}>{suffix}</span>}
      </div>
      {error ? (
        <p id={messageId} className={styles.error} role="alert">
          {error}
        </p>
      ) : (
        help && (
          <p id={messageId} className={styles.help}>
            {help}
          </p>
        )
      )}
    </div>
  );
}
