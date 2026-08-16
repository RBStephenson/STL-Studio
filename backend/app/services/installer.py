"""STL Installer: extract a ZIP or copy a folder into scan_root/creator/character
(STUDIO-386, part of the STUDIO-101 installer feature).

Builds on ``safe_copy.copy_verified`` (folder-copy) and
``path_guard.assert_within_roots`` (destination containment). RAR is explicitly
out of scope here -- see STUDIO-103, blocked on STUDIO-101.

Error-handling boundary (STUDIO-387's endpoint must catch both): a creator/
character combination that resolves outside ``scan_root`` raises a bare
``ValueError`` from ``path_guard``, deliberately left unwrapped to match that
module's existing convention. Every installer-specific failure raises an
``InstallError`` subclass instead.

Collision handling: ``character_dir`` existing at all -- full, empty, or a
crashed prior attempt -- is a hard error. No auto-cleanup, no resume; a
blocked character folder must be cleared manually before retrying.

Known non-goal: folder-copy walks files only, so empty subdirectories in the
source are not recreated at the destination (matches common archive-tool
behavior; not worth the extra bookkeeping for STL packs, which are never
empty-directory-shaped in practice).
"""
from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services import path_guard
from app.services.safe_copy import copy_verified

# Zip-bomb / runaway-pack guard, not a real-pack limiter. A real 67-file,
# 5.4 GiB multi-variant pack (3DMOONN's "Percy") sits comfortably under this.
MAX_INSTALL_SIZE_BYTES = 20 * 1024**3  # 20 GiB

_CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming chunk for zip extraction

# Top-level zip path segments that are packaging noise, not real content --
# excluded from the flatten decision so a Mac-authored zip's sibling __MACOSX/
# entry doesn't look like "two top-level folders" and silently disable
# flatten on exactly the archives it's meant for.
_IGNORED_TOP_LEVEL_PREFIXES = {"__MACOSX"}


class InstallError(Exception):
    """Base class for installer domain errors (see module docstring for the
    ValueError/InstallError split callers must handle)."""


class DestinationExistsError(InstallError):
    """The character destination folder already exists (full or empty)."""


class InstallSizeExceededError(InstallError):
    """Total install size exceeds MAX_INSTALL_SIZE_BYTES."""


class InvalidArchiveError(InstallError):
    """Source is not a readable ZIP, or an entry fails the zip-slip
    containment check."""


class UnsupportedSourceError(InstallError):
    """Source is neither a directory nor a .zip file (e.g. .rar -- see
    STUDIO-103)."""


class EmptySourceError(InstallError):
    """Source contains no files to install."""


@dataclass
class InstallResult:
    dest: Path
    file_count: int
    total_bytes: int


def install(source: str | Path, scan_root: str | Path, creator: str, character: str) -> InstallResult:
    """Install *source* (a folder or a .zip file) into scan_root/creator/character.

    Raises DestinationExistsError / InstallSizeExceededError / InvalidArchiveError /
    UnsupportedSourceError / EmptySourceError (all InstallError subclasses), or a
    bare ValueError from path_guard if creator/character resolve outside scan_root.
    """
    creator = creator.strip()
    character = character.strip()
    if not creator or not character:
        raise ValueError("creator and character must be non-empty")

    source = Path(source)
    scan_root = Path(scan_root)
    creator_dir = scan_root / creator
    character_dir = Path(path_guard.assert_within_roots(creator_dir / character, [scan_root]))

    if character_dir.exists():
        raise DestinationExistsError(f"destination already exists: {character_dir}")

    if source.is_dir():
        return _install_from_folder(source, creator_dir, character_dir)
    if source.is_file() and source.suffix.lower() == ".zip":
        return _install_from_zip(source, creator_dir, character_dir)
    raise UnsupportedSourceError(
        f"unsupported source {source!r} -- only folders and .zip files are supported "
        "(.rar support is tracked separately, STUDIO-103)"
    )


def _install_from_folder(source: Path, creator_dir: Path, character_dir: Path) -> InstallResult:
    files = [p for p in source.rglob("*") if p.is_file()]
    if not files:
        raise EmptySourceError(f"source folder contains no files: {source}")

    total = sum(p.stat().st_size for p in files)
    if total > MAX_INSTALL_SIZE_BYTES:
        raise InstallSizeExceededError(f"install size {total} exceeds cap {MAX_INSTALL_SIZE_BYTES}")

    creator_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for src_file in files:
        dst_file = character_dir / src_file.relative_to(source)
        copy_verified(str(src_file), str(dst_file))
        written += dst_file.stat().st_size

    return InstallResult(dest=character_dir, file_count=len(files), total_bytes=written)


def _flattened_parts(filename: str, flatten: bool) -> tuple[str, ...]:
    parts = PurePosixPath(filename).parts
    if flatten and parts and parts[0] not in _IGNORED_TOP_LEVEL_PREFIXES:
        parts = parts[1:]
    return parts


def _install_from_zip(source: Path, creator_dir: Path, character_dir: Path) -> InstallResult:
    try:
        zf = zipfile.ZipFile(source)
    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError(f"not a valid zip file: {source}") from exc

    with zf:
        file_infos = [i for i in zf.infolist() if not i.is_dir()]
        if not file_infos:
            raise EmptySourceError(f"zip contains no files: {source}")

        # Single pass: sum declared size (see MAX_INSTALL_SIZE_BYTES cap below),
        # pre-validate every entry's unflattened path stays within
        # character_dir, and collect top-level components to decide the
        # flatten question. Only
        # *file* entries count toward the flatten decision -- a lone directory
        # entry for the wrapping folder itself (which real creator zips do
        # include, e.g. Abe3D's "1_4 Zarana - Abe3D by Ramses" dir entry)
        # would otherwise look like a disqualifying single-part entry.
        declared_total = 0
        top_level_components: set[str] = set()
        real_file_infos = []
        for info in file_infos:
            parts = PurePosixPath(info.filename).parts
            if not parts:
                raise InvalidArchiveError(f"empty entry name in zip: {info.filename!r}")
            declared_total += info.file_size
            try:
                path_guard.assert_within_roots(character_dir / Path(*parts), [character_dir])
            except ValueError as exc:
                raise InvalidArchiveError(f"zip entry escapes destination: {info.filename!r}") from exc
            if parts[0] not in _IGNORED_TOP_LEVEL_PREFIXES:
                top_level_components.add(parts[0])
                real_file_infos.append(info)

        if declared_total > MAX_INSTALL_SIZE_BYTES:
            raise InstallSizeExceededError(
                f"declared install size {declared_total} exceeds cap {MAX_INSTALL_SIZE_BYTES}"
            )

        # Flatten only when every real file entry is nested under one shared
        # top-level folder. A bare top-level file (e.g. a single-file zip with
        # no wrapping folder) or more than one distinct top-level folder (e.g.
        # 3DMOONN's "standard version/" + "bonus parts/" pack) disables it.
        flatten = len(top_level_components) == 1 and all(
            len(PurePosixPath(i.filename).parts) >= 2 for i in real_file_infos
        )

        creator_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        running_total = 0
        for info in file_infos:
            parts = _flattened_parts(info.filename, flatten)
            if not parts:
                continue  # flatten stripped a bare wrapping-folder entry down to nothing
            dst_file = Path(path_guard.assert_within_roots(character_dir / Path(*parts), [character_dir]))
            dst_file.parent.mkdir(parents=True, exist_ok=True)

            # running_total re-checks the cap against bytes actually written,
            # not just the pre-flight declared-size sum above. For stdlib
            # zipfile this is redundant today -- ZipExtFile bounds reads by
            # each entry's declared file_size itself, so an honest archive
            # can never cause actual bytes to exceed what the pre-flight sum
            # already validated. Kept as a cheap invariant in case extraction
            # ever stops going through that reader (e.g. a future format or a
            # different unzip path).
            tmp = dst_file.with_name(dst_file.name + ".safecopytmp")
            try:
                with zf.open(info) as src_fh, open(tmp, "wb") as dst_fh:
                    while chunk := src_fh.read(_CHUNK_SIZE):
                        running_total += len(chunk)
                        if running_total > MAX_INSTALL_SIZE_BYTES:
                            raise InstallSizeExceededError(
                                f"actual extracted size exceeded cap {MAX_INSTALL_SIZE_BYTES} "
                                f"while writing {info.filename!r}"
                            )
                        dst_fh.write(chunk)
                    dst_fh.flush()
                    os.fsync(dst_fh.fileno())
            except zipfile.BadZipFile as exc:
                tmp.unlink(missing_ok=True)
                raise InvalidArchiveError(f"corrupt entry in zip: {info.filename!r}") from exc
            except Exception:
                tmp.unlink(missing_ok=True)
                raise

            if tmp.stat().st_size != info.file_size:
                tmp.unlink(missing_ok=True)
                raise InvalidArchiveError(
                    f"size mismatch extracting {info.filename!r}: "
                    f"expected {info.file_size}, wrote {tmp.stat().st_size}"
                )
            os.replace(tmp, dst_file)
            written += dst_file.stat().st_size

    return InstallResult(dest=character_dir, file_count=len(file_infos), total_bytes=written)
