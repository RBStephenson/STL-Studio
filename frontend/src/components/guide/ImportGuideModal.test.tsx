import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import ImportGuideModal, { slugFromFilename } from "./ImportGuideModal";

const importMock = vi.fn();
const forceAddMock = vi.fn();
const listMock = vi.fn(async (..._a: unknown[]) => ({ total: 0, page: 1, page_size: 20, items: [] }));

vi.mock("../../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../../api/client")>();
  return {
    ...orig,
    api: {
      painting: {
        guides: { import_: (...a: unknown[]) => importMock(...a) },
        paints: {
          forceAdd: (...a: unknown[]) => forceAddMock(...a),
          list: (...a: unknown[]) => listMock(...a),
        },
      },
    },
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

const emptyReport = (over = {}) => ({
  resolved_paints: 0, unresolved_paints: [], unmapped_nodes: [], notes: [], ...over,
});

describe("slugFromFilename", () => {
  it("strips .html and slugifies", () => {
    expect(slugFromFilename("RoboCop 1987-painting-guide.html")).toBe("robocop-1987-painting-guide");
    expect(slugFromFilename("presto.htm")).toBe("presto");
    expect(slugFromFilename("__weird__.HTML")).toBe("weird");
  });
});

describe("ImportGuideModal", () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it("auto-commits when the dry-run preview has no unresolved paints", async () => {
    importMock.mockImplementation((_html, _slug, opts: { dryRun?: boolean } = {}) =>
      opts.dryRun
        ? Promise.resolve({ guide: null, report: emptyReport({ resolved_paints: 12 }) })
        : Promise.resolve({ guide: { id: 7, title: "RoboCop", status: "draft" }, report: emptyReport({ resolved_paints: 12 }) })
    );

    renderModal();
    await userEvent.upload(screen.getByTestId("guide-file-input"), htmlFile("robocop.html"));

    expect(await screen.findByTestId("import-report")).toBeInTheDocument();
    // dry-run preview, then the committing import.
    expect(importMock).toHaveBeenCalledTimes(2);
    expect(importMock.mock.calls[0][2]).toEqual({ dryRun: true });
    expect(screen.getByRole("link", { name: /view draft/i })).toHaveAttribute("href", "/painting/guides/7");
  });

  it("shows the resolution step when paints are unresolved (no auto-import)", async () => {
    importMock.mockResolvedValue({
      guide: null,
      report: emptyReport({ unresolved_paints: [{ name: "Mystery Silver", brand: "Acme", step: "Metals", hex: "#c0c0c0" }] }),
    });

    renderModal();
    await userEvent.upload(screen.getByTestId("guide-file-input"), htmlFile("robocop.html"));

    expect(await screen.findByTestId("resolve-paints")).toBeInTheDocument();
    expect(screen.getByText("Mystery Silver")).toBeInTheDocument();
    expect(screen.queryByTestId("import-report")).toBeNull(); // not committed yet
    expect(importMock).toHaveBeenCalledTimes(1); // dry-run only
  });

  it("force-adds an unresolved paint and commits with the override", async () => {
    importMock.mockImplementation((_html, _slug, opts: { dryRun?: boolean } = {}) =>
      opts.dryRun
        ? Promise.resolve({ guide: null, report: emptyReport({ unresolved_paints: [{ name: "Mystery Silver", brand: null, step: "Metals", hex: "#c0c0c0" }] }) })
        : Promise.resolve({ guide: { id: 9, title: "Done", status: "draft" }, report: emptyReport({ resolved_paints: 1 }) })
    );
    forceAddMock.mockResolvedValue({ id: 55, name: "Mystery Silver", code: "Mystery Silver", hex: "#c0c0c0" });

    renderModal();
    await userEvent.upload(screen.getByTestId("guide-file-input"), htmlFile("g.html"));
    await screen.findByTestId("resolve-paints");

    await userEvent.click(screen.getByRole("button", { name: /add/i }));
    expect(forceAddMock).toHaveBeenCalledWith("Mystery Silver", "#c0c0c0");
    expect(await screen.findByText(/Added to shelf/)).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("commit-import"));
    await waitFor(() =>
      expect(importMock).toHaveBeenLastCalledWith(
        expect.any(String), expect.any(String),
        { paintOverrides: [{ name: "Mystery Silver", paint_id: 55 }] },
      )
    );
    expect(await screen.findByTestId("import-report")).toBeInTheDocument();
  });

  it("skips an unresolved paint and commits with no override", async () => {
    importMock.mockImplementation((_html, _slug, opts: { dryRun?: boolean } = {}) =>
      opts.dryRun
        ? Promise.resolve({ guide: null, report: emptyReport({ unresolved_paints: [{ name: "Mystery Silver", brand: null, step: "Metals", hex: null }] }) })
        : Promise.resolve({ guide: { id: 9, title: "Done", status: "draft" }, report: emptyReport() })
    );

    renderModal();
    await userEvent.upload(screen.getByTestId("guide-file-input"), htmlFile("g.html"));
    await screen.findByTestId("resolve-paints");

    await userEvent.click(screen.getByRole("button", { name: /skip/i }));
    await userEvent.click(screen.getByTestId("commit-import"));

    await waitFor(() =>
      expect(importMock).toHaveBeenLastCalledWith(
        expect.any(String), expect.any(String), { paintOverrides: [] },
      )
    );
    expect(await screen.findByTestId("import-report")).toBeInTheDocument();
  });

  it("surfaces a slug-conflict (409) on the dry-run clearly", async () => {
    importMock.mockRejectedValue(new Error("409 Conflict"));

    renderModal();
    await userEvent.upload(screen.getByTestId("guide-file-input"), htmlFile("robocop.html"));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already exists/i);
    expect(screen.queryByTestId("import-report")).toBeNull();
  });

  it("imports a file dropped onto the dropzone (#413)", async () => {
    importMock.mockImplementation((_html, _slug, opts: { dryRun?: boolean } = {}) =>
      opts.dryRun
        ? Promise.resolve({ guide: null, report: emptyReport({ resolved_paints: 3 }) })
        : Promise.resolve({ guide: { id: 9, title: "Presto", status: "draft" }, report: emptyReport({ resolved_paints: 3 }) })
    );

    renderModal();
    fireEvent.drop(screen.getByTestId("guide-dropzone"), {
      dataTransfer: { files: [htmlFile("presto.html")] },
    });

    expect(await screen.findByTestId("import-report")).toBeInTheDocument();
    expect(importMock.mock.calls[0][1]).toBe("presto");
  });

  it("rejects a non-HTML drop with an error and no import (#413)", async () => {
    renderModal();
    const notHtml = new File(["x"], "model.stl", { type: "application/octet-stream" });
    fireEvent.drop(screen.getByTestId("guide-dropzone"), {
      dataTransfer: { files: [notHtml] },
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/html file/i);
    expect(importMock).not.toHaveBeenCalled();
  });
});
