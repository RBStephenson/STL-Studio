# STL Studio — Technical Summary

Local-first web app for cataloguing, browsing, and organizing a personal STL
(3D-printable model) file library. Ships as a standalone desktop app (Electron,
Windows/Linux), a Docker deployment, or a bare backend+frontend dev setup.
Currently in `v1.0.0-beta.5`.

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI 0.139, SQLAlchemy 2.0, Alembic (schema migrations), Uvicorn |
| Database | SQLite (WAL mode), file-based — no external DB server |
| Frontend | React 19, TypeScript, Vite, TanStack Query, React Router 7, Tailwind 4 |
| Desktop | Electron — wraps the frontend + a windowless backend sidecar on a dynamic port |
| 3D preview | `@react-three/fiber` / `three.js` |
| Testing | pytest (backend, ≥88% coverage gate) + Vitest/Testing Library (frontend) |
| CI/CD | GitHub Actions — lint, typecheck, pytest, vitest, CodeQL, Docker image publish (GHCR), cross-platform build-check (Windows/Linux), tagged release pipeline |

## Architecture

**Backend** (`backend/app/`) is a single FastAPI app split into per-domain
routers, each mounted under a shared prefix and included in a specific order
(the catch-all `/models/{id}` router must load last so it doesn't shadow
sibling literal paths):

- `routers/` — `scan`, `models`, `tags`, `groups`, `reorganize`, `imports`,
  `collections`, `files`, `thumbnails`, `print_queue`, `settings`, `database`,
  `enrich`, `scrape`, `cults` (+ a `painting/` sub-app for AI paint-guide
  generation)
- `services/` — the actual business logic the routers call into: the
  filesystem scanner, reorganize/apply engine (template-driven library
  layout + safe cross-device moves), variant grouping/matching, tag sync,
  AI-organize (LLM-backed part/unit categorization), secrets (encrypted
  API-key storage), scrapers (Cults3D, Gumroad, MyMiniFactory, generic
  storefronts), write-lock (single-writer guard around scan/reorganize/import)

Long-running operations (scan, reorganize apply, import apply, image
download) run through a shared `job_runner` — POST kicks off a background job
and returns immediately; the client polls a `/status` endpoint for progress
instead of holding one long HTTP request open.

**Database**: SQLite in WAL mode, no `PRAGMA foreign_keys` (deliberate —
cascades are done manually in Python at delete time, documented at each call
site). Alembic manages schema migrations (32+ revisions to date). Core tables:
`models`, `creators`, `stl_files`, `model_tags` (denormalized tag index derived
from JSON `tags`/`auto_tags` columns), `variant_groups`, `collections`,
`scan_roots`, `app_settings` (generic key/value store — new settings need no
migration), `ai_api_config`.

**Frontend** (`frontend/src/`) is a single-page React app: `pages/` per route,
`hooks/queries/` wrapping TanStack Query around the API client, `api/` for the
typed HTTP client, `context/` for cross-cutting UI state (toasts, confirm
dialogs, app settings). All Library filter/sort/page state lives in the URL so
views are shareable and back-button-safe.

**Desktop** (`desktop/`): Electron shell. Launches the backend as a sidecar
process on a dynamically chosen port, points the renderer at it, and packages
via `electron-builder` (NSIS installer on Windows, AppImage-style binary on
Linux). Auto-update wired through `electron-updater`, gated so pre-release
(beta/RC) channels are never offered to stable users.

## Core features

- **Scanning**: heuristic filesystem walk of configured scan roots,
  auto-detecting creator/character/part-type from folder and filename
  conventions; inbox flow for unstructured drops
- **Library**: paginated/filtered/sorted grid with variant grouping (multiple
  format variants of one character collapse to a representative card),
  Prev/Next keyboard navigation, bulk actions (tag, exclude, delete, enrich)
- **Reorganize**: template-driven physical file reorganization
  (`{creator}/{character}/{title}`-style), dry-run preview before apply,
  crash-safe undo log, cross-device-safe moves
- **Import**: browse-first import of unstructured "inbox" folders into the
  organized library, per-pack preview, source→library mapping, collision
  retry with auto-disambiguation
- **Tagging**: user tags + scanner auto-tags merge into one index; rename,
  merge, delete, and bulk operations all respect the auto-tag suppression list
  so an edit can't be silently undone by the next sync
- **AI Organize**: optional LLM-backed part-type/unit categorization and
  metadata suggestion (never auto-applied — always a review-then-confirm flow)
- **Painting guides**: separate `painting/` subsystem generates AI paint
  recipes for a model's stored paint shelf, with draft→review→publish and
  color-matching support
- **Print queue, Collections, Variant grouping, Cults3D/storefront scraping,
  encrypted secrets storage** round out the feature set

## Release & versioning

Tag-triggered GitHub Actions pipeline (`.github/workflows/release.yml`):
pushing `vX.Y.Z` (or `vX.Y.Z-beta.N`) builds installers for both platforms,
generates SBOMs (CycloneDX), computes SHA256SUMS, and publishes a GitHub
Release — automatically flagged prerelease for any hyphenated tag so beta/RC
builds never get offered to stable auto-update users. A separate rolling
"Main Build" prerelease tracks the latest green `main` commit for early
testers. Currently at `v1.0.0-beta.5`, working toward a stable v1.0.0.

## Testing & quality gates

- Backend: pytest with an 88% coverage floor (`pyproject.toml`), ruff lint
- Frontend: Vitest + Testing Library, ESLint, `tsc --noEmit`
- CodeQL security scanning on every push
- Docker images built and pushed to GHCR on every green `main` build and every
  release
- Cross-platform `build-check` workflow validates the Windows and Linux
  desktop builds independently of the release pipeline
