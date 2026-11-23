/**
 * Settings → OCR: whether Tesseract is found, Search for OCR, Install OCR
 * (with live progress), the OCR language and the per-page timeout.
 */
import { useEffect, useId, useState } from "react";
import { Action, type Issue } from "../../api/types";
import { Button } from "../../components/Button/Button";
import fieldStyles from "../../components/Field/Field.module.css";
import { Icon } from "../../components/Icon/Icon";
import { InfoTip } from "../../components/InfoTip/InfoTip";
import { IssuePopup } from "../../components/Issue/IssuePopup";
import { Section } from "../../components/Page/Page";
import { Spinner } from "../../components/Progress/Progress";
import { defaultActionSettings } from "../../lib/actions";
import { languageName } from "../../lib/format";
import { useApp } from "../../state/AppContext";
import { NumberSetting } from "./NumberSetting";
import styles from "./SettingsPage.module.css";

interface OcrStatus {
  loading: boolean;
  present: boolean;
  path: string | null;
  languages: string[];
}

/**
 * The OCR part of Settings. The status comes from a tool check for a job that
 * uses OCR and has no files, so only the OCR row matters.
 */
export function OcrSection() {
  const { api, state, updateSettings, ocrInstall, startOcrInstall, ocrVersion, bumpOcrVersion } = useApp();
  const [status, setStatus] = useState<OcrStatus>({ loading: true, present: false, path: null, languages: [] });
  const [searching, setSearching] = useState(false);
  const [popupIssue, setPopupIssue] = useState<Issue | null>(null);
  const [dismissedInstallIssue, setDismissedInstallIssue] = useState<Issue | null>(null);
  const languageId = useId();

  // Refresh the status on open and whenever OCR may have become available.
  useEffect(() => {
    let active = true;
    const settings = { ...defaultActionSettings(), useOcr: true };
    void Promise.all([api.checkTools(Action.Flatten, settings, { files: [] }), api.getOcrLanguages()]).then(
      ([check, languages]) => {
        if (!active) return;
        setStatus({ loading: false, present: check.ocr.present, path: check.ocr.path, languages });
      },
    );
    return () => {
      active = false;
    };
  }, [api, ocrVersion]);

  const search = async () => {
    setSearching(true);
    try {
      const result = await api.searchOcr();
      if (result.found) bumpOcrVersion();
      else if (result.issue) setPopupIssue(result.issue);
    } finally {
      setSearching(false);
    }
  };

  const installing = ocrInstall.status === "running";
  const installIssue = ocrInstall.status === "failed" && ocrInstall.issue !== dismissedInstallIssue ? ocrInstall.issue : null;
  // Tesseract lists "osd" (page layout detection), which isn't a language to read.
  const languages = status.languages.filter((code) => code !== "osd");
  const current = state.settings.ocrLanguage;
  const options = languages.includes(current) || languages.length === 0 ? languages : [current, ...languages];

  return (
    <Section
      title="OCR (reading text)"
      titleExtra={
        <InfoTip
          label="OCR"
          text="OCR reads the text in page images, so you can search and copy it. It uses a free program called Tesseract."
        />
      }
    >
      <div className={styles.statusRow}>
        <div className={styles.status} aria-live="polite">
          {status.loading ? (
            <>
              <Spinner /> Checking for OCR
            </>
          ) : status.present ? (
            <>
              <Icon name="check" className={styles.ok} /> OCR is installed
            </>
          ) : (
            <>
              <Icon name="alert" className={styles.missing} /> OCR wasn't found
            </>
          )}
        </div>
        {status.path && (
          <p className={styles.path} title={status.path}>
            {status.path}
          </p>
        )}
        <div className={styles.buttons}>
          <Button onClick={search} disabled={searching || installing}>
            {searching ? "Searching" : "Search for OCR"}
          </Button>
          <Button variant={status.present ? "secondary" : "primary"} onClick={() => void startOcrInstall()} disabled={installing}>
            {installing ? "Installing OCR" : "Install OCR"}
          </Button>
        </div>
        {installing && (
          <p className={styles.progressLine} aria-live="polite">
            <Spinner /> {ocrInstall.message}
          </p>
        )}
        {ocrInstall.status === "succeeded" && <p className={styles.help}>OCR was installed.</p>}
      </div>

      <div className={fieldStyles.field}>
        <div className={fieldStyles.labelRow}>
          <label htmlFor={languageId} className={fieldStyles.label}>
            OCR language
          </label>
          <InfoTip label="OCR language" text="The language of the text in your files. Choosing the right one makes reading more accurate." />
        </div>
        {options.length === 0 ? (
          <p id={languageId} className={styles.help}>
            English (install OCR to choose other languages)
          </p>
        ) : (
          <select
            id={languageId}
            className={fieldStyles.select}
            value={current}
            onChange={(event) => void updateSettings({ ocrLanguage: event.target.value })}
          >
            {options.map((code) => (
              <option key={code} value={code}>
                {languageName(code)}
              </option>
            ))}
          </select>
        )}
      </div>

      <NumberSetting
        key={state.settings.ocrPageTimeoutSec}
        label="Give up on a page after"
        tip="If reading the text on one page takes longer than this, that page is skipped so the job doesn't get stuck."
        value={Math.round(state.settings.ocrPageTimeoutSec / 60)}
        min={1}
        max={30}
        suffix="minutes"
        help="Default: 2 minutes."
        onCommit={(minutes) => void updateSettings({ ocrPageTimeoutSec: minutes * 60 })}
      />

      {popupIssue && <IssuePopup issue={popupIssue} onClose={() => setPopupIssue(null)} />}
      {installIssue && <IssuePopup issue={installIssue} onClose={() => setDismissedInstallIssue(installIssue)} />}
    </Section>
  );
}
