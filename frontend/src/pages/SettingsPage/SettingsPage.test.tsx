import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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

  it("opens the logs folder and shows the version", async () => {
    const { user } = await renderApp({ state: { page: "settings" } });
    await user.click(screen.getByRole("button", { name: "Open logs folder" }));
    expect(screen.getByText(/version 1\.0\.0/)).toBeInTheDocument();
  });
});
