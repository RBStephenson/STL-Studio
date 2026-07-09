"""
Library reorganize — Phase 2a apply (#324).

Executes an approved, persisted manifest (built in Phase 1, #323): re-verifies each
source file hasn't drifted since preview, moves the files safely, writes a
crash-safe undo log, then repaths the DB in a single transaction. This is the only
code in the app that moves user files, so every step is defensive.

Scope boundary (2a): there is no undo *endpoint* yet. A failure mid-batch stops
and leaves the append-only undo log for recovery; the DB is repathed only when the
whole batch succeeds, so a partial move never leaves the catalog half-rewritten.

Move safety:
  - never overwrite an existing non-source destination;
  - cross-device (EXDEV) moves go copy → fsync → verify-size → atomic os.replace →
    unlink-source, not a bare rename;
  - case-only renames use a temp-name dance (case-insensitive filesystems treat
    ``Foo`` and ``foo`` as the same entry);
  - moves run deepest-source-first so a destination nested under another source is
    never clobbered.

The move and stat primitives are injectable so tests can simulate EXDEV, a
mid-batch crash, and drift without a second real filesystem.
"""
import errno
import json
import logging
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.models import AppSetting, Model, PackOverride, ReorganizeManifest, ScanRoot, STLFile
from app.services import write_lock
from app.utils import utcnow

_log = logging.getLogger(__name__)

MoveFn = Callable[[str, str], None]
StatFn = Callable[[str], tuple[int, int]]   # path -> (size_bytes, mtime_ns)

# The reorganize feature flag (app_settings). Default off — see AppSettingsRead.
REORGANIZE_ENABLED_KEY = "reorganize_enabled"
_REORGANIZE_ENABLED_DEFAULT = False


def reorganize_enabled(db: Session) -> bool:
    """Whether the Library reorganize feature is enabled (app-setting flag).

    Single source of truth for both the destructive apply/undo write gate here
    and the read-only ``write_enabled`` hint the libraries endpoint surfaces.
    """
    row = db.get(AppSetting, REORGANIZE_ENABLED_KEY)
    return bool(row.value) if row is not None else _REORGANIZE_ENABLED_DEFAULT


class ApplyError(Exception):
    """Apply failed a precondition or safety check. ``status`` maps to HTTP."""

    def __init__(self, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(message)
        self.status = status
        self.detail = detail or {}


@dataclass
class ApplyResult:
    manifest_id: str
    moved_files: int
    moved_models: int
    undo_log: str


def _os_native(path: str) -> str:
    """Canonical '/'-internal path → an OS-native path for disk operations."""
    return str(Path(path))


def _stat(path: str) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_size, st.st_mtime_ns


def _key(path: str) -> str:
    """Case-insensitive identity key (matches the Phase 1 builder's casefold key)."""
    return unicodedata.normalize("NFC", path or "").replace("\\", "/").casefold()


# Manifest ids are generated as ``uuid4().hex`` (32 lowercase hex chars). The id
# arrives from the request body and is interpolated into the undo-log *filename*,
# so it must be allow-listed before any path use — otherwise a value like
# ``../../etc`` would escape the data dir (path traversal). Reject anything that
# isn't exactly the expected token.
_MANIFEST_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")


def _validate_manifest_id(manifest_id: str) -> str:
    if not _MANIFEST_ID_RE.match(manifest_id or ""):
        raise ApplyError("Invalid manifest id", status=400)
    return manifest_id


def _allowed_roots(db: Session) -> list[str]:
    """Normalized scan-root directories — the only places apply/undo may touch.

    Every move source and destination must resolve inside one of these. Phase 1
    already marks scan-root escapes ineligible, but apply executes a *persisted*
    manifest, so re-confining here defends against a tampered manifest row and
    keeps the path a move operates on from being uncontrolled user data."""
    return [os.path.normpath(os.path.abspath(r.path))
            for r in db.query(ScanRoot).all() if r.path]


def _confine(raw: str, roots: list[str]) -> str:
    """Normalize a manifest path and assert it lives under an allowed scan root.

    Returns the normalized OS-native path to use for the actual file operation
    (reassigning to the validated value is the path-traversal barrier). Raises if
    the path escapes every root. Uses normpath (lexical, case-preserving) — never
    realpath — so case-only renames aren't canonicalized away."""
    native = os.path.normpath(os.path.abspath(_os_native(raw)))
    for root in roots:
        if native == root or native.startswith(root + os.sep):
            return native
    raise ApplyError(f"Path escapes the allowed scan roots: {raw}", status=400,
                     detail={"path": raw})


def _safe_move(src: str, dst: str) -> None:
    """Move one file from src to dst with the safety guarantees above.

    Raises OSError/ApplyError-free; callers wrap. Assumes src exists (drift check
    ran) and dst's existence has business meaning."""
    src_n, dst_n = _os_native(src), _os_native(dst)
    same_entry = _key(src) == _key(dst)

    # Never overwrite a *different* existing file at the destination.
    if os.path.exists(dst_n) and not same_entry:
        raise FileExistsError(f"destination already exists: {dst}")

    os.makedirs(os.path.dirname(dst_n) or ".", exist_ok=True)

    # Case-only rename on a case-insensitive FS: os.replace(Foo→foo) can no-op or
    # refuse, so stage through a temp name.
    if same_entry and src_n != dst_n:
        tmp = src_n + ".reorgtmp"
        os.rename(src_n, tmp)
        os.replace(tmp, dst_n)
        return

    try:
        os.rename(src_n, dst_n)
        return
    except OSError as e:
        if e.errno != errno.EXDEV:
            raise
    # Cross-device: copy to a temp sibling, fsync, verify, atomic swap, unlink src.
    tmp = dst_n + ".reorgtmp"
    shutil.copyfile(src_n, tmp)
    with open(tmp, "rb") as fh:
        os.fsync(fh.fileno())
    if os.path.getsize(tmp) != os.path.getsize(src_n):
        os.unlink(tmp)
        raise OSError(f"size mismatch after cross-device copy of {src}")
    os.replace(tmp, dst_n)
    os.unlink(src_n)


class _UndoLog:
    """Append-only, newline-delimited JSON, one record per completed move,
    fsync'd after each write. Lives beside the DB (never under the library root a
    move could relocate), so a kill mid-batch leaves a replayable partial log."""

    def __init__(self, manifest_id: str):
        self.path = undo_log_path(manifest_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def record(
        self, src: str, dst: str, size_bytes: int, mtime_ns: int,
        kind: str = "stl", model_id: int | None = None,
    ) -> None:
        rec = {
            "from": src, "to": dst,
            "size_bytes": size_bytes, "mtime_ns": mtime_ns,
            "ts": utcnow().isoformat(), "status": "done",
            "kind": kind, "model_id": model_id,
        }
        self._fh.write(json.dumps(rec) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        try:
            self._fh.close()
        except OSError:
            pass


def _load_manifest(db: Session, manifest_id: str) -> dict:
    row = db.get(ReorganizeManifest, manifest_id)
    if row is None:
        raise ApplyError("Manifest not found — regenerate the preview", status=404)
    return row.payload


def _select_entries(payload: dict, entry_ids: list[int]) -> list[dict]:
    wanted = set(entry_ids)
    selected = [e for e in payload.get("entries", []) if e["model_id"] in wanted]
    missing = wanted - {e["model_id"] for e in selected}
    if missing:
        raise ApplyError(f"Entries not in manifest: {sorted(missing)}", status=400)
    ineligible = [e["model_id"] for e in selected if not e["eligible"]]
    if ineligible:
        raise ApplyError(
            "Selected entries are ineligible — resolve blockers and regenerate",
            status=409, detail={"ineligible": ineligible},
        )
    return selected


def _probe_writable(dirs: set[str], roots: list[str]) -> None:
    """Create+delete a temp file under each destination's nearest existing
    ancestor. Re-run at apply time because permissions vary per subtree and the
    read-only Docker mount must fail here, not after a partial move."""
    for d in sorted(dirs):
        target = Path(_confine(d, roots))
        while not target.exists():
            parent = target.parent
            if parent == target:
                break
            target = parent
        probe = target / ".reorg_write_probe"
        try:
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            raise ApplyError(
                f"Destination is not writable: {d} ({e})", status=409,
                detail={"path": d},
            )


def _verify_no_drift(
    selected: list[dict], stat_fn: StatFn, roots: list[str], src_roots: list[str] | None = None
) -> None:
    """Re-stat every source; abort the whole batch on any fingerprint mismatch."""
    _src = src_roots if src_roots is not None else roots
    drifted: list[str] = []
    for entry in selected:
        for f in entry["files"]:
            try:
                size, mtime_ns = stat_fn(_confine(f["current_path"], _src))
            except OSError:
                drifted.append(f["current_path"])
                continue
            if size != f["size_bytes"] or mtime_ns != f["mtime_ns"]:
                drifted.append(f["current_path"])
    if drifted:
        raise ApplyError(
            "Source files changed since preview — regenerate the manifest",
            status=409, detail={"drifted": drifted},
        )


def _ordered_moves(selected: list[dict]) -> list[dict]:
    """Flatten entries to per-file moves, deepest source first so a destination
    nested under another source can't destroy the child before it's extracted.

    Each move carries its owning model_id — undo needs it to repath an image
    move directly (there's no STLFile row to look it up by, the way an STL
    move's model is found)."""
    moves = [
        {**f, "model_id": entry["model_id"]}
        for entry in selected for f in entry["files"]
    ]
    moves.sort(key=lambda f: f["current_path"].count("/"), reverse=True)
    return moves


def apply_manifest(
    db: Session,
    manifest_id: str,
    entry_ids: list[int],
    *,
    move_fn: MoveFn = _safe_move,
    stat_fn: StatFn = _stat,
    on_progress: Callable[[int, int], None] | None = None,
) -> ApplyResult:
    """Execute the selected entries of a persisted manifest. See module docstring
    for the safety contract. Raises ApplyError (mapped to HTTP by the router) or
    write_lock.LibraryBusy on contention.

    ``on_progress(moved, total)``, when given, is called after each file moves
    — purely additive, optional progress reporting for a caller that wants to
    surface it (e.g. import-apply's background job); existing callers that
    don't pass it see no behavior change."""
    if not reorganize_enabled(db):
        raise ApplyError(
            "Reorganize is disabled — enable it on the Library settings tab",
            status=403,
        )
    _validate_manifest_id(manifest_id)

    payload = _load_manifest(db, manifest_id)
    selected = _select_entries(payload, entry_ids)
    roots = _allowed_roots(db)

    # Inbox models live outside scan roots — their source dirs must be allowed as
    # move sources (only). Destinations must still be within a scan root.
    inbox_src_dirs: list[str] = []
    for entry in selected:
        m = db.get(Model, entry["model_id"])
        if m and m.is_inbox and m.folder_path:
            inbox_src_dirs.append(
                os.path.normpath(os.path.abspath(_os_native(m.folder_path)))
            )
    src_roots = roots + inbox_src_dirs

    # Persist the approved inbox source dirs into the *trusted* manifest row
    # (DB-backed) so undo can validate restore targets without trusting the
    # writable undo log on disk. Written before any move so a crash mid-batch
    # still leaves undo able to confine the original inbox paths.
    if inbox_src_dirs:
        row = db.get(ReorganizeManifest, manifest_id)
        if row is not None:
            row.payload = {**row.payload, "applied_inbox_roots": sorted(set(inbox_src_dirs))}
            db.commit()

    dest_dirs = {e["proposed_dir"] for e in selected}
    _probe_writable(dest_dirs, roots)

    # Hold the app-wide write lock for the whole operation: no scan may prune or
    # insert rows under the move, and no second apply/undo may interleave.
    with write_lock.library_write("apply", timeout=0.0):
        _verify_no_drift(selected, stat_fn, roots, src_roots=src_roots)

        log = _UndoLog(manifest_id)
        moves = _ordered_moves(selected)
        total = len(moves)
        moved = 0
        # (model_id, current_path) of image moves skipped below — never STL
        # moves, which still hard-fail. Excluded from _repath_db afterward so
        # the DB isn't repathed to a destination the file was never actually
        # written to.
        skipped_images: set[tuple[int | None, str]] = set()
        try:
            for f in moves:
                # Source may be an inbox dir (outside scan roots); destination
                # must always be within a scan root. The value the move operates
                # on is now validated, not raw manifest data.
                src = _confine(f["current_path"], src_roots)
                dst = _confine(f["proposed_path"], roots)
                try:
                    move_fn(src, dst)
                except FileExistsError:
                    # A non-STL image colliding with an unrelated leftover file
                    # (e.g. marketing art bundled with a download, or debris
                    # from an earlier interrupted apply) isn't worth failing an
                    # otherwise-successful STL move over — skip it and keep
                    # going. An STL collision is never this forgiving: it still
                    # aborts the batch below, since a wrong/missing STL file is
                    # a real data problem, not an incidental extra image.
                    if f.get("kind") != "image":
                        raise
                    _log.warning(
                        "Skipping colliding image (destination already exists): %s", dst,
                    )
                    skipped_images.add((f.get("model_id"), f["current_path"]))
                    continue
                # Record only AFTER the move completes — the log is the recovery
                # source of truth, so it must reflect reality on disk.
                log.record(
                    f["current_path"], f["proposed_path"], f["size_bytes"], f["mtime_ns"],
                    kind=f.get("kind", "stl"), model_id=f.get("model_id"),
                )
                moved += 1
                if on_progress is not None:
                    on_progress(moved, total)
        except Exception as e:
            # 2a does not auto-undo: stop, keep the partial log for recovery, and
            # leave the DB untouched so the catalog isn't half-rewritten.
            raise ApplyError(
                f"Move failed after {moved} file(s) — recovery log written, DB unchanged: {e}",
                status=500, detail={"undo_log": str(log.path), "moved": moved},
            ) from e
        finally:
            log.close()

        if skipped_images:
            for entry in selected:
                entry["files"] = [
                    f for f in entry["files"]
                    if (entry["model_id"], f["current_path"]) not in skipped_images
                ]

        _repath_db(db, selected)
        _prune_empty_sources(selected)
        return ApplyResult(
            manifest_id=manifest_id,
            moved_files=moved,
            moved_models=len(selected),
            undo_log=str(log.path),
        )


def _repath_db(db: Session, selected: list[dict]) -> None:
    """Update Model.folder_path, STLFile.path, the model's own image fields,
    and the path-keyed PackOverride references — all in one transaction under
    the write lock. A row-by-row repath in a partially-moved state would race
    the unique constraints on STLFile.path / Model.folder_path.

    GroupOverride no longer needs this (#678 Phase 5): the equivalent flag
    (Model.no_group) lives on the Model row itself, so it moves for free."""
    for entry in selected:
        model = db.get(Model, entry["model_id"])
        if model is not None:
            model.folder_path = entry["proposed_dir"]
            model.is_inbox = False   # moved into the managed library
            model.updated_at = utcnow()
        for f in entry["files"]:
            if f.get("kind") == "image":
                if model is not None:
                    _repath_model_image(model, f["current_path"], f["proposed_path"])
                continue
            stl = db.get(STLFile, f["stl_file_id"])
            if stl is not None:
                stl.path = f["proposed_path"]

        old_dir = _entry_source_dir(entry)
        new_dir = entry["proposed_dir"]
        if old_dir is not None:
            _repath_overrides(db, PackOverride, old_dir, new_dir)
    db.commit()


def _repath_model_image(model: Model, old_path: str, new_path: str) -> None:
    """Point a moved gallery image's occurrences on the model row at its new
    location — image_paths, thumbnail_path, primary_image_path, and any
    removed_image_paths entry (so a previously-removed image doesn't
    reappear on the next rescan just because its old path no longer matches
    the moved file's new one)."""
    old_key = _key(old_path)
    if isinstance(model.image_paths, list):
        model.image_paths = [
            new_path if _key(p) == old_key else p
            for p in model.image_paths
        ]
    if model.thumbnail_path and _key(model.thumbnail_path) == old_key:
        model.thumbnail_path = new_path
    if model.primary_image_path and _key(model.primary_image_path) == old_key:
        model.primary_image_path = new_path
    if isinstance(model.removed_image_paths, list):
        model.removed_image_paths = [
            new_path if _key(p) == old_key else p
            for p in model.removed_image_paths
        ]


def _entry_source_dir(entry: dict) -> str | None:
    """The model's source folder, derived from the first file's source parent.
    All eligible entries are single-dir (multi-dir is flagged ineligible in
    Phase 1), so the first file's parent is the model dir."""
    files = entry["files"]
    if not files:
        return None
    cur = files[0]["current_path"]
    return cur.rsplit("/", 1)[0] if "/" in cur else None


def _repath_overrides(db: Session, model_cls, old_dir: str, new_dir: str) -> None:
    """Repath any path-keyed override row (e.g. PackOverride) whose path is the
    moved dir or nested under it, preserving the suffix below the model dir."""
    old_key = _key(old_dir)
    for row in db.query(model_cls).all():
        rk = _key(row.path or "")
        if rk == old_key:
            row.path = new_dir
        elif rk.startswith(old_key + "/"):
            suffix = row.path[len(old_dir):]
            row.path = new_dir + suffix


def _prune_empty_sources(selected: list[dict]) -> None:
    """Remove now-empty source directories — only if truly empty. Never recursive:
    a non-empty source means a sibling model still lives there."""
    for entry in selected:
        old_dir = _entry_source_dir(entry)
        if old_dir is None:
            continue
        native = Path(_os_native(old_dir))
        try:
            if native.is_dir() and not any(native.iterdir()):
                native.rmdir()
        except OSError:
            pass


# --- Phase 2b: undo --------------------------------------------------------


@dataclass
class UndoResult:
    manifest_id: str
    reversed_files: int
    skipped: list[dict]               # [{path, reason}] entries left in place


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def undo_log_path(manifest_id: str) -> Path:
    """Validated path of a manifest's undo log.

    ``manifest_id`` is allow-listed to the generated token, then the assembled
    path is normalized and re-confined under the data dir — the same containment
    barrier the move paths use — so the request-supplied value provably can't
    traverse out (belt and braces, and a sanitizer CodeQL recognizes)."""
    safe = _validate_manifest_id(manifest_id)
    base = write_lock.data_dir().resolve()
    # os.path.basename makes it explicit to CodeQL that no directory component
    # can survive — only the bare filename part of `safe` is used.
    filename = "reorg_undo_" + os.path.basename(safe) + ".log"
    candidate = (base / filename).resolve()
    # The log is a single file directly under the data dir; its resolved parent
    # must be exactly that dir. resolve() + parent-equality is the path-traversal
    # barrier CodeQL models (plain normpath/startswith was not recognized).
    if candidate.parent != base:
        raise ApplyError("Invalid manifest id", status=400)
    return candidate


def _read_undo_log(manifest_id: str) -> list[dict]:
    path = undo_log_path(manifest_id)
    if not path.exists():
        raise ApplyError("No undo log for this manifest — nothing to undo", status=404)
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def undo_manifest(
    db: Session,
    manifest_id: str,
    *,
    move_fn: MoveFn = _safe_move,
    stat_fn: StatFn = _stat,
) -> UndoResult:
    """Reverse a completed apply by replaying its undo log to → from in reverse.

    Idempotent and partial-apply safe: each step is re-derived from the log plus
    current disk state, never assumed. A destination (``to``) that's missing,
    drifted, or whose origin (``from``) is now occupied is skipped and reported,
    not forced. Running undo twice simply skips everything the first run already
    reversed.
    """
    if not reorganize_enabled(db):
        raise ApplyError(
            "Reorganize is disabled — enable it on the Library settings tab",
            status=403,
        )

    records = _read_undo_log(manifest_id)
    roots = _allowed_roots(db)

    # Restore targets are confined to the scan roots PLUS the inbox source dirs
    # this manifest actually approved at apply time. Those are read from the
    # trusted manifest row (DB), never from the writable undo log — so a tampered
    # log cannot redirect a restore outside an approved root.
    row = db.get(ReorganizeManifest, manifest_id)
    applied_inbox = list((row.payload.get("applied_inbox_roots") or []) if row else [])
    frm_roots = roots + [
        os.path.normpath(os.path.abspath(_os_native(r))) for r in applied_inbox
    ]

    with write_lock.library_write("undo", timeout=0.0):
        skipped: list[dict] = []
        # (to, from, kind, model_id) per succeeded reversal.
        reversed_moves: list[tuple[str, str, str, int | None]] = []

        # Reverse order: a move made last is undone first, mirroring apply's
        # deepest-source-first so a re-created parent never blocks a child.
        for rec in reversed(records):
            to, frm = rec["to"], rec["from"]
            rec_kind = rec.get("kind", "stl")  # older logs predate the field
            rec_model_id = rec.get("model_id")  # older logs predate the field
            # The "to" path (current location after apply) must be inside a scan
            # root. The "frm" path (original location) must be inside a scan root
            # OR an approved inbox source dir from the trusted manifest. Either
            # escape is refused, not forced.
            try:
                to_n = _confine(to, roots)
                frm_n = _confine(frm, frm_roots)
            except ApplyError:
                skipped.append({"path": to, "reason": "escapes_roots"})
                continue

            if not os.path.exists(to_n):
                # Already reversed (idempotent re-run) or never landed.
                skipped.append({"path": to, "reason": "missing"})
                continue
            try:
                size, mtime_ns = stat_fn(to_n)
            except OSError:
                skipped.append({"path": to, "reason": "unreadable"})
                continue
            if size != rec["size_bytes"] or mtime_ns != rec["mtime_ns"]:
                # User edited/replaced the file after apply — don't move blind.
                skipped.append({"path": to, "reason": "drift"})
                continue
            if os.path.exists(frm_n) and _key(frm) != _key(to):
                # Something new occupies the original location — refuse to clobber.
                skipped.append({"path": to, "reason": "origin_occupied"})
                continue

            try:
                move_fn(to_n, frm_n)
            except Exception as e:
                skipped.append({"path": to, "reason": f"move_failed: {e}"})
                continue
            reversed_moves.append((to, frm, rec_kind, rec_model_id))

        _repath_db_undo(db, reversed_moves, roots)
        return UndoResult(
            manifest_id=manifest_id,
            reversed_files=len(reversed_moves),
            skipped=skipped,
        )


def _repath_db_undo(
    db: Session, reversed_moves: list[tuple[str, str, str, int | None]], roots: list[str]
) -> None:
    """Point STLFile.path / Model.folder_path, the model's own image fields,
    and the path-keyed overrides back to the pre-apply locations, in one
    transaction. STL rows are found by their current (``to``) path; an image
    move has no such row, so it's repathed via the record's own model_id."""
    override_dirs: set[tuple[str, str]] = set()   # (proposed_dir, source_dir)
    for to, frm, kind, model_id in reversed_moves:
        if kind == "image":
            model = db.get(Model, model_id) if model_id is not None else None
            if model is not None:
                _repath_model_image(model, to, frm)
            continue

        stl = db.query(STLFile).filter(STLFile.path == to).first()
        if stl is None:
            continue
        stl.path = frm
        model = db.get(Model, stl.model_id)
        if model is not None:
            model.folder_path = _parent(frm)
            # If the original location is outside every scan root, this was an
            # inbox model — restore the flag so the model surfaces in inbox views.
            frm_dir = os.path.normpath(os.path.abspath(_os_native(_parent(frm))))
            model.is_inbox = bool(frm_dir and all(
                frm_dir != r and not frm_dir.startswith(r + os.sep) for r in roots
            ))
            model.updated_at = utcnow()
        override_dirs.add((_parent(to), _parent(frm)))

    for proposed_dir, source_dir in override_dirs:
        if proposed_dir and source_dir:
            _repath_overrides(db, PackOverride, proposed_dir, source_dir)
    db.commit()
