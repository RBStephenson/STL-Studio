# Painting domain reference

Source-of-truth domain knowledge for the painting module's guide generator
(#491/#525), validator (#498/#506), and authors. Derived from the working
figure-painting skill; scrubbed of personal/session data for the repo.

The app's **Paint Shelf** database is the live source of truth for which paints
are owned, and the generator injects it directly — so there is no static
inventory file here (it would only go stale). These docs cover the *rules and
conventions* the shelf and generator apply.

| File | What it covers |
|------|----------------|
| [figure-painting-skill.md](figure-painting-skill.md) | The full generator skill — value-first method, structure, paint lines |
| [skin-painting-methods.md](skin-painting-methods.md) | Three skin methods + decision table + mid-tone reference + freckling |
| [white-black-rule.md](white-black-rule.md) | Pure white = specular only; pure black = occlusion/lining only; shadow anchor = Payne's Grey |
| [airbrush-thinning-rule.md](airbrush-thinning-rule.md) | Nozzle-size = paint-fraction thinning rule (+ VMC exception) |
| [eye-painting-order.md](eye-painting-order.md) | Sclera before iris; full eye step order |
| [paint-code-conventions.md](paint-code-conventions.md) | Pro Acryl / AMP / Signature code+name conventions for validating swatches |
| [metallic-preferences.md](metallic-preferences.md) | Accuracy-over-brand rule; VMC equivalency + TMM steps |
| [transparent-red-substitution.md](transparent-red-substitution.md) | PA Transparent Red shifts magenta thinned; use FW Crimson Ink for glazes |
| [series-badge-css-rule.md](series-badge-css-rule.md) | Series-badge markup/CSS convention |
| [figure-creators.md](figure-creators.md) | Go-to 1:6 creators + Instagram handles for hero credits |
