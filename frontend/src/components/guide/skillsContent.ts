/**
 * Shared, guide-independent reference content — the React port of
 * painting-guides/assets/skills-reference.js. In the static HTML these tables
 * and cards are injected at runtime; the reader renders them directly. The
 * per-guide rows/cards from `thinning_config` slot in around the static ones
 * (see ThinningReference). Keep in sync with skills-reference.js.
 */

export interface AirbrushRow {
  technique: string;
  nozzle: string;
  ratio: string;
  behavior: string;
}

export interface BrushRow {
  technique: string;
  ratio: string;
  behavior: string;
}

// Airbrush thinning rows that always precede the per-guide rows.
export const STATIC_AIRBRUSH_LEADING: AirbrushRow[] = [
  {
    technique: "Priming", nozzle: "0.5mm", ratio: "Undiluted — do not thin",
    behavior: "Full opaque coverage; flows freely at 30+ PSI without clogging.",
  },
  {
    technique: "Zenithal — black prime", nozzle: "0.5mm", ratio: "Undiluted (primer)",
    behavior: "Full coverage from all angles; black retained fully in recesses and undercuts.",
  },
  {
    technique: "Zenithal — white prime", nozzle: "0.5mm", ratio: "Undiluted (primer)",
    behavior: "Heavy from directly above; fades to nothing at sides.",
  },
];

// Airbrush thinning rows that always follow the per-guide rows.
export const STATIC_AIRBRUSH_TRAILING: AirbrushRow[] = [
  {
    technique: "Transparent / glaze layer", nozzle: "0.2mm", ratio: "1:6 to 1:10",
    behavior: "Near-watercolor; thin color-temperature shift over sealed surface.",
  },
  {
    technique: "Freckling", nozzle: "0.2mm", ratio: "1:8 to 1:12",
    behavior: "Atomizes to micro-dots at 3–5cm with needle almost closed. Practice on card first.",
  },
  {
    technique: "Speedpaint 2.0 — standard", nozzle: "0.3mm",
    ratio: "Undiluted or 1:1 with Speedpaint Medium",
    behavior: "One-pass product. Let flow and leave it — overworking activates self-leveling agent.",
  },
  {
    technique: "Speedpaint 2.0 — filter", nozzle: "0.3mm",
    ratio: "1:3 Speedpaint : Speedpaint Medium",
    behavior: "Over fully dried and varnished layer only. Wipe back lightly with damp flat brush for control.",
  },
];

// Brush thinning rows that always precede the per-guide rows.
export const STATIC_BRUSH_LEADING: BrushRow[] = [
  { technique: "Base coat", ratio: "2:1", behavior: "Full coverage in two passes; some brush drag acceptable." },
  { technique: "Layering", ratio: "1:1", behavior: "Semi-transparent; builds in thin passes without obscuring underlayer." },
  { technique: "Glazing", ratio: "1:4 to 1:8", behavior: "Highly transparent color shift; pools lightly in recesses." },
  { technique: "Wash / pin wash", ratio: "1:6 to 1:10", behavior: "Flows into recesses via capillary action; do not brush around once placed." },
  { technique: "Wet blending", ratio: "1:0.5 (minimal thinner)", behavior: "Re-wettable window; color pulled while wet using a clean damp brush." },
  { technique: "Expert Acrylics — glaze", ratio: "1:3 to 1:5", behavior: "Heavy pigment; needs more thinner than standard acrylics. Test on card first." },
  { technique: "Expert Acrylics — drybrush", ratio: "Near-undiluted", behavior: "Heavy-body holds on nearly dry brush; wipe to almost-dry before loading." },
];

export interface ThinningCardContent {
  title: string;
  body: string; // inline HTML
}

// Thinning cards that always precede the per-guide cards.
export const STATIC_THINNING_CARDS: ThinningCardContent[] = [
  {
    title: "Flow Improver",
    body:
      "Add 5–10% flow improver to airbrush mixes to reduce surface tension and prevent tip dry." +
      " Do not exceed 15% — reduces adhesion on varnished surfaces.",
  },
  {
    title: "Speedpaint 2.0 — Key Rules",
    body:
      "Always thin Speedpaint 2.0 with <strong>Speedpaint Medium</strong>, not water." +
      " As a filter, apply 1:3 Speedpaint:Speedpaint Medium over a sealed (varnished) surface only" +
      " — never over bare or unsealed acrylics.",
  },
  {
    title: "Transparent Red ⚠",
    body:
      "Pro Acryl Transparent Red 047 turns <strong>magenta</strong> when thinned." +
      " For any thinned or glazed transparent red application (glazes, color filters, washes)," +
      " use <strong>FW Crimson Ink</strong> instead." +
      " PA Transparent Red 047 is fine undiluted or minimally thinned where full body is maintained.",
  },
];

// Nozzle callout body (inline HTML) shown at the top of the Thinning Reference.
export const NOZZLE_CALLOUT_HTML =
  "<strong>0.5mm nozzle → 50% paint</strong> (1:1 paint:thinner) &nbsp;·&nbsp; " +
  "<strong>0.3mm nozzle → 30% paint</strong> (~1:2.3 paint:thinner) &nbsp;·&nbsp; " +
  "<strong>0.2mm nozzle → 20% paint</strong> (1:4 paint:thinner)" +
  "<br>Starting points only. Adjust for pigment density and humidity." +
  " Flow test on a card before each session." +
  "<br><strong>Primer exception: Do NOT thin primer.</strong>" +
  " Use undiluted at 30+ PSI, 0.5mm nozzle.";

// Greyscale-check callout (inline HTML), shared by both skills tabs.
export const GREYSCALE_AIRBRUSH_HTML =
  "<strong>✦ GREYSCALE CHECK:</strong>" +
  " After zenithal and before any color, photograph the figure and desaturate." +
  " Confirm a full value range from near-black in recesses to near-white on top planes." +
  " If you don’t have value contrast in greyscale, color won’t save it.";

export const GREYSCALE_BRUSH_HTML =
  "<strong>✦ GREYSCALE CHECK:</strong>" +
  " At any point during painting, desaturate a photo of the figure in your phone’s editor." +
  " It should read clearly in greyscale — visible light source, form, and depth." +
  " If it looks flat, values are too compressed. Fix values before correcting color.";

export interface ZenithalStep {
  number: string;  // ".step-number airbrush" text
  title: string;
  body: string;    // inline HTML
  tip?: string;    // inline HTML
  warning?: string; // inline HTML
}

// The static zenithal sequence injected into the Airbrush Skills tab.
export const ZENITHAL_STEPS: ZenithalStep[] = [
  {
    number: "Airbrush · Zenithal Step 1",
    title: "Black Prime",
    body:
      "P-002 Black Primer — undiluted, 0.5mm nozzle, 30+ PSI, 20–25cm." +
      " Full coverage from all angles. No bare surface showing.",
    warning:
      "<strong>⚠ NOTE:</strong> Do NOT thin primer." +
      " Thinning breaks down its purpose and turns it into paint." +
      " Use undiluted at 30+ PSI with a 0.5mm nozzle.",
  },
  {
    number: "Airbrush · Zenithal Step 2",
    title: "White Zenithal — Top Down",
    body:
      "P-003 White Primer — undiluted, 0.5mm nozzle, 30+ PSI, 20–25cm." +
      " Heavy from directly above, fading to nothing at the sides." +
      " Black retained fully in recesses and undercuts.",
    tip:
      "<strong>✦ TIP:</strong>" +
      " Photograph and desaturate immediately after this step." +
      " Confirm full value range before adding any color.",
  },
];

// Tip Dry trouble card prepended to the Airbrush Skills trouble grid.
export const TIP_DRY_CARD: ThinningCardContent = {
  title: "Tip Dry / Spattering",
  body:
    "Paint dries on needle tip causing spits and spatters." +
    " Cause: paint too thick, low humidity, or pausing too long between passes." +
    " Fix: add 5–10% flow improver." +
    " Between passes, remove dried paint from the needle tip using a dry brush lightly dipped" +
    " in airbrush cleaner or thinner — gentle strokes," +
    " do not let the ferrule enter the airbrush cap.",
};
