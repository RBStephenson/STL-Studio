# Enrichment Code Fixes — Implementation Plan

Findings from a review of the enrichment stack (2026-07-02): `backend/app/routers/enrich.py`,
`backend/app/services/matcher.py`, `backend/app/services/metadata_apply.py`, and
`backend/app/services/scrapers/*`. The matcher itself (creator-strip, denoise, variant-group
collapse) was reviewed and found solid — no changes needed there.

Work is split into three PRs, severity-ordered. Each PR must include unit tests (hard project
requirement), follow Conventional Commits, branch per PR (`fix/enrich-...`), CI green before merge.

---

## PR 1 — Behavior bugs (`fix/enrich-behavior-bugs`)

### 1.1 Creator reassignment on every deep enrich (worst bug)

**Where:** `backend/app/services/metadata_apply.py:73-74`

```python
if scraped.creator_name:
    model.creator_id = resolve_creator(scraped.creator_name, db).id
```

**Problem:** Any scraped `creator_name` re-points `model.creator_id` via get-or-create
(`resolve_creator` in `backend/app/services/scanner.py:1178`, case-insensitive exact match only).
In the bulk creator-enrichment flow the user has already matched a storefront *for a known
creator*, but the MMF/Cults detail fetch carries the store's spelling (e.g. "Abe 3D Prints" vs
folder-derived creator "abe3d"). Different spelling → new `Creator` row created and models silently
moved out of the creator being enriched. Splits the library, breaks creator model counts, and
`POST /enrich/refresh` re-triggers it library-wide.

**Fix:** Add a keyword-only flag to `apply_scraped_to_model`, e.g. `reassign_creator: bool = True`
(matches the existing `overwrite_title` / `thumbnail_fill_only` flag pattern documented in the
module docstring). Pass `reassign_creator=False` from both call sites in
`backend/app/routers/enrich.py` (`bulk_apply` and `refresh_enrich`). The single-model
Find-on-Web path (scrape router) keeps current behavior. Optionally: even when False, fill
`creator_id` if it is currently NULL.

**Tests:** In `backend/tests/test_metadata_apply.py` — scraped creator_name with a different
spelling does NOT move the model or create a Creator when flag is False; does when True.
In `backend/tests/test_api_bulk_enrich.py` / `test_enrich_refresh.py` — bulk apply and refresh
leave `creator_id` untouched.

### 1.2 `rating` overwritten with store like counts

**Where:** `backend/app/services/metadata_apply.py:68-69`

```python
if scraped.like_count is not None:
    model.rating = scraped.like_count  # store likes as proxy for rating
```

**Problem:** User-set ratings are clobbered by store like counts on every enrich/refresh.
Semantic abuse (admitted in the comment).

**Fix:** Add a `like_count` integer column to `Model` (new alembic migration — current head is
0018, so this is **0019**). Write `scraped.like_count` there; stop writing `rating` entirely.
Check the frontend for anything reading `rating` that actually meant likes and update it
(grep `rating` in `frontend/src`).

**Tests:** enrich leaves `rating` untouched; `like_count` persisted.

### 1.3 `needs_review` cleared unconditionally

**Where:** `backend/app/services/metadata_apply.py:80` (`model.needs_review = False`)

**Problem:** Bulk-applying medium/low-confidence matches clears the review flag even though no
human looked at the deep data.

**Fix:** Add flag `clear_needs_review: bool = True`; the single-model reviewed path keeps True.
For bulk apply, either pass False always, or (preferred) have the frontend/router pass the match
confidence through `ApplyItem` and only clear for high-confidence items. Simplest correct
version: `clear_needs_review=False` on bulk, `True` on refresh (refresh operates on
already-matched data).

**Tests:** bulk apply of a match leaves `needs_review` intact; single-model path clears it.

### 1.4 Excluded-model inconsistency in bulk apply

**Where:** `backend/app/routers/enrich.py`

- `match_storefront` (lines ~151-162) queries ALL creator models — excluded ones can match and
  be enriched directly.
- Sibling propagation in `bulk_apply` (line ~227) filters `Model.excluded == False`.

**Fix:** Apply one rule everywhere — filter `excluded == False` in the match query too.

**Tests:** excluded model never appears in match results.

---

## PR 2 — Robustness (`fix/enrich-robustness`)

### 2.1 MMF JSON-LD `image` may be a plain string

**Where:** `backend/app/services/scrapers/mmf.py:262`

```python
for img in ld.get("image", []):
```

**Problem:** schema.org allows `image` to be a single string URL; iterating a string yields
characters which get appended to `images`. The later `startswith("http")` filter hides most of
the damage, but it's wrong and fragile.

**Fix:**

```python
imgs = ld.get("image") or []
if isinstance(imgs, str):
    imgs = [imgs]
for img in imgs:
```

**Tests:** `_parse` with JSON-LD where `image` is a string → single image extracted, no char junk.

### 2.2 Shared `ScrapedModel` objects mutated per-model

**Where:** `backend/app/routers/enrich.py` — `bulk_apply` (lines ~245-249) and `refresh_enrich`
(lines ~321-324).

**Problem:** `_fetch_unique_deep` returns one `ScrapedModel` per unique URL, shared by all
variant siblings referencing that URL. The apply loop mutates it in place
(`scraped.source_url = scraped.source_url or item.source_url`, same for source_site /
external_id). First model's item values stick for all sharers — latent aliasing trap.

**Fix:** Don't mutate the shared object. Either `dataclasses.replace(scraped, source_url=...)`
per model, or compute the effective values into locals and pass them / set them on the model
after `apply_scraped_to_model`. Keep bulk and refresh paths symmetric.

**Tests:** two items sharing a URL but with different external_id — second model gets its own,
and the cached `ScrapedModel` is unchanged after the loop.

### 2.3 Per-item error isolation in apply/refresh loops

**Where:** `backend/app/routers/enrich.py` — both loops, single `db.commit()` at end.

**Problem:** One exception inside `apply_scraped_to_model` (e.g. unexpected error beyond
`ThumbnailDownloadError`) 500s the whole request and rolls back every model in the batch.

**Fix:** Wrap the per-model apply in try/except, log, count into an `errors` field added to
both response payloads. Keep the single commit (partial success is fine — each successful model
is fully applied). Do NOT swallow silently: log with model id + url.

**Tests:** monkeypatch apply to raise for one model → others still applied, response reports
`errors: 1`.

### 2.4 (Optional, flag before doing) Move library-wide refresh off the request path

`POST /enrich/refresh` with an empty body re-fetches every enriched model synchronously —
minutes for a big library, HTTP timeout risk. If tackled, reuse the existing background-job
pattern from the scan router. Otherwise file an issue and skip; do not bolt on ad-hoc threading.

---

## PR 3 — Cleanup (`chore/enrich-cleanup`, optional)

### 3.1 Duplicate thumbnail downloads for variant siblings

`apply_scraped_to_model` downloads the same remote image once per sibling (N siblings = N CDN
hits + N files). Cache downloaded thumbnails per-URL within a batch (dict in the router loop,
copy the file per model via `download_thumbnail`-adjacent helper).

### 3.2 Cults3D credentials via ad-hoc session

`backend/app/services/scrapers/cults3d.py:101-113` opens its own `SessionLocal` (sync DB work
inside async path). Thread credentials from the caller like `mmf_api_key` already is: resolve in
router via `secrets.get_cults_credentials(db)`, pass through `scrapers.fetch_url` /
`scrape_storefront`. Touches `scrapers/__init__.py`, `storefront.py`, `enrich.py`, scrape router.

### 3.3 Minor

- `match_storefront` runs `.count()` then `.all()` — fetch once, check `len`.
- `bulk_apply`'s `item_map` silently keeps the last item on duplicate `model_id`s — reject
  duplicates with a 422 or document last-wins.
- `matcher._score` (line 74) unused outside tests — inline into tests or mark as test helper.
- `StorefrontProduct_Out` → rename to `StorefrontProductOut` (touches schema refs only).

---

## Conventions / guardrails for the implementing session

- No Node/Python runtimes on this machine's PATH — run lint/type/tests via the Docker throwaway
  container workflow (see local CI notes) or push and let CI verify.
- Every PR: unit tests included, Conventional Commit messages, branch per PR, never commit to
  main, arm auto-merge on CI green (tpagden is requested as reviewer by convention but does not
  review).
- When changing behavior, run the WHOLE affected test file, not `-k` subsets — old tests pin old
  behavior and may need updating (e.g. existing tests may assert creator reassignment or
  `rating` writes; update them deliberately, don't delete).
- Alembic: current head 0018; PR 1's migration is 0019. No app_settings migration needed for
  anything here.
