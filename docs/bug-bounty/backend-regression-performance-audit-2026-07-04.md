# Backend Bug Bounty: Regression and Performance Audit

Date: 2026-07-04
Scope: `backend/app` static review, focused on likely regressions, correctness risks, security-adjacent issues, and performance improvements.

## Executive Summary

The backend has good coverage around the obvious dangerous surfaces: localhost CSRF protection, file-serving allowlists, path guards, SSRF checks for thumbnail fetches, capped remote downloads, encrypted app secrets, scan prune caps, and write-locking for reorganize apply/undo.

The highest-value findings are not classic injection bugs. They are lifecycle and consistency issues where newer shared primitives are not used uniformly:

- Database restore/reset can run during non-scan write operations.
- Scan launch endpoints can report success even when no scan started.
- Enrichment refresh can double-launch under concurrent requests.
- One file-browser endpoint touches the filesystem before checking its allowlist.

Performance concerns cluster around endpoints that materialize large result sets or run repeated counts. These are acceptable for small libraries, but they will become visible as the model count grows.

## Findings

### P1: Database restore/reset can race reorganize apply/undo

Severity: High
Confidence: High
Category: Correctness / data integrity

Evidence:

- `backend/app/routers/database.py:45`
- `backend/app/routers/database.py:126`
- `backend/app/routers/database.py:174`
- `backend/app/services/write_lock.py:93`
- `backend/app/services/reorganize_apply.py:307`
- `backend/app/services/reorganize_apply.py:490`

`_require_idle()` only checks `scanner.get_status()["running"]`. Restore and reset then replace or drop/recreate database state without checking the shared library write lock used by reorganize apply/undo. A reorganize operation can be moving files and updating DB rows while restore/reset swaps the DB underneath it.

Impact:

- File paths on disk and DB rows can diverge.
- An apply/undo recovery log may no longer match the restored/reset DB.
- A reset during apply could leave moved files with no corresponding model state.

Recommendation:

Make database restore/reset honor the same shared library write gate as apply/undo. A conservative option is to expose a non-mutating `write_lock.is_locked()`/`current in-memory operation` check, or run restore/reset inside `library_write("database_restore")` / `library_write("database_reset")` with a persisted marker.

Suggested tests:

- Holding `write_lock.library_write("apply")` makes `/database/restore` return `409`.
- Holding `write_lock.library_write("apply")` makes `/database/reset` return `409`.
- Restore/reset still succeed when idle.

### P1: Scan launch endpoints can return success when no scan started

Severity: High
Confidence: High
Category: Correctness / user-visible regression

Evidence:

- `backend/app/routers/scan.py:141`
- `backend/app/routers/scan.py:149`
- `backend/app/routers/scan.py:155`
- `backend/app/routers/scan.py:165`
- `backend/app/services/scanner.py:174`
- `backend/app/services/scanner.py:590`

`scanner.start_full_scan()` and `scanner.start_creator_scan()` silently return when `write_lock.try_acquire_for_scan()` fails. The router does not inspect that outcome and still returns `200` with `"scan started"`.

`/scan/inbox` already handles this correctly through `scanner.start_inbox_scan()` returning `False` and mapping that to `409`.

Impact:

- UI can show a scan as started when the library is actually busy.
- Users may assume a rescan happened and trust stale data.
- This makes busy-state bugs harder to diagnose because the API response lies.

Recommendation:

Make `start_full_scan()` and `start_creator_scan()` return `bool`, then map `False` to `409 Conflict` in the router, matching inbox import behavior.

Suggested tests:

- With the write lock held, `POST /scan/start` returns `409`.
- With the write lock held, `POST /scan/creator/{id}` returns `409`.
- Existing happy-path scan launch still returns `200`.

### P2: Image browser checks filesystem before allowlist

Severity: Medium
Confidence: High
Category: Security-adjacent / path exposure

Evidence:

- `backend/app/routers/files.py:335`
- `backend/app/routers/files.py:355`
- `backend/app/routers/files.py:356`
- `backend/app/routers/files.py:358`
- Safer pattern in `backend/app/routers/scan.py:116`

`browse_images()` builds `Path(path)` and calls `exists()` / `is_dir()` before `_is_safe_path()`. That means a request outside configured roots can distinguish missing paths from existing non-allowed paths.

This is not a full path traversal because the endpoint still blocks listing outside allowed roots. It is still inconsistent with the stricter pattern used by `/scan/browse`, where containment is checked before filesystem access.

Impact:

- Small filesystem existence oracle outside configured roots.
- More importantly, this weakens the project’s path-guard discipline and may invite copy/paste regressions.

Recommendation:

Normalize and verify containment before any `exists()`, `is_dir()`, or `iterdir()` call. Return `403` for all out-of-allowlist paths regardless of whether they exist.

Suggested tests:

- Existing path outside roots returns `403`.
- Missing path outside roots returns `403`, not `404`.
- Missing path inside roots returns `404`.

### P2: Enrichment refresh has a double-launch race

Severity: Medium
Confidence: High
Category: Concurrency / background jobs

Evidence:

- `backend/app/routers/enrich.py:268`
- `backend/app/routers/enrich.py:285`
- `backend/app/routers/enrich.py:287`
- `backend/app/services/enrich_refresh.py:144`
- `backend/app/services/enrich_refresh.py:187`

The router checks `enrich_refresh.get_status()["running"]`, then starts a raw `threading.Thread`. The shared runner job is only registered inside that new thread when `run_refresh()` reaches `runner.run_inline()`.

Two fast requests can both observe not-running before either thread registers the job.

Impact:

- Duplicate refreshes can run concurrently.
- Remote storefronts may get unnecessary duplicate traffic.
- Both workers can apply metadata to the same rows, increasing SQLite contention and making progress status unreliable.

Recommendation:

Move job registration into the synchronous request path. Prefer a service method such as `start_refresh(...) -> bool` that calls `runner.start(_JOB_KEY, ...)` with `single_flight=True`, rather than wrapping `run_refresh()` in a raw thread from the router.

Suggested tests:

- Two immediate refresh starts: one succeeds, one returns `409`.
- Status is `running` immediately after the first response.

### P2: Neighbor lookup materializes every matching ID

Severity: Medium
Confidence: High
Category: Performance / scalability

Evidence:

- `backend/app/routers/models.py:720`
- `backend/app/routers/models.py:762`

`get_neighbors()` applies the full filter/sort and then does:

```python
ids = [row[0] for row in _apply_sort(q.with_entities(Model.id), sort).all()]
```

It then finds the current ID in Python. For large libraries this turns every detail-page navigation into a full filtered ID load. Grouped variants make this more expensive because `_collapse_variants()` adds a window-function subquery.

Impact:

- Detail-page next/previous controls get slower as the library grows.
- Large filtered result sets consume avoidable memory.
- Sorts like `creator` and grouped views can require more DB work than necessary.

Recommendation:

Replace full materialization with a bounded query approach. Options:

- Use ordered window functions to calculate `lag(id)` / `lead(id)` in SQL.
- For simpler sorts, query the target row’s sort keys and fetch the nearest previous/next rows with keyset predicates.
- Keep the existing implementation as fallback only for complex grouped cases if needed.

Suggested tests:

- Existing neighbor behavior for all filters/sorts stays unchanged.
- Add a regression test that proves the query uses bounded results where practical, or benchmark with a seeded large library.

### P3: Search filter treats `%` and `_` as wildcards

Severity: Low
Confidence: High
Category: Correctness / performance

Evidence:

- `backend/app/routers/models.py:66`
- `backend/app/routers/models.py:68`
- `backend/app/routers/models.py:71`
- Existing escaped pattern in `backend/app/routers/models.py:299`

The main `q` filter uses raw `f"%{search}%"` with `ilike()`. The character filter uses `like_escape(character)` and an explicit escape character, but the general search does not.

Impact:

- Searching for `%` matches nearly everything.
- Searching for `_` matches any single character.
- Accidental wildcard searches can trigger broad scans and confusing results.

Recommendation:

Use `like_escape(search)` consistently for title/name/description/character search, with `escape="\\"`.

Suggested tests:

- Searching `%` only matches literal `%` in text.
- Searching `_` only matches literal `_` in text.
- Normal substring search behavior is unchanged.

### P3: Bulk zip can return an empty archive with 200

Severity: Low
Confidence: Medium
Category: Correctness / UX

Evidence:

- `backend/app/routers/files.py:254`
- `backend/app/routers/files.py:263`
- `backend/app/routers/files.py:270`
- `backend/app/routers/files.py:272`

`download_zip()` verifies matching `STLFile` rows exist, then silently skips files that are outside allowed roots or missing on disk. If every requested row is skipped, the endpoint still returns a valid but empty zip.

Impact:

- User receives a successful download that contains nothing.
- Missing-drive or stale DB-row problems are hidden.

Recommendation:

Track how many files are written. If zero, delete the temp zip and return a `404` or `409` with a clear message such as "No requested files were available on disk."

Suggested tests:

- All requested files missing returns an error.
- Mixed available/missing files returns a zip with the available files.
- All available files behavior is unchanged.

### P3: Listing and stats perform repeated full-count work

Severity: Low
Confidence: Medium
Category: Performance

Evidence:

- `backend/app/routers/models.py:307`
- `backend/app/routers/models.py:363`
- `backend/app/routers/models.py:365`
- `backend/app/routers/models.py:367`
- `backend/app/routers/models.py:369`
- `backend/app/routers/models.py:372`
- `backend/app/routers/models.py:375`
- `backend/app/routers/models.py:378`
- `backend/app/routers/models.py:381`

`list_models()` always performs a `count()` before fetching the current page. `model_stats()` runs multiple independent count queries for status chips.

This is not wrong. It is a likely scaling hotspot because library views are core UI paths, and count queries over filtered/grouped data can become expensive.

Impact:

- Library page loads get slower with large data sets.
- Stats refresh cost grows with every added status dimension.

Recommendation:

Keep exact counts for now if the UI depends on them, but consider:

- Returning `has_next` from `limit(page_size + 1)` and making `total` optional for expensive filtered/grouped views.
- Consolidating stats into fewer aggregate queries with `SUM(CASE...)`.
- Caching stats briefly and invalidating on scan/import/enrich/write operations.

Suggested tests:

- Existing response shape stays compatible if exact totals remain.
- If totals become optional, update frontend contract deliberately.

### P3: Common filters lack dedicated indexes

Severity: Low
Confidence: Medium
Category: Performance

Evidence:

- Existing indexes in `backend/app/models.py:88`
- Existing indexes in `backend/app/models.py:91`
- Existing indexes in `backend/app/models.py:93`
- Common filters in `backend/app/routers/models.py:78`
- Common filters in `backend/app/routers/models.py:98`
- Common filters in `backend/app/routers/models.py:117`
- Common filters in `backend/app/services/enrich_refresh.py:95`

The model table has indexes for creator/character, character/name, created_at, inbox, rating, print_status, favorite, excluded, and variant group. Other common filters appear unindexed:

- `source_site`
- `needs_review`
- thumbnail presence checks
- `source_last_fetched`
- JSON-derived `parsed_attributes` fields like `support_status` and `slicer`

Impact:

- Filtered library views may degrade as row count grows.
- Stale enrichment refresh may scan all enriched models when filtering by fetch age.
- JSON filters are especially likely to be table scans unless expression indexes are added.

Recommendation:

Use SQLite `EXPLAIN QUERY PLAN` against realistic library sizes before adding indexes. Likely candidates:

- `models(source_site)`
- `models(needs_review)`
- `models(source_last_fetched)`
- expression indexes for `json_extract(parsed_attributes, '$.support_status')` and `json_extract(parsed_attributes, '$.slicer')` if those filters are used heavily.

Avoid indexing thumbnail presence until profiling proves it matters; boolean/null-presence indexes can be low-value depending on distribution.

### P3: Enrichment refresh materializes all candidates before work

Severity: Low
Confidence: Medium
Category: Performance / resilience

Evidence:

- `backend/app/services/enrich_refresh.py:80`
- `backend/app/services/enrich_refresh.py:100`
- `backend/app/services/enrich_refresh.py:105`
- `backend/app/services/enrich_refresh.py:109`
- `backend/app/services/enrich_refresh.py:135`

`_do_refresh()` loads all matching models with `query.all()`, builds a full unique URL set, fetches detail for all URLs, applies changes to all models, then commits once at the end.

Impact:

- Library-wide refresh can be memory-heavy.
- A long run keeps many ORM objects alive.
- Progress is coarse; counters are only updated after the full run completes.
- One late failure can leave a lot of work uncommitted longer than necessary.

Recommendation:

Process refreshes in chunks:

- Page model IDs in stable order.
- Fetch unique URLs per chunk.
- Commit after each chunk.
- Update job progress incrementally.
- Keep the existing bounded fetch concurrency.

Suggested tests:

- Chunked refresh updates all eligible models.
- Failed fetches do not block later chunks.
- Status counters advance during the job.

## Positive Controls Observed

- `backend/app/main.py` blocks cross-origin state-changing requests with local Origin/Host checks.
- `backend/app/services/url_guard.py` rejects private, loopback, link-local, reserved, multicast, and unspecified remote fetch targets.
- `backend/app/services/thumbnails.py` caps thumbnail and HTML preview downloads.
- `backend/app/services/path_guard.py` centralizes realpath/commonpath containment checks.
- `backend/app/services/write_lock.py` serializes scan/apply/undo and persists apply/undo markers.
- Scanner prune paths include offline-root and bulk-delete safety caps.
- Secrets are encrypted at rest in `backend/app/services/secrets.py`.

## Suggested Triage Order

1. Fix restore/reset locking.
2. Fix scan launch false-success responses.
3. Fix enrichment refresh single-flight launch.
4. Move `browse_images()` allowlist checks before filesystem access.
5. Add tests for the four regression candidates above.
6. Profile `get_neighbors()` and model listing with a large seeded library.
7. Tune indexes based on `EXPLAIN QUERY PLAN`, not guesswork.

