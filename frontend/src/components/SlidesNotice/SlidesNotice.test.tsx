import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { emitEvent } from "../../api/bridge";
import { Action } from "../../api/types";
import { renderApp, SAMPLE_FILES } from "../../test/renderApp";

const slides = SAMPLE_FILES.filter((file) => file.kind === "pptx");
const pdfs = SAMPLE_FILES.filter((file) => file.kind === "pdf");
const NOTICE = "Error: LibreOffice is needed for PowerPoint files";

describe("SlidesNotice", () => {
  it("explains what to install as soon as a presentation is added without LibreOffice", async () => {
    await renderApp({ mock: { tools: { libreoffice: false } } });
    act(() => emitEvent("filesAdded", { files: slides }));
    const notice = await screen.findByRole("region", { name: NOTICE });
    expect(within(notice).getByText(/libreoffice\.org/)).toBeInTheDocument();
    expect(within(notice).getByText(/save or export it as a PDF/)).toBeInTheDocument();
  });

  it("never checks for LibreOffice when only PDFs are added", async () => {
    const { mock } = await renderApp({ mock: { tools: { libreoffice: false } } });
    const check = vi.spyOn(mock, "checkTools");
    act(() => emitEvent("filesAdded", { files: pdfs }));
    await screen.findByText(pdfs[0].name);
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(check).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: NOTICE })).not.toBeInTheDocument();
  });

  it("says nothing when LibreOffice is installed", async () => {
    const { mock } = await renderApp({ mock: { tools: { libreoffice: true } } });
    const check = vi.spyOn(mock, "checkTools");
    act(() => emitEvent("filesAdded", { files: slides }));
    await waitFor(() => expect(check).toHaveBeenCalled());
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(screen.queryByRole("region", { name: NOTICE })).not.toBeInTheDocument();
  });

  it("isn't shown on a tab that doesn't take PowerPoint files", async () => {
    await renderApp({ state: { page: Action.Compress, files: SAMPLE_FILES }, mock: { tools: { libreoffice: false } } });
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));
    expect(screen.queryByRole("region", { name: NOTICE })).not.toBeInTheDocument();
  });

  it("goes away once the presentation is removed", async () => {
    const { user } = await renderApp({ state: { files: [...pdfs, ...slides] }, mock: { tools: { libreoffice: false } } });
    await screen.findByRole("region", { name: NOTICE });
    await user.click(screen.getByRole("button", { name: `Remove ${slides[0].name}` }));
    expect(screen.queryByRole("region", { name: NOTICE })).not.toBeInTheDocument();
  });
});
