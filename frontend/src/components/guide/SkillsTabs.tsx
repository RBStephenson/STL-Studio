import {
  GREYSCALE_AIRBRUSH_HTML, GREYSCALE_BRUSH_HTML, TIP_DRY_CARD, ZENITHAL_STEPS,
} from "./skillsContent";

/**
 * The shared Airbrush/Brush Skills tabs — the React port of the static content
 * skills-reference.js injects (zenithal sequence, greyscale checks, Tip Dry
 * card). Guide-independent; rendered as inner tab content by GuideReader.
 */

export function AirbrushSkills() {
  return (
    <>
      <div className="section-header">
        <h2>Airbrush Skills</h2>
        <p>Zenithal priming and value-first foundation. Confirm value range before any color.</p>
      </div>

      <div className="phase-label">Zenithal Sequence</div>
      {ZENITHAL_STEPS.map((s, i) => (
        <div className="step" key={i}>
          <span className="step-number airbrush">{s.number}</span>
          <h3>{s.title}</h3>
          <p dangerouslySetInnerHTML={{ __html: s.body }} />
          {s.tip && <div className="tip" dangerouslySetInnerHTML={{ __html: s.tip }} />}
          {s.warning && <div className="warning" dangerouslySetInnerHTML={{ __html: s.warning }} />}
        </div>
      ))}

      <div className="tip" dangerouslySetInnerHTML={{ __html: GREYSCALE_AIRBRUSH_HTML }} />

      <div className="phase-label">Troubleshooting</div>
      <div className="trouble-grid">
        <div className="trouble-card">
          <h4>{TIP_DRY_CARD.title}</h4>
          <p dangerouslySetInnerHTML={{ __html: TIP_DRY_CARD.body }} />
        </div>
      </div>
    </>
  );
}

export function BrushSkills() {
  return (
    <>
      <div className="section-header">
        <h2>Brush Skills</h2>
        <p>Layering, glazing, and value control by hand. Check values in greyscale as you go.</p>
      </div>
      <div className="tip" dangerouslySetInnerHTML={{ __html: GREYSCALE_BRUSH_HTML }} />
    </>
  );
}
