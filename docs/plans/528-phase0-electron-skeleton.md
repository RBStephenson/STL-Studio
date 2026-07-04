# Plan — STUDIO-70 (Phase 0): Electron project skeleton

**Parent:** epic STUDIO-69 · overall plan [528-pywebview-to-electron.md](528-pywebview-to-electron.md)
**Scope:** scaffolding only. No backend wiring, no change to the shipped product.

---

## Goal

Stand up the `desktop/` Electron project and its toolchain (electron,
electron-builder, TypeScript) so later phases have somewhere to build. Success =
`npm install && npm run build && npm start` opens a window showing a static
placeholder page.

This is the one phase with no runtime logic to unit-test — nothing testable
exists yet. Real tests arrive in Phase 1 with `sidecar.ts` (spawn / health-poll /
shutdown).

## Files

| File | Purpose |
|------|---------|
| `desktop/package.json` | Own manifest (not the frontend's). electron + electron-builder + typescript devDeps; `build` (tsc), `start` scripts. Package manager: **npm** (matches plan 528 Phase 4 CI `npm ci`). |
| `desktop/tsconfig.json` | `src/*.ts` → `dist/`, CommonJS (Electron main), strict. |
| `desktop/src/main.ts` | App lifecycle + single `BrowserWindow` loading the placeholder. No preload/IPC yet. |
| `desktop/index.html` | Static placeholder page ("STL Studio — Phase 0"). Bundled via `loadFile`. |
| `desktop/electron-builder.yml` | **Stub** — appId, productName, Windows NSIS target. Not exercised until Phase 3. |
| `desktop/.gitignore` | `node_modules/`, `dist/`, `release/`. |

## Deliberately deferred to later phases

- `src/sidecar.ts`, `src/paths.ts` — Phase 1 (backend spawn + resource resolution).
- Real `electron-builder.yml` (extraResources sidecar, icon, metadata) — Phase 3.
- CI wiring in `build.yml` — Phase 4.
- Single-instance lock, splash window, logfile — Phase 1+.

## Verification

- `npm install` in `desktop/` resolves cleanly.
- `npm run build` (tsc) emits `dist/main.js` with no type errors.
- `npm start` opens a 1280×800 window showing the placeholder (local manual check).

## Risks

- Low. Greenfield directory; touches no existing file. Installer size / sidecar
  orphaning / CI-chain risks all belong to later phases (see parent plan §Risks).
- Electron devDep download is large (~150 MB) — first `npm install` is slow; not
  a code risk.

## Exit

`desktop/` builds and launches a placeholder window. PR merged, CI green. Unblocks
Phase 1 (STUDIO-71).
