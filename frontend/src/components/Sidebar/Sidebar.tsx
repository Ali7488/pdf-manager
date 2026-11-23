/**
 * The sidebar (F15): Home, one tab per action, and Settings at the bottom.
 */
import { ACTIONS } from "../../lib/actions";
import { useApp } from "../../state/AppContext";
import type { Page } from "../../state/appReducer";
import { Icon, type IconName } from "../Icon/Icon";
import styles from "./Sidebar.module.css";
import { COPYRIGHT } from "../../lib/about";

/** Sidebar navigation. The current tab is marked with `aria-current="page"`. */
export function Sidebar() {
  const { state, dispatch } = useApp();

  const item = (page: Page, label: string, icon: IconName, badge?: number) => (
    <li key={page}>
      <button
        type="button"
        className={`${styles.item} ${state.page === page ? styles.current : ""}`}
        aria-current={state.page === page ? "page" : undefined}
        onClick={() => dispatch({ type: "navigate", page })}
      >
        <Icon name={icon} />
        <span className={styles.label}>{label}</span>
        {badge !== undefined && badge > 0 && (
          <span className={styles.badge} title={`${badge} files in the list`}>
            {badge}
          </span>
        )}
      </button>
    </li>
  );

  return (
    <nav className={styles.sidebar} aria-label="Main">
      <div className={styles.brand}>
        <span className={styles.logo} aria-hidden="true">
          <Icon name="file" size={20} />
        </span>
        PDF Manager
      </div>
      <ul className={styles.list}>
        {item("home", "Home", "home", state.files.length)}
        <li className={styles.divider} role="presentation" />
        {ACTIONS.map((info) => item(info.action, info.label, info.icon))}
      </ul>
      <ul className={`${styles.list} ${styles.bottom}`}>{item("settings", "Settings", "settings")}</ul>
      <p className={styles.copyright}>{COPYRIGHT} · MIT License</p>
    </nav>
  );
}
