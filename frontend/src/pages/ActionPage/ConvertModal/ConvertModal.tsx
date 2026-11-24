/**
 * The Convert modal (F14, F12, F13, F22): tool check, then progress with
 * Cancel, then the results with saving, warnings or the error.
 */
import { useEffect, useEffectEvent, useRef, useState, type ReactNode } from "react";
import {
  Action,
  type ActionSettings,
  type InputFile,
  type Issue,
  type JobFinished,
  type JobProgress,
  type SaveOutcome,
  type ToolCheckResult,
} from "../../../api/types";
import { Button } from "../../../components/Button/Button";
import { Icon } from "../../../components/Icon/Icon";
import { IssuePopup } from "../../../components/Issue/IssuePopup";
import { IssueView } from "../../../components/Issue/IssueView";
import { Modal } from "../../../components/Modal/Modal";
import { ProgressBar, Spinner } from "../../../components/Progress/Progress";
import { isSlides } from "../../../lib/actions";
import { connectionIssue } from "../../../lib/connectionIssue";
import { formatBytes, formatPages } from "../../../lib/format";
import { useApp } from "../../../state/AppContext";
import styles from "./ConvertModal.module.css";
import { ToolRows } from "./ToolRows";

/** Props for {@link ConvertModal}. */
export interface ConvertModalProps {
  action: Action;
  /** The tab's settings at the moment Convert was clicked. */
  settings: ActionSettings;
  /** The files the action accepts, in display order. */
  files: InputFile[];
  /** Save here straight away when the job succeeds, or null to let the user choose. */
  autoSaveFolder: string | null;
  /** Called when the modal is closed (after results are saved or discarded). */
  onClose(): void;
  /**
   * Browser mode, after the page was reloaded: follow this job, which is already
   * running or finished, instead of checking the tools and starting a new one.
   */
  resumeJobId?: string;
  /**
   * How the resumed job's results were already saved. A job saved to a folder shows where
   * (its results are no longer in the app, so Save isn't offered); a download keeps
   * Download again until Done.
   */
  resumeSaved?: SaveOutcome | null;
  /** Whether that save was one .zip. */
  resumeSavedAsZip?: boolean;
}

/** Where the modal is in the flow. */
type Phase =
  | { name: "checking" }
  | { name: "blocked"; check: ToolCheckResult }
  | { name: "starting"; check: ToolCheckResult }
  | { name: "startFailed"; issue: Issue }
  | { name: "running"; check: ToolCheckResult | null; jobId: string; progress: JobProgress | null; cancelling: boolean }
  | { name: "lost"; check: ToolCheckResult | null; jobId: string }
  | { name: "finished"; result: JobFinished };

/** Saving the results of a succeeded job. */
type SaveState =
  | { status: "idle" }
  | { status: "saving"; folder: string | null }
  | { status: "pickerCancelled" }
  | { status: "saved"; outcome: SaveOutcome }
  | { status: "failed"; issue: Issue };

type JobEvent = { kind: "progress"; payload: JobProgress } | { kind: "finished"; payload: JobFinished };

/**
 * Runs one conversion from start to finish.
 *
 * 1. Calls `checkTools` and shows only the rows this job needs. If the check
 *    fails it lists the issues with fixes (Install OCR, Search for OCR, Open
 *    Settings) and doesn't start.
 * 2. Otherwise starts the job straight away and shows progress with Cancel.
 * 3. When it ends: on success, saves to the default folder without asking if
 *    that was chosen, or offers Save / Save as one .zip (Split) / Discard. A
 *    cancelled folder picker keeps the results. Warnings are listed with their
 *    troubleshooting steps. On failure, shows the error.
 *
 * Results are never lost by accident: while they're unsaved the modal can only
 * be left with Save or Discard (which asks to confirm).
 */
export function ConvertModal({
  action,
  settings,
  files,
  autoSaveFolder,
  onClose,
  resumeJobId,
  resumeSaved = null,
  resumeSavedAsZip = false,
}: ConvertModalProps) {
  const { api, onEvent, dispatch, ocrInstall, ocrVersion, bumpOcrVersion } = useApp();
  const [phase, setPhase] = useState<Phase>(() =>
    resumeJobId
      ? { name: "running", check: null, jobId: resumeJobId, progress: null, cancelling: false }
      : { name: "checking" },
  );
  const [save, setSave] = useState<SaveState>(() =>
    resumeSaved ? { status: "saved", outcome: resumeSaved } : { status: "idle" },
  );
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [lastAsZip, setLastAsZip] = useState(resumeSavedAsZip);
  const [popupIssue, setPopupIssue] = useState<Issue | null>(null);
  const jobIdRef = useRef<string | null>(resumeJobId ?? null);
  const earlyEvents = useRef<JobEvent[]>([]);
  const startedRef = useRef(false);
  const lastOcrVersion = useRef(ocrVersion);

  const paths = files.map((file) => file.path);
  const needsOcr = settings.useOcr && action !== Action.Compress;
  const hasSlides = files.some((file) => isSlides(file.kind));

  const saveTo = async (jobId: string, folder: string | null, asZip: boolean) => {
    setSave({ status: "saving", folder });
    setLastAsZip(asZip);
    let outcome: SaveOutcome;
    try {
      outcome = await api.saveResults(jobId, { folder, asZip });
    } catch (error) {
      // The results are still in the app: Save stays available to try again.
      setSave({ status: "failed", issue: connectionIssue(error) });
      return;
    }
    if (outcome.issue) setSave({ status: "failed", issue: outcome.issue });
    else if (outcome.cancelled) setSave({ status: "pickerCancelled" });
    else setSave({ status: "saved", outcome });
  };

  const applyEvent = (event: JobEvent) => {
    if (event.kind === "progress") {
      const progress = event.payload;
      setPhase((current) => (current.name === "running" && current.jobId === progress.jobId ? { ...current, progress } : current));
      return;
    }
    const result = event.payload;
    setPhase({ name: "finished", result });
    if (result.status === "succeeded" && autoSaveFolder) void saveTo(result.jobId, autoSaveFolder, false);
  };

  /** Checks the tools, then starts the job if nothing blocks it. */
  const checkThenStart = async () => {
    if (resumeJobId) return; // A resumed job is already running or finished.
    const data = { files: paths };
    const check = await api.checkTools(action, settings, data);
    if (!check.ok) {
      setPhase({ name: "blocked", check });
      return;
    }
    setPhase({ name: "starting", check });
    const started = await api.startJob(action, settings, data);
    if (started.issue) {
      setPhase({ name: "startFailed", issue: started.issue });
      return;
    }
    jobIdRef.current = started.jobId;
    setPhase({ name: "running", check, jobId: started.jobId, progress: null, cancelling: false });
    // Replay anything Python sent before startJob returned.
    const early = earlyEvents.current.filter((event) => event.payload.jobId === started.jobId);
    earlyEvents.current = [];
    early.forEach(applyEvent);
  };

  /** {@link checkThenStart}; a request PDF Manager didn't answer ends in "The job couldn't start". */
  const checkAndStart = async () => {
    try {
      await checkThenStart();
    } catch (error) {
      setPhase({ name: "startFailed", issue: connectionIssue(error) });
    }
  };

  const recheck = () => {
    setPhase({ name: "checking" });
    void checkAndStart();
  };

  const onJobEvent = useEffectEvent((event: JobEvent) => {
    if (jobIdRef.current === null) earlyEvents.current.push(event);
    else if (event.payload.jobId === jobIdRef.current) applyEvent(event);
  });
  const onMount = useEffectEvent(() => {
    // Guard against running twice (React StrictMode mounts effects twice in development).
    if (startedRef.current) return;
    startedRef.current = true;
    void checkAndStart();
  });
  const onConnectionLost = useEffectEvent((jobId: string | null) => {
    if (jobId === null || jobId !== jobIdRef.current) return;
    setPhase((current) => (current.name === "running" ? { name: "lost", check: current.check, jobId } : current));
  });
  const onOcrMaybeAvailable = useEffectEvent(() => {
    if (phase.name === "blocked") recheck();
  });

  useEffect(() => {
    const offProgress = onEvent("jobProgress", (payload) => onJobEvent({ kind: "progress", payload }));
    const offFinished = onEvent("jobFinished", (payload) => onJobEvent({ kind: "finished", payload }));
    const offLost = onEvent("connectionLost", ({ jobId }) => onConnectionLost(jobId));
    return () => {
      offProgress();
      offFinished();
      offLost();
    };
  }, [onEvent]);

  useEffect(() => onMount(), []);

  // A resumed job: follow it (browser mode polls the app for its status).
  useEffect(() => {
    if (resumeJobId) api.watchJob(resumeJobId);
  }, [api, resumeJobId]);

  // After OCR is installed or found, check again automatically.
  useEffect(() => {
    if (lastOcrVersion.current === ocrVersion) return;
    lastOcrVersion.current = ocrVersion;
    onOcrMaybeAvailable();
  }, [ocrVersion]);

  const cancel = async () => {
    if (phase.name !== "running") return;
    setPhase({ ...phase, cancelling: true });
    try {
      await api.cancelJob(phase.jobId);
    } catch {
      // Not sent: let the user press Cancel again.
      setPhase((current) => (current.name === "running" ? { ...current, cancelling: false } : current));
    }
  };

  /** After a lost connection: follow the job again (its status is kept in the app). */
  const reconnect = () => {
    if (phase.name !== "lost") return;
    setPhase({ name: "running", check: phase.check, jobId: phase.jobId, progress: null, cancelling: false });
    api.watchJob(phase.jobId);
  };

  const searchOcr = async () => {
    const result = await api.searchOcr();
    if (result.found) bumpOcrVersion();
    else if (result.issue) setPopupIssue(result.issue);
  };

  /**
   * RESULT_PENDING (decision P40): open the unsaved result again, in its own tab,
   * the same way a reload does, so it can be saved, downloaded or discarded.
   */
  const showPendingResult = async () => {
    const job = await api.latestJob().catch(() => null); // Not answering: reported separately.
    if (!job?.action) return;
    onClose();
    dispatch({
      type: "jobRecovered",
      jobId: job.jobId,
      action: job.action,
      saved: job.saved ?? null,
      savedAsZip: job.savedAsZip === true,
    });
  };

  const openSettings = () => {
    dispatch({ type: "navigate", page: "settings" });
    onClose();
  };

  /** Closes and frees the job's scratch folder. Only called once results are saved or not needed. */
  const closeAndCleanUp = (jobId: string | null) => {
    if (jobId) api.discardResults(jobId).catch(() => undefined); // Cleaned up when the app closes.
    onClose();
  };

  // ---- Render by phase ----
  let title = "Getting ready";
  let body: ReactNode;
  let footer: ReactNode = null;
  let closable = false;
  // Browser mode without a folder picker: results go to the browser's downloads.
  const downloads = api.saveMode === "download";

  if (phase.name === "checking" || phase.name === "starting") {
    body = (
      <>
        <p className={styles.lead} aria-live="polite">
          {phase.name === "checking" ? "Checking what this job needs." : "Starting."}
        </p>
        <ToolRows needsOcr={needsOcr} hasSlides={hasSlides} check={phase.name === "starting" ? phase.check : null} />
        {phase.name === "starting" && (
          <p className={styles.statusLine}>
            <Spinner /> Starting the job
          </p>
        )}
      </>
    );
  } else if (phase.name === "blocked") {
    title = "Something is missing";
    closable = true;
    const errors = phase.check.issues.filter((issue) => issue.severity === "error");
    body = (
      <>
        <p className={styles.lead}>This job can't start yet. Here's what to do.</p>
        <ToolRows needsOcr={needsOcr} hasSlides={hasSlides} check={phase.check} />
        {errors.map((issue, index) => (
          <IssueView
            key={`${issue.code}-${index}`}
            issue={issue}
            compact
            actions={issue.code === "OCR_MISSING" ? <OcrActions onSearch={searchOcr} onOpenSettings={openSettings} /> : null}
          />
        ))}
        {ocrInstall.status === "running" && (
          <p className={styles.statusLine} aria-live="polite">
            <Spinner /> {ocrInstall.message || "Installing OCR"}
          </p>
        )}
        {ocrInstall.status === "failed" && ocrInstall.issue && <IssueView issue={ocrInstall.issue} compact />}
      </>
    );
    footer = (
      <>
        <Button onClick={onClose}>Close</Button>
        <Button variant="primary" onClick={recheck}>
          Check again
        </Button>
      </>
    );
  } else if (phase.name === "startFailed") {
    title = "The job couldn't start";
    closable = true;
    body = <IssueView issue={phase.issue} />;
    const pending = phase.issue.code === "RESULT_PENDING" && api.mode !== "desktop";
    footer = pending ? (
      <>
        <Button onClick={onClose}>Close</Button>
        <Button variant="primary" onClick={() => void showPendingResult()}>
          Show the results
        </Button>
      </>
    ) : (
      <Button variant="primary" onClick={onClose}>
        Close
      </Button>
    );
  } else if (phase.name === "lost") {
    title = "Lost contact with PDF Manager";
    closable = true;
    body = <IssueView issue={connectionIssue("The app stopped answering while the job was running.")} />;
    footer = (
      <>
        <Button onClick={onClose}>Close</Button>
        <Button variant="primary" onClick={reconnect}>
          Try again
        </Button>
      </>
    );
  } else if (phase.name === "running") {
    title = "Converting";
    const progress = phase.progress;
    body = (
      <>
        <ToolRows needsOcr={needsOcr} hasSlides={hasSlides} check={phase.check} />
        <div className={styles.progress}>
          <ProgressBar fraction={progress?.fraction ?? 0} label="Conversion progress" />
          <div className={styles.progressText}>
            <span aria-live="polite">{phase.cancelling ? "Cancelling" : (progress?.message ?? "Starting")}</span>
            {progress && progress.fileCount > 1 && (
              <span className={styles.muted}>
                File {progress.fileIndex} of {progress.fileCount}
              </span>
            )}
          </div>
        </div>
      </>
    );
    footer = (
      <Button variant="danger" onClick={cancel} disabled={phase.cancelling}>
        {phase.cancelling ? "Cancelling" : "Cancel"}
      </Button>
    );
  } else {
    const { result } = phase;
    const warnings = result.warnings.length > 0 && (
      <div className={styles.warnings}>
        <h3 className={styles.subTitle}>Please check</h3>
        {result.warnings.map((issue, index) => (
          <IssueView key={`${issue.code}-${index}`} issue={issue} compact />
        ))}
      </div>
    );

    if (result.status === "cancelled") {
      title = "Cancelled";
      closable = true;
      body = <p className={styles.lead}>The job was cancelled. Nothing was saved.</p>;
      footer = (
        <Button variant="primary" onClick={() => closeAndCleanUp(result.jobId)}>
          Close
        </Button>
      );
    } else if (result.status === "failed") {
      title = "It didn't work";
      closable = true;
      body = (
        <>
          {result.error && <IssueView issue={result.error} />}
          {warnings}
        </>
      );
      footer = (
        <Button variant="primary" onClick={() => closeAndCleanUp(result.jobId)}>
          Close
        </Button>
      );
    } else {
      title = "Done";
      const saved = save.status === "saved" ? save.outcome : null;
      closable = saved !== null;
      body = (
        <>
          <div>
            <h3 className={styles.subTitle}>{result.outputs.length === 1 ? "Your new file" : `Your ${result.outputs.length} new files`}</h3>
            <ul className={styles.outputs}>
              {result.outputs.map((output) => (
                <li key={output.name} className={styles.output}>
                  <Icon name="file" size={16} />
                  <span className={styles.outputName}>{output.name}</span>
                  <span className={styles.muted}>
                    {formatPages(output.pageCount)} · {formatBytes(output.sizeBytes)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <SaveStatus save={save} downloads={downloads} />
          {warnings}
        </>
      );
      if (saved) {
        footer = (
          <>
            {saved.downloaded && (
              <Button icon="folder" onClick={() => void saveTo(result.jobId, null, lastAsZip)}>
                Download again
              </Button>
            )}
            {saved.folder && (
              <Button icon="folder" onClick={() => void api.openFolder(saved.folder!)}>
                Open folder
              </Button>
            )}
            <Button variant="primary" onClick={() => closeAndCleanUp(result.jobId)}>
              Done
            </Button>
          </>
        );
      } else if (confirmDiscard) {
        footer = (
          <>
            <span className={styles.confirmText}>Delete these results? This can't be undone.</span>
            <Button onClick={() => setConfirmDiscard(false)}>Keep them</Button>
            <Button variant="danger" onClick={() => closeAndCleanUp(result.jobId)}>
              Discard
            </Button>
          </>
        );
      } else {
        const busy = save.status === "saving";
        footer = (
          <>
            <Button variant="ghost" onClick={() => setConfirmDiscard(true)} disabled={busy}>
              Discard
            </Button>
            {action === Action.Split && result.outputs.length > 1 && (
              <Button onClick={() => void saveTo(result.jobId, null, true)} disabled={busy}>
                {downloads ? "Download as one .zip" : "Save as one .zip"}
              </Button>
            )}
            <Button variant="primary" icon="folder" onClick={() => void saveTo(result.jobId, null, false)} disabled={busy}>
              {downloads ? "Download" : "Save"}
            </Button>
          </>
        );
      }
    }
  }

  return (
    <>
      <Modal title={title} onClose={closable ? onClose : undefined} footer={footer}>
        {body}
      </Modal>
      {popupIssue && <IssuePopup issue={popupIssue} onClose={() => setPopupIssue(null)} />}
    </>
  );
}

/** Fix-it buttons shown with an OCR_MISSING issue. */
function OcrActions({ onSearch, onOpenSettings }: { onSearch(): void; onOpenSettings(): void }) {
  const { ocrInstall, startOcrInstall } = useApp();
  const installing = ocrInstall.status === "running";
  return (
    <>
      <Button size="sm" variant="primary" onClick={() => void startOcrInstall()} disabled={installing}>
        {installing ? "Installing OCR" : "Install OCR"}
      </Button>
      <Button size="sm" onClick={onSearch} disabled={installing}>
        Search for OCR
      </Button>
      <Button size="sm" onClick={onOpenSettings}>
        Open Settings
      </Button>
    </>
  );
}

/** What happened when saving, in plain words. */
function SaveStatus({ save, downloads }: { save: SaveState; downloads: boolean }) {
  switch (save.status) {
    case "idle":
      return null;
    case "saving":
      return (
        <p className={styles.statusLine} aria-live="polite">
          <Spinner /> {save.folder ? `Saving to ${save.folder}` : downloads ? "Preparing your download" : "Choose a folder to save to"}
        </p>
      );
    case "pickerCancelled":
      return (
        <p className={styles.notice} role="status">
          No folder was chosen. Your results are kept, so you can save them now.
        </p>
      );
    case "failed":
      return <IssueView issue={save.issue} compact />;
    case "saved":
      if (save.outcome.downloaded)
        return (
          <p className={`${styles.notice} ${styles.success}`} role="status">
            <Icon name="check" size={18} />
            <span>
              {save.outcome.savedPaths.length === 1
                ? "Sent to your browser's downloads. "
                : `${save.outcome.savedPaths.length} files sent to your browser's downloads. `}
              If you don't see them, click Download again.
            </span>
          </p>
        );
      return (
        <p className={`${styles.notice} ${styles.success}`} role="status">
          <Icon name="check" size={18} />
          <span>
            {save.outcome.savedPaths.length === 1 ? "Saved to " : `Saved ${save.outcome.savedPaths.length} files to `}
            <span className={styles.folder}>{save.outcome.folder}</span>
          </span>
        </p>
      );
  }
}
