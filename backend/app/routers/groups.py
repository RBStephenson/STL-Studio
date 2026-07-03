"""Variant-group and grouping-strategy endpoints, split out of the models router
(STUDIO-58). Paths are unchanged (prefix `/models`).

Covers the per-model group-rep flag, manual merge/split/relabel of durable
variant groups (#617), the pack-split action, and per-subtree grouping strategy.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.dialects.sqlite import insert as _sqlite_insert
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Model, VariantGroup, GroupingStrategy
from app.schemas import (
    GroupRepUpdate, GroupReorder, GroupMergeBody, GroupSplitBody, GroupPatchBody,
    VariantGroupRead, GroupingStrategyBody,
)
from app.services import scanner, grouping
from app.utils import utcnow, like_escape


router = APIRouter(prefix="/models", tags=["models"])


@router.patch("/{model_id}/group-rep")
def set_group_rep(model_id: int, body: GroupRepUpdate, db: Session = Depends(get_db)):
    """Designate a model as its variant group's display thumbnail (#193).

    Sets `is_group_rep` on this model and clears it from every sibling in the
    same (creator, character) group, so at most one member is the rep. Pass
    `is_group_rep=false` to clear it and fall back to the heuristic. 400 if the
    model isn't part of a group (no creator/character).
    """
    model = db.query(Model).filter(Model.id == model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    if model.creator_id is None or not model.character:
        raise HTTPException(status_code=400, detail="Model is not part of a variant group.")

    if body.is_group_rep:
        # Clear the flag across the whole group first, then set it on this model.
        db.query(Model).filter(
            Model.creator_id == model.creator_id,
            Model.character == model.character,
            Model.id != model.id,
        ).update({Model.is_group_rep: False}, synchronize_session=False)
        model.is_group_rep = True
        # Rep resolution for durable groups reads VariantGroup.rep_model_id, not
        # this legacy flag (#678) — keep both in sync so the button's effect is
        # visible everywhere the group is shown, not just this page (STUDIO-7).
        if model.variant_group_id is not None:
            group = db.get(VariantGroup, model.variant_group_id)
            if group is not None:
                group.rep_model_id = model.id
    else:
        model.is_group_rep = False
        if model.variant_group_id is not None:
            group = db.get(VariantGroup, model.variant_group_id)
            if group is not None and group.rep_model_id == model.id:
                group.rep_model_id = None
    model.updated_at = utcnow()
    db.commit()
    return {"ok": True, "is_group_rep": model.is_group_rep}


@router.patch("/group/reorder")
def reorder_group(body: GroupReorder, db: Session = Depends(get_db)):
    """Persist a manual model order within a variant group (#399).

    `ids` is the group's members in the user's desired order; each member's index
    becomes its `variant_order`, and the lowest order is the group's representative
    card (see _rep_order). An **empty `ids` resets** the whole (creator, character)
    group — clears every member's variant_order so the heuristic order resumes.
    Ids that don't belong to the group are ignored. Scans never touch
    variant_order, so no scan-in-progress guard is needed."""
    group = db.query(Model).filter(
        Model.creator_id == body.creator_id,
        Model.character == body.character,
    )
    if not body.ids:
        updated = group.update({Model.variant_order: None}, synchronize_session=False)
        db.commit()
        return {"ok": True, "reset": True, "updated": updated}

    pos_by_id = {mid: i for i, mid in enumerate(body.ids)}
    members = group.all()
    touched = 0
    for m in members:
        # Members listed in `ids` get their drag position; any group member the
        # client omitted is sent to the back (keeps a stable, gap-free order).
        m.variant_order = pos_by_id.get(m.id, len(pos_by_id))
        touched += 1
    db.commit()
    return {"ok": True, "reset": False, "updated": touched}


@router.post("/{model_id}/split")
def split_pack(model_id: int, db: Session = Depends(get_db)):
    """Split a model whose folder is actually a multi-product pack into one model
    per child folder (opt-in; persisted so it survives rescans). The original
    model is replaced by its children, so the caller should navigate away."""
    if not db.query(Model.id).filter(Model.id == model_id).first():
        raise HTTPException(status_code=404, detail="Model not found")
    result = scanner.split_pack(model_id)
    if not result["ok"]:
        # A running scan is a conflict; everything else is a bad request.
        code = 409 if "scan is already running" in result["message"] else 400
        raise HTTPException(status_code=code, detail=result["message"])
    return result


# ---------------------------------------------------------------------------
# Manual variant groups (#617): user-curated merge / split / relabel. These set
# source="manual" so the scanner's proposal engine never reassigns the members.
# ---------------------------------------------------------------------------

def _mark_ungrouped(db: Session, model: Model) -> None:
    """Pin a model as explicitly ungrouped, sticky across rescans (#678 Phase 5).

    Used when a model is deliberately removed from its group (split, or a
    dissolve that drops a group below 2 members) — without this the proposal
    engine would happily re-propose the same auto group on the next scan."""
    model.no_group = True
    model.updated_at = utcnow()


def _prune_empty_group(db: Session, group_id: int | None) -> None:
    """Delete a group that has dropped below 2 members; clear the lone member."""
    if group_id is None:
        return
    remaining = db.query(Model).filter(Model.variant_group_id == group_id).all()
    if len(remaining) < 2:
        for m in remaining:
            m.variant_group_id = None
            _mark_ungrouped(db, m)
        grp = db.get(VariantGroup, group_id)
        if grp is not None:
            db.delete(grp)


@router.post("/groups/merge", response_model=VariantGroupRead)
def merge_group(body: GroupMergeBody, db: Session = Depends(get_db)):
    """Merge models into one manual variant group. Creates the group when
    group_id is omitted, else extends it. Marks the group manual so a rescan
    won't undo it. 409 while a scan is running."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    ids = list(dict.fromkeys(body.model_ids))
    if len(ids) < 2 and body.group_id is None:
        raise HTTPException(status_code=400, detail="Need at least two models to form a group.")

    models = db.query(Model).filter(Model.id.in_(ids)).all()
    if not models:
        raise HTTPException(status_code=400, detail="No valid models to merge.")
    creator_ids = {m.creator_id for m in models}
    if len(creator_ids) > 1:
        raise HTTPException(status_code=400, detail="Can't merge models from different creators.")
    creator_id = next(iter(creator_ids))

    if body.group_id is not None:
        group = db.get(VariantGroup, body.group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="Group not found.")
        if body.label is not None:
            group.label = body.label
    else:
        label = body.label or models[0].character or models[0].name
        group = VariantGroup(
            creator_id=creator_id, label=label, source="manual",
            reason="manual", confidence=1.0,
        )
        db.add(group)
        db.flush()
    group.source = "manual"

    orphaned = {m.variant_group_id for m in models if m.variant_group_id not in (None, group.id)}
    for m in models:
        m.variant_group_id = group.id
        # An explicit merge overrides any earlier "keep me out" pin (#678 Phase 5).
        m.no_group = False
        m.updated_at = utcnow()
    if group.rep_model_id is None:
        group.rep_model_id = next((m.id for m in models if m.is_group_rep), models[0].id)
    db.flush()
    for gid in orphaned:
        _prune_empty_group(db, gid)
    db.commit()
    db.refresh(group)
    return group


@router.post("/groups/{group_id}/split", response_model=dict)
def split_group(group_id: int, body: GroupSplitBody, db: Session = Depends(get_db)):
    """Remove members from a group (they become ungrouped). The remaining group is
    marked manual so the split sticks across rescans. Dissolves the group if it
    drops below two members. 409 while a scan is running."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    group = db.get(VariantGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found.")
    ids = set(body.model_ids)
    removed = (
        db.query(Model)
        .filter(Model.variant_group_id == group_id, Model.id.in_(ids))
        .all()
    )
    for m in removed:
        m.variant_group_id = None
        _mark_ungrouped(db, m)
    group.source = "manual"
    # If the designated rep left, fall back to a remaining member.
    if group.rep_model_id in ids:
        rest = db.query(Model).filter(Model.variant_group_id == group_id).first()
        group.rep_model_id = rest.id if rest else None
    db.flush()
    _prune_empty_group(db, group_id)
    db.commit()
    return {"ok": True, "removed": [m.id for m in removed]}


@router.patch("/groups/{group_id}", response_model=VariantGroupRead)
def patch_group(group_id: int, body: GroupPatchBody, db: Session = Depends(get_db)):
    """Relabel a group or set its representative. Marks the group manual."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    group = db.get(VariantGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found.")
    if body.label is not None:
        group.label = body.label
    if body.rep_model_id is not None:
        rep = db.get(Model, body.rep_model_id)
        if rep is None or rep.variant_group_id != group_id:
            raise HTTPException(status_code=400, detail="rep_model_id must be a member of the group.")
        group.rep_model_id = body.rep_model_id
    group.source = "manual"
    db.commit()
    db.refresh(group)
    return group


@router.get("/grouping-strategy")
def get_grouping_strategy(path: str = Query(...), db: Session = Depends(get_db)):
    """Effective grouping strategy for a folder path (nearest ancestor, default auto)."""
    strategies = [(grouping._norm(p), s) for (p, s) in db.query(GroupingStrategy.path, GroupingStrategy.strategy)]
    return {"path": path, "strategy": grouping._resolve_strategy(path, strategies)}


@router.post("/grouping-strategy")
def set_grouping_strategy(body: GroupingStrategyBody, db: Session = Depends(get_db)):
    """Set a per-subtree grouping strategy (#618). "off" leaves the subtree's
    models ungrouped; "auto" clears the override (restores the proposal engine).
    Re-runs the engine for affected creators so the change shows immediately.
    409 while a scan is running."""
    if scanner.get_status()["running"]:
        raise HTTPException(status_code=409, detail="A scan is running — try again after it completes.")
    if body.strategy not in ("auto", "off"):
        raise HTTPException(status_code=400, detail="strategy must be 'auto' or 'off'.")

    if body.strategy == "off":
        stmt = (
            _sqlite_insert(GroupingStrategy)
            .values(path=body.path, strategy="off")
            .on_conflict_do_update(index_elements=["path"], set_={"strategy": "off"})
        )
        db.execute(stmt)
    else:
        db.query(GroupingStrategy).filter(GroupingStrategy.path == body.path).delete()
    db.flush()

    # Re-group only the creators that actually have models under this subtree so
    # the strategy takes effect now rather than at the next scan.
    path_prefix = body.path.rstrip("/\\")
    affected = (
        db.query(Model.creator_id)
        .filter(
            Model.creator_id != None,  # noqa: E711
            (Model.folder_path == body.path)
            | Model.folder_path.like(like_escape(path_prefix) + "%", escape="\\"),
        )
        .distinct()
        .all()
    )
    for (creator_id,) in affected:
        grouping.regroup_creator(db, creator_id)
    db.commit()
    return {"ok": True, "path": body.path, "strategy": body.strategy}
