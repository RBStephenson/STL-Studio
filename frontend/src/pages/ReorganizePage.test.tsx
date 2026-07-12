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

/** Scanning is explicit now (STUDIO-155) — every test that needs a preview
 *  loaded has to click Build first, since the page no longer auto-scans on mount. */
function buildPlan() {
  fireEvent.click(screen.getByRole("button", { name: /Build Reorganize Plan/ }));
}

describe("ReorganizePage", () => {
  it("selects an eligible entry and applies it", async () => {
    reorg.apply.mockResolvedValue({
      manifest_id: "deadbeef", moved_files: 3, moved_models: 1, undo_log: "/x.log",
    });
    render(<ReorganizePage />);
    buildPlan();

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
    buildPlan();
    // Blocked-and-resolvable rows auto-expand (STUDIO-170) — no click needed.
    expect(await screen.findByLabelText("character for Mystery")).toBeInTheDocument();
    expect(await screen.findByLabelText("scale for Mystery")).toBeInTheDocument();
    // The eligible entry exposes a selection checkbox; the ineligible one doesn't.
    expect(screen.queryByLabelText("Select Mystery")).not.toBeInTheDocument();
  });

  it("auto-expands a blocked, resolvable row on first load", async () => {
    render(<ReorganizePage />);
    buildPlan();
    expect(await screen.findByLabelText("character for Mystery")).toBeInTheDocument();
    // No "click to resolve" cue while already expanded.
    expect(screen.queryByText("click to resolve")).not.toBeInTheDocument();
  });

  it("shows a resolve cue on a blocked row collapsed by the user", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByLabelText("character for Mystery");
    // Collapse the auto-expanded row.
    fireEvent.click(screen.getByText("Mystery"));
    expect(await screen.findByText("click to resolve")).toBeInTheDocument();
    expect(screen.queryByLabelText("character for Mystery")).not.toBeInTheDocument();
  });

  it("re-fetches via overrides endpoint when a resolution is entered", async () => {
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    buildPlan();
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

describe("ReorganizePage Moves tab bucketing (STUDIO-164)", () => {
  it("excludes a blocked move-kind entry from the Moves tab", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    // Mystery is kind "move" but eligible: false (unclassifiable) — it
    // should show under All but not under Moves until it's resolved.
    expect(screen.getByText("Mystery")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Moves" }));

    expect(screen.getByText("Joker Bust")).toBeInTheDocument();
    expect(screen.queryByText("Mystery")).not.toBeInTheDocument();
  });

  it("shows an explanatory hint on each filter tab", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    expect(screen.getByRole("button", { name: "Moves" })).toHaveAttribute(
      "title",
      expect.stringContaining("blocked movers show under"),
    );
  });
});

describe("ReorganizePage loading indicator (STUDIO-165)", () => {
  it("shows a prominent spinner before the first preview resolves", async () => {
    let resolvePreview: (v: unknown) => void;
    reorg.preview.mockReturnValue(new Promise((resolve) => { resolvePreview = resolve; }));

    render(<ReorganizePage />);
    buildPlan();

    expect(await screen.findByText(/Building reorganize plan/i)).toBeInTheDocument();

    resolvePreview!(previewFixture());
    await waitFor(() => expect(screen.queryByText(/Building reorganize plan/i)).not.toBeInTheDocument());
  });

  it("shows an inline updating indicator on a re-fetch, keeping the stale preview visible", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    let resolveOverride: (v: unknown) => void;
    reorg.previewWithOverrides.mockReturnValue(
      new Promise((resolve) => { resolveOverride = resolve; }),
    );
    fireEvent.change(await screen.findByLabelText("character for Mystery"), {
      target: { value: "Harley" },
    });

    expect(await screen.findByText(/Updating preview/i)).toBeInTheDocument();
    // The stale table stays visible while the re-fetch is in flight.
    expect(screen.getByText("Joker Bust")).toBeInTheDocument();

    resolveOverride!(previewFixture());
    await waitFor(() => expect(screen.queryByText(/Updating preview/i)).not.toBeInTheDocument());
  });
});

describe("ReorganizePage explicit-trigger states (STUDIO-155)", () => {
  it("shows the idle empty state on mount without scanning", () => {
    render(<ReorganizePage />);
    expect(screen.getByText("No plan yet")).toBeInTheDocument();
    expect(reorg.preview).not.toHaveBeenCalled();
  });

  it("builds the plan only after clicking Build Reorganize Plan", async () => {
    render(<ReorganizePage />);
    expect(reorg.preview).not.toHaveBeenCalled();
    buildPlan();
    expect(await screen.findByText("Joker Bust")).toBeInTheDocument();
    expect(reorg.preview).toHaveBeenCalledTimes(1);
  });

  it("shows an error panel with Retry when the initial build fails", async () => {
    reorg.preview.mockReset();
    reorg.preview.mockRejectedValueOnce(new Error("boom"));
    render(<ReorganizePage />);
    buildPlan();

    expect(await screen.findByText("Couldn't build the plan")).toBeInTheDocument();

    reorg.preview.mockResolvedValueOnce(previewFixture());
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    expect(await screen.findByText("Joker Bust")).toBeInTheDocument();
  });

  it("returns to the idle empty state after Cancel, not a blank panel", async () => {
    let resolvePreview: (v: unknown) => void;
    reorg.preview.mockReturnValue(new Promise((resolve) => { resolvePreview = resolve; }));
    render(<ReorganizePage />);
    buildPlan();

    fireEvent.click(await screen.findByRole("button", { name: /Cancel/ }));

    expect(screen.getByText("No plan yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Build Reorganize Plan/ })).toBeInTheDocument();

    // The abandoned request resolving late shouldn't resurrect the scanning UI.
    resolvePreview!(previewFixture());
    await Promise.resolve();
    expect(screen.getByText("No plan yet")).toBeInTheDocument();
  });

  it("re-runs the preview via Rebuild Plan once content is showing", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    expect(reorg.preview).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /Rebuild Plan/ }));
    await waitFor(() => expect(reorg.preview).toHaveBeenCalledTimes(2));
  });
});

describe("ReorganizePage select all eligible (STUDIO-160)", () => {
  function twoEligiblePreview() {
    return {
      manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
      generated_at: "now",
      entries: [
        entry({ model_id: 1, model_name: "Joker Bust", eligible: true }),
        entry({ model_id: 3, model_name: "Batman Bust", eligible: true }),
        entry({
          model_id: 2, model_name: "Mystery", eligible: false,
          unclassifiable: true, missing_fields: ["character"],
          proposed_dir: "/lib/Abe3D/_Unknown Character/Mystery",
        }),
      ],
      stats: STATS,
    };
  }

  it("selects every eligible row in the current tab, then deselects", async () => {
    reorg.preview.mockResolvedValue(twoEligiblePreview());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    const selectAll = screen.getByRole("checkbox", { name: /Select all eligible/ });
    fireEvent.click(selectAll);

    expect(screen.getByLabelText("Select Joker Bust")).toBeChecked();
    expect(screen.getByLabelText("Select Batman Bust")).toBeChecked();
    expect(screen.getByRole("button", { name: /Apply 2/ })).toBeEnabled();
    expect(screen.getByRole("checkbox", { name: /Deselect all eligible/ })).toBeChecked();

    fireEvent.click(screen.getByRole("checkbox", { name: /Deselect all eligible/ }));
    expect(screen.getByLabelText("Select Joker Bust")).not.toBeChecked();
    expect(screen.getByLabelText("Select Batman Bust")).not.toBeChecked();
  });

  it("only selects rows visible in the active filter tab", async () => {
    reorg.preview.mockResolvedValue(twoEligiblePreview());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    // Mystery is unclassifiable, not a move — Moves tab should only have
    // the two eligible move entries, and select-all should stay scoped to them.
    fireEvent.click(screen.getByRole("button", { name: "Moves" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Select all eligible/ }));

    expect(screen.getByLabelText("Select Joker Bust")).toBeChecked();
    expect(screen.getByLabelText("Select Batman Bust")).toBeChecked();
    expect(screen.getByRole("button", { name: /Apply 2/ })).toBeEnabled();
  });

  it("does not show a select-all control when nothing selectable is visible", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    fireEvent.click(screen.getByRole("button", { name: "Unclassifiable" }));
    expect(screen.queryByRole("checkbox", { name: /select all eligible/i })).not.toBeInTheDocument();
  });
});

describe("ReorganizePage resolvable vs unresolvable coloring (STUDIO-161)", () => {
  it("gives resolvable and unresolvable ineligible rows different colors", async () => {
    reorg.preview.mockResolvedValue({
      manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
      generated_at: "now",
      entries: [
        entry({ model_id: 1, model_name: "Joker Bust", eligible: true }),
        entry({
          model_id: 2, model_name: "Mystery", eligible: false,
          unclassifiable: true, missing_fields: ["character"],
        }),
        entry({
          model_id: 4, model_name: "Locked Model", eligible: false,
          locked: true,
        }),
      ],
      stats: STATS,
    });
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    const resolvableRow = screen.getByText("Mystery").closest("div.rounded.border") as HTMLElement;
    const unresolvableRow = screen.getByText("Locked Model").closest("div.rounded.border") as HTMLElement;

    expect(resolvableRow.className).toContain("border-amber-700/60");
    expect(unresolvableRow.className).toContain("border-rose-900/60");
    expect(resolvableRow.className).not.toContain("border-rose-900/60");
    expect(unresolvableRow.className).not.toContain("border-amber-700/60");
  });
});

describe("ReorganizePage error explanations (STUDIO-162)", () => {
  function blockedPreview() {
    return {
      manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
      generated_at: "now",
      entries: [
        entry({
          model_id: 2, model_name: "Mystery", eligible: false,
          unclassifiable: true, missing_fields: ["character"],
        }),
        entry({
          model_id: 4, model_name: "Locked Model", eligible: false,
          locked: true,
        }),
      ],
      stats: STATS,
    };
  }

  it("puts a specific explanation on the chip tooltip", async () => {
    reorg.preview.mockResolvedValue(blockedPreview());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");

    expect(screen.getByText("unclassifiable")).toHaveAttribute(
      "title",
      expect.stringContaining("Missing a value for: character"),
    );
    expect(screen.getByText("locked")).toHaveAttribute(
      "title",
      expect.stringContaining("locked and won't be touched"),
    );
  });

  it("lists a Why section with the explanation when the row is expanded", async () => {
    reorg.preview.mockResolvedValue(blockedPreview());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    // Blocked-resolvable rows auto-expand (STUDIO-170); Locked Model needs a click.
    fireEvent.click(screen.getByText("Locked Model"));

    expect(screen.getAllByText("Why")).toHaveLength(2);
    expect(screen.getByText(/Missing a value for: character/)).toBeInTheDocument();
    expect(screen.getByText(/locked and won't be touched by Reorganize/)).toBeInTheDocument();
  });
});
