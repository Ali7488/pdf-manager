/**
 * Settings: theme, default save folder, quality (DPI), OCR, and help.
 * Every change is saved straight away with `saveSettings`. If saving to disk
 * fails, the page says so plainly (the change still applies until the app
 * closes) and shows the issue's steps, instead of claiming it was saved.
 */
import { Button } from "../../components/Button/Button";
import { Icon } from "../../components/Icon/Icon";
import { IssueView } from "../../components/Issue/IssueView";
import { PageHeader, Section } from "../../components/Page/Page";
import { useApp } from "../../state/AppContext";
import { NumberSetting } from "./NumberSetting";
import { OcrSection } from "./OcrSection";
import styles from "./SettingsPage.module.css";
import { ThemePicker } from "./ThemePicker";
import { APP_LICENSE, COPYRIGHT, SOURCE_URL, sourceUrlFor } from "../../lib/about";

/** The Settings page. */
export function SettingsPage() {
  const { api, state, dispatch, updateSettings } = useApp();
  const { settings, appInfo, settingsSaveIssue } = state;

  const chooseFolder = async () => {
    const folder = await api.pickFolder();
    if (folder) await updateSettings({ defaultSaveFolder: folder });
  };

  return (
    <>
      <PageHeader
        title="Settings"
        description={
          settingsSaveIssue ? (
            <span className={styles.unsaved}>
              <Icon name="alert" className={styles.unsavedIcon} />
              Not saved: your changes apply until you close PDF Manager.
            </span>
          ) : undefined
        }
      />

      {settingsSaveIssue && (
        <div role="alert" className={styles.unsavedIssue}>
          <IssueView
            issue={settingsSaveIssue}
            actions={
              // An empty change makes Python write all the current settings again.
              <Button size="sm" onClick={() => void updateSettings({})}>
                Try saving again
              </Button>
            }
          />
        </div>
      )}

      <Section title="Appearance">
        <ThemePicker value={settings.theme} onChange={(theme) => void updateSettings({ theme })} />
      </Section>

      <Section title="Saving">
        <div className={styles.folderRow}>
          <div className={styles.folderText}>
            <p className={styles.label}>Default save folder</p>
            {settings.defaultSaveFolder ? (
              <p className={styles.path} title={settings.defaultSaveFolder}>
                {settings.defaultSaveFolder}
              </p>
            ) : api.saveMode === "download" ? (
              <p className={styles.help}>Results go to your browser's downloads.</p>
            ) : (
              <p className={styles.help}>Not set. You'll choose a folder each time you save.</p>
            )}
          </div>
          <div className={styles.buttons}>
            {api.saveMode === "folder" && (
              <Button icon="folder" onClick={chooseFolder}>
                Choose folder
              </Button>
            )}
            {settings.defaultSaveFolder && (
              <Button variant="ghost" onClick={() => void updateSettings({ defaultSaveFolder: null })}>
                Clear
              </Button>
            )}
          </div>
        </div>
      </Section>

      <Section title="Quality">
        <NumberSetting
          key={settings.dpi}
          label="Resolution (DPI)"
          tip="How sharp flattened pages are. Higher is sharper, but files are bigger and take longer to make."
          value={settings.dpi}
          min={100}
          max={400}
          step={10}
          suffix="DPI"
          help="From 100 to 400. Default: 200."
          onCommit={(dpi) => void updateSettings({ dpi })}
        />
      </Section>

      <OcrSection />

      <Section title="Help">
        <div className={styles.folderRow}>
          <p className={styles.help}>
            If something goes wrong, the details are saved in the logs folder. You can send these files when asking for help.
          </p>
          <Button icon="folder" onClick={() => void api.openLogsFolder()}>
            Open logs folder
          </Button>
        </div>
      </Section>

      {api.mode === "browser" && (
        <Section title="Close PDF Manager">
          <div className={styles.folderRow}>
            <p className={styles.help}>
              PDF Manager keeps running after you close this window, so it opens again quickly. Quit it here when
              you're done.
            </p>
            <Button onClick={() => void api.quit().then(() => dispatch({ type: "appClosed" }), () => undefined)}>
              Quit PDF Manager
            </Button>
          </div>
        </Section>
      )}

      <Section title="About">
        <p>
          PDF Manager {appInfo ? `version ${appInfo.version}` : ""} · {COPYRIGHT}
        </p>
        <p>
          PDF Manager is free software: you can redistribute it and/or change it under the terms of the{" "}
          {APP_LICENSE} (GNU Affero General Public License, version 3). It comes with ABSOLUTELY NO WARRANTY.
        </p>
        <p>
          It includes third-party components, each under its own licence: among them PyMuPDF and MuPDF
          ({APP_LICENSE}){api.mode === "browser" ? "" : ", and, on Windows, Microsoft's WebView2 SDK files"}. The author's own
          source code is also available under the MIT License. The full licence texts, the third-party notices
          and the build instructions come with the app; the third-party source code is attached to each release.
        </p>
        <p>
          Complete source code: {appInfo ? `${sourceUrlFor(appInfo.version)} (this version)` : SOURCE_URL}
        </p>
        <div>
          <Button
            icon="folder"
            disabled={!appInfo?.licensesDir}
            onClick={() => appInfo && void api.openFolder(appInfo.licensesDir)}
          >
            Open licences folder
          </Button>
        </div>
      </Section>
    </>
  );
}
