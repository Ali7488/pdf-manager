import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createMockApi } from "../../api/mock";
import type { Issue } from "../../api/types";
import { AppProvider } from "../../state/AppProvider";
import { IssueView } from "./IssueView";

const COMMAND = "sudo apt install tesseract-ocr tesseract-ocr-eng";

const ISSUE: Issue = {
  code: "OCR_INSTALL_FAILED",
  severity: "warning",
  title: "Install OCR with one command",
  message: "PDF Manager can't install OCR by itself on Linux.",
  troubleshooting: ["Then click Search for OCR in Settings."],
  details: null,
  logFile: null,
  command: COMMAND,
  file: null,
};

const originalClipboard = Object.getOwnPropertyDescriptor(window.navigator, "clipboard");
const originalExecCommand = Object.getOwnPropertyDescriptor(document, "execCommand");

/** Replaces navigator.clipboard (undefined removes it). */
function setClipboard(clipboard: Partial<Clipboard> | undefined) {
  Object.defineProperty(window.navigator, "clipboard", { value: clipboard, configurable: true });
}

/** Replaces document.execCommand. */
function setExecCommand(execCommand: (command: string) => boolean) {
  Object.defineProperty(document, "execCommand", { value: vi.fn(execCommand), configurable: true });
  return document.execCommand as unknown as ReturnType<typeof vi.fn>;
}

function renderIssue(issue: Issue) {
  return render(
    <AppProvider api={createMockApi({ tickMs: 1 })}>
      <IssueView issue={issue} />
    </AppProvider>,
  );
}

/** Clicks Copy and lets the copy promise settle. */
async function clickCopy() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
  });
}

afterEach(() => {
  if (originalClipboard) Object.defineProperty(window.navigator, "clipboard", originalClipboard);
  else delete (window.navigator as { clipboard?: unknown }).clipboard;
  if (originalExecCommand) Object.defineProperty(document, "execCommand", originalExecCommand);
  else delete (document as { execCommand?: unknown }).execCommand;
  window.getSelection()?.removeAllRanges();
  vi.useRealTimers();
});

describe("IssueView command block", () => {
  it("shows no command block when the issue has no command", () => {
    renderIssue({ ...ISSUE, command: null });
    expect(screen.queryByRole("button", { name: "Copy command" })).not.toBeInTheDocument();
    expect(screen.queryByText(/paste it into a Terminal window/)).not.toBeInTheDocument();
  });

  it("shows the command in a separate block, with the steps still visible", () => {
    renderIssue(ISSUE);
    const block = screen.getByRole("group", { name: /paste it into a Terminal window/ });
    expect(block).toHaveTextContent(COMMAND);
    expect(screen.getByText(COMMAND).tagName).toBe("CODE");
    expect(screen.getByText("Then click Search for OCR in Settings.")).toBeInTheDocument();
  });

  it("copies with the clipboard API and says Copied", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setClipboard({ writeText });
    const execCommand = setExecCommand(() => true);
    renderIssue(ISSUE);

    await clickCopy();

    expect(writeText).toHaveBeenCalledWith(COMMAND);
    expect(execCommand).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
  });

  it("hides Copied again after a few seconds", async () => {
    vi.useFakeTimers();
    setClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });
    renderIssue(ISSUE);

    await clickCopy();
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
    act(() => vi.advanceTimersByTime(3500));
    expect(screen.getByRole("status")).toHaveTextContent("");
  });

  it("falls back to selecting the text and execCommand when writeText rejects", async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException("Not allowed", "NotAllowedError"));
    setClipboard({ writeText });
    const execCommand = setExecCommand(() => true);
    renderIssue(ISSUE);

    await clickCopy();

    expect(writeText).toHaveBeenCalledWith(COMMAND);
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(window.getSelection()?.toString()).toBe(COMMAND);
    expect(screen.getByRole("status")).toHaveTextContent("Copied");
  });

  it("leaves the text selected and asks for Ctrl+C when no copy works", async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("blocked")) });
    setExecCommand(() => false);
    renderIssue(ISSUE);

    await clickCopy();

    expect(window.getSelection()?.toString()).toBe(COMMAND);
    expect(screen.getByRole("status")).toHaveTextContent("Press Ctrl+C to copy");
  });

  it("uses the fallback when there is no clipboard API at all", async () => {
    setClipboard(undefined);
    const execCommand = setExecCommand(() => {
      throw new Error("not supported");
    });
    renderIssue(ISSUE);

    await clickCopy();

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(window.getSelection()?.toString()).toBe(COMMAND);
    expect(screen.getByRole("status")).toHaveTextContent("Press Ctrl+C to copy");
  });
});
