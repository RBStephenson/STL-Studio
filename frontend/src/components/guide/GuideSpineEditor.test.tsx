import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GuideSpineEditor from "./GuideSpineEditor";
import { GuideTab } from "../../api/client";

vi.mock("../../api/client", async (importOriginal) => {
  const orig = await importOriginal<typeof import("../../api/client")>();
  return { ...orig, api: { painting: { paints: { list: vi.fn().mockResolvedValue({ items: [] }) } } } };
});

function oneTab(): GuideTab {
  return {
    id: 1, name: "Skin", dom_id: null, sort_order: 0, has_expert_subtab: false,
    section: { heading: "Flesh tones", intro: null }, value_map: null, subtabs: [], callouts: [], method_block: null,
    phases: [{
      id: 1, label: "Base", subtab_key: null, sort_order: 0,
      steps: [{
        id: 1, title: "Basecoat", technique_tag: "brush", technique_label: null, body: null,
        value_intent: null, tip: null, warning: null, ratio_box: null, sort_order: 0,
        swatches: [{ id: 1, paint_id: 7, value_pct: 50, role_label: "base", sort_order: 0, paint: { name: "Cadmium", code: "MPA-001", brand: "Pro Acryl", hex: "#fff" } }],
        mix_components: [],
      }],
    }],
  } as unknown as GuideTab;
}

describe("GuideSpineEditor", () => {
  beforeEach(() => vi.clearAllMocks());

  it("serializes the tree on save with sort_order and the existing swatch paint", async () => {
    const onSave = vi.fn();
    render(<GuideSpineEditor initialTabs={[oneTab()]} onSave={onSave} onCancel={vi.fn()} />);

    expect(screen.getByDisplayValue("Skin")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Basecoat")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Save content" }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const tabs = onSave.mock.calls[0][0];
    expect(tabs[0]).toMatchObject({ name: "Skin", sort_order: 0, section: { heading: "Flesh tones", intro: null } });
    const step = tabs[0].phases[0].steps[0];
    expect(step).toMatchObject({ title: "Basecoat", technique_tag: "brush", sort_order: 0 });
    expect(step.swatches).toEqual([{ paint_id: 7, value_pct: 50, role_label: "base", sort_order: 0 }]);
  });

  it("blocks save when a step has no title", async () => {
    const onSave = vi.fn();
    render(<GuideSpineEditor initialTabs={[oneTab()]} onSave={onSave} onCancel={vi.fn()} />);

    await userEvent.clear(screen.getByDisplayValue("Basecoat"));
    await userEvent.click(screen.getByRole("button", { name: "Save content" }));

    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/step needs a title/i);
  });

  it("drops a paintless swatch from the saved payload", async () => {
    const onSave = vi.fn();
    render(<GuideSpineEditor initialTabs={[oneTab()]} onSave={onSave} onCancel={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /add swatch/i }));
    await userEvent.click(screen.getByRole("button", { name: "Save content" }));

    const step = onSave.mock.calls[0][0][0].phases[0].steps[0];
    expect(step.swatches).toHaveLength(1); // the new paintless one is dropped
  });

  it("adds a new tab", async () => {
    const onSave = vi.fn();
    render(<GuideSpineEditor initialTabs={[oneTab()]} onSave={onSave} onCancel={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /add tab/i }));
    const names = screen.getAllByPlaceholderText("Tab name *");
    expect(names).toHaveLength(2);

    // New tab has no name → save is blocked.
    await userEvent.click(screen.getByRole("button", { name: "Save content" }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/tab needs a name/i);
    // sanity: the first tab still shows its step
    expect(screen.getByDisplayValue("Basecoat")).toBeInTheDocument();
  });
});
