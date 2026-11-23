/**
 * A whole-number setting that saves when the user leaves the box or presses Enter.
 */
import { useState } from "react";
import { TextField } from "../../components/Field/TextField";

/** Props for {@link NumberSetting}. */
export interface NumberSettingProps {
  label: string;
  tip?: string;
  /** The saved value. */
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  /** Shown under the box while the value is fine. */
  help?: string;
  /** Called with a valid new value. */
  onCommit(value: number): void;
}

/**
 * Keeps a local draft so typing "3" on the way to "300" isn't treated as an
 * error or saved. On blur or Enter, a valid number is saved; anything else
 * shows a friendly message and nothing is saved. Remount it (via `key`) to
 * reset the draft when the saved value changes elsewhere.
 */
export function NumberSetting({ label, tip, value, min, max, step = 1, suffix, help, onCommit }: NumberSettingProps) {
  const [draft, setDraft] = useState(String(value));
  const [error, setError] = useState<string | null>(null);

  const commit = () => {
    const parsed = Number(draft);
    if (draft.trim() === "" || !Number.isInteger(parsed) || parsed < min || parsed > max) {
      setError(`Choose a whole number from ${min} to ${max}.`);
      return;
    }
    setError(null);
    if (parsed !== value) onCommit(parsed);
  };

  return (
    <TextField
      label={label}
      tip={tip}
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      step={step}
      value={draft}
      suffix={suffix}
      help={help}
      error={error}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    />
  );
}
