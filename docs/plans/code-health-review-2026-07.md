# Code Health Review & Remediation Plan (July 2026)

Full-app review of STL Studio (backend FastAPI + frontend React/TS), 2026-07-02.
Jira: STUDIO-55 … STUDIO-64.

## Overall assessment

The codebase is healthier than average for a solo project: async `httpx` for all
scraping, a library write lock, localhost CSRF middleware, encrypted-at-rest API
keys, 74 backend + 58 frontend test files, and CI running both suites on every
PR. The problems are structural, not correctness: god files, three overlapping
schema-migration mechanisms, a four-times-duplicated background-job pattern, and
a frontend with no server-state layer.

## Findings

### F1 — Three schema systems coexist (backend/app/main.py)

- `Base.metadata.create_all(bind=engine)` runs at module import (line 14),
  *before* the lifespan Alembic upgrade.
- Hand-rolled `_migrate_schema()` holds a 40+-entry additive column list that is
  still growing (`is_inbox` added recently). Its gaps already caused shipped
  bugs (#279, #280 — noted in its own comments).
- Alembic (head 0018) is the third system.

Every new column needs an entry in 2–3 places; ordering between `create_all`
and Alembic is fragile.

### F2 — God files

| File | Size | Problem |
|---|---|---|
| `backend/app/routers/models.py` | 1418 lines | ~35 endpoints across 5 domains (CRUD/list, tags, variant groups, print queue, thumbnails) |
| `backend/app/services/scanner.py` | 1320 lines | module-level global state + two locks |
| `frontend/src/pages/ModelDetail.tsx` | 2150 lines | 46 `useState`, 10 `useEffect` |
| `frontend/src/api/client.ts` | 1652 lines | 107 exports, flat API monolith |
| `frontend/src/pages/Library.tsx` | 1327 lines | 24 `useState` |

### F3 — No server-state library

All data fetching is hand-rolled `fetch` + `useState` + `useEffect`. Cache
invalidation and refetch-after-mutation are manual. This is *why* ModelDetail
has 46 state variables, and it is the standing source of stale-UI bugs.

### F4 — Background-job pattern duplicated ×4

`threading.Thread(daemon=True)` + module-global state dict + `threading.Lock`
reimplemented independently in `services/scanner.py`,
`services/enrich_refresh.py`, `routers/imports.py`, and
`painting/services/draft_jobs.py`, each with a slightly different
progress/status protocol.

### F5 — No lint/type gates in CI

`tests.yml` runs pytest + vitest only. No ruff, mypy, eslint, or
`tsc --noEmit`. STUDIO-11 was a tsc break that reached main because nothing
gated it.

### F6 — Untyped endpoint bodies

`rename_tag(body: dict)` and `merge_tags(body: dict)`
(`routers/models.py:421,453`) bypass Pydantic validation.

### F7 — 67 broad `except Exception` across 24 files

Scrapers are justified (hostile HTML). `imports.py` (10) and `scanner.py` (7)
are high-risk given the prior scan data-loss incident (#590).

### F8 — 36 `any` in frontend despite `strict: true`

Concentrated in `ModelCard.test.tsx` (10), `FindOnWeb.tsx` (4),
`ModelDetail.tsx` (5).

### F9 — Local junk (no ticket)

Untracked `backend;C` / `frontend;C` dirs (PowerShell quoting mishap) and stray
`bulk_import_report.csv` / `corpus_validation_report.csv` at repo root. Delete
locally; add report-CSV patterns to `.gitignore`.

## Remediation plan

Order matters: Phase 1 lands the guardrails so every later refactor merges with
lint + type gates already on.

### Phase 1 — Guardrails (cheap, first)

| Ticket | Work |
|---|---|
| STUDIO-55 | CI lint job: `ruff check` + `ruff format --check` (backend), `eslint` + `tsc --noEmit` (frontend). mypy as timeboxed stretch. |
| STUDIO-56 | Pydantic models for the `body: dict` endpoints; sweep for others. |
| — | Delete local junk dirs/CSVs, extend `.gitignore` (F9, no ticket). |

### Phase 2 — Migration consolidation

| Ticket | Work |
|---|---|
| STUDIO-57 | Alembic becomes sole schema owner: drop startup `create_all`; freeze `_migrate_schema()` (legacy pre-Alembic DBs only, never append again); CI test asserting fresh-DB-via-Alembic == `Base.metadata`; legacy-DB boot test. Rule going forward: new columns → Alembic only. |

### Phase 3 — Backend decomposition

| Ticket | Work |
|---|---|
| STUDIO-58 | Split `routers/models.py` → `models` / `tags` / `groups` / `print_queue` / `thumbnails` routers. Pure move, URL paths unchanged, existing API tests must pass unchanged. |
| STUDIO-59 | Shared `services/job_runner.py` (start/status/cancel, single registry + lock, uniform progress payload); migrate the four call sites. Non-goals: persistence, queueing. |
| STUDIO-60 | Audit all `except Exception`: narrow types, ensure `logger.exception` / re-raise, kill silent swallows. Priority: scanner → imports → reorganize_apply. |

### Phase 4 — Frontend (biggest win, biggest effort)

| Ticket | Work |
|---|---|
| STUDIO-62 | Split `api/client.ts` into domain modules with shared `api/base.ts`; barrel re-export keeps existing imports working. Do first or with STUDIO-61. |
| STUDIO-61 | Adopt TanStack Query: provider, `hooks/queries/` per domain, migrate ModelDetail then Library. client.ts functions remain the fetch layer. |
| STUDIO-63 | Decompose ModelDetail.tsx and Library.tsx into section components + hooks. **After** STUDIO-61, or state churn gets refactored twice. |
| STUDIO-64 | Burn down `any`: eslint `no-explicit-any` warn → fix → error. |

### Sequencing & coordination

```
STUDIO-55 ──► STUDIO-58/59/60 (backend refactors, any order)
   │
   ├──► STUDIO-64 (needs eslint gate)
   │
STUDIO-62 ──► STUDIO-61 ──► STUDIO-63 (frontend chain)

STUDIO-56, STUDIO-57 — independent, anytime
```

Phase 4 overlaps with grouping-unification #678 Phase 4 (frontend): do TanStack
Query adoption on ModelDetail/Library first (or fold it into that work) to
avoid refactoring the same pages twice.
