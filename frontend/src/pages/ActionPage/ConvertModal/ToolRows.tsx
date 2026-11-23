/**
 * The tool-check rows in the Convert modal (F14): only the tools this job
 * needs, each with a spinner and then a clear found/missing state.
 */
import type { ToolCheckResult } from "../../../api/types";
import { Icon } from "../../../components/Icon/Icon";
import { Spinner } from "../../../components/Progress/Progress";
import styles from "./ConvertModal.module.css";

/** Props for {@link ToolRows}. */
export interface ToolRowsProps {
  /** Whether the job uses OCR (known before the check returns). */
  needsOcr: boolean;
  /** Whether the job has PowerPoint files (known before the check returns). */
  hasSlides: boolean;
  /** The check result, or null while checking. */
  check: ToolCheckResult | null;
}

type RowState = "checking" | "found" | "missing" | "notNeeded";

interface Row {
  name: string;
  state: RowState;
  text: string;
}

/** Works out which rows to show and what each says. */
function buildRows({ needsOcr, hasSlides, check }: ToolRowsProps): Row[] {
  const rows: Row[] = [];
  const showOcr = check ? check.ocr.required : needsOcr;
  const showSlides = hasSlides || Boolean(check && (check.powerpoint.required || check.libreoffice.required));

  if (showOcr) {
    rows.push(
      !check
        ? { name: "OCR (text recognition)", state: "checking", text: "Checking" }
        : check.ocr.present
          ? { name: "OCR (text recognition)", state: "found", text: "Found" }
          : { name: "OCR (text recognition)", state: "missing", text: "Missing" },
    );
  }
  if (showSlides) {
    if (!check) {
      rows.push({ name: "Microsoft PowerPoint", state: "checking", text: "Checking" });
      rows.push({ name: "LibreOffice", state: "checking", text: "Checking" });
    } else {
      const { powerpoint, libreoffice } = check;
      rows.push(
        powerpoint.present
          ? { name: "Microsoft PowerPoint", state: "found", text: "Found" }
          : libreoffice.present
            ? { name: "Microsoft PowerPoint", state: "notNeeded", text: "Not present (LibreOffice will be used)" }
            : { name: "Microsoft PowerPoint", state: "missing", text: "Missing" },
      );
      rows.push(
        libreoffice.present
          ? { name: "LibreOffice", state: "found", text: "Found" }
          : powerpoint.present
            ? { name: "LibreOffice", state: "notNeeded", text: "Not present (not needed)" }
            : { name: "LibreOffice", state: "missing", text: "Missing" },
      );
    }
  }
  return rows;
}

/**
 * Lists the tools the job needs. Shows nothing if the job needs no external
 * tools (for example Merge of PDFs without OCR).
 */
export function ToolRows(props: ToolRowsProps) {
  const rows = buildRows(props);
  if (rows.length === 0) return null;
  return (
    <ul className={styles.tools} aria-label="Tools this job needs">
      {rows.map((row) => (
        <li key={row.name} className={styles.toolRow} data-state={row.state}>
          <span className={styles.toolName}>{row.name}</span>
          <span className={`${styles.toolState} ${styles[row.state]}`}>
            {row.state === "checking" && <Spinner size={14} />}
            {row.state === "found" && <Icon name="check" size={16} />}
            {row.state === "missing" && <Icon name="alert" size={16} />}
            {row.state === "notNeeded" && <Icon name="minus" size={16} />}
            {row.text}
          </span>
        </li>
      ))}
    </ul>
  );
}
