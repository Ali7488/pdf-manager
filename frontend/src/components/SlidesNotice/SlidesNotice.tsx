/**
 * Shown under the file list as soon as PowerPoint files are added while
 * LibreOffice Impress, which converts them (decision C17), isn't installed:
 * what to install, and the manual PowerPoint-to-PDF route. PDF and image
 * files never need LibreOffice, so without presentations nothing is checked.
 */
import { useEffect, useState } from "react";
import { Action, type Issue } from "../../api/types";
import { actionAcceptsFile, defaultActionSettings, isSlides } from "../../lib/actions";
import { useApp } from "../../state/AppContext";
import { Button } from "../Button/Button";
import { IssueView } from "../Issue/IssueView";

/** Props for {@link SlidesNotice}. */
export interface SlidesNoticeProps {
  /** The tab's action; on a tab that doesn't take PowerPoint files, nothing is shown. */
  action?: Action;
}

/** Asks the app whether LibreOffice is there whenever the list's presentations change. */
export function SlidesNotice({ action }: SlidesNoticeProps) {
  const { api, state } = useApp();
  const slides = state.files.filter(
    (file) => isSlides(file.kind) && (!action || actionAcceptsFile(action, file)),
  );
  const key = slides.map((file) => file.path).join("\n");
  const [result, setResult] = useState<{ key: string; issues: Issue[] } | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!key) return;
    let active = true;
    // The same check the Convert window runs, for the presentations alone and without OCR.
    api.checkTools(Action.Flatten, defaultActionSettings(), { files: key.split("\n") }).then(
      (check) => {
        if (!active) return;
        const missing = check.issues.filter((issue) => issue.code === "SLIDE_RENDERER_MISSING");
        setResult({ key, issues: check.libreoffice.present ? [] : missing });
      },
      () => undefined, // The app isn't answering; that is reported elsewhere.
    );
    return () => {
      active = false;
    };
  }, [api, key, attempt]);

  if (!key || result?.key !== key || result.issues.length === 0) return null;
  return (
    <div role="status">
      {result.issues.map((issue, index) => (
        <IssueView
          key={`${issue.code}-${index}`}
          issue={issue}
          compact
          actions={
            <Button size="sm" onClick={() => setAttempt((n) => n + 1)}>
              Check again
            </Button>
          }
        />
      ))}
    </div>
  );
}
