/**
 * Home (F15): a large drop zone, the shared file list, and a button for each
 * action that opens its tab.
 */
import { AddFilesButton } from "../../components/AddFilesButton/AddFilesButton";
import { FileList } from "../../components/FileList/FileList";
import { Icon } from "../../components/Icon/Icon";
import { PageHeader } from "../../components/Page/Page";
import { ACTIONS } from "../../lib/actions";
import { useApp } from "../../state/AppContext";
import styles from "./HomePage.module.css";

/** The start page. */
export function HomePage() {
  const { dispatch } = useApp();

  return (
    <>
      <PageHeader title="Welcome to PDF Manager" />

      <div className={styles.dropZone}>
        <Icon name="upload" size={28} className={styles.dropIcon} />
        <p className={styles.dropTitle}>Drop files here, or click Add files</p>
        <div className={styles.dropButtons}>
          <AddFilesButton kind="all" variant="primary" />
        </div>
      </div>

      <div className={styles.files}>
        <FileList />
      </div>

      <section aria-labelledby="home-actions" className={styles.actions}>
        <h2 id="home-actions" className={styles.actionsTitle}>
          Then choose a tool
        </h2>
        <div className={styles.grid}>
          {ACTIONS.map((info) => (
            <button
              key={info.action}
              type="button"
              className={styles.card}
              aria-label={`Open ${info.label}`}
              onClick={() => dispatch({ type: "navigate", page: info.action })}
            >
              <span className={styles.cardIcon} aria-hidden="true">
                <Icon name={info.icon} size={22} />
              </span>
              <span className={styles.cardLabel}>{info.label}</span>
            </button>
          ))}
        </div>
      </section>
    </>
  );
}
