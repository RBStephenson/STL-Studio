# Dependency and license audit — 2026-07-16

This report records the STUDIO-209 audit performed from `main` at `ae0bbd8` and
the dependency corrections made by the audit branch. Signing-certificate
acquisition and signed-installer verification are outside this audit's scope.

## Result

**Pass for the v1.0 dependency gate.** `pip-audit` and both complete
`npm audit` scans reported no known vulnerabilities. The full transitive
inventories contain only licenses accepted by
`scripts/dependency_license_policy.json`; no incompatible or unclear
third-party license remains.

The recurring Dependency Audit workflow runs on pull requests, pushes to
`main`, every Monday, and manual dispatch. It publishes separate backend,
frontend, and desktop JSON inventories for 30 days and fails on:

- any Python advisory reported by `pip-audit`;
- any high or critical npm runtime or build advisory; or
- any package license not explicitly approved by the repository policy.

## Direct dependency inventory

### Backend runtime

`fastapi`, `uvicorn[standard]`, `sqlalchemy`, `alembic`, `pydantic`,
`pydantic-settings`, `httpx`, `truststore`, `beautifulsoup4`,
`python-multipart`, `nh3`, `cryptography`, `numpy`, `scikit-image`, `pillow`,
`playwright`, `anthropic`, and `pypdf`.

Backend test/build tooling is `pytest`, `pytest-cov`, and `ruff`.

### Frontend runtime

`@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`,
`@react-three/drei`, `@react-three/fiber`, `@tanstack/react-query`,
`dompurify`, `lucide-react`, `react`, `react-dom`, `react-router-dom`, `three`,
and `three-stdlib`.

The audit found that `STLViewer.tsx` imported `three-stdlib` through another
package's transitive installation. It is now a declared direct dependency.

### Electron runtime

`electron-updater` is the only production dependency. Electron,
electron-builder, TypeScript, Vitest, V8 coverage, and Node types are build or
test dependencies. Dependabot now scans this package tree independently.

## License review

The Python inventory contains MIT, Apache, BSD, PSF, MPL-2.0, 0BSD, Zlib,
CC0-1.0, and equivalent compound or metadata-alias expressions. The complete
Node runtime and build inventories contain MIT, Apache-2.0, ISC, BSD-3-Clause, 0BSD,
BlueOak-1.0.0, Python-2.0, CC0 alternatives, WTFPL alternatives, and an
MPL-2.0-or-Apache-2.0 expression. WTFPL appears only in transitive Electron
build tooling and is accepted as a permissive build-time license; the exact
expressions are allowlisted rather than the policy accepting arbitrary aliases.

The frontend build inventory also includes `caniuse-lite` browser-compatibility
data under CC-BY-4.0, `mdn-data` under CC0-1.0, and Lightning CSS tooling under
MPL-2.0. They are not packaged application modules. Attribution: `caniuse-lite`
is maintained by the Browserslist project and distributed from
`https://github.com/browserslist/caniuse-lite` under CC-BY-4.0.

These are permissive licenses or, for MPL-2.0, a file-level weak-copyleft
license compatible with this distribution. The application packages report
`UNLICENSED` because their manifests are private; the policy ignores only the
two named private application packages. Unknown licenses and every other
`UNLICENSED` package fail the gate.

## Unused dependency review

Static scans were checked against runtime and configuration usage rather than
accepted blindly:

| Finding | Resolution |
|---|---|
| `aiofiles` had no imports or runtime integration | Removed |
| `watchdog` had no imports or runtime integration | Removed |
| `apscheduler` had no imports or runtime integration | Removed |
| `uvicorn` is not imported | Retained: it is the backend container entry point |
| `python-multipart` is not imported | Retained: FastAPI loads it for `File`, `Form`, and `UploadFile` routes |
| frontend CSS tools appeared unused | Retained: Vite, PostCSS, and CSS configuration consume them |
| Vitest V8 coverage appeared unused | Retained: Vitest loads it through the coverage provider configuration |
| `three-stdlib` appeared missing | Added as a direct frontend dependency |

No direct Electron production dependency was unused.

## Reproducing the audit

The authoritative commands are in `.github/workflows/dependency-audit.yml`.
The policy itself can be checked independently with:

```bash
python scripts/check_dependency_licenses.py \
  --policy scripts/dependency_license_policy.json \
  --pip path/to/backend-licenses.json \
  --node path/to/frontend-licenses.json \
  --node path/to/desktop-licenses.json
```

The generated JSON reports are evidence artifacts rather than committed
snapshots, so scheduled scans can detect newly published advisories without a
documentation-only commit.
