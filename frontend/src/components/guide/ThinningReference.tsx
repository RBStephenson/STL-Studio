import { ThinningConfig } from "../../api/client";
import {
  NOZZLE_CALLOUT_HTML,
  STATIC_AIRBRUSH_LEADING, STATIC_AIRBRUSH_TRAILING,
  STATIC_BRUSH_LEADING, STATIC_THINNING_CARDS,
} from "./skillsContent";

/**
 * The Thinning Reference tab, built from the static reference content plus the
 * guide's `thinning_config` per-guide rows/cards (spec §9.3). Mirrors
 * skills-reference.js buildThinningRef(): per-guide airbrush rows slot between
 * the leading (priming/zenithal) and trailing (glaze/freckling/speedpaint)
 * static rows; per-guide brush rows append after the static ones; per-guide
 * cards append after the static cards.
 */
export default function ThinningReference({ config }: { config: ThinningConfig | null }) {
  const airRows = config?.airbrush_rows ?? [];
  const brushRows = config?.brush_rows ?? [];
  const extraCards = config?.thinning_cards ?? [];

  return (
    <>
      <div className="section-header">
        <h2>Thinning Reference</h2>
        <p>
          Ratios, flow behavior, and coverage tests for every technique in this guide.
          {" "}Ratios and observable behavior only.
        </p>
      </div>

      <div className="nozzle-callout">
        <h4>🎯 Nozzle Size = Paint Fraction</h4>
        <p dangerouslySetInnerHTML={{ __html: NOZZLE_CALLOUT_HTML }} />
      </div>

      <div className="phase-label">Airbrush Thinning</div>
      <table className="thin-table">
        <thead>
          <tr>
            <th>Technique</th><th>Nozzle</th>
            <th>Ratio (paint:thinner)</th><th>Behavior</th>
          </tr>
        </thead>
        <tbody>
          {STATIC_AIRBRUSH_LEADING.map((r, i) => (
            <tr key={`al${i}`}>
              <td>{r.technique}</td><td>{r.nozzle}</td><td>{r.ratio}</td><td>{r.behavior}</td>
            </tr>
          ))}
          {airRows.map((r, i) => (
            <tr key={`ag${i}`}>
              <td>{r.technique}</td><td>{r.nozzle ?? ""}</td><td>{r.ratio}</td><td>{r.behavior ?? ""}</td>
            </tr>
          ))}
          {STATIC_AIRBRUSH_TRAILING.map((r, i) => (
            <tr key={`at${i}`}>
              <td>{r.technique}</td><td>{r.nozzle}</td><td>{r.ratio}</td><td>{r.behavior}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="phase-label">Brush Thinning</div>
      <table className="thin-table">
        <thead>
          <tr><th>Technique</th><th>Ratio (paint:water)</th><th>Behavior</th></tr>
        </thead>
        <tbody>
          {STATIC_BRUSH_LEADING.map((r, i) => (
            <tr key={`bl${i}`}><td>{r.technique}</td><td>{r.ratio}</td><td>{r.behavior}</td></tr>
          ))}
          {brushRows.map((r, i) => (
            <tr key={`bg${i}`}><td>{r.technique}</td><td>{r.ratio}</td><td>{r.behavior ?? ""}</td></tr>
          ))}
        </tbody>
      </table>

      <div className="thinning-grid">
        {STATIC_THINNING_CARDS.map((c, i) => (
          <div className="thinning-card" key={`sc${i}`}>
            <h4>{c.title}</h4>
            <p dangerouslySetInnerHTML={{ __html: c.body }} />
          </div>
        ))}
        {extraCards.map((c, i) => (
          <div className="thinning-card" key={`gc${i}`}>
            <h4>{c.title}</h4>
            <p>{c.body}</p>
          </div>
        ))}
      </div>
    </>
  );
}
