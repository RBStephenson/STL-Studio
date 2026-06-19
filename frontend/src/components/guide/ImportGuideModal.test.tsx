import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ImportGuideModal, { slugFromFilename } from "./ImportGuideModal";

vi.mock("../../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../../api/client")>();
  return {
    ...orig,
    api: { painting: { guides: { import_: vi.fn() } } },
  };
});

function renderModal(onImported = vi.fn(), onClose = vi.fn()) {
  render(
    <MemoryRouter>
      <ImportGuideModal onClose={onClose} onImported={onImported} />
    </MemoryRouter>
  );
  return { onImported, onClose };
}

function htmlFile(name: string) {
  return new File(["<html><body>guide</body></html>"], name, { type: "text/html" });
}

describe("slugFromFilename", () => {
  it("strips .html and slugifies", () => {
    expect(slugFromFilename("RoboCop 1987-painting-guide.html")).toBe("robocop-1987-painting-guide");
    expect(slugFromFilename("presto.htm")).toBe("presto");
    expect(slugFromFilename("__weird__.HTML")).toBe("weird");
  });
});

describe("ImportGuideModal", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("imports a file and shows the report with dropped swatches + a draft link", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.painting.guides.import_).mockResolvedValue({
      guide: { id: 7, title: "RoboCop", status: "draft" } as never,
      report: {
        resolved_paints: 12,
        unresolved_paints: [{ name: "Mystery Silver", brand: "Acme", step: "Base metals" }],
        unmapped_nodes: ["#punk-clothing > div.tier-card"],
        notes: [],
      },
    });

    renderModal();
    await userEvent.upload(screen.getByTestId("guide-file-input"), htmlFile("robocop.html"));

    // Called with the file HTML + slug derived from the filename.
    expect(api.painting.guides.import_).toHaveBeenCalledWith(expect.stringContaining("guide"), "robocop");

    expect(await screen.findByTestId("import-report")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();           // resolved count
    expect(screen.getByText("Mystery Silver")).toBeInTheDocument(); // dropped swatch listed
    expect(screen.getByTestId("unmapped-nodes")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view draft/i })).toHaveAttribute("href", "/painting/guides/7");
  });

  it("imports a file dropped onto the dropzone (#413)", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.painting.guides.import_).mockResolvedValue({
      guide: { id: 9, title: "Presto", status: "draft" } as never,
      report: { resolved_paints: 3, unresolved_paints: [], unmapped_nodes: [], notes: [] },
    });

    renderModal();
    fireEvent.drop(screen.getByTestId("guide-dropzone"), {
      dataTransfer: { files: [htmlFile("presto.html")] },
    });

    expect(await screen.findByTestId("import-report")).toBeInTheDocument();
    expect(api.painting.guides.import_).toHaveBeenCalledWith(expect.stringContaining("guide"), "presto");
  });

  it("rejects a non-HTML drop with an error and no import (#413)", async () => {
    const { api } = await import("../../api/client");

    renderModal();
    const notHtml = new File(["x"], "model.stl", { type: "application/octet-stream" });
    fireEvent.drop(screen.getByTestId("guide-dropzone"), {
      dataTransfer: { files: [notHtml] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/html file/i);
    expect(api.painting.guides.import_).not.toHaveBeenCalled();
  });

  it("surfaces a slug-conflict (409) clearly", async () => {
    const { api } = await import("../../api/client");
    vi.mocked(api.painting.guides.import_).mockRejectedValue(new Error("409 Conflict"));

    renderModal();
    await userEvent.upload(screen.getByTestId("guide-file-input"), htmlFile("robocop.html"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
    // Stays on the upload step so the user can rename + retry.
    expect(screen.queryByTestId("import-report")).toBeNull();
  });
});
