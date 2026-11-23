/**
 * A small popup for one error or warning (F13).
 */
import type { Issue } from "../../api/types";
import { Button } from "../Button/Button";
import { Modal } from "../Modal/Modal";
import { IssueView } from "./IssueView";

/** Props for {@link IssuePopup}. */
export interface IssuePopupProps {
  issue: Issue;
  onClose(): void;
}

/** Shows an issue in a modal with an OK button. */
export function IssuePopup({ issue, onClose }: IssuePopupProps) {
  return (
    <Modal
      title={issue.severity === "error" ? "Something went wrong" : "Please note"}
      size="sm"
      onClose={onClose}
      footer={
        <Button variant="primary" onClick={onClose}>
          OK
        </Button>
      }
    >
      <IssueView issue={issue} />
    </Modal>
  );
}
