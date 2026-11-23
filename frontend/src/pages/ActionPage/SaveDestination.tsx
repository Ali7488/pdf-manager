/**
 * Where results go (F22, F32): the "Save to default folder" box when a
 * default folder is set, otherwise a link to set one.
 */
import type { Action } from "../../api/types";
import { Button } from "../../components/Button/Button";
import { Checkbox } from "../../components/Field/Checkbox";
import { useApp } from "../../state/AppContext";
import styles from "./ActionPage.module.css";

/** Props for {@link SaveDestination}. */
export interface SaveDestinationProps {
  action: Action;
}

/**
 * With a default folder: a checkbox (ticked to start with) and a
 * "Change default folder" button that opens Settings. Without one: a short
 * note and a "Set a default folder" link to Settings.
 */
export function SaveDestination({ action }: SaveDestinationProps) {
  const { state, dispatch } = useApp();
  const folder = state.settings.defaultSaveFolder;
  const toSettings = () => dispatch({ type: "navigate", page: "settings" });

  if (!folder) {
    return (
      <div className={styles.saveRow}>
        <p className={styles.muted}>You'll choose where to save the results after converting.</p>
        <Button variant="ghost" size="sm" onClick={toSettings}>
          Set a default folder
        </Button>
      </div>
    );
  }

  return (
    <div className={styles.saveBlock}>
      <Checkbox
        label="Save to default folder"
        tip="Results are saved straight into your default folder, without asking. Untick to choose a folder each time."
        checked={state.saveToDefault[action]}
        onChange={(value) => dispatch({ type: "saveToDefaultChanged", action, value })}
      >
        <Button variant="ghost" size="sm" icon="folder" onClick={toSettings}>
          Change default folder
        </Button>
      </Checkbox>
      <p className={styles.path} title={folder}>
        {folder}
      </p>
    </div>
  );
}
