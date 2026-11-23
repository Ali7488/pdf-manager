/**
 * Settings: theme, default save folder, quality (DPI), OCR, and help.
 * Every change is saved straight away with `saveSettings`.
 */
import { Button } from "../../components/Button/Button";
import { PageHeader, Section } from "../../components/Page/Page";
import { useApp } from "../../state/AppContext";
import { NumberSetting } from "./NumberSetting";
import { OcrSection } from "./OcrSection";
import styles from "./SettingsPage.module.css";
import { ThemePicker } from "./ThemePicker";

/** The Settings page. */
export function SettingsPage() {
  const { api, state, updateSettings } = useApp();
  const { settings, appInfo } = state;

  const chooseFolder = async () => {
    const folder = await api.pickFolder();
    if (folder) await updateSettings({ defaultSaveFolder: folder });
  };

  return (
    <>
      <PageHeader title="Settings" description="Changes are saved straight away." />

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
            ) : (
              <p className={styles.help}>Not set. You'll choose a folder each time you save.</p>
            )}
          </div>
          <div className={styles.buttons}>
            <Button icon="folder" onClick={chooseFolder}>
              Choose folder
            </Button>
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
        <p className={styles.help}>PDF Manager {appInfo ? `version ${appInfo.version}` : ""}</p>
      </Section>
    </>
  );
}
