import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GuideReader from "./GuideReader";
import { Guide } from "../../api/client";

function mkSwatch(over = {}) {
  return {
    id: 1, paint_id: 10, value_pct: 10, role_label: "shadow base", sort_order: 0,
    paint: { name: "Coal Black", code: "002", brand: "Monument Hobbies", hex: "#2A2A2A" },
    ...over,
  };
}

const GUIDE: Guide = {
  id: 1, slug: "robocop-1987", title: "RoboCop 1987", title_lead: "RoboCop",
  subtitle: "1:6 · Action", category_id: null, category_label: "Film & TV",
  series_id: null, model_id: null, scale: "1:6", status: "published",
  franchise: "RoboCop", quote: "Dead or alive, you're coming with me.",
  creator_credit: { name: "Acme Studio", url: "https://example.com", link_text: "@acme" },
  light_source: null, philosophy_note: null,
  paint_lines_used: [{ name: "Pro Acryl", color: "#c0a060" }, { name: "Citadel", color: null }],
  technique_tags: ["TMM"],
  character_brief: { philosophy: "Value <strong>first</strong>." },
  theme: { accent: "#c0a060", hero_gradient: "linear-gradient(135deg,#222,#111)" },
  head_style: ":root { --accent: #ff0000; }",
  thinning_config: {
    airbrush_rows: [{ technique: "Base coat", nozzle: "0.3mm", ratio: "1:2", behavior: "smooth" }],
    brush_rows: [{ technique: "Edge highlight", ratio: "1:1", behavior: "crisp" }],
    thinning_cards: [{ title: "Custom Card", body: "guide-specific note" }],
  },
  tabs: [
    {
      id: 1, name: "Metals", dom_id: null, sort_order: 0, has_expert_subtab: false,
      section: { heading: "True Metallics", intro: "Gloss black <em>first</em>." },
      value_map: { label: "Value Zones", chips: [
        { hex: "#101010", value_pct: 10, zone_label: "deep shadow" },
      ] },
      subtabs: [], method_block: null,
      phases: [
        {
          id: 11, label: "Base", subtab_key: null, sort_order: 0,
          steps: [
            {
              id: 111, title: "Gloss black base", technique_tag: "airbrush",
              technique_label: null, body: "Lay it <strong>down</strong>.", value_intent: null,
              tip: "Thin to milk.", warning: null, ratio_box: "1:1 paint:thinner", sort_order: 0,
              swatches: [mkSwatch()], mix_components: [],
            },
          ],
        },
      ],
    },
    {
      id: 2, name: "Skin", dom_id: "skin", sort_order: 1, has_expert_subtab: true,
      section: null, value_map: null, method_block: null,
      subtabs: [
        { key: "pa", label: "Pro Acryl", css_class: null, sort_order: 0 },
        { key: "ex", label: "Expert", css_class: "expert-tab", sort_order: 1 },
      ],
      phases: [
        { id: 21, label: "PA Base", subtab_key: "pa", sort_order: 0, steps: [
          { id: 211, title: "PA midtone", technique_tag: "brush", technique_label: null,
            body: null, value_intent: null, tip: null, warning: null, ratio_box: null,
            sort_order: 0, swatches: [], mix_components: [] },
        ] },
        { id: 22, label: "Expert Base", subtab_key: "ex", sort_order: 1, steps: [
          { id: 221, title: "Expert midtone", technique_tag: "brush", technique_label: null,
            body: null, value_intent: null, tip: null, warning: null, ratio_box: null,
            sort_order: 0, swatches: [], mix_components: [] },
        ] },
      ],
    },
  ],
  created_at: null, updated_at: null, published_at: null,
};

const panel = (container: HTMLElement, id: string) =>
  container.querySelector(`#${id}`) as HTMLElement;

describe("GuideReader", () => {
  it("renders the hero with accent lead span, subtitle, quote, and creator credit", () => {
    render(<GuideReader guide={GUIDE} />);
    const h1 = screen.getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("RoboCop 1987");
    expect(h1.querySelector("span")?.textContent).toBe("RoboCop"); // accent lead
    expect(screen.getByText("Film & TV")).toBeInTheDocument();
    expect(screen.getByText(/Dead or alive/)).toBeInTheDocument();
    const credit = screen.getByRole("link", { name: "@acme" });
    expect(credit).toHaveAttribute("href", "https://example.com");
  });

  it("renders the paint bar pills and the character brief HTML", () => {
    const { container } = render(<GuideReader guide={GUIDE} />);
    const bar = container.querySelector(".paint-bar") as HTMLElement;
    expect(within(bar).getByText("Paint Lines Used")).toBeInTheDocument();
    expect(within(bar).getByText("Pro Acryl")).toBeInTheDocument();  // also a sub-tab label elsewhere
    expect(within(bar).getByText("Citadel")).toBeInTheDocument();
    const brief = container.querySelector(".char-brief");
    expect(brief?.innerHTML).toContain("<strong>first</strong>");
  });

  it("lists authored tabs plus the three shared skills tabs", () => {
    render(<GuideReader guide={GUIDE} />);
    for (const name of ["Metals", "Skin", "Airbrush Skills", "Brush Skills", "Thinning Ref"]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
  });

  it("renders a step with technique-derived number, swatch, ratio box, and tip", () => {
    const { container } = render(<GuideReader guide={GUIDE} />);
    const metals = panel(container, "metals");
    expect(within(metals).getByText("Step 1 · Airbrush")).toBeInTheDocument();
    expect(within(metals).getByText("Coal Black 002")).toBeInTheDocument();
    expect(within(metals).getByText("Monument Hobbies")).toBeInTheDocument();
    expect(within(metals).getByText("~10% value — shadow base")).toBeInTheDocument();
    expect(within(metals).getByText("1:1 paint:thinner")).toBeInTheDocument();
    // value map chip
    expect(within(metals).getByText("deep shadow")).toBeInTheDocument();
    expect(within(metals).getByText("~10%")).toBeInTheDocument();
  });

  it("defaults to the first tab active and switches on click", async () => {
    const { container } = render(<GuideReader guide={GUIDE} />);
    expect(panel(container, "metals")).toHaveClass("active");
    expect(panel(container, "skin")).not.toHaveClass("active");

    await userEvent.click(screen.getByRole("tab", { name: "Skin" }));
    expect(panel(container, "skin")).toHaveClass("active");
    expect(panel(container, "metals")).not.toHaveClass("active");
  });

  it("switches sub-tabs within a tab", async () => {
    const { container } = render(<GuideReader guide={GUIDE} />);
    const skin = panel(container, "skin");
    const subContents = skin.querySelectorAll(".sub-content");
    expect(subContents[0]).toHaveClass("active");   // Pro Acryl default
    expect(subContents[1]).not.toHaveClass("active");

    await userEvent.click(within(skin).getByText("Expert"));
    expect(skin.querySelectorAll(".sub-content")[1]).toHaveClass("active");
    expect(skin.querySelectorAll(".sub-content")[0]).not.toHaveClass("active");
  });

  it("builds the Thinning Reference from static + per-guide config", () => {
    const { container } = render(<GuideReader guide={GUIDE} />);
    const thin = panel(container, "thinning-ref");
    expect(within(thin).getByText("Thinning Reference")).toBeInTheDocument();
    expect(within(thin).getByText("Priming")).toBeInTheDocument();          // static leading
    expect(within(thin).getByText("Edge highlight")).toBeInTheDocument();   // per-guide brush row
    expect(within(thin).getByText("Custom Card")).toBeInTheDocument();      // per-guide card
    expect(within(thin).getByText("Flow Improver")).toBeInTheDocument();    // static card
  });

  it("scopes the per-guide head_style to .guide-reader", () => {
    const { container } = render(<GuideReader guide={GUIDE} />);
    const style = container.querySelector("style");
    expect(style?.innerHTML).toContain(".guide-reader { --accent: #ff0000; }");
    expect(style?.innerHTML).not.toContain(":root");
  });
});
