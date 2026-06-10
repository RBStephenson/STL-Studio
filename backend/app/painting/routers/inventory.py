"""PaintRack CSV import/export endpoints (#242/#243, spec §7.3).

Import is a two-step flow: POST /inventory/import returns a diff preview and
writes nothing; POST /inventory/import/confirm re-sends the same CSV plus
which diff sections to apply, recomputes server-side, and applies. Stateless —
nothing from the preview is trusted.
"""
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.painting.services import inventory

router = APIRouter()


async def _read_rows(file: UploadFile) -> list[inventory.CsvRow]:
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    try:
        return inventory.parse_paintrack_csv(text)
    except inventory.PaintRackFormatError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/inventory/import")
async def import_preview(file: UploadFile = File(...), db: Session = Depends(get_db)):
    rows = await _read_rows(file)
    diff = inventory.compute_diff(db, rows)
    return {
        **diff,
        "summary": {
            "rows": len(rows),
            "added": len(diff["added"]),
            "changed": len(diff["changed"]),
            "removed": len(diff["removed"]),
        },
    }


@router.post("/inventory/import/confirm")
async def import_confirm(
    file: UploadFile = File(...),
    apply_added: bool = Form(True),
    apply_changed: bool = Form(True),
    apply_removed: bool = Form(False),
    db: Session = Depends(get_db),
):
    rows = await _read_rows(file)
    source_label = f"{inventory.IMPORT_SOURCE_PREFIX} {date.today().isoformat()}"
    counts = inventory.apply_diff(
        db, rows,
        apply_added=apply_added,
        apply_changed=apply_changed,
        apply_removed=apply_removed,
        source_label=source_label,
    )
    return {"ok": True, "applied": counts, "source": source_label}


@router.get("/inventory/export.csv")
def export_csv(db: Session = Depends(get_db)):
    content = inventory.export_csv(db)
    stamp = date.today().isoformat()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="paintRack_export_{stamp}.csv"'
        },
    )
