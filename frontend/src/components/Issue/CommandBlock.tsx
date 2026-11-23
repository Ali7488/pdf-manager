/**
 * A command the user can copy and run themselves (decision C16), for example
 * the Linux package install for Tesseract. The app never runs it.
 */
import { useEffect, useId, useRef, useState } from "react";
import { copyText } from "../../lib/clipboard";
import { Button } from "../Button/Button";
import styles from "./Issue.module.css";

/** How long "Copied" stays visible, in milliseconds. */
const COPIED_VISIBLE_MS = 3000;

/** Props for {@link CommandBlock}. */
export interface CommandBlockProps {
  /** The exact command text, shown as is. */
  command: string;
}

type CopyState = "idle" | "copied" | "manual";

/**
 * Shows a command in a separate monospace block the user can select, with a
 * Copy button. After copying it says "Copied"; if the clipboard can't be used,
 * it leaves the command selected and says "Press Ctrl+C to copy".
 */
export function CommandBlock({ command }: CommandBlockProps) {
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const codeRef = useRef<HTMLElement>(null);
  const labelId = useId();

  // Let "Copied" fade back to the plain button after a moment.
  useEffect(() => {
    if (copyState !== "copied") return;
    const timer = setTimeout(() => setCopyState("idle"), COPIED_VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [copyState]);

  const copy = async () => {
    const result = await copyText(command, codeRef.current);
    setCopyState(result === "copied" ? "copied" : "manual");
  };

  return (
    <div className={styles.command} role="group" aria-labelledby={labelId}>
      <p id={labelId} className={styles.commandLabel}>
        Copy this command, paste it into a Terminal window and press Enter:
      </p>
      <div className={styles.commandRow}>
        <pre className={styles.commandText}>
          <code ref={codeRef}>{command}</code>
        </pre>
        <Button size="sm" aria-label="Copy command" onClick={() => void copy()}>
          Copy
        </Button>
        <span className={styles.copyStatus} role="status">
          {copyState === "copied" ? "Copied" : copyState === "manual" ? "Press Ctrl+C to copy" : ""}
        </span>
      </div>
    </div>
  );
}
