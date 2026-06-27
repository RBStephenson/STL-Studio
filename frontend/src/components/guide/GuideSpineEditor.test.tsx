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
    expect(step.swatches).toEqual([{ paint_id: 7, name: null, value_pct: 50, role_label: "base", sort_order: 0 }]);
  });

  it("preserves a name-only swatch through edit + save (#477)", async () => {
    const onSave = vi.fn();
    const tab = oneTab();
    // An unresolved (name-only) swatch from import — no shelf paint.
    (tab as unknown as { phases: { steps: { swatches: unknown[] }[] }[] })
      .phases[0].steps[0].swatches.push(
        { id: 2, paint_id: null, name: "Nonexistent NX1", value_pct: 30, role_label: null, sort_order: 1, paint: null },
      );
    render(<GuideSpineEditor initialTabs={[tab]} onSave={onSave} onCancel={vi.fn()} />);

    expect(screen.getByText(/Nonexistent NX1/)).toBeInTheDocument(); // shown read-only
    await userEvent.click(screen.getByRole("button", { name: "Save content" }));

    const swatches = onSave.mock.calls[0][0][0].phases[0].steps[0].swatches;
    expect(swatches).toContainEqual(
      { paint_id: null, name: "Nonexistent NX1", value_pct: 30, role_label: null, sort_order: 1 },
    );
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

  it("emits a live preview projection on mount and on edit (#488)", async () => {
    const onPreviewChange = vi.fn();
    render(
      <GuideSpineEditor
        initialTabs={[oneTab()]} onSave={vi.fn()} onCancel={vi.fn()}
        onPreviewChange={onPreviewChange}
      />,
    );

    // Mount: the draft is projected to the read-shape GuideReader consumes,
    // with the picked paint's display fields carried through.
    expect(onPreviewChange).toHaveBeenCalled();
    const last = () => onPreviewChange.mock.calls[onPreviewChange.mock.calls.length - 1][0];
    let preview = last();
    expect(preview[0]).toMatchObject({ name: "Skin", section: { heading: "Flesh tones" } });
    const sw = preview[0].phases[0].steps[0].swatches[0];
    expect(sw).toMatchObject({ paint_id: 7, paint: { name: "Cadmium", code: "MPA-001", hex: "#fff" } });

    // Edit: the projection re-fires and reflects the change live.
    await userEvent.type(screen.getByDisplayValue("Basecoat"), "X");
    preview = last();
    expect(preview[0].phases[0].steps[0].title).toBe("BasecoatX");
  });

  it("renders drag handles at every level", async () => {
    const tab = oneTab();
    render(<GuideSpineEditor initialTabs={[tab]} onSave={vi.fn()} onCancel={vi.fn()} />);
    // Each level (tab, phase, step, swatch) gets a grip handle.
    const handles = screen.getAllByRole("button", { name: "Drag to reorder" });
    // 1 tab + 1 phase + 1 step + 1 swatch = 4
    expect(handles.length).toBeGreaterThanOrEqual(4);
  });

  it("up/down buttons still reorder steps after drag-reorder added (#503)", async () => {
    const onSave = vi.fn();
    const tab = oneTab();
    // Add a second step so reorder is meaningful.
    tab.phases[0].steps.push({
      id: 2, title: "Layer", technique_tag: "brush", technique_label: null, body: null,
      value_intent: null, tip: null, warning: null, ratio_box: null, sort_order: 1,
      swatches: [], mix_components: [],
    } as unknown as typeof tab.phases[0]["steps"][0]);
    render(<GuideSpineEditor initialTabs={[tab]} onSave={onSave} onCancel={vi.fn()} />);

    // Move "Layer" (index 1) up → should become index 0.
    const upButtons = screen.getAllByRole("button", { name: "Move up" });
    // Step-level move-up buttons: first step's is index 1 (tab+phase before it), second step's is index 2.
    // Click the Move up for "Layer" (the second step — last step-level up button at this point).
    const stepUpButtons = upButtons.filter((_, i) => i >= 1); // skip tab/phase up buttons
    await userEvent.click(stepUpButtons[stepUpButtons.length - 1]);

    await userEvent.click(screen.getByRole("button", { name: "Save content" }));
    const steps = onSave.mock.calls[0][0][0].phases[0].steps;
    expect(steps[0].title).toBe("Layer");
    expect(steps[1].title).toBe("Basecoat");
  });

  // --- Mix-component authoring (#504) --------------------------------------

  function mixTab(): GuideTab {
    const tab = oneTab();
    (tab as unknown as { phases: { steps: { mix_components: unknown[] }[] }[] })
      .phases[0].steps[0].mix_components = [
        { id: 1, paint_id: null, name: "Bold Red", parts: 4, sort_order: 0, paint: null },
        { id: 2, paint_id: null, name: "Orange", parts: 1, sort_order: 1, paint: null },
      ];
    return tab;
  }

  it("round-trips a mix swatch's components and ratio on save (#504)", async () => {
    const onSave = vi.fn();
    render(<GuideSpineEditor initialTabs={[mixTab()]} onSave={onSave} onCancel={vi.fn()} />);

    expect(screen.getByText(/Bold Red/)).toBeInTheDocument();
    expect(screen.getByText(/ratio 4:1/)).toBeInTheDocument(); // ≥2 components → ratio shown

    await userEvent.click(screen.getByRole("button", { name: "Save content" }));
    const step = onSave.mock.calls[0][0][0].phases[0].steps[0];
    expect(step.mix_components).toEqual([
      { paint_id: null, name: "Bold Red", parts: 4, sort_order: 0 },
      { paint_id: null, name: "Orange", parts: 1, sort_order: 1 },
    ]);
  });

  it("edits a mix component's parts (#504)", async () => {
    const onSave = vi.fn();
    render(<GuideSpineEditor initialTabs={[mixTab()]} onSave={onSave} onCancel={vi.fn()} />);

    const parts = screen.getAllByLabelText("Parts");
    await userEvent.clear(parts[0]);
    await userEvent.type(parts[0], "3");
    await userEvent.click(screen.getByRole("button", { name: "Save content" }));

    const mix = onSave.mock.calls[0][0][0].phases[0].steps[0].mix_components;
    expect(mix[0].parts).toBe(3);
  });

  it("drops an empty mix component from the saved payload (#504)", async () => {
    const onSave = vi.fn();
    render(<GuideSpineEditor initialTabs={[oneTab()]} onSave={onSave} onCancel={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /add mix component/i }));
    await userEvent.click(screen.getByRole("button", { name: "Save content" }));

    const step = onSave.mock.calls[0][0][0].phases[0].steps[0];
    expect(step.mix_components).toEqual([]); // paintless + nameless → dropped
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
