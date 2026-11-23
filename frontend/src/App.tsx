/**
 * The app: sidebar navigation on the left, the current page on the right, and
 * a window-wide drop target for files.
 */
import type { onEvent as onEventType } from "./api/bridge";
import type { PdfManagerApi } from "./api/types";
import { AppNotice } from "./components/AppNotice/AppNotice";
import { DropOverlay } from "./components/DropOverlay/DropOverlay";
import { Sidebar } from "./components/Sidebar/Sidebar";
import { ActionPage } from "./pages/ActionPage/ActionPage";
import { HomePage } from "./pages/HomePage/HomePage";
import { SettingsPage } from "./pages/SettingsPage/SettingsPage";
import { useApp } from "./state/AppContext";
import { AppProvider } from "./state/AppProvider";
import type { AppState } from "./state/appReducer";
import { useApplyTheme } from "./state/useApplyTheme";
import styles from "./App.module.css";

/** Props for {@link App}. All optional; tests use them to inject a mock. */
export interface AppProps {
  api?: PdfManagerApi;
  onEvent?: typeof onEventType;
  initialState?: Partial<AppState>;
}

/** The root component. */
export function App({ api, onEvent, initialState }: AppProps) {
  return (
    <AppProvider api={api} onEvent={onEvent} initialState={initialState}>
      <Shell />
    </AppProvider>
  );
}

/** Layout and page switching. Tabs are app state, not URLs (no router). */
function Shell() {
  const { state } = useApp();
  useApplyTheme(state.settings.theme);

  let page;
  if (state.page === "home") page = <HomePage />;
  else if (state.page === "settings") page = <SettingsPage />;
  else page = <ActionPage action={state.page} />;

  return (
    <div className={styles.shell}>
      <Sidebar />
      <main className={styles.main}>
        <div key={state.page} className={styles.page}>
          {page}
        </div>
      </main>
      <DropOverlay />
      <AppNotice />
    </div>
  );
}
