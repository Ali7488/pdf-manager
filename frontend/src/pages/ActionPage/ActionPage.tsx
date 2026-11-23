/**
 * One action tab (Flatten, Merge, Split and so on): what it does, the shared
 * file list, its options, where results go, and the Convert button.
 */
import { useState } from "react";
import { Action, type ActionSettings } from "../../api/types";
import { AddFilesButton } from "../../components/AddFilesButton/AddFilesButton";
import { Button } from "../../components/Button/Button";
import { FileList } from "../../components/FileList/FileList";
import { PageHeader, Section } from "../../components/Page/Page";
import { actionAcceptsFile, getActionInfo } from "../../lib/actions";
import { useApp } from "../../state/AppContext";
import { ActionOptions } from "./ActionOptions";
import styles from "./ActionPage.module.css";
import { ConvertModal } from "./ConvertModal/ConvertModal";
import { SaveDestination } from "./SaveDestination";
import { splitProblem } from "./splitValidation";

/** Props for {@link ActionPage}. */
export interface ActionPageProps {
  action: Action;
}

/** A snapshot of everything one Convert click uses, so later edits can't change a running job. */
interface ConvertRequest {
  settings: ActionSettings;
  autoSaveFolder: string | null;
}

/**
 * Renders the tab for `action`. Files the action doesn't accept stay in the
 * list (greyed) but are left out of the job. The tab's options are kept in app
 * state, so they survive switching tabs.
 */
export function ActionPage({ action }: ActionPageProps) {
  const { state, dispatch } = useApp();
  const recovered = state.recoveredJob?.action === action ? state.recoveredJob : null;
  const info = getActionInfo(action);
  const settings = state.actionSettings[action];
  const usedFiles = state.files.filter((file) =>
    actionAcceptsFile(action, file),
  );
  const [request, setRequest] = useState<ConvertRequest | null>(null);

  const problem = action === Action.Split ? splitProblem(settings.split) : null;
  const canConvert = usedFiles.length > 0 && problem === null;
  const kindsText = info.accepts.includes("image")
    ? "an image (PNG or JPG)"
    : info.accepts.includes("pptx")
      ? "a PDF or PowerPoint file"
      : "a PDF";

  const onChange = (patch: Partial<ActionSettings>) =>
    dispatch({ type: "actionSettingsChanged", action, patch });

  const startConvert = () => {
    const folder = state.settings.defaultSaveFolder;
    setRequest({
      // Compress never uses OCR, whatever the stored value.
      settings:
        action === Action.Compress ? { ...settings, useOcr: false } : settings,
      autoSaveFolder: folder && state.saveToDefault[action] ? folder : null,
    });
  };

  return (
    <>
      <PageHeader
        title={info.label}
        description={`${info.description} Add your files, choose options, then click Convert. Your original files are never changed.`}
      />

      {/* Two columns on wide windows: files left, options right; one column when narrow. */}
      <div className={styles.columns}>
        <div className={styles.filesColumn}>
          <FileList
            action={action}
            headerActions={<AddFilesButton kind={info.pickKind} size="sm" />}
          />
        </div>
        <div className={styles.sections}>
          <Section title="Options">
            <ActionOptions
              action={action}
              settings={settings}
              onChange={onChange}
              usedFiles={usedFiles}
            />
          </Section>
          <Section title="Saving">
            <SaveDestination action={action} />
          </Section>
        </div>
      </div>

      <div className={styles.convertBar}>
        <p className={styles.muted} aria-live="polite">
          {usedFiles.length === 0
            ? `Add ${kindsText} to start.`
            : problem
              ? settings.split.method === "ranges" &&
                settings.split.ranges.trim() === ""
                ? "Type the pages to split above."
                : "Fix the options above to start."
              : usedFiles.length === 1
                ? "Ready: 1 file."
                : `Ready: ${usedFiles.length} files.`}
        </p>
        <Button
          variant="primary"
          size="lg"
          disabled={!canConvert}
          onClick={startConvert}
        >
          Convert
        </Button>
      </div>

      {request && (
        <ConvertModal
          action={action}
          settings={request.settings}
          files={usedFiles}
          autoSaveFolder={request.autoSaveFolder}
          onClose={() => setRequest(null)}
        />
      )}
      {!request && recovered && (
        <ConvertModal
          action={action}
          settings={settings}
          files={[]}
          autoSaveFolder={null}
          resumeJobId={recovered.jobId}
          resumeSaved={recovered.saved}
          resumeSavedAsZip={recovered.savedAsZip}
          onClose={() => dispatch({ type: "recoveredJobClosed" })}
        />
      )}
    </>
  );
}
