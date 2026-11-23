/**
 * How every error and warning is shown (F13): a plain title and message,
 * a command to copy when the issue has one (C16), numbered troubleshooting steps, optional technical details, and a button
 * that opens the logs folder.
 */
import { useId, useState, type ReactNode } from "react";
import type { Issue } from "../../api/types";
import { useApp } from "../../state/AppContext";
import { Button } from "../Button/Button";
import { Icon } from "../Icon/Icon";
import { CommandBlock } from "./CommandBlock";
import styles from "./Issue.module.css";

/** Props for {@link IssueView}. */
export interface IssueViewProps {
  issue: Issue;
  /** Extra buttons for this issue (for example "Install OCR"). */
  actions?: ReactNode;
  /** Use a smaller title, for issues listed inside another dialog. */
  compact?: boolean;
}

/** Shows one issue. Used inside {@link IssuePopup} and the Convert modal. */
export function IssueView({ issue, actions, compact = false }: IssueViewProps) {
  const { api } = useApp();
  const [showDetails, setShowDetails] = useState(false);
  const detailsId = useId();
  const isError = issue.severity === "error";

  return (
    <section
      className={`${styles.issue} ${isError ? styles.error : styles.warning}`}
      aria-label={`${isError ? "Error" : "Warning"}: ${issue.title}`}
    >
      <div className={styles.heading}>
        <Icon name="alert" className={styles.icon} />
        {compact ? <h4 className={styles.title}>{issue.title}</h4> : <h3 className={styles.title}>{issue.title}</h3>}
      </div>
      <p className={styles.message}>{issue.message}</p>
      {issue.command && <CommandBlock command={issue.command} />}
      {issue.troubleshooting.length > 0 && (
        <div>
          <p className={styles.stepsTitle}>Things to try:</p>
          <ol className={styles.steps}>
            {issue.troubleshooting.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      )}
      <div className={styles.actions}>
        {actions}
        {issue.details && (
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={showDetails}
            aria-controls={detailsId}
            onClick={() => setShowDetails((value) => !value)}
          >
            {showDetails ? "Hide details" : "Show details"}
          </Button>
        )}
        <Button size="sm" variant="ghost" icon="folder" onClick={() => void api.openLogsFolder()}>
          Open logs folder
        </Button>
      </div>
      {issue.details && showDetails && (
        <pre id={detailsId} className={styles.details}>
          {issue.details}
        </pre>
      )}
    </section>
  );
}
