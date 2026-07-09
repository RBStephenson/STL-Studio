import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import ReorganizePage from "./ReorganizePage";

vi.mock("../api/client", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    api: {
      reorganize: {
        preview: vi.fn(),
        previewWithOverrides: vi.fn(),
        apply: vi.fn(),
        undo: vi.fn(),
      },
    },
  };
});

import { api } from "../api/client";

const reorg = api.reorganize as unknown as {
  preview: ReturnType<typeof vi.fn>;
  previewWithOverrides: ReturnType<typeof vi.fn>;
  apply: ReturnType<typeof vi.fn>;
  undo: ReturnType<typeof vi.fn>;
};

function entry(over: Record<string, unknown>) {
  return {
    model_id: 1, model_name: "Joker Bust", files: [], kind: "move",
    proposed_dir: "/lib/Abe3D/Joker/Bust", eligible: true,
    pack_override_paths: [],
    collision: false, collision_kind: "none", collision_with: [],
    unclassifiable: false, missing_fields: [], over_length: false,
    reserved_name: false, overlaps_other: false, spans_multiple_dirs: false,
    is_symlink: false, escapes_scan_root: false, missing_files_on_disk: false,
    ...over,
  };
}

const STATS = {
  total: 2, eligible: 1, moves_needed: 1, already_in_place: 0, collisions: 0,
  unclassifiable: 1, over_length: 0, reserved: 0, overlaps: 0, blocked: 1,
};

function previewFixture() {
  return {
    manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
    generated_at: "now",
    entries: [
      entry({ model_id: 1, model_name: "Joker Bust", eligible: true }),
      entry({
        model_id: 2, model_name: "Mystery", eligible: false,
        unclassifiable: true, missing_fields: ["character"],
        proposed_dir: "/lib/Abe3D/_Unknown Character/Mystery",
      }),
    ],
    stats: STATS,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  reorg.preview.mockResolvedValue(previewFixture());
});

describe("ReorganizePage", () => {
  it("selects an eligible entry and applies it", async () => {
    reorg.apply.mockResolvedValue({
      manifest_id: "deadbeef", moved_files: 3, moved_models: 1, undo_log: "/x.log",
    });
    render(<ReorganizePage />);

    const checkbox = await screen.findByLabelText("Select Joker Bust");
    fireEvent.click(checkbox);

    const applyBtn = screen.getByRole("button", { name: /Apply 1/ });
    expect(applyBtn).toBeEnabled();
    fireEvent.click(applyBtn);

    await waitFor(() =>
      expect(reorg.apply).toHaveBeenCalledWith("deadbeef", [1]),
    );
    expect(await screen.findByText(/Moved 3 file/)).toBeInTheDocument();
  });

  it("shows resolve inputs only on an ineligible row", async () => {
    render(<ReorganizePage />);
    // Expand the ineligible entry.
    fireEvent.click(await screen.findByText("Mystery"));
    expect(await screen.findByLabelText("character for Mystery")).toBeInTheDocument();
    expect(await screen.findByLabelText("scale for Mystery")).toBeInTheDocument();
    // The eligible entry exposes a selection checkbox; the ineligible one doesn't.
    expect(screen.queryByLabelText("Select Mystery")).not.toBeInTheDocument();
  });

  it("re-fetches via overrides endpoint when a resolution is entered", async () => {
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    fireEvent.click(await screen.findByText("Mystery"));
    fireEvent.change(await screen.findByLabelText("character for Mystery"), {
      target: { value: "Harley" },
    });
    await waitFor(() =>
      expect(reorg.previewWithOverrides).toHaveBeenCalledWith(
        expect.objectContaining({ overrides: { 2: { character: "Harley" } } }),
      ),
    );
  });
});
