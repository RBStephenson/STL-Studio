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
      scan: {
        roots: vi.fn(),
      },
      reorganize: {
        preview: vi.fn(),
        previewWithOverrides: vi.fn(),
        templatePreview: vi.fn(),
        apply: vi.fn(),
        undo: vi.fn(),
        aiSuggest: vi.fn(),
      },
    },
  };
});

let aiSuggestionsEnabled = false;
let packageModeEnabled = false;
let slugifyEnabled = true;
// The template field seeds from settings since STUDIO-406 — there is no
// frontend default any more — so this mock has to answer `loaded` and carry
// the server's default, not just the feature flags.
let settingsLoaded = true;
let savedTemplate = "";
let templateDefault = "{creator}/{character}/{title}";
vi.mock("../context/AppSettingsContext", () => ({
  useAppSettings: () => ({
    loaded: settingsLoaded,
    settings: {
      reorganize_ai_suggestions_enabled: aiSuggestionsEnabled,
      reorganize_package_mode_enabled: packageModeEnabled,
      reorganize_slugify: slugifyEnabled,
      reorganize_template: savedTemplate,
      reorganize_template_default: templateDefault,
    },
  }),
}));

import { api, ApiError } from "../api/client";
// Type-only import of the entry shape, so this survives the api/client mock above.
import { mkEntry, mkFileMove } from "../test/reorganize";

const reorg = api.reorganize as unknown as {
  preview: ReturnType<typeof vi.fn>;
  previewWithOverrides: ReturnType<typeof vi.fn>;
  templatePreview: ReturnType<typeof vi.fn>;
  apply: ReturnType<typeof vi.fn>;
  undo: ReturnType<typeof vi.fn>;
  aiSuggest: ReturnType<typeof vi.fn>;
};
const scan = api.scan as unknown as {
  roots: ReturnType<typeof vi.fn>;
};

const ROOTS = [
  {
    id: 7,
    path: "C:/STL Library",
    enabled: true,
    layout: "{creator}",
    last_scanned: null,
    name: "Main Library",
    is_writable: true,
    group_by_character: false,
  },
  {
    id: 9,
    path: "D:/Archive",
    enabled: false,
    layout: "{creator}",
    last_scanned: null,
    name: null,
    is_writable: false,
    group_by_character: false,
  },
];

const STATS = {
  total: 2, eligible: 1, moves_needed: 1, already_in_place: 0, collisions: 0,
  unclassifiable: 1, over_length: 0, reserved: 0, overlaps: 0, blocked: 1,
};

function previewFixture() {
  return {
    manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
    generated_at: "now",
    entries: [
      mkEntry({ model_id: 1, model_name: "Joker Bust", eligible: true }),
      mkEntry({
        model_id: 2, model_name: "Mystery", eligible: false,
        unclassifiable: true, missing_fields: ["character"],
        proposed_dir: "/lib/Abe3D/_Unknown Character/Mystery",
      }),
    ],
    stats: STATS,
  };
}

// The embedded TemplateEditor (STUDIO-402) calls the cheap template-preview
// endpoint whenever the field has content, which is every render of this page —
// so every test here needs it stubbed, not just the ones that assert on it.
function templatePreviewFixture(over: Record<string, unknown> = {}) {
  return {
    template: "{creator}/{character}/{title}",
    // Deliberately NOT one of the manifest fixture's model names — the live
    // example and the manifest table both render model names, so a shared name
    // makes every getByText in this file ambiguous.
    samples: [{
      model_id: 1, model_name: "Template Example Model",
      source_dir: "Abe3D/Example", proposed_dir: "Abe3D/Example/Template Example Model",
      unclassifiable: false, missing_fields: [], over_length: false, reserved_name: false,
    }],
    package_mode: false,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  aiSuggestionsEnabled = false;
  packageModeEnabled = false;
  slugifyEnabled = true;
  settingsLoaded = true;
  savedTemplate = "";
  templateDefault = "{creator}/{character}/{title}";
  scan.roots.mockReturnValue(new Promise(() => {}));
  reorg.preview.mockResolvedValue(previewFixture());
  reorg.templatePreview.mockResolvedValue(templatePreviewFixture());
});

/** Scanning is explicit now (STUDIO-155) — every test that needs a preview
 *  loaded has to click Build first, since the page no longer auto-scans on mount. */
function buildPlan() {
  fireEvent.click(screen.getByRole("button", { name: /Build Reorganize Plan/ }));
}

describe("ReorganizePage", () => {
  it("builds a plan for the selected scan root", async () => {
    scan.roots.mockResolvedValue(ROOTS);
    render(<ReorganizePage />);

    const rootSelect = await screen.findByRole("combobox", { name: "Scan root" });
    await waitFor(() => expect(rootSelect).toBeEnabled());
    expect(rootSelect).toHaveValue("");
    expect(screen.getByRole("option", { name: "Main Library (C:/STL Library)" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "D:/Archive (disabled)" })).toBeInTheDocument();

    fireEvent.change(rootSelect, { target: { value: "7" } });
    buildPlan();

    await waitFor(() =>
      expect(reorg.preview).toHaveBeenCalledWith("{creator}/{character}/{title}", 7),
    );
  });

  it("keeps all-roots preview available when scan roots fail to load", async () => {
    scan.roots.mockRejectedValue(new Error("offline"));
    render(<ReorganizePage />);

    expect(await screen.findByText(/Scan roots could not be loaded/)).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Scan root" })).toBeEnabled();
    buildPlan();

    await waitFor(() =>
      expect(reorg.preview).toHaveBeenCalledWith("{creator}/{character}/{title}", undefined),
    );
  });

  it("keeps the selected root when overrides rebuild the preview", async () => {
    scan.roots.mockResolvedValue(ROOTS);
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    fireEvent.change(await screen.findByRole("combobox", { name: "Scan root" }), {
      target: { value: "7" },
    });
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));
    fireEvent.change(await screen.findByLabelText("character for Mystery"), {
      target: { value: "Harley" },
    });

    await waitFor(() =>
      expect(reorg.previewWithOverrides).toHaveBeenCalledWith(expect.objectContaining({
        root_id: 7,
        overrides: { 2: { character: "Harley" } },
      })),
    );
  });

  it("clears stale plan state before rebuilding for another root", async () => {
    scan.roots.mockResolvedValue(ROOTS);
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    buildPlan();
    const checkbox = await screen.findByLabelText("Select Joker Bust");
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByText("Mystery"));
    fireEvent.change(await screen.findByLabelText("character for Mystery"), {
      target: { value: "Harley" },
    });
    await waitFor(() => expect(reorg.previewWithOverrides).toHaveBeenCalled());

    fireEvent.change(await screen.findByRole("combobox", { name: "Scan root" }), {
      target: { value: "7" },
    });

    expect(screen.queryByLabelText("Select Joker Bust")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(reorg.preview).toHaveBeenLastCalledWith("{creator}/{character}/{title}", 7),
    );
  });

  it("surfaces slugify and empty-source cleanup before building a plan", () => {
    render(<ReorganizePage />);

    expect(screen.getByText(/Directory slugify is on/)).toHaveTextContent(
      "destination folders are lowercased and hyphenated",
    );
    expect(screen.getByRole("link", { name: "Change in Settings" })).toHaveAttribute(
      "href",
      "/settings#library",
    );
    expect(screen.getByText(/source folders left empty by the selected moves are removed/))
      .toBeInTheDocument();
  });

  it("explains when directory slugify is off", () => {
    slugifyEnabled = false;
    render(<ReorganizePage />);

    expect(screen.getByText(/Directory slugify is off/)).toHaveTextContent(
      "destination folders keep their original casing and spacing",
    );
  });

  // Since STUDIO-402 this note comes from `package_mode` in the template-preview
  // RESPONSE rather than the local setting — the server is the authority on
  // whether the template is actually driving placement, and the note now says so.
  it("explains that package mode makes the destination template inert", async () => {
    reorg.templatePreview.mockResolvedValue(templatePreviewFixture({ package_mode: true }));
    render(<ReorganizePage />);
    expect(await screen.findByText(/Package preservation is on/)).toHaveTextContent(
      "this template does not decide placement",
    );
  });

  it("says nothing about package mode when the server reports it off", async () => {
    render(<ReorganizePage />);
    expect(await screen.findByText("Example destinations")).toBeInTheDocument();
    expect(screen.queryByText(/Package preservation is on/)).not.toBeInTheDocument();
  });

  it("scopes the live template example to the selected scan root", async () => {
    scan.roots.mockResolvedValue(ROOTS);
    render(<ReorganizePage />);

    const rootSelect = await screen.findByRole("combobox", { name: "Scan root" });
    await waitFor(() => expect(rootSelect).toBeEnabled());
    fireEvent.change(rootSelect, { target: { value: "7" } });

    await waitFor(() =>
      expect(reorg.templatePreview).toHaveBeenLastCalledWith("{creator}/{character}/{title}", 7),
    );
  });

  it("says the page's template is a one-off that is not saved", () => {
    render(<ReorganizePage />);
    expect(screen.getByText(/applies to/)).toHaveTextContent("this plan only");
  });

  it("shows shared character assets moving only for a complete package selection", async () => {
    const sharedFile = mkFileMove("/lib/Abe3D/Ada Wong/img/preview.jpg", {
      proposed_path: "/lib/abe3d/ada-wong/img/preview.jpg",
      size_bytes: 3,
      mtime_ns: 1,
      kind: "character_asset",
    });
    reorg.preview.mockResolvedValue({
      ...previewFixture(),
      entries: [
        mkEntry({
          model_id: 1, model_name: "Release One", character_package_ids: [1, 2],
          character_model_ids: [1, 2], shared_files: [sharedFile],
        }),
        mkEntry({ model_id: 2, model_name: "Release Two", character_package_ids: [1, 2] }),
      ],
      stats: { ...STATS, total: 2, eligible: 2, blocked: 0, unclassifiable: 0, moves_needed: 2 },
    });
    render(<ReorganizePage />);
    buildPlan();

    expect(await screen.findByText(/will remain unless all 2 packages are selected/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Select Release One"));
    expect(screen.getByText(/will remain unless all 2 packages are selected/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Select Release Two"));
    expect(screen.getByText(/will move with the complete character/)).toBeInTheDocument();
  });

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

  it("keeps the selected root after apply and undo refreshes", async () => {
    scan.roots.mockResolvedValue(ROOTS);
    reorg.apply.mockResolvedValue({
      manifest_id: "deadbeef", moved_files: 3, moved_models: 1, undo_log: "/x.log",
    });
    reorg.undo.mockResolvedValue({ reversed_files: 3, skipped: [] });
    render(<ReorganizePage />);
    const rootSelect = await screen.findByRole("combobox", { name: "Scan root" });
    await waitFor(() => expect(rootSelect).toBeEnabled());
    fireEvent.change(rootSelect, { target: { value: "7" } });
    buildPlan();

    fireEvent.click(await screen.findByLabelText("Select Joker Bust"));
    fireEvent.click(screen.getByRole("button", { name: /Apply 1/ }));

    await waitFor(() =>
      expect(reorg.preview).toHaveBeenLastCalledWith("{creator}/{character}/{title}", 7),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Undo last apply" }));

    await waitFor(() => expect(reorg.undo).toHaveBeenCalledWith("deadbeef"));
    await waitFor(() => {
      expect(reorg.preview).toHaveBeenCalledTimes(3);
      expect(reorg.preview).toHaveBeenLastCalledWith("{creator}/{character}/{title}", 7);
    });
  });

  it("shows resolve inputs on a blocked row, once expanded", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));
    expect(await screen.findByLabelText("character for Mystery")).toBeInTheDocument();
    expect(await screen.findByLabelText("scale for Mystery")).toBeInTheDocument();
    // Headed "Resolve" here, vs "Adjust" on an eligible row (STUDIO-400).
    expect(screen.getByText("Resolve")).toBeInTheDocument();
    // The eligible entry exposes a selection checkbox; the ineligible one doesn't.
    expect(screen.queryByLabelText("Select Mystery")).not.toBeInTheDocument();
  });

  it("explains an ambiguous package boundary", async () => {
    reorg.preview.mockResolvedValue({
      ...previewFixture(),
      entries: [mkEntry({ eligible: false, ambiguous_package: true })],
    });
    render(<ReorganizePage />);
    buildPlan();
    expect(await screen.findByText("package boundary")).toBeInTheDocument();
  });

  it("hides Suggest with AI when the flag is off", async () => {
    aiSuggestionsEnabled = false;
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));
    await screen.findByLabelText("character for Mystery");
    expect(screen.queryByRole("button", { name: /suggest with ai/i })).not.toBeInTheDocument();
  });

  it("prefills override fields from an AI suggestion", async () => {
    aiSuggestionsEnabled = true;
    reorg.aiSuggest.mockResolvedValue({
      llm_status: "ok",
      llm_detail: null,
      suggestions: [{ model_id: 2, creator: "Some Studio", character: "Mystery Head", title: "Mystery Head" }],
    });
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));
    await screen.findByLabelText("character for Mystery");

    fireEvent.click(screen.getByRole("button", { name: /suggest with ai/i }));

    await waitFor(() => expect(reorg.aiSuggest).toHaveBeenCalledWith("deadbeef", [2]));
    expect(await screen.findByLabelText("character for Mystery")).toHaveValue("Mystery Head");
    expect(screen.getByLabelText("creator for Mystery")).toHaveValue("Some Studio");
  });

  it("shows an error when the AI suggestion call fails", async () => {
    aiSuggestionsEnabled = true;
    reorg.aiSuggest.mockResolvedValue({ llm_status: "error", llm_detail: "Timed out", suggestions: [] });
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));
    await screen.findByLabelText("character for Mystery");

    fireEvent.click(screen.getByRole("button", { name: /suggest with ai/i }));

    expect(await screen.findByText("Timed out")).toBeInTheDocument();
  });

  it("starts every row collapsed on first load (STUDIO-183)", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    // Resolve fields aren't shown until the row is clicked open.
    expect(screen.queryByLabelText("character for Mystery")).not.toBeInTheDocument();
    // A blocked-resolvable row shows the resolve cue by default since it starts collapsed.
    expect(screen.getByText("click to resolve")).toBeInTheDocument();
  });

  it("expands a blocked row on click to reveal the resolve cue's fields", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));
    expect(await screen.findByLabelText("character for Mystery")).toBeInTheDocument();
    expect(screen.queryByText("click to resolve")).not.toBeInTheDocument();
  });

  it("re-fetches via overrides endpoint when a resolution is entered", async () => {
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));
    fireEvent.change(await screen.findByLabelText("character for Mystery"), {
      target: { value: "Harley" },
    });
    await waitFor(() =>
      expect(reorg.previewWithOverrides).toHaveBeenCalledWith(
        expect.objectContaining({ overrides: { 2: { character: "Harley" } } }),
      ),
    );
  });

  it("prefills a collision suffix from the source-folder suggestion", async () => {
    reorg.preview.mockResolvedValue({
      ...previewFixture(),
      entries: [mkEntry({
        model_id: 2,
        model_name: "Mystery",
        eligible: false,
        collision: true,
        collision_kind: "same_destination",
        collision_with: [1],
        suggested_suffix: "alternative",
      })],
    });
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    fireEvent.click(screen.getByText("Mystery"));

    fireEvent.click(await screen.findByRole("button", { name: /use suggested suffix: alternative/i }));

    expect(screen.getByLabelText("suffix for Mystery")).toHaveValue("alternative");
    await waitFor(() =>
      expect(reorg.previewWithOverrides).toHaveBeenCalledWith(
        expect.objectContaining({ overrides: { 2: { suffix: "alternative" } } }),
      ),
    );
  });
});

describe("ReorganizePage keeps a resolved row visible in its tab (STUDIO-182)", () => {
  it("stays on the Blocked tab and shows a checkbox after an override resolves it", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    fireEvent.click(screen.getByRole("button", { name: "Blocked" }));
    expect(screen.getByText("Mystery")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Mystery"));

    reorg.previewWithOverrides.mockResolvedValue({
      ...previewFixture(),
      entries: [
        mkEntry({ model_id: 1, model_name: "Joker Bust", eligible: true }),
        mkEntry({ model_id: 2, model_name: "Mystery", eligible: true }),
      ],
    });
    fireEvent.change(screen.getByLabelText("character for Mystery"), {
      target: { value: "Harley" },
    });

    await waitFor(() => expect(reorg.previewWithOverrides).toHaveBeenCalled());
    // Now eligible, so it no longer matches "Blocked" on its own — but the
    // active override should keep it visible with its checkbox selectable.
    expect(await screen.findByLabelText("Select Mystery")).toBeInTheDocument();
    expect(screen.getByText("Mystery")).toBeInTheDocument();
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
    fireEvent.click(screen.getByText("Mystery"));

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
        mkEntry({ model_id: 1, model_name: "Joker Bust", eligible: true }),
        mkEntry({ model_id: 3, model_name: "Batman Bust", eligible: true }),
        mkEntry({
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

describe("ReorganizePage creator filter (#1035)", () => {
  function multiCreatorPreview() {
    return {
      ...previewFixture(),
      entries: [
        mkEntry({ model_id: 1, model_name: "Joker Bust", creator_id: 1, creator_name: "Abe3D" }),
        mkEntry({ model_id: 3, model_name: "Ada Wong", creator_id: 2, creator_name: "CA3D" }),
      ],
      stats: { ...STATS, total: 2, eligible: 2, moves_needed: 2, blocked: 0, unclassifiable: 0 },
    };
  }

  it("filters rows and page-level select-all by creator", async () => {
    reorg.preview.mockResolvedValue(multiCreatorPreview());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    fireEvent.change(screen.getByLabelText("Filter by creator"), { target: { value: "id:2" } });

    expect(screen.queryByText("Joker Bust")).not.toBeInTheDocument();
    expect(screen.getByText("Ada Wong")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Select all eligible/ }));
    expect(screen.getByLabelText("Select Ada Wong")).toBeChecked();
    expect(screen.getByRole("button", { name: /Apply 1/ })).toBeEnabled();
  });

  it("preserves a valid creator filter on rebuild and clears it when stale", async () => {
    reorg.preview
      .mockResolvedValueOnce(multiCreatorPreview())
      .mockResolvedValueOnce(multiCreatorPreview())
      .mockResolvedValueOnce(previewFixture());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");

    const filter = screen.getByLabelText("Filter by creator");
    fireEvent.change(filter, { target: { value: "id:2" } });
    fireEvent.click(screen.getByRole("button", { name: /Rebuild Plan/ }));
    await waitFor(() => expect(reorg.preview).toHaveBeenCalledTimes(2));
    expect(filter).toHaveValue("id:2");

    fireEvent.click(screen.getByRole("button", { name: /Rebuild Plan/ }));
    await waitFor(() => expect(reorg.preview).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(filter).toHaveValue("all"));
  });
});

describe("ReorganizePage resolvable vs unresolvable coloring (STUDIO-161)", () => {
  it("gives resolvable and unresolvable ineligible rows different colors", async () => {
    reorg.preview.mockResolvedValue({
      manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
      generated_at: "now",
      entries: [
        mkEntry({ model_id: 1, model_name: "Joker Bust", eligible: true }),
        mkEntry({
          model_id: 2, model_name: "Mystery", eligible: false,
          unclassifiable: true, missing_fields: ["character"],
        }),
        mkEntry({
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

describe("ReorganizePage collision source context (#1026)", () => {
  it("shows source paths on collapsed collision rows without cluttering other rows", async () => {
    reorg.preview.mockResolvedValue({
      manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
      generated_at: "now",
      entries: [
        mkEntry({
          model_id: 1, model_name: "2B", source_path: "/library/Abe3D/2B/Alternative",
          eligible: false, collision: true, collision_kind: "same_destination", collision_with: [2],
        }),
        mkEntry({
          model_id: 2, model_name: "Joker Bust", source_path: "/library/Abe3D/Joker/Bust",
        }),
      ],
      stats: STATS,
    });

    render(<ReorganizePage />);
    buildPlan();

    expect(await screen.findByText("Source: /library/Abe3D/2B/Alternative")).toBeVisible();
    expect(screen.queryByText("Source: /library/Abe3D/Joker/Bust")).not.toBeInTheDocument();
  });
});

describe("ReorganizePage error explanations (STUDIO-162)", () => {
  function blockedPreview() {
    return {
      manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
      generated_at: "now",
      entries: [
        mkEntry({
          model_id: 2, model_name: "Mystery", eligible: false,
          unclassifiable: true, missing_fields: ["character"],
        }),
        mkEntry({
          model_id: 4, model_name: "Locked Model", eligible: false,
          locked: true,
        }),
        mkEntry({
          model_id: 5, model_name: "Split Model", eligible: false,
          spans_multiple_dirs: true,
          source_directories: ["/library/Abe3D/Joker", "/library/Abe3D/Joker/Alternative"],
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
    expect(screen.getByText("multi-dir")).toHaveAttribute(
      "title",
      expect.stringContaining("/library/Abe3D/Joker/Alternative"),
    );
  });

  it("lists a Why section with the explanation when the row is expanded", async () => {
    reorg.preview.mockResolvedValue(blockedPreview());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Mystery");
    // All rows start collapsed (STUDIO-183) — click both open.
    fireEvent.click(screen.getByText("Mystery"));
    fireEvent.click(screen.getByText("Locked Model"));
    fireEvent.click(screen.getByText("Split Model"));

    expect(screen.getAllByText("Why")).toHaveLength(3);
    expect(screen.getByText(/Missing a value for: character/)).toBeInTheDocument();
    expect(screen.getByText(/locked and won't be touched by Reorganize/)).toBeInTheDocument();
    expect(screen.getByText(/Source directories: \/library\/Abe3D\/Joker;/)).toBeInTheDocument();
  });
});

describe("ReorganizePage pagination (ADDENDUM §6)", () => {
  function manyEligiblePreview(count: number) {
    return {
      manifest_id: "deadbeef", template: "{creator}/{character}/{title}",
      generated_at: "now",
      entries: Array.from({ length: count }, (_, i) =>
        mkEntry({ model_id: i + 1, model_name: `Model ${i + 1}`, eligible: true })),
      stats: { ...STATS, total: count, eligible: count, moves_needed: count, blocked: 0, unclassifiable: 0 },
    };
  }

  it("shows only the first page (default 20) and a correct footer count", async () => {
    reorg.preview.mockResolvedValue(manyEligiblePreview(45));
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Model 1");

    expect(screen.getByText("Showing 1–20 of 45")).toBeInTheDocument();
    expect(screen.getByText("Model 20")).toBeInTheDocument();
    expect(screen.queryByText("Model 21")).not.toBeInTheDocument();
  });

  it("advances to the next page and shows the remainder", async () => {
    reorg.preview.mockResolvedValue(manyEligiblePreview(45));
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Model 1");

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(screen.getByText("Showing 21–40 of 45")).toBeInTheDocument();
    expect(screen.getByText("Model 21")).toBeInTheDocument();
    expect(screen.queryByText("Model 1")).not.toBeInTheDocument();
  });

  it("resets to page 1 when the page size changes", async () => {
    reorg.preview.mockResolvedValue(manyEligiblePreview(45));
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Model 1");

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Showing 21–40 of 45")).toBeInTheDocument();

    // 45 items at 50/page fits on one page — footer disappears, and page 1's
    // rows (including the earlier ones page 2 hid) are all visible again.
    fireEvent.click(screen.getByRole("button", { name: "50" }));
    expect(screen.queryByText(/^Showing/)).not.toBeInTheDocument();
    expect(screen.getByText("Model 1")).toBeInTheDocument();
    expect(screen.getByText("Model 45")).toBeInTheDocument();
  });

  it("resets to page 1 when switching filter tabs", async () => {
    reorg.preview.mockResolvedValue(manyEligiblePreview(45));
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Model 1");

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("Showing 21–40 of 45")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Already In Place" }));
    fireEvent.click(screen.getByRole("button", { name: "All" }));
    expect(screen.getByText("Showing 1–20 of 45")).toBeInTheDocument();
  });

  it("does not render a pagination footer when everything fits on one page", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^Showing/)).not.toBeInTheDocument();
  });
});

describe("ReorganizePage override on any row (STUDIO-400)", () => {
  it("opens the override fields on an eligible row, headed Adjust", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    fireEvent.click(screen.getByText("Joker Bust"));

    expect(await screen.findByLabelText("character for Joker Bust")).toBeInTheDocument();
    expect(screen.getByLabelText("creator for Joker Bust")).toBeInTheDocument();
    // A correctly-classified row is being adjusted, not repaired — the heading
    // distinguishes the two so the form doesn't read as "something is wrong".
    expect(screen.getByText("Adjust")).toBeInTheDocument();
  });

  it("re-previews with the override when an eligible row is edited", async () => {
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    fireEvent.click(screen.getByText("Joker Bust"));
    fireEvent.change(await screen.findByLabelText("character for Joker Bust"), {
      target: { value: "Harley" },
    });

    await waitFor(() =>
      expect(reorg.previewWithOverrides).toHaveBeenCalledWith(
        expect.objectContaining({ overrides: { 1: { character: "Harley" } } }),
      ),
    );
  });

  it("keeps an adjusted eligible row selectable", async () => {
    reorg.previewWithOverrides.mockResolvedValue(previewFixture());
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    fireEvent.click(screen.getByText("Joker Bust"));
    fireEvent.change(await screen.findByLabelText("character for Joker Bust"), {
      target: { value: "Harley" },
    });
    await waitFor(() => expect(reorg.previewWithOverrides).toHaveBeenCalled());

    expect(await screen.findByLabelText("Select Joker Bust")).toBeInTheDocument();
  });

  it("still hides Suggest with AI on an eligible row", async () => {
    // The endpoint only ever returns suggestions for unclassifiable/collision
    // entries (routers/reorganize.py), so offering the action on a row it will
    // silently skip would just round-trip to "No suggestion returned".
    aiSuggestionsEnabled = true;
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    fireEvent.click(screen.getByText("Joker Bust"));
    await screen.findByLabelText("character for Joker Bust");

    expect(screen.queryByRole("button", { name: /suggest with ai/i })).not.toBeInTheDocument();
  });

  it("shows no override fields on a blocked row no override can fix", async () => {
    // Locked ONLY — a row that is also unclassifiable stays resolvable and
    // keeps its form, so the fixture has to isolate the unresolvable blocker.
    reorg.preview.mockResolvedValue({
      ...previewFixture(),
      entries: [mkEntry({
        model_id: 4, model_name: "Locked Model", eligible: false, locked: true,
      })],
    });
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Locked Model");
    fireEvent.click(screen.getByText("Locked Model"));

    expect(await screen.findByText("Why")).toBeInTheDocument();
    expect(screen.queryByLabelText("character for Locked Model")).not.toBeInTheDocument();
  });
});

describe("ReorganizePage template hygiene (STUDIO-406)", () => {
  const templateField = () =>
    screen.getByRole("textbox", { name: /destination template/i });

  it("holds the template editor back until the settings have loaded", () => {
    // The template seeds from the server now, so rendering the editor early
    // would flash "the template is empty" over a library that has one.
    settingsLoaded = false;
    render(<ReorganizePage />);
    expect(screen.queryByRole("textbox", { name: /destination template/i })).toBeNull();
  });

  // Deliberately NOT the canonical template: a test using that string cannot
  // tell "seeded from settings" apart from "hard-coded in the frontend".
  it("seeds the field from the server's default, not a frontend literal", async () => {
    templateDefault = "{creator}/{scale}";
    render(<ReorganizePage />);
    expect(templateField()).toHaveValue("{creator}/{scale}");
    await waitFor(() =>
      expect(reorg.templatePreview).toHaveBeenLastCalledWith("{creator}/{scale}", undefined),
    );
  });

  it("prefers a saved template over the server default", async () => {
    savedTemplate = "{creator}/{title}";
    templateDefault = "{creator}/{scale}";
    render(<ReorganizePage />);
    expect(templateField()).toHaveValue("{creator}/{title}");
  });

  // The manifest preview stats every file on disk. Throwing it away because a
  // template was mid-edit cost minutes over a state that lasts one keypress.
  it("keeps the last good plan when a half-typed template returns 400", async () => {
    render(<ReorganizePage />);
    buildPlan();
    expect(await screen.findByText("Joker Bust")).toBeInTheDocument();

    reorg.preview.mockRejectedValue(new ApiError(400, "Unknown token: {char"));
    fireEvent.change(templateField(), { target: { value: "{creator}/{char" } });

    expect(await screen.findByText("Unknown token: {char")).toBeInTheDocument();
    // The plan is still on screen, and the "couldn't build" empty state never
    // replaced it.
    expect(screen.getByText("Joker Bust")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't build the plan")).toBeNull();
  });

  it("still recovers to a fresh plan once the template is valid again", async () => {
    render(<ReorganizePage />);
    buildPlan();
    expect(await screen.findByText("Joker Bust")).toBeInTheDocument();

    reorg.preview.mockRejectedValueOnce(new ApiError(400, "Unknown token: {char"));
    fireEvent.change(templateField(), { target: { value: "{creator}/{char" } });
    expect(await screen.findByText("Unknown token: {char")).toBeInTheDocument();

    fireEvent.change(templateField(), { target: { value: "{creator}/{title}" } });
    await waitFor(() =>
      expect(reorg.preview).toHaveBeenLastCalledWith("{creator}/{title}", undefined),
    );
    await waitFor(() =>
      expect(screen.queryByText("Unknown token: {char")).toBeNull(),
    );
  });
});

// The tree and the list are two shapes of one plan (STUDIO-404). What matters
// here is that they never disagree — same filters, same eligibility, one
// selection — so these assert across the boundary rather than inside the tree,
// which has its own suite in components/reorganize/DestinationTree.test.tsx.
describe("ReorganizePage destination tree (STUDIO-404)", () => {
  const showTree = () => fireEvent.click(screen.getByRole("button", { name: "Tree" }));
  const showList = () => fireEvent.click(screen.getByRole("button", { name: "List" }));

  it("swaps the row list for the proposed folder structure", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    // Pagination belongs to the list; the tree expands lazily instead.
    expect(screen.getByText("Per page")).toBeInTheDocument();

    showTree();
    expect(screen.getByText("/lib/Abe3D")).toBeInTheDocument();
    expect(screen.queryByText("Per page")).toBeNull();
  });

  it("counts the same models the list is showing", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    showTree();
    // Two entries in the fixture, one of them eligible — matching the list's
    // own "Select all eligible (1)".
    expect(screen.getByText(/2 models · 0 files · 1 eligible/)).toBeInTheDocument();
  });

  it("carries a selection made in the list through to the tree", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Joker Bust" }));

    showTree();
    expect(
      screen.getByRole("checkbox", { name: /Deselect 1 eligible model under \/lib\/Abe3D/ }),
    ).toBeChecked();
  });

  it("carries a selection made in the tree back to the list and to Apply", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    showTree();

    fireEvent.click(screen.getByRole("checkbox", { name: /Select 1 eligible model under \/lib\/Abe3D/ }));
    expect(screen.getByRole("button", { name: "Apply 1" })).toBeInTheDocument();

    showList();
    expect(screen.getByRole("checkbox", { name: "Select Joker Bust" })).toBeChecked();
  });

  it("unticking a folder gives the selection back", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    showTree();

    fireEvent.click(screen.getByRole("checkbox", { name: /Select 1 eligible model under \/lib\/Abe3D/ }));
    expect(screen.getByRole("button", { name: "Apply 1" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: /Deselect 1 eligible model under \/lib\/Abe3D/ }));
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled();
  });

  it("selects every eligible model under a folder and leaves the blocked ones alone", async () => {
    reorg.preview.mockResolvedValue({
      ...previewFixture(),
      entries: [
        mkEntry({ model_id: 1, model_name: "Joker Bust", proposed_dir: "/lib/Abe3D/Joker/Bust" }),
        mkEntry({ model_id: 2, model_name: "Joker Statue", proposed_dir: "/lib/Abe3D/Joker/Statue" }),
        mkEntry({
          model_id: 3, model_name: "Mystery", eligible: false, unclassifiable: true,
          proposed_dir: "/lib/Abe3D/Joker/Mystery",
        }),
      ],
    });
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    showTree();

    fireEvent.click(screen.getByRole("checkbox", { name: /Select 2 eligible models under \/lib\/Abe3D\/Joker/ }));
    // Two selected, and the blocked third never joined them.
    expect(screen.getByRole("button", { name: "Apply 2" })).toBeInTheDocument();
  });

  it("applies the creator filter to the tree, not just the list", async () => {
    reorg.preview.mockResolvedValue({
      ...previewFixture(),
      entries: [
        mkEntry({ model_id: 1, model_name: "Joker Bust", proposed_dir: "/lib/Abe3D/Joker/Bust" }),
        mkEntry({
          model_id: 2, model_name: "Riddler Bust", creator_id: 2, creator_name: "Bob3D",
          proposed_dir: "/lib/Bob3D/Riddler/Bust",
        }),
      ],
    });
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    showTree();
    // Matched on the title, which is always the full path — the visible label
    // changes as chains collapse, and dropping one creator changes what
    // collapses.
    expect(screen.getByTitle("/lib/Abe3D/Joker/Bust")).toBeInTheDocument();
    expect(screen.getByTitle("/lib/Bob3D/Riddler/Bust")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Filter by creator" }), {
      target: { value: "id:1" },
    });
    expect(screen.getByTitle("/lib/Abe3D/Joker/Bust")).toBeInTheDocument();
    expect(screen.queryByTitle("/lib/Bob3D/Riddler/Bust")).toBeNull();
  });

  it("applies the filter tabs to the tree as well", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    showTree();
    fireEvent.click(screen.getByRole("button", { name: "Unclassifiable" }));

    // Only the blocked entry survives the tab, so its branch is all that's left.
    expect(screen.getByText("/lib/Abe3D/_Unknown Character/Mystery")).toBeInTheDocument();
    expect(screen.queryByText("/lib/Abe3D/Joker/Bust")).toBeNull();
  });

  it("stays on the tree across a rebuild, unlike the tab and page", async () => {
    render(<ReorganizePage />);
    buildPlan();
    await screen.findByText("Joker Bust");
    showTree();

    fireEvent.click(screen.getByRole("button", { name: /Rebuild Plan/ }));
    await waitFor(() => expect(reorg.preview).toHaveBeenCalledTimes(2));
    expect(screen.getByText("/lib/Abe3D")).toBeInTheDocument();
  });
});
