/**
 * Loading indicators: a small spinner and a progress bar.
 */
import styles from "./Progress.module.css";

/** Props for {@link Spinner}. */
export interface SpinnerProps {
  /** Size in pixels. Default 18. */
  size?: number;
}

/** A small spinning ring. Decorative; pair it with text that says what's happening. */
export function Spinner({ size = 18 }: SpinnerProps) {
  return <span className={styles.spinner} style={{ width: size, height: size }} aria-hidden="true" />;
}

/** Props for {@link ProgressBar}. */
export interface ProgressBarProps {
  /** Progress from 0 to 1. */
  fraction: number;
  /** Accessible name, e.g. "Conversion progress". */
  label: string;
}

/** A horizontal progress bar that animates smoothly between values. */
export function ProgressBar({ fraction, label }: ProgressBarProps) {
  const percent = Math.round(Math.min(1, Math.max(0, fraction)) * 100);
  return (
    <div
      className={styles.track}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
    >
      <div className={styles.fill} style={{ width: `${percent}%` }} />
    </div>
  );
}
