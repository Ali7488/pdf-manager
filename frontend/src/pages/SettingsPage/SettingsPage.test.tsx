import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LINUX_OCR_INSTALL_COMMAND } from "../../api/mock";
import { renderApp } from "../../test/renderApp";

const FOLDER = "D:\\Results";

describe("SettingsPage", () => {
  it("applies a theme straight away and saves it", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" } });
    // "system" follows prefers-color-scheme (light in jsdom).
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(screen.getByRole("radio", { name: /System/ })).toBeChecked();

    await user.click(screen.getByRole("radio", { name: /Burgundy/ }));
    expect(document.documentElement.dataset.theme).toBe("burgundy");
    await waitFor(async () => expect((await mock.getSettings()).theme).toBe("burgundy"));

    await user.click(screen.getByRole("radio", { name: /Green/ }));
    expect(document.documentElement.dataset.theme).toBe("green");
  });

  it("loads the saved theme on start", async () => {
    await renderApp({ mock: { settings: { theme: "dark" } } });
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("dark"));
  });

  it("chooses and clears the default save folder", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" }, mock: { folderPicker: () => FOLDER } });
    expect(screen.getByText(/Not set/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Choose folder" }));
    expect(await screen.findByText(FOLDER)).toBeInTheDocument();
    expect((await mock.getSettings()).defaultSaveFolder).toBe(FOLDER);

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(await screen.findByText(/Not set/)).toBeInTheDocument();
    await waitFor(async () => expect((await mock.getSettings()).defaultSaveFolder).toBeNull());
  });

  it("saves a valid DPI and rejects one out of range", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" } });
    const dpi = screen.getByRole("spinbutton", { name: "Resolution (DPI)" });
    expect(dpi).toHaveValue(200);

    await user.clear(dpi);
    await user.type(dpi, "900");
    fireEvent.blur(dpi);
    expect(screen.getByRole("alert")).toHaveTextContent("from 100 to 400");
    expect((await mock.getSettings()).dpi).toBe(200);

    await user.clear(dpi);
    await user.type(dpi, "300{Enter}");
    await waitFor(async () => expect((await mock.getSettings()).dpi).toBe(300));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the OCR timeout in minutes and saves it in seconds", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" } });
    const timeout = screen.getByRole("spinbutton", { name: "Give up on a page after" });
    expect(timeout).toHaveValue(2);
    await user.clear(timeout);
    await user.type(timeout, "5{Enter}");
    await waitFor(async () => expect((await mock.getSettings()).ocrPageTimeoutSec).toBe(300));
  });

  it("reads the OCR status with getOcrStatus", async () => {
    const { mock } = await renderApp({ mock: { tools: { ocr: true } } });
    const getOcrStatus = vi.spyOn(mock, "getOcrStatus");
    const checkTools = vi.spyOn(mock, "checkTools");
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("OCR is installed")).toBeInTheDocument();
    expect(screen.getByText("C:\\Program Files\\Tesseract-OCR\\tesseract.exe")).toBeInTheDocument();
    expect(getOcrStatus).toHaveBeenCalled();
    expect(checkTools).not.toHaveBeenCalled();
  });

  it("shows English when no OCR languages are installed", async () => {
    await renderApp({ state: { page: "settings" } });
    expect(await screen.findByText("OCR wasn't found")).toBeInTheDocument();
    expect(screen.getByText(/English \(install OCR/)).toBeInTheDocument();
  });

  it("explains when Search for OCR finds nothing", async () => {
    const { user } = await renderApp({ state: { page: "settings" } });
    await user.click(screen.getByRole("button", { name: "Search for OCR" }));
    expect(await screen.findByRole("dialog")).toHaveTextContent("OCR wasn't found");
    await user.click(screen.getByRole("button", { name: "OK" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("installs OCR with progress, then offers its languages", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" }, mock: { tickMs: 5 } });
    await screen.findByText("OCR wasn't found");
    await user.click(screen.getByRole("button", { name: "Install OCR" }));
    expect(screen.getByRole("button", { name: "Installing OCR" })).toBeDisabled();
    expect(await screen.findByText("OCR is installed", {}, { timeout: 3000 })).toBeInTheDocument();

    const language = await screen.findByRole("combobox", { name: "OCR language" });
    expect(screen.queryByRole("option", { name: "osd" })).not.toBeInTheDocument();
    await user.selectOptions(language, "German");
    await waitFor(async () => expect((await mock.getSettings()).ocrLanguage).toBe("deu"));
  });

  it("shows the install error in a popup", async () => {
    const { user } = await renderApp({ state: { page: "settings" }, mock: { ocrInstallFails: true } });
    await user.click(screen.getByRole("button", { name: "Install OCR" }));
    expect(await screen.findByRole("dialog", {}, { timeout: 3000 })).toHaveTextContent("OCR couldn't be installed");
  });

  it("on Linux, shows the install command to copy instead of installing (C16)", async () => {
    const { user, mock } = await renderApp({ state: { page: "settings" }, mock: { platform: "linux" } });
    expect((await mock.getAppInfo()).platform).toBe("linux");
    await screen.findByText("OCR wasn't found");
    await user.click(screen.getByRole("button", { name: "Install OCR" }));

    const popup = within(await screen.findByRole("dialog", {}, { timeout: 3000 }));
    expect(popup.getByText("Install OCR with one command")).toBeInTheDocument();
    expect(popup.getByText(LINUX_OCR_INSTALL_COMMAND).tagName).toBe("CODE");
    // The steps still point to Search for OCR for after the command has run.
    expect(popup.getByText("Then click Search for OCR in Settings.")).toBeInTheDocument();

    await user.click(popup.getByRole("button", { name: "Copy command" }));
    expect(await popup.findByRole("status")).toHaveTextContent("Copied");
    expect(await navigator.clipboard.readText()).toBe(LINUX_OCR_INSTALL_COMMAND);

    // Nothing was installed.
    await user.click(popup.getByRole("button", { name: "OK" }));
    expect(screen.getByText("OCR wasn't found")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Install OCR" })).toBeEnabled();
  });

  it("opens the logs folder and shows the version", async () => {
    const { user } = await renderApp({ state: { page: "settings" } });
    await user.click(screen.getByRole("button", { name: "Open logs folder" }));
    expect(screen.getByText(/version 1\.0\.0/)).toBeInTheDocument();
  });

  describe("when settings can't be saved (audit R6)", () => {
    const NOT_SAVED = "Not saved: your changes apply until you close PDF Manager.";

    it("says the change isn't saved, keeps it, and clears the warning after a save that works", async () => {
      const { user, mock } = await renderApp({ state: { page: "settings" }, mock: { settingsSaveFails: true } });
      expect(screen.queryByText(NOT_SAVED)).not.toBeInTheDocument();

      await user.click(screen.getByRole("radio", { name: /^Burgundy/ }));
      const alert = (await screen.findByText("Your settings couldn't be saved")).closest("[role=alert]");
      expect(alert).not.toBeNull();
      const warning = within(alert as HTMLElement);
      expect(warning.getByText(/lost when PDF Manager closes/)).toBeInTheDocument();
      expect(warning.getByText("Check the drive isn't full.")).toBeInTheDocument();
      expect(warning.getByRole("button", { name: "Open logs folder" })).toBeInTheDocument();
      expect(screen.getByText(NOT_SAVED)).toBeInTheDocument();
      expect(screen.queryByText("Changes are saved straight away.")).not.toBeInTheDocument();
      // The change still applies for now.
      expect(screen.getByRole("radio", { name: /^Burgundy/ })).toBeChecked();
      expect(document.documentElement.dataset.theme).toBe("burgundy");

      mock.setSettingsSaveFails(false);
      await user.click(screen.getByRole("radio", { name: /^Green/ }));
      await waitFor(() => expect(screen.queryByText(NOT_SAVED)).not.toBeInTheDocument());
      expect(screen.queryByText(NOT_SAVED)).not.toBeInTheDocument();
      expect(screen.queryByText("Your settings couldn't be saved")).not.toBeInTheDocument();
      expect(document.documentElement.dataset.theme).toBe("green");
    });

    it("tries again with the button once the problem is fixed", async () => {
      const { user, mock } = await renderApp({ state: { page: "settings" }, mock: { settingsSaveFails: true } });
      const dpi = screen.getByRole("spinbutton", { name: "Resolution (DPI)" });
      await user.clear(dpi);
      await user.type(dpi, "300{Enter}");
      expect(await screen.findByText(NOT_SAVED)).toBeInTheDocument();
      expect(screen.getByRole("spinbutton", { name: "Resolution (DPI)" })).toHaveValue(300);

      mock.setSettingsSaveFails(false);
      const saveSettings = vi.spyOn(mock, "saveSettings");
      await user.click(screen.getByRole("button", { name: "Try saving again" }));
      await waitFor(() => expect(screen.queryByText(NOT_SAVED)).not.toBeInTheDocument());
      expect(saveSettings).toHaveBeenCalledWith({});
      expect((await mock.getSettings()).dpi).toBe(300);
    });

    it("also warns when the save call itself fails", async () => {
      const { user, mock } = await renderApp({ state: { page: "settings" } });
      vi.spyOn(mock, "saveSettings").mockRejectedValueOnce(new Error("The bridge stopped answering."));
      await user.click(screen.getByRole("radio", { name: /^Dark/ }));
      expect(await screen.findByText(NOT_SAVED)).toBeInTheDocument();
      expect(screen.getByRole("radio", { name: /^Dark/ })).toBeChecked();
    });
  });

  describe("About and licensing (AGPL-3.0 appropriate legal notices)", () => {
    it("shows the copyright, licence terms, no-warranty notice and source location", async () => {
      await renderApp({ state: { page: "settings" } });
      const about = within(screen.getByRole("region", { name: "About" }));
      expect(about.getByText(/© 2026 Mohannad Ali/)).toBeInTheDocument();
      expect(about.getByText(/GNU Affero General Public License, version 3/)).toBeInTheDocument();
      expect(about.getByText(/ABSOLUTELY NO WARRANTY/)).toBeInTheDocument();
      expect(about.getByText(/PyMuPDF/)).toBeInTheDocument();
      expect(about.getByText(/github\.com\/Ali7488\/pdf-manager/)).toBeInTheDocument();
    });

    it("opens the licences folder", async () => {
      const { user, mock } = await renderApp({ state: { page: "settings" } });
      const openFolder = vi.spyOn(mock, "openFolder");
      const button = await screen.findByRole("button", { name: "Open licences folder" });
      await waitFor(() => expect(button).toBeEnabled());
      await user.click(button);
      const info = await mock.getAppInfo();
      expect(openFolder).toHaveBeenCalledWith(info.licensesDir);
    });

    it("never describes the app as MIT-only in the side pane", async () => {
      await renderApp();
      const footer = screen.getByText(/© 2026 Mohannad Ali/);
      expect(footer).toHaveTextContent("GNU AGPL-3.0");
      expect(footer).not.toHaveTextContent("MIT");
    });
  });
});
