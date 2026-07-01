# Plan — #676: `merge_group` must write `GroupOverride` rows so durable merges survive rescans

**Parent:** #674 (flaky manual grouping)
**Related:** #675 (root cause — `_apply_group_override` nulls `variant_group_id`), #678 (two-systems tech debt)

**Status update:** PR #686 (merged, closes #675) already shipped the core dual-write this plan called
for — `merge_group` now upserts `GroupOverride` rows inline (not via the `_upsert_group_override` extraction
this plan originally proposed, but functionally equivalent) and `_apply_group_override` no longer
unconditionally nulls `variant_group_id` on manual groups. The one gap #686 left: `split_group` did not
clean up the `GroupOverride` row (or `model.character`) it inherits from a merge, so a split member stayed
phantom-grouped via the legacy character key. That gap is what this implementation closes.

---

## Problem

`merge_group` (`POST /models/groups/merge`, [models.py:1231](../../backend/app/routers/models.py)) sets
`variant_group_id` on each member and marks the `VariantGroup` as `source="manual"`, but it never writes
`GroupOverride` rows.

The scanner's proposal engine ([grouping.py:115](../../backend/app/services/grouping.py)) decides which models
it may re-group:

```python
candidates = [
    m for m in models
    if m.variant_group_id not in manual_group_ids and m.folder_path not in override_paths
]
```

A model is protected from re-proposal only if **at least one** of these is true:

1. `variant_group_id in manual_group_ids`, or
2. `folder_path in override_paths` (a `GroupOverride` row exists)

A durable merge satisfies only (1). The moment another code path zeros `variant_group_id`
(exactly what #675 does on any drag/rename), the model satisfies **neither** — scan protection is gone
and the next rescan re-proposes it into an auto group. The user's merge silently evaporates.

## Goal

Make durable merges resilient: a model merged via `merge_group` stays protected from the scanner even if
its `variant_group_id` is later cleared. Achieve this by dual-writing a `GroupOverride` row alongside the
`variant_group_id` assignment, so protection path (2) always holds.

## Non-goals

- Fixing #675 (the `variant_group_id` nulling itself) — separate issue, separate PR.
- Unifying the two grouping systems (#678) — this is the short-term dual-write bridge that #678 tracks
  as tech debt.
- Changing the drag/`batchSetGroup` path.

---

## Approach

In `merge_group`, after assigning `variant_group_id` to each member, upsert a `GroupOverride` row per
member keyed on `folder_path`, with `character` set to the group's label. Reuse the existing
conflict-safe upsert already used by `_apply_group_override` ([models.py:1147](../../backend/app/routers/models.py))
rather than hand-rolling a second one — but **without** the `variant_group_id = None` side effect that
`_apply_group_override` carries (that side effect is the #675 bug; calling it verbatim here would
re-introduce the very problem we are protecting against).

### Why `character = group.label`

`GroupOverride.character` is the character-system's grouping key. Setting it to the group label keeps the
two systems pointing at the same logical group, so if `variant_group_id` is later lost the character path
still collapses these models together under the same name. The read path (`_group_key_sql`) prefers
`variant_group_id` when present, so this dual-write does not change display while the durable id survives —
it only provides a fallback.

### Extract a shared upsert helper

`_apply_group_override` currently bundles two concerns: (a) upsert the `GroupOverride` row + set
`model.character`, and (b) null `variant_group_id`. Split (a) into a helper so `merge_group` can reuse the
persistence without the destructive (b):

```python
def _upsert_group_override(db: Session, model: Model, character: str | None) -> None:
    """Upsert the GroupOverride row and mirror character onto the model row.
    Does NOT touch variant_group_id — callers that need the legacy character-only
    behavior clear it themselves."""
    stmt = (
        _sqlite_insert(GroupOverride)
        .values(path=model.folder_path, character=character)
        .on_conflict_do_update(index_elements=["path"], set_={"character": character})
    )
    db.execute(stmt)
    model.character = character
    model.updated_at = utcnow()
```

`_apply_group_override` becomes:

```python
def _apply_group_override(db: Session, model: Model, character: str | None) -> None:
    _upsert_group_override(db, model, character)
    model.variant_group_id = None  # legacy character-group semantics (#616)
```

Then in `merge_group`, inside the member loop:

```python
for m in models:
    m.variant_group_id = group.id
    _upsert_group_override(db, m, group.label)
```

This is a pure refactor of existing behavior plus one added call — no behavior change to the character path.

---

## Files

- **`backend/app/routers/models.py`**
  - Extract `_upsert_group_override` from `_apply_group_override` (no behavior change to existing callers).
  - Call `_upsert_group_override(db, m, group.label)` in `merge_group`'s member loop.
  - In `split_group`, delete `GroupOverride` rows for removed members (locked decision).
- **`backend/tests/test_variant_groups.py`** (or the existing manual-group test file — confirm location)
  - New tests (below).

## Tests

Behavior-level, exercising the endpoint + a simulated rescan:

1. **Merge writes GroupOverride rows** — `POST /models/groups/merge` with two models → assert a
   `GroupOverride` row exists for each member's `folder_path` with `character == group.label`.
2. **Merge survives a rescan after variant_group_id is cleared** — merge two models, manually null their
   `variant_group_id` (simulating #675's damage), run the grouping engine for that creator, assert the
   models are **not** re-proposed into an auto group (they remain excluded via `override_paths`).
3. **Merge into existing group (`group_id` provided)** — assert new members also get `GroupOverride` rows.
4. **Label change on merge** — merging with a new `label` updates both `group.label` and the members'
   `GroupOverride.character`.
5. **Regression: character path unchanged** — `_apply_group_override` still nulls `variant_group_id` and
   upserts the override (existing `batch_set_group` / `set_group` tests must stay green — run the full
   file, not a `-k` subset).

## Decisions (locked)

- **`split_group` cleanup is IN SCOPE for this PR.** Deleting the `GroupOverride` rows for removed members
  is the direct dual of the merge dual-write; omitting it reintroduces a stale-override bug. Included here.
- **Dual-write bridge only.** #675 (the `variant_group_id = None` root cause) stays a separate PR. This PR
  is the short-term fallback; #678 tracks the long-term unification.

## Risks

- **Stale `GroupOverride` on split.** Addressed in this PR (see locked decision above): `split_group`
  deletes the `GroupOverride` rows for removed members so they truly ungroup.
- **`character` collision.** Writing `group.label` into `character` could clobber a meaningful pre-existing
  `character` value on a member. Acceptable — the user explicitly merged these into one named group, so a
  unified character is the intended outcome. Worth a one-line comment.
- **Interaction with #675.** This plan protects against #675's symptom but does not fix its cause. Land
  order does not matter for correctness, but if #675 lands first this becomes belt-and-suspenders. Either
  way both are needed: #675 stops the destruction, #676 provides the fallback.

## Out-of-scope follow-ups (do not fix here)

- #675 — the `variant_group_id = None` root cause.
- #679 — orphaned `VariantGroup` pruning.
- #678 — collapsing the two grouping systems.

## Sequencing

1. Refactor `_apply_group_override` → `_upsert_group_override` + thin wrapper.
2. Add the `_upsert_group_override` call in `merge_group`.
3. Delete `GroupOverride` rows for removed members in `split_group` (+ test: split member truly ungroups).
4. Tests, full-file run, PR, arm auto-merge.
