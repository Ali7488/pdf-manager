/**
 * Settings → Close PDF Manager (browser mode only). Quitting never silently
 * deletes work (decision P35): if a conversion is running or finished results
 * aren't saved yet, the app answers `quit: false` and this asks the user to
 * confirm before quitting anyway.
 */
import { useState } from "react";
import type { QuitResult } from "../../api/types";
import { quitWarning } from "../../lib/quit";
import { Button } from "../../components/Button/Button";
import { Icon } from "../../components/Icon/Icon";
import { Section } from "../../components/Page/Page";
import { useApp } from "../../state/AppContext";
import styles from "./SettingsPage.module.css";

/** The Quit button, with a confirmation when quitting would delete results. */
export function QuitSection() {
  const { api, dispatch } = useApp();
  const [held, setHeld] = useState<QuitResult | null>(null);
  const [busy, setBusy] = useState(false);

  const quit = async (discardUnsaved: boolean) => {
    setBusy(true);
    try {
      const result = await api.quit({ discardUnsaved });
      if (result.quit) dispatch({ type: "appClosed" });
      else setHeld(result);
    } catch {
      // The app isn't answering; that is reported separately.
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="Close PDF Manager">
      <div className={styles.folderRow}>
        <p className={styles.help}>
          PDF Manager keeps running after you close this window, so it opens again quickly. Quit it here when you're
          done. It also closes by itself after an hour without use, but never while results are waiting to be saved.
        </p>
        {!held && (
          <Button onClick={() => void quit(false)} disabled={busy}>
            Quit PDF Manager
          </Button>
        )}
      </div>
      {held && (
        <div role="alert" className={styles.quitConfirm}>
          <p className={styles.unsaved}>
            <Icon name="alert" className={styles.unsavedIcon} />
            {quitWarning(held)}
          </p>
          <div className={styles.buttons}>
            <Button variant="primary" onClick={() => setHeld(null)} disabled={busy}>
              Keep PDF Manager open
            </Button>
            <Button variant="danger" onClick={() => void quit(true)} disabled={busy}>
              Quit anyway
            </Button>
          </div>
        </div>
      )}
    </Section>
  );
}
