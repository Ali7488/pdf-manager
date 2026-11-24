/**
 * Browser mode only: tells the user when PDF Manager stops answering (it was
 * closed, or the connection failed outside a job), and after they quit it.
 * A running job's own Convert window reports a lost connection itself.
 */
import { useEffect, useState } from "react";
import { connectionIssue } from "../../lib/connectionIssue";
import { useApp } from "../../state/AppContext";
import { Button } from "../Button/Button";
import { IssueView } from "../Issue/IssueView";
import { Modal } from "../Modal/Modal";

/** Renders nothing until the app is gone or was quit. */
export function AppNotice() {
  const { state, onEvent } = useApp();
  const [lost, setLost] = useState(false);

  useEffect(
    () =>
      onEvent("connectionLost", ({ jobId }) => {
        if (jobId === null) setLost(true);
      }),
    [onEvent],
  );

  if (state.closed) {
    return (
      <Modal title="PDF Manager has closed">
        <p>You can close this window. To use PDF Manager again, start it from its shortcut.</p>
      </Modal>
    );
  }
  if (!lost) return null;
  return (
    <Modal
      title="Lost contact with PDF Manager"
      onClose={() => setLost(false)}
      footer={
        <>
          <Button onClick={() => setLost(false)}>Close</Button>
          <Button variant="primary" onClick={() => window.location.reload()}>
            Try again
          </Button>
        </>
      }
    >
      <IssueView issue={connectionIssue("A request to PDF Manager wasn't answered.")} />
    </Modal>
  );
}
