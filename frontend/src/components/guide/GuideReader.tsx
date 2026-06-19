import { useState, CSSProperties } from "react";
import {
  Guide, GuideTab, GuidePhase, GuideStep, GuideSwatch, GuideTheme, MethodBlock,
  TabCallout,
} from "../../api/client";
import ThinningReference from "./ThinningReference";
import { AirbrushSkills, BrushSkills } from "./SkillsTabs";
import "./guide-reader.css";
import "./guide-print.css"; // @media print: expands all tabs, applies print.css (#262)

// The three shared tabs (mirrors the static guides' skills-reference.js tabs).
const SKILLS_TABS = [
  { id: "airbrush-skills", label: "Airbrush Skills" },
  { id: "brush-skills", label: "Brush Skills" },
  { id: "thinning-ref", label: "Thinning Ref" },
];

function slugify(text: string): string {
  const out = Array.from(text.toLowerCase(), (c) => (/[a-z0-9]/.test(c) ? c : "-"))
    .join("")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return out || "tab";
}

const tabDomId = (tab: GuideTab): string => tab.dom_id || slugify(tab.name);

// theme JSON block -> inline CSS custom properties on the reader root.
function themeVars(theme: GuideTheme | null): CSSProperties {
  const v: Record<string, string> = {};
  const set = (key: string, val?: string | null) => { if (val) v[key] = val; };
  if (theme) {
    set("--bg", theme.bg);
    set("--surface", theme.surface);
    set("--surface2", theme.surface2);
    set("--surface3", theme.surface3);
    set("--border", theme.border);
    set("--text", theme.text);
    set("--text-muted", theme.text_muted);
    set("--text-dim", theme.text_dim);
    set("--accent", theme.accent);
    set("--hero-gradient", theme.hero_gradient);
  }
  return v as CSSProperties;
}

function swatchValue(sw: GuideSwatch): string {
  const bits: string[] = [];
  if (sw.value_pct != null) bits.push(`~${sw.value_pct}% value`);
  if (sw.role_label) bits.push(sw.role_label);
  return bits.join(" — ");
}

function SwatchRow({ swatch }: { swatch: GuideSwatch }) {
  const p = swatch.paint;
  if (!p) return null; // CRUD validates paint ids; defensive only
  const name = `${p.name} ${p.code}`.trim();
  const value = swatchValue(swatch);
  return (
    <div className="swatch">
      <div className="swatch-dot" style={p.hex ? { background: p.hex } : undefined} />
      <div className="swatch-info">
        <div className="swatch-name">{name}</div>
        <div className="swatch-brand">{p.brand}</div>
        {value && <div className="swatch-value">{value}</div>}
      </div>
    </div>
  );
}

function StepCard({ step, number }: { step: GuideStep; number: number }) {
  const tag = step.technique_tag || "";
  const label = step.technique_label || (tag ? tag.charAt(0).toUpperCase() + tag.slice(1) : "");
  const numberText = label ? `Step ${number} · ${label}` : `Step ${number}`;
  return (
    <div className="step">
      <span className={`step-number ${tag}`.trim()}>{numberText}</span>
      <h3>{step.title}</h3>
      {step.body && <p dangerouslySetInnerHTML={{ __html: step.body }} />}
      {step.swatches.length > 0 && (
        <div className="swatches">
          {step.swatches.map((s) => <SwatchRow key={s.id} swatch={s} />)}
        </div>
      )}
      {step.ratio_box && <div className="ratio-box">{step.ratio_box}</div>}
      {step.tip && <div className="tip" dangerouslySetInnerHTML={{ __html: step.tip }} />}
      {step.warning && <div className="warning" dangerouslySetInnerHTML={{ __html: step.warning }} />}
    </div>
  );
}

// Tab-level callouts (#271): intro 'text' nodes render a <p>; 'tip'/'warning'
// render the matching callout div. `kinds` filters so intros sit above the
// content and tip/warning below it, mirroring the static exporter.
function Callouts({ callouts, kinds }: { callouts: TabCallout[]; kinds: TabCallout["kind"][] }) {
  return (
    <>
      {callouts
        .filter((c) => kinds.includes(c.kind))
        .map((c, i) =>
          c.kind === "text" ? (
            <p key={i} dangerouslySetInnerHTML={{ __html: c.html }} />
          ) : (
            <div key={i} className={c.kind} dangerouslySetInnerHTML={{ __html: c.html }} />
          ),
        )}
    </>
  );
}

// A run of phases (one tab or sub-content); steps numbered continuously 1..N.
function Phases({ phases }: { phases: GuidePhase[] }) {
  let number = 0;
  return (
    <>
      {phases.map((phase) => (
        <div key={phase.id}>
          {phase.label && <div className="phase-label">{phase.label}</div>}
          {phase.steps.map((step) => {
            number += 1;
            return <StepCard key={step.id} step={step} number={number} />;
          })}
        </div>
      ))}
    </>
  );
}

function ValueMapBlock({ valueMap }: { valueMap: GuideTab["value_map"] }) {
  if (!valueMap || valueMap.chips.length === 0) return null;
  return (
    <>
      {valueMap.label && <div className="phase-label">{valueMap.label}</div>}
      <div className="value-map">
        {valueMap.chips.map((chip, i) => (
          <div className="value-chip" key={i}>
            <div className="chip-swatch" style={{ background: chip.hex }} />
            <div className="chip-val">~{chip.value_pct}%</div>
            <div className="chip-label">{chip.zone_label}</div>
          </div>
        ))}
      </div>
    </>
  );
}

function MethodBlockView({ method }: { method: MethodBlock }) {
  return (
    <>
      <div className="phase-label">Method Selection</div>
      {method.recommendation && (
        <div className="method-rec-block" dangerouslySetInnerHTML={{ __html: method.recommendation }} />
      )}
      {method.cards.length > 0 && (
        <div className="method-cards">
          {method.cards.map((card, i) => (
            <div className={card.recommended ? "method-card recommended" : "method-card"} key={i}>
              {card.badge && <span className="method-card-badge">{card.badge}</span>}
              <h4>{card.title}</h4>
              {card.body && <p dangerouslySetInnerHTML={{ __html: card.body }} />}
              {card.pros && <span className="mc-pros">{card.pros}</span>}
              {card.cons && <span className="mc-cons">{card.cons}</span>}
              {card.best && <span className="mc-best">{card.best}</span>}
            </div>
          ))}
        </div>
      )}
      {method.freckle_note && (
        <div className="freckle-note" dangerouslySetInnerHTML={{ __html: method.freckle_note }} />
      )}
    </>
  );
}

function TabPanel({
  tab, activeSub, onSelectSub,
}: {
  tab: GuideTab;
  activeSub: string | undefined;
  onSelectSub: (key: string) => void;
}) {
  const subtabs = tab.subtabs ?? [];
  const callouts = tab.callouts ?? [];
  return (
    <>
      {tab.section && (
        <div className="section-header">
          <h2>{tab.section.heading}</h2>
          {tab.section.intro && <p dangerouslySetInnerHTML={{ __html: tab.section.intro }} />}
        </div>
      )}
      <Callouts callouts={callouts} kinds={["text"]} />
      <ValueMapBlock valueMap={tab.value_map} />
      {tab.method_block && <MethodBlockView method={tab.method_block} />}

      {subtabs.length > 0 ? (
        <>
          <div className="phase-label">Step-by-Step</div>
          <div className="sub-tabs">
            {subtabs.map((sub) => {
              const active = (activeSub ?? subtabs[0].key) === sub.key;
              const cls = ["sub-tab", sub.css_class, active ? "active" : ""].filter(Boolean).join(" ");
              return (
                <div className={cls} key={sub.key} onClick={() => onSelectSub(sub.key)}>
                  {sub.label}
                </div>
              );
            })}
          </div>
          {subtabs.map((sub) => {
            const active = (activeSub ?? subtabs[0].key) === sub.key;
            const subCallouts = sub.callouts ?? [];
            return (
              <div className={active ? "sub-content active" : "sub-content"} key={sub.key}>
                <Callouts callouts={subCallouts} kinds={["text"]} />
                <Phases phases={tab.phases.filter((p) => p.subtab_key === sub.key)} />
                <Callouts callouts={subCallouts} kinds={["tip", "warning"]} />
              </div>
            );
          })}
        </>
      ) : (
        <Phases phases={tab.phases.filter((p) => !p.subtab_key)} />
      )}
      <Callouts callouts={callouts} kinds={["tip", "warning"]} />
    </>
  );
}

export default function GuideReader({ guide }: { guide: Guide }) {
  const tabs = guide.tabs;
  const allTabIds = [...tabs.map(tabDomId), ...SKILLS_TABS.map((t) => t.id)];
  const [activeTab, setActiveTab] = useState(allTabIds[0] ?? "thinning-ref");
  // active sub-tab key per tab dom id
  const [activeSub, setActiveSub] = useState<Record<string, string>>({});

  const lead = guide.title_lead || guide.title;
  const remainder =
    guide.title_lead && guide.title.startsWith(guide.title_lead)
      ? guide.title.slice(guide.title_lead.length)
      : "";
  const brief = guide.character_brief?.philosophy;
  const pills = guide.paint_lines_used ?? [];
  const credit = guide.creator_credit;
  const scopedHeadStyle = guide.head_style ? guide.head_style.replace(/:root/g, ".guide-reader") : "";

  return (
    <div className="guide-reader" style={themeVars(guide.theme)}>
      {scopedHeadStyle && <style dangerouslySetInnerHTML={{ __html: scopedHeadStyle }} />}

      {/* HERO */}
      <div className="hero">
        {guide.category_label && <div className="category">{guide.category_label}</div>}
        <h1><span>{lead}</span>{remainder}</h1>
        {guide.subtitle && <div className="subtitle">{guide.subtitle}</div>}
        {guide.quote && <div className="film-ref"><em>&ldquo;{guide.quote}&rdquo;</em></div>}
        <div className="series-badge">
          <span className="active">{guide.title_lead || guide.title}</span>
        </div>
        {credit?.name && (
          <div className="creator-credit">
            Figure by <strong>{credit.name}</strong>
            {credit.url && (
              <>
                {" · "}
                <a href={credit.url} target="_blank" rel="noreferrer">
                  {credit.link_text || credit.url}
                </a>
              </>
            )}
          </div>
        )}
      </div>

      {/* PAINT BAR */}
      {pills.length > 0 && (
        <div className="paint-bar">
          <span className="paint-bar-label">Paint Lines Used</span>
          {pills.map((pill, i) => (
            <span className="paint-pill" key={i}>
              {pill.color && <span className="pill-dot" style={{ background: pill.color }} />}
              {pill.name}
            </span>
          ))}
        </div>
      )}

      <div className="container">
        {brief && <div className="char-brief" dangerouslySetInnerHTML={{ __html: brief }} />}

        {/* TAB NAV */}
        <div className="tabs" role="tablist">
          {tabs.map((tab) => {
            const id = tabDomId(tab);
            return (
              <div
                key={id}
                role="tab"
                aria-selected={activeTab === id}
                className={activeTab === id ? "tab tab-btn active" : "tab tab-btn"}
                onClick={() => setActiveTab(id)}
              >
                {tab.name}
              </div>
            );
          })}
          {SKILLS_TABS.map((t) => (
            <div
              key={t.id}
              role="tab"
              aria-selected={activeTab === t.id}
              className={activeTab === t.id ? "tab tab-btn active" : "tab tab-btn"}
              onClick={() => setActiveTab(t.id)}
            >
              {t.label}
            </div>
          ))}
        </div>

        {/* AUTHORED TAB PANELS */}
        {tabs.map((tab) => {
          const id = tabDomId(tab);
          return (
            <div
              key={id}
              id={id}
              role="tabpanel"
              className={activeTab === id ? "tab-content active" : "tab-content"}
            >
              <TabPanel
                tab={tab}
                activeSub={activeSub[id]}
                onSelectSub={(key) => setActiveSub((prev) => ({ ...prev, [id]: key }))}
              />
            </div>
          );
        })}

        {/* SHARED SKILLS PANELS */}
        <div id="airbrush-skills" role="tabpanel"
          className={activeTab === "airbrush-skills" ? "tab-content active" : "tab-content"}>
          <AirbrushSkills />
        </div>
        <div id="brush-skills" role="tabpanel"
          className={activeTab === "brush-skills" ? "tab-content active" : "tab-content"}>
          <BrushSkills />
        </div>
        <div id="thinning-ref" role="tabpanel"
          className={activeTab === "thinning-ref" ? "tab-content active" : "tab-content"}>
          <ThinningReference config={guide.thinning_config} />
        </div>
      </div>

      <footer className="guide-footer">
        {guide.scale ? `${guide.scale} scale` : "Painting guide"}
        {guide.franchise ? ` · ${guide.franchise}` : ""}
      </footer>
    </div>
  );
}
