"""Import pipeline endpoints (#449 epic).

Child A (#450) starts this router with the persisted source→library mapping.
Children B/C/D extend it with the pack-grouped preview projection, scoped
ingest, and batch apply. Module is named `imports` because `import` is a
reserved word.
"""
import asyncio
import logging
import os
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import ImportSourceMapping, Model, ScanRoot, STLFile
from app.routers.reorganize import _build_and_persist, _slugify_all, _slugify_filenames
from app.routers.scan import _bootstrap_roots, _configured_roots
from app.schemas import (
    DownloadImagesRequest, DownloadImagesResult, DownloadImagesStart, DownloadImagesStatus,
    ImportApplyIneligible, ImportApplyRequest, ImportApplyResponse,
    ImportApplyStart, ImportApplyStatus,
    ImportPreviewPack, ImportPreviewResponse, InboxScanRequest,
    SourceContentsEntry, SourceContentsResponse,
    SourceMappingRead, SourceMappingSet,
)
from app.services import reorganize_apply, scanner, write_lock
from app.services.job_runner import JobHandle, JobState, runner
from app.services.path_guard import assert_within_roots
from app.services.reorganize_apply import ApplyError
from app.services.thumbnails import CONTENT_TYPE_EXT, IMAGE_EXTS

# Single global job key — an import-apply's real mutual exclusion comes from
# the write lock apply_manifest already holds; this just lets one apply be
# tracked/polled at a time, mirroring scanner.py's _SCAN_KEY.
_IMPORT_APPLY_KEY = "import_apply"

# Same pattern for the gallery-image download step: one download at a time,
# tracked/polled through the shared job runner.
_DOWNLOAD_IMAGES_KEY = "download_images"
_DOWNLOAD_CONCURRENCY = 6
_DOWNLOAD_IMAGE_TIMEOUT = 10.0

router = APIRouter(prefix="/import", tags=["import"])


# Entry flags (Phase 1) that make a pack ineligible to move, mapped to a reason.
_INELIGIBLE_FLAGS = [
    ("unclassifiable", "missing creator/character"),
    ("collision", "destination collision"),
    ("over_length", "path too long"),
    ("reserved_name", "reserved filename"),
    ("overlaps_other", "overlaps another move"),
    ("spans_multiple_dirs", "files span multiple folders"),
    ("is_symlink", "symlinked"),
    ("escapes_scan_root", "no writable destination library"),
    ("missing_files_on_disk", "files missing on disk"),
]


def _ineligible_reasons(entry) -> list[str]:
    reasons = [label for attr, label in _INELIGIBLE_FLAGS if getattr(entry, attr, False)]
    if getattr(entry, "missing_fields", None):
        reasons.append("missing " + ", ".join(entry.missing_fields))
    return reasons or ["ineligible"]


def _allowed_bases(db: Session) -> list[str]:
    """Resolved allow set for import paths: configured scan roots + the bootstrap
    browse allowlist. Import sources come through the allowlist-guarded folder
    picker, and a pack may sit inside a configured root, so both are permitted."""
    return [os.path.realpath(str(r)) for r in _configured_roots(db) + _bootstrap_roots()]


def _mapped_source_for(db: Session, src: str) -> ImportSourceMapping | None:
    """The mapping covering `src`: an exact match, or the longest mapped ancestor.

    A mapping is set once on the root a user picks in the UI (e.g. `/import`),
    but apply is scoped per-pack (`src` = a specific subfolder under that root)
    so one pack's move can't sweep in every other pending pack. This mirrors the
    longest-prefix resolution build_manifest's own `_dest_for` already does for
    the destination library — this is just the existence check ahead of it."""
    key = os.path.normcase(src)
    best_len, best = -1, None
    for m in db.query(ImportSourceMapping).all():
        mkey = os.path.normcase(m.source_path)
        if (key == mkey or key.startswith(mkey + os.sep)) and len(mkey) > best_len:
            best_len, best = len(mkey), m
    return best


def _pack_key(folder_path: str, source: str) -> str:
    """The pack a model belongs to = the first path segment below `source`.

    A model sitting directly in `source` (flat layout) is its own pack, keyed by
    the source basename. Lexical only (normpath), separator-safe for Windows."""
    rel = os.path.relpath(folder_path, source)
    first = rel.replace("\\", "/").split("/", 1)[0]
    if first in ("", ".", ".."):
        return os.path.basename(source.rstrip("/\\")) or source
    return first


def _collapse(values: list) -> object | None:
    """Single distinct non-empty value across the pack, else None."""
    distinct = {v for v in values if v}
    return next(iter(distinct)) if len(distinct) == 1 else None


@router.get("/source-contents", response_model=SourceContentsResponse)
def source_contents(source: str, db: Session = Depends(get_db)):
    """List a source folder's immediate subfolders as browse-first pack cards (#452).

    `already_imported` flags a subfolder that already has inbox models ingested,
    so a re-listing ("Scan for New Files") distinguishes new packs from imported
    ones. Each entry carries a recursive STL-family file count from disk (#456).
    The source is resolved and confined to the allowed roots (configured scan
    roots + bootstrap allowlist) before any disk access."""
    if not source.strip():
        raise HTTPException(status_code=400, detail="source is required")

    try:
        real = assert_within_roots(source.strip(), _allowed_bases(db))
    except ValueError:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")

    p = Path(real)
    src = real
    if not p.exists() or not p.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    # A source whose root holds STLs directly is a single flat pack (mirrors the
    # inbox scanner's flat-layout branch).
    is_flat = scanner._has_stls(p, recurse=False)

    # Recursive STL-family counts (#456) in one walk rooted at the already-confined
    # `p` (the raising barrier above dominates this sink, so no tainted path is
    # walked): the running total feeds the flat single-card, and each top-level
    # child accumulates its whole subtree for that pack's card.
    total_stls = 0
    child_stls: dict[str, int] = {}
    for dirpath, _dirnames, filenames in os.walk(p):
        n = sum(1 for f in filenames if os.path.splitext(f)[1].lower() in scanner.STL_EXTENSIONS)
        if not n:
            continue
        total_stls += n
        rel = os.path.relpath(dirpath, src)
        if rel != ".":
            top = rel.replace("\\", "/").split("/", 1)[0]
            cp = os.path.normpath(os.path.join(src, top))
            child_stls[cp] = child_stls.get(cp, 0) + n
    root_file_count = total_stls if is_flat else 0

    # Inbox model folder_paths already under this source, for the imported flag.
    prefix = src + os.sep
    imported = {
        os.path.normpath(fp)
        for (fp,) in db.query(Model.folder_path)
        .filter(Model.is_inbox == True)  # noqa: E712
        .filter((Model.folder_path == src) | (Model.folder_path.like(f"{prefix}%")))
    }

    entries: list[SourceContentsEntry] = []
    if not is_flat:
        for d in sorted(p.iterdir(), key=lambda e: e.name.lower()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            dp = os.path.normpath(str(d))
            child_prefix = dp + os.sep
            already = any(m == dp or m.startswith(child_prefix) for m in imported)
            entries.append(SourceContentsEntry(
                name=d.name, path=dp, already_imported=already,
                file_count=child_stls.get(dp, 0),
            ))

    return SourceContentsResponse(
        source=src, is_flat=is_flat, entries=entries, file_count=root_file_count,
    )


@router.post("/scan-folder", response_model=dict)
def scan_folder(body: InboxScanRequest, db: Session = Depends(get_db)):
    """Scoped inbox ingest of a single pack folder (#452, browse-first import).

    Unlike POST /scan/inbox, this does NOT reject a path overlapping a scan root:
    importing a specific folder is explicit, and the source may legitimately live
    inside a configured root. Models are indexed is_inbox=True; the move into the
    destination library is the batch apply (Child D)."""
    status = scanner.get_status()
    if status["running"]:
        raise HTTPException(status_code=409, detail="Scan already running")

    if not body.path.strip():
        raise HTTPException(status_code=400, detail="Path is required")

    try:
        real = assert_within_roots(body.path.strip(), _allowed_bases(db))
    except ValueError:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")

    p = Path(real)
    if not p.exists():
        raise HTTPException(status_code=400, detail="Path does not exist")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    # Launch off the request path via scanner.start_inbox_scan (shared job runner,
    # STUDIO-59): it takes the write lock synchronously so the 200 is authoritative,
    # returns False when the library is busy, and releases the lock on launch
    # failure. Same launcher /scan/inbox uses. single_pack=True (#1087): this
    # endpoint is always scoped to exactly one pack (Import Preview's per-pack
    # Import button, or the browse-a-folder-directly flow) — never a multi-creator
    # dump, unlike /scan/inbox. creator_name (#1110), when the caller already
    # knows it, resolves to the real creator directly — see InboxScanRequest.
    try:
        started = scanner.start_inbox_scan(
            str(p), single_pack=True, creator_name=body.creator_name,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start import: {e}")
    if not started:
        raise HTTPException(
            status_code=409,
            detail="Library is busy — reorganize in progress, try again shortly",
        )

    return {"running": True, "message": "importing"}


@router.get("/preview", response_model=ImportPreviewResponse)
def import_preview(source: str, db: Session = Depends(get_db)):
    """Group the inbox models under a source folder into one card per pack (#451).

    A pack = a top-level subfolder of `source` (flat-layout models at the root
    form a single pack). Representative metadata collapses to the common value
    across the pack, or null when members disagree. The destination library is
    inherited from the persisted source→library mapping."""
    src = os.path.normpath(source.strip())
    if not src or src == ".":
        raise HTTPException(status_code=400, detail="source is required")

    prefix = src + os.sep
    models = (
        db.query(Model)
        .filter(Model.is_inbox == True)  # noqa: E712
        # ilike, not == (STUDIO-316): the flat-layout case needs an exact match
        # too, and SQLite's `==` is byte-case-sensitive — a folder_path stored
        # with different casing than `src` would never even reach the Python
        # normcase filtering below.
        .filter(Model.folder_path.ilike(src) | Model.folder_path.like(f"{prefix}%"))
        .all()
    )

    # Only count models actually under `src` after normalization (LIKE is a coarse
    # prefilter; normpath comparison is authoritative). Compared case-insensitively
    # (normcase) — Windows folder_path/src casing can differ (e.g. `D:\Import` vs
    # `d:\import`), which otherwise silently drops the model from every pack
    # while still preserving mp's original casing for grouping/display (STUDIO-316).
    src_key = os.path.normcase(src)
    prefix_key = os.path.normcase(prefix)
    buckets: dict[str, list[Model]] = {}
    for m in models:
        mp = os.path.normpath(m.folder_path)
        mp_key = os.path.normcase(mp)
        if mp_key != src_key and not mp_key.startswith(prefix_key):
            continue
        buckets.setdefault(_pack_key(mp, src), []).append(m)

    file_counts = dict(
        db.query(STLFile.model_id, func.count(STLFile.id))
        .filter(STLFile.model_id.in_([m.id for m in models]))
        .group_by(STLFile.model_id)
        .all()
    ) if models else {}

    packs: list[ImportPreviewPack] = []
    for key in sorted(buckets):
        members = buckets[key]
        tag_sets = [tuple(sorted(m.tags or [])) for m in members]
        # Flat-layout pack (a model sitting directly in src) → src itself;
        # otherwise the pack lives at src/<key>. normcase (STUDIO-316) for the
        # same reason as the bucketing filter above.
        is_flat = any(os.path.normcase(os.path.normpath(m.folder_path)) == src_key for m in members)
        packs.append(ImportPreviewPack(
            name=key,
            source_path=src if is_flat else os.path.join(src, key),
            file_count=sum(file_counts.get(m.id, 0) for m in members),
            model_ids=sorted(m.id for m in members),
            creator_name=_collapse([m.creator.name if m.creator else None for m in members]),
            title=_collapse([m.title for m in members]),
            character=_collapse([m.character for m in members]),
            notes=_collapse([m.notes for m in members]),
            source_url=_collapse([m.source_url for m in members]),
            tags=list(_collapse(tag_sets) or ()),
        ))

    mapping = _mapped_source_for(db, src)
    return ImportPreviewResponse(
        source=src,
        library_id=mapping.library_id if mapping else None,
        packs=packs,
    )


@router.get("/source-mapping", response_model=SourceMappingRead | None)
def get_source_mapping(path: str, db: Session = Depends(get_db)):
    """Return the destination library mapped to a source root, or null (#450).

    Resolved via _mapped_source_for (STUDIO-315) — the same normcase +
    longest-prefix match POST /import/apply uses — so a mapping saved under a
    different case or trailing separator than the queried path still surfaces
    here instead of silently reading back as unmapped."""
    source = path.strip()
    if not source:
        raise HTTPException(status_code=400, detail="path is required")
    return _mapped_source_for(db, source)


@router.put("/source-mapping", response_model=SourceMappingRead)
def set_source_mapping(body: SourceMappingSet, db: Session = Depends(get_db)):
    """Persist (upsert) a source root → destination library mapping (#450).

    The destination must be a writable library; the actual disk-write probe and
    deployment flag are still enforced at apply time (#324)."""
    source = body.source_path.strip()
    if not source:
        raise HTTPException(status_code=400, detail="source_path is required")

    library = db.query(ScanRoot).filter(ScanRoot.id == body.library_id).first()
    if not library:
        raise HTTPException(status_code=404, detail="Library not found")
    if not library.is_writable:
        raise HTTPException(
            status_code=400,
            detail="Destination is not a writable library.",
        )

    mapping = (
        db.query(ImportSourceMapping)
        .filter(ImportSourceMapping.source_path == source)
        .first()
    )
    if mapping:
        mapping.library_id = library.id
    else:
        mapping = ImportSourceMapping(source_path=source, library_id=library.id)
        db.add(mapping)
    db.commit()
    db.refresh(mapping)
    return mapping


def _image_ext(url: str, content_type: str) -> str:
    """Best-effort image extension from Content-Type, falling back to URL suffix."""
    ext = CONTENT_TYPE_EXT.get(content_type.split(";")[0].strip().lower(), "")
    if ext:
        return ext
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in IMAGE_EXTS else ".jpg"


async def _download_images_async(handle: JobHandle, pack_dir_str: str, urls: list[str]) -> int:
    """Fetch every URL into pack_dir concurrently (bounded), reporting progress
    on handle after each one finishes. Returns the count actually written.

    Concurrent + a short per-image timeout, replacing a fully sequential loop
    with a 30s-per-image timeout — a couple of slow/unreachable CDN URLs used
    to serialize into minutes of dead time with zero feedback to the UI."""
    pack_dir = Path(pack_dir_str)
    total = len(urls)
    downloaded = 0
    done = 0
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(_DOWNLOAD_CONCURRENCY)

    async def fetch_one(client: httpx.AsyncClient, n: int, url: str) -> None:
        nonlocal downloaded, done
        async with sem:
            try:
                r = await client.get(url)
                r.raise_for_status()
                ct = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if ct in ("image/svg+xml", "text/html", "application/json"):
                    logger.warning("gallery image %d skipped — unsupported content-type %r", n, ct)
                    return
                ext = _image_ext(url, ct)
                # Guard: ext must be a known-safe image extension — reject anything
                # that could escape the filename (e.g. a crafted URL suffix).
                if ext not in IMAGE_EXTS:
                    logger.warning("gallery image %d skipped — unexpected ext %r", n, ext)
                    return
                dest = pack_dir / f"gallery_{n:02d}{ext}"
                dest.write_bytes(r.content)
                async with lock:
                    downloaded += 1
            except Exception as e:
                logger.warning("gallery image %d download failed: %s", n, e)
            finally:
                async with lock:
                    done += 1
                    handle.update(
                        message=f"Downloading images ({done}/{total})",
                        downloaded=downloaded, total=total,
                    )

    async with httpx.AsyncClient(
        timeout=_DOWNLOAD_IMAGE_TIMEOUT, follow_redirects=True,
        headers={"User-Agent": "STL-Inventory/1.0"},
    ) as client:
        await asyncio.gather(*(fetch_one(client, n, url) for n, url in enumerate(urls)))
    return downloaded


def _run_download_images_job(handle: JobHandle, pack_dir_str: str, urls: list[str]) -> None:
    """Background body for POST /import/download-images. Runs its own asyncio
    event loop on this job's dedicated thread (JobRunner threads are plain
    sync callables) so the fetches above can run concurrently."""
    downloaded = asyncio.run(_download_images_async(handle, pack_dir_str, urls))
    handle.update(
        state=JobState.DONE,
        message=f"done — {downloaded} image(s)",
        result=DownloadImagesResult(downloaded=downloaded).model_dump(),
    )


@router.post("/download-images", response_model=DownloadImagesStart)
def download_images(body: DownloadImagesRequest, db: Session = Depends(get_db)):
    """Download CDN image URLs into the pack folder so they travel with the pack
    during apply. Called from the import UI after enrichment, before apply.
    Runs as a background job (mirroring /import/apply) — poll
    GET /import/download-images/status for progress and the eventual result."""
    raw_pack_path = body.pack_path.strip()
    if not raw_pack_path:
        raise HTTPException(status_code=400, detail="pack_path is required")
    if "\x00" in raw_pack_path:
        raise HTTPException(status_code=400, detail="pack_path is invalid")

    try:
        pack_dir_str = assert_within_roots(os.path.expanduser(raw_pack_path), _allowed_bases(db))
    except ValueError:
        raise HTTPException(status_code=403, detail="Path is outside the allowed folders")

    pack_dir = Path(pack_dir_str)
    if not pack_dir.is_dir():
        raise HTTPException(status_code=404, detail="Pack folder not found")

    urls = body.image_urls[:30]  # cap at 30 images
    if not urls:
        return DownloadImagesStart(started=False, result=DownloadImagesResult(downloaded=0))

    handle = runner.start(
        _DOWNLOAD_IMAGES_KEY, _run_download_images_job, single_flight=True,
        pack_dir_str=pack_dir_str, urls=urls,
    )
    if handle is None:
        raise HTTPException(status_code=409, detail="An image download is already in progress.")
    return DownloadImagesStart(started=True)


@router.get("/download-images/status", response_model=DownloadImagesStatus)
def download_images_status():
    """Poll target for the job POST /import/download-images starts."""
    payload = runner.status(_DOWNLOAD_IMAGES_KEY)
    prog = payload["progress"]
    result = prog.get("result")
    return DownloadImagesStatus(
        running=payload["state"] == JobState.RUNNING.value,
        message=payload["message"] or "idle",
        downloaded=prog.get("downloaded", 0),
        total=prog.get("total", 0),
        error=payload["error"],
        result=DownloadImagesResult(**result) if result else None,
    )


def _move_non_stl_files(
    old_folder: str,
    new_folder: str,
    models: list,
    db: Session,
) -> None:
    """Move every non-STL file from old_folder to new_folder (preserving relative
    paths) and update image_paths / other_files on all models in that folder.

    Called after the reorganize engine has already moved the STL files, so only
    non-tracked files remain. Images go into model.image_paths; everything else
    into model.other_files."""
    if not os.path.isdir(old_folder):
        return

    new_images: list[str] = []
    new_others: list[str] = []

    for dirpath, dirnames, filenames in os.walk(old_folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            ext = os.path.splitext(filename)[1].lower()
            if ext in scanner.STL_EXTENSIONS:
                continue  # already moved by the reorganize engine

            src = Path(os.path.join(dirpath, filename)).resolve()
            rel = os.path.relpath(str(src), old_folder)
            dst = (Path(new_folder) / rel).resolve()

            # Verify the resolved destination is still inside new_folder to
            # prevent symlink-based traversal escaping the target directory.
            if not dst.is_relative_to(Path(new_folder).resolve()):
                logger.warning("Skipping %r — resolved outside target folder", str(src))
                continue

            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                if ext in IMAGE_EXTS:
                    new_images.append(str(dst))
                else:
                    new_others.append(str(dst))
            except OSError as e:
                logger.warning("Could not move %r → %r: %s", src, dst, e)

    old_boundary = Path(old_folder)
    for m in models:
        # Merge rather than "only overwrite if we moved something new": a
        # model whose old_folder held nothing but hidden-directory junk
        # (e.g. a stale .manyfold cache — #903-follow-up) got an empty
        # new_images, so `if new_images:` never fired and those stale
        # image_paths entries — still pointing at the now-emptied old
        # folder — survived indefinitely. The merge drops anything within
        # old_folder that wasn't rediscovered while preserving paths that
        # live elsewhere (manually-added images, remote URLs, etc.).
        m.image_paths = scanner._merge_scan_gallery_paths(
            existing=m.image_paths or [],
            discovered=new_images,
            removed=m.removed_image_paths or [],
            boundary=old_boundary,
        )
        # Merge, not overwrite (STUDIO-318): the old `m.other_files = new_others`
        # gave every model sharing old_folder the whole folder's rediscovered
        # file list and dropped anything the user had added that lived
        # elsewhere, the same class of bug the image_paths merge above
        # already fixed (#903-follow-up).
        m.other_files = scanner._merge_scan_gallery_paths(
            existing=m.other_files or [],
            discovered=new_others,
            removed=[],
            boundary=old_boundary,
        )
        # Remap thumbnail_path if it pointed into the old folder (stale after
        # move). normpath first: thumbnail_path/folder_path are stored with
        # forward slashes (see Model helpers), so a raw
        # `.startswith(old_folder + os.sep)` against Windows' backslash
        # os.sep never matched — this silently skipped every remap on
        # Windows until normpath puts both sides on the same separator.
        if m.thumbnail_path:
            thumb_norm = os.path.normpath(m.thumbnail_path)
            old_norm = os.path.normpath(old_folder)
            if thumb_norm.startswith(old_norm + os.sep):
                rel = os.path.relpath(thumb_norm, old_norm)
                remapped = os.path.join(new_folder, rel)
                m.thumbnail_path = remapped if os.path.exists(remapped) else None


def _copy_shared_pack_images(
    db: Session, src: str, eligible_ids: list[int],
    all_folder_map: dict[int, str], all_old_to_new: dict[str, str],
) -> None:
    """A single-pack scan (#1087) attaches gallery images sitting at the pack
    ROOT to every nested format-variant model (boundary=inbox at scan time),
    so two sibling variants' image_paths can point at the exact same source
    file outside either model's own folder_path. _move_non_stl_files above
    only walks each model's own folder, so those pack-root images are never
    relocated — image_paths keeps pointing at the old /import location, which
    stops resolving once the model leaves inbox (the file-serving allowlist
    only trusts an is_inbox model's own folder_path), so the gallery goes
    blank despite everything else importing fine.

    Copies (not moves — siblings may share the same source image) any
    still-existing pack-root image referenced in a model's image_paths OR
    thumbnail_path into that model's own new folder, and remaps the entry to
    the copy. thumbnail_path drives the Library grid card image — leaving it
    stale is what made the grid stay blank even after image_paths (used by
    the model detail page's filmstrip) was already fixed."""
    try:
        src_resolved = Path(src).resolve()
    except OSError:
        return
    models = db.query(Model).filter(Model.id.in_(eligible_ids)).all()
    for m in models:
        old_folder = all_folder_map.get(m.id)
        new_folder = old_folder and all_old_to_new.get(old_folder)
        if not new_folder or not os.path.isdir(new_folder):
            continue
        new_resolved = Path(new_folder).resolve()

        def _relocate(path_str: str) -> tuple[str, bool]:
            """Return (possibly-remapped path, changed?)."""
            ip = Path(path_str)
            try:
                ip_resolved = ip.resolve()
            except OSError:
                return path_str, False
            if ip_resolved.is_relative_to(new_resolved) or not ip_resolved.is_relative_to(src_resolved):
                return path_str, False  # already relocated, or not part of this pack
            if not ip_resolved.exists():
                return path_str, False  # dead reference — not this fix's job
            dst = new_resolved / ip_resolved.name
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy2(str(ip_resolved), str(dst))
                return str(dst), True
            except OSError as e:
                logger.warning("Could not copy shared pack image %r -> %r: %s", ip_resolved, dst, e)
                return path_str, False

        changed = False
        remapped: list[str] = []
        for img in (m.image_paths or []):
            new_path, did_change = _relocate(img)
            remapped.append(new_path)
            changed = changed or did_change
        if changed:
            m.image_paths = remapped

        if m.thumbnail_path:
            new_thumb, thumb_changed = _relocate(m.thumbnail_path)
            if thumb_changed:
                m.thumbnail_path = new_thumb
    db.commit()


def _cleanup_non_stl_folders(old_to_new: dict[str, str], db: Session) -> None:
    """Move non-STL files from import folders to their library destinations and
    remove the source folder. Only runs when the destination already exists on
    disk — handles the case where STLs were moved by a prior import session but
    the gallery images were left behind."""
    for old_folder, new_folder in old_to_new.items():
        if not os.path.isdir(old_folder):
            continue
        if not os.path.isdir(new_folder):
            logger.warning(
                "Destination %r does not exist; skipping non-STL cleanup for %r",
                new_folder, old_folder,
            )
            continue
        # Find the library model at the destination so we can update image_paths.
        dest_models = db.query(Model).filter(Model.folder_path == new_folder).all()
        try:
            _move_non_stl_files(old_folder, new_folder, dest_models, db)
            db.commit()
            # "new_folder exists" doesn't prove old_folder's own files ever
            # landed there — it can just as easily be a stray/partial
            # destination from an interrupted earlier run. Only remove
            # old_folder once nothing real is left in it (#1087 data-loss
            # incident — see the matching guard in _run_import_apply_job).
            old_resolved = os.path.realpath(old_folder)
            if any(True for _ in Path(old_resolved).rglob("*") if _.is_file()):
                logger.warning(
                    "Leaving %r in place — still has unaccounted-for files "
                    "after cleanup (not confirmed fully moved)", old_resolved,
                )
                continue
            try:
                shutil.rmtree(old_resolved)
            except OSError as e:
                logger.warning("Could not remove old pack folder %r: %s", old_resolved, e)
        except Exception:
            logger.exception("Non-STL cleanup failed for %r → %r", old_folder, new_folder)


def _retry_with_suffix(
    db: Session, src: str, eligible_ids: list[int], slugify_all: bool,
    slugify_filenames: bool,
) -> tuple[ImportPreviewResponse, list[int]]:
    """Regenerate the manifest with a short random suffix appended to every
    currently-eligible model's title, and return the new (manifest, eligible
    ids) pair for a retry. Only called when nothing has moved yet, so a full
    regenerate-and-retry is safe — this never runs mid-batch.

    ``slugify_all``/``slugify_filenames`` must be the same values the initial
    manifest for this apply was built with (resolved once by the router, not
    re-read here) — reading the settings fresh on retry could pick different
    values than the initial build if a setting changed mid-request, splitting
    this single pack's STL and image destinations across two casings again
    (#874)."""
    suffix = uuid.uuid4().hex[:4]
    overrides = {mid: {"suffix": suffix} for mid in eligible_ids}
    resp = _build_and_persist(
        db, "{creator}/{title}", None, overrides, inbox_source=src,
        slugify_title=True, slugify_all=slugify_all,
        slugify_filenames=slugify_filenames,
    )
    retry_ids = [e.model_id for e in resp.entries if e.eligible]
    return resp, retry_ids


def _cleanup_stale_source_dirs(db: Session, src: str, force_remove_root: bool = False) -> None:
    """Remove now-empty directories left behind in the source root after a
    move. Best-effort: a containment/validation miss skips cleanup rather than
    failing the caller, and any unexpected error is logged, not raised.

    ``force_remove_root`` (#1087): when the caller knows every inbox model
    under ``src`` was successfully moved (nothing left ineligible), whatever
    remains directly in the pack root is import scaffolding no model
    references any more — untracked slicer project files (e.g.
    ``*.chitubox``), a ``config.orynt3d``, or a pack-root gallery image
    that's already been copied into each variant's own destination by
    ``_copy_shared_pack_images``. The default (conservative, empty-dirs-only)
    prune below would leave all of that behind forever, since it never had a
    tracked file of its own to be removed alongside. Only reachable from the
    single-pack Import Preview apply flow, where ``inbox_source`` scoping in
    build_manifest guarantees ``src`` is exactly the one pack folder just
    fully processed — not a shared ancestor of other, untouched packs."""
    matched_root = None
    for _base in _allowed_bases(db):
        _b = os.path.realpath(os.path.expanduser(_base))
        try:
            if os.path.commonpath([src, _b]) == _b:
                matched_root = _b
                break
        except ValueError:
            continue

    try:
        if not matched_root:
            raise ValueError("source not within a configured scan root")
        resolved_root = os.path.realpath(matched_root)
        rel_src = os.path.relpath(src, resolved_root)
        if rel_src == ".." or rel_src.startswith(".." + os.sep):
            raise ValueError("source must be within a configured scan root")
        safe_src = os.path.realpath(os.path.join(resolved_root, rel_src))
        if os.path.commonpath([safe_src, resolved_root]) != resolved_root:
            raise ValueError("source must be within a configured scan root")
        if not os.path.isdir(safe_src):
            raise ValueError("source is not an existing directory")
        if force_remove_root:
            shutil.rmtree(safe_src)
            return
        for dirpath, _, filenames in os.walk(safe_src, topdown=False):
            if not filenames:
                dirpath_resolved = os.path.realpath(dirpath)
                if os.path.commonpath([dirpath_resolved, safe_src]) != safe_src:
                    logger.warning(
                        "Skipping cleanup outside source root: %r (source: %r)",
                        dirpath_resolved, safe_src,
                    )
                    continue
                try:
                    os.rmdir(dirpath_resolved)
                except OSError:
                    pass
    except ValueError as e:
        logger.info("Skipped stale-dir cleanup after import: %s", e)
    except Exception:
        logger.exception("Stale-dir cleanup after import failed (non-fatal)")


def _run_import_apply_job(
    handle: JobHandle,
    manifest_id: str,
    eligible_ids: list[int],
    ineligible: list[ImportApplyIneligible],
    src: str,
    all_old_to_new: dict[str, str],
    all_folder_map: dict[int, str],
    all_proposed_dirs: dict[int, str],
    slugify_all: bool,
    slugify_filenames: bool,
    is_single_pack: bool = False,
) -> None:
    """Background body for POST /import/apply once there's real work to do.
    Moving files (and the best-effort cleanup after) can take a while for a
    large/nested pack or a slow mount — running it off the request thread
    means the client polls GET /import/apply/status for real progress instead
    of one long-lived HTTP request with zero feedback either way it ends."""
    db = SessionLocal()
    try:
        def _on_progress(moved: int, total: int) -> None:
            handle.update(message=f"Moving files ({moved}/{total})", moved_files=moved, total_files=total)

        try:
            result = reorganize_apply.apply_manifest(
                db, manifest_id, eligible_ids, on_progress=_on_progress,
            )
        except write_lock.LibraryBusy as e:
            handle.update(state=JobState.ERROR, error=str(e), message=str(e))
            return
        except ApplyError as e:
            if e.detail.get("moved", 0) != 0 or "already exists" not in str(e):
                handle.update(state=JobState.ERROR, error=str(e), message=str(e))
                return
            # Nothing moved yet, and the destination already has a stray file
            # on disk (e.g. left over from an earlier interrupted import at
            # the same path) — safe to retry once with an auto-disambiguated
            # destination instead of failing the whole import outright.
            logger.warning("Import destination collision for %r — retrying with a suffix", src)
            resp, eligible_ids = _retry_with_suffix(db, src, eligible_ids, slugify_all, slugify_filenames)
            if not eligible_ids:
                handle.update(state=JobState.ERROR, error=str(e), message=str(e))
                return
            manifest_id = resp.manifest_id
            try:
                result = reorganize_apply.apply_manifest(
                    db, manifest_id, eligible_ids, on_progress=_on_progress,
                )
            except (write_lock.LibraryBusy, ApplyError) as e2:
                handle.update(state=JobState.ERROR, error=str(e2), message=str(e2))
                return
            # The retry manifest picked a different (suffixed) proposed_dir for
            # these models — the pre-retry all_old_to_new still points at the
            # stray/colliding folder, not where the files actually landed.
            # Refresh it so the non-STL cleanup pass below moves images into
            # the real destination instead of the leftover collision folder.
            for entry in resp.entries:
                if entry.model_id in eligible_ids:
                    old = all_folder_map.get(entry.model_id)
                    if old:
                        all_old_to_new[old] = entry.proposed_dir
                    all_proposed_dirs[entry.model_id] = entry.proposed_dir

        handle.update(message="Cleaning up")
        # Move all remaining non-STL files (images, PDFs, etc.) from each old
        # folder to the new library folder, then remove the now-empty source.
        try:
            # All manifest entries (not just eligible_ids), STUDIO-317: an
            # ineligible model whose destination already exists on disk still
            # gets its files physically moved by _move_non_stl_files below, so
            # it must be in models_here to get image_paths/thumbnail_path
            # remapped too — otherwise its gallery keeps pointing at the
            # now-deleted source folder despite the files having moved.
            model_by_id = {
                m.id: m
                for m in db.query(Model).filter(Model.id.in_(list(all_folder_map))).all()
            }
            for old_folder, new_folder in all_old_to_new.items():
                # For ineligible packs only move non-STL files if the
                # destination already exists; eligible packs always get moved.
                if not os.path.isdir(new_folder):
                    continue
                # STUDIO-319: all_old_to_new is first-wins per old_folder.
                # Model.folder_path is DB-unique, so two distinct models can't
                # literally share an old_folder today — this can't currently
                # trigger — but if that constraint is ever relaxed, a model
                # whose OWN proposed_dir differs from the winning new_folder
                # is excluded here rather than silently having its
                # image_paths/thumbnail_path remapped to the wrong
                # destination. Defensive only; left in as cheap insurance.
                models_here = []
                for mid, old in all_folder_map.items():
                    if old != old_folder or mid not in model_by_id:
                        continue
                    own_dir = all_proposed_dirs.get(mid)
                    if own_dir and own_dir != new_folder:
                        logger.warning(
                            "Import destination collision: model %s wants %r but "
                            "old_folder %r already claimed by %r — leaving model %s "
                            "unmoved for retry", mid, own_dir, old_folder, new_folder, mid,
                        )
                        continue
                    models_here.append(model_by_id[mid])
                _move_non_stl_files(old_folder, new_folder, models_here, db)
                # Resolve before checking/removing so symlink traversal is
                # collapsed first. "new_folder already exists" is not proof
                # this old_folder's own STLs were actually moved there — it
                # can just as easily be a stray/partial destination left by
                # an earlier interrupted run (e.g. the apply job's process
                # dying mid-move). Blindly rmtree-ing here deleted 9 STL
                # files from a still-ineligible model that never got a
                # chance to move (#1087 data-loss incident) — only remove
                # old_folder once _move_non_stl_files has emptied it out;
                # any file still sitting in it (most commonly STLs an
                # ineligible/partial model never got to move) means it's
                # not actually done, so leave it for a future retry instead
                # of discarding it.
                old_resolved = os.path.realpath(old_folder)
                if any(True for _ in Path(old_resolved).rglob("*") if _.is_file()):
                    logger.warning(
                        "Leaving %r in place — still has unaccounted-for files "
                        "after cleanup (not confirmed fully moved)", old_resolved,
                    )
                    continue
                try:
                    shutil.rmtree(old_resolved)
                except OSError as rmtree_err:
                    logger.warning("Could not remove old pack folder %r: %s", old_resolved, rmtree_err)
            db.commit()
        except Exception:
            logger.exception("Non-STL file move/cleanup failed; STL files were already moved successfully")

        try:
            _copy_shared_pack_images(db, src, eligible_ids, all_folder_map, all_old_to_new)
        except Exception:
            logger.exception("Shared pack-root image copy failed (non-fatal)")

        # Every inbox model build_manifest found under src is now accounted
        # for (moved) — nothing left ineligible means it's safe to remove the
        # whole pack folder outright, not just prune what's now empty. Only
        # for a single-pack apply — src is the whole mapped root in the
        # "Import All" case, and force-removing that could delete files no
        # model here ever touched (see is_single_pack above).
        _cleanup_stale_source_dirs(db, src, force_remove_root=is_single_pack and not ineligible)

        final = ImportApplyResponse(
            manifest_id=result.manifest_id,
            moved_models=result.moved_models,
            moved_files=result.moved_files,
            skipped=len(ineligible),
            ineligible=ineligible,
            undo_log=result.undo_log,
        )
        handle.update(
            state=JobState.DONE,
            message=f"done — {result.moved_models} model(s), {result.moved_files} file(s)",
            result=final.model_dump(mode="json"),
        )
    finally:
        db.close()


@router.post("/apply", response_model=ImportApplyStart)
def import_apply(body: ImportApplyRequest, db: Session = Depends(get_db)):
    """Batch-move the ingested inbox packs under a source into their mapped
    library (#453). Builds a manifest scoped to those inbox models (destination
    = mapped library via the source→library mapping); when there's anything to
    move, the actual apply + cleanup runs as a background job — poll
    GET /import/apply/status for progress and the eventual result. Everything
    the job does is identical to the old synchronous body: drift verification
    + crash-safe undo log, is_inbox cleared on move (#324), then non-STL files
    (images, PDFs, etc.) moved and the old pack folder removed."""
    if not body.source.strip():
        raise HTTPException(status_code=400, detail="source is required")
    src = os.path.realpath(body.source.strip())

    mapping = _mapped_source_for(db, src)
    if not mapping:
        raise HTTPException(status_code=400, detail="No destination library mapped for this source.")
    # A mapping is set once on the whole source root the user picked (e.g.
    # `/import`) via the "Import All" flow, which applies that exact root —
    # `src == mapping.source_path` there. The Import Preview per-pack button
    # instead applies one specific pack subfolder underneath it. Only the
    # latter is safe to remove wholesale on a fully-successful apply (#1087):
    # sweeping the whole mapped root could delete not-yet-scanned files that
    # were never part of any model this apply touched.
    is_single_pack = os.path.normcase(src) != os.path.normcase(os.path.realpath(mapping.source_path))

    # Use {creator}/{title} template so imports land in creator/slug-of-title.
    # slugify_title=True converts the {title} segment to a lowercase-dashes slug.
    # slugify_all mirrors the Reorganize page's reorganize_slugify setting so an
    # import lands already-organized without a separate manual Reorganize pass —
    # but it's resolved ONCE here and threaded through the whole apply (including
    # a collision retry), never re-read mid-request. Reading it fresh at each step
    # is what caused a single pack's STL and image destinations to split across
    # two casings when the setting changed between calls (#874).
    slugify_all = _slugify_all(db)
    slugify_filenames = _slugify_filenames(db)
    resp = _build_and_persist(
        db, "{creator}/{title}", None, None, inbox_source=src,
        slugify_title=True, slugify_all=slugify_all,
        slugify_filenames=slugify_filenames,
    )
    eligible_ids = [e.model_id for e in resp.entries if e.eligible]
    ineligible = [
        ImportApplyIneligible(
            model_id=e.model_id, proposed_dir=e.proposed_dir, reasons=_ineligible_reasons(e),
        )
        for e in resp.entries if not e.eligible
    ]

    # Capture old folder paths for ALL manifest entries (eligible + ineligible) so
    # we can move non-STL files and remove old pack folders regardless of eligibility.
    all_model_ids = [e.model_id for e in resp.entries]
    all_folder_map: dict[int, str] = {
        m.id: m.folder_path
        for m in db.query(Model).filter(Model.id.in_(all_model_ids)).all()
        if m.folder_path
    }
    # old→new from ALL manifest entries; we only move non-STL files when the
    # destination already exists on disk (covers "files missing on disk" ineligible
    # models whose STLs were already moved by a prior import).
    all_old_to_new: dict[str, str] = {}
    # Every entry's own proposed_dir (STUDIO-319) — lets the job tell a real
    # destination collision (two models sharing old_folder but wanting
    # different new folders) apart from two entries that simply agree, so the
    # loser isn't silently remapped to the winner's destination.
    all_proposed_dirs: dict[int, str] = {
        e.model_id: e.proposed_dir for e in resp.entries if e.proposed_dir
    }
    for entry in resp.entries:
        old = all_folder_map.get(entry.model_id, "")
        if old and old not in all_old_to_new and entry.proposed_dir:
            all_old_to_new[old] = entry.proposed_dir

    if not eligible_ids:
        # No STLs to move, but still clean up non-STL files (gallery images, etc.)
        # that were downloaded into the import folder before eligibility was checked.
        _cleanup_non_stl_folders(all_old_to_new, db)
        return ImportApplyStart(started=False, result=ImportApplyResponse(
            manifest_id=resp.manifest_id, moved_models=0, moved_files=0,
            skipped=len(ineligible), ineligible=ineligible,
        ))

    handle = runner.start(
        _IMPORT_APPLY_KEY, _run_import_apply_job, single_flight=True,
        manifest_id=resp.manifest_id, eligible_ids=eligible_ids, ineligible=ineligible,
        src=src, all_old_to_new=all_old_to_new, all_folder_map=all_folder_map,
        all_proposed_dirs=all_proposed_dirs,
        slugify_all=slugify_all, slugify_filenames=slugify_filenames,
        is_single_pack=is_single_pack,
    )
    if handle is None:
        raise HTTPException(status_code=409, detail="An import is already in progress.")
    return ImportApplyStart(started=True)


@router.get("/apply/status", response_model=ImportApplyStatus)
def import_apply_status():
    """Poll target for the job POST /import/apply starts. Uniform job payload
    mapped to the import-apply contract, mirroring GET /scan/status."""
    payload = runner.status(_IMPORT_APPLY_KEY)
    prog = payload["progress"]
    result = prog.get("result")
    return ImportApplyStatus(
        running=payload["state"] == JobState.RUNNING.value,
        message=payload["message"] or "idle",
        moved_files=prog.get("moved_files", 0),
        total_files=prog.get("total_files", 0),
        error=payload["error"],
        result=ImportApplyResponse(**result) if result else None,
    )
