"""Local fast-storage cache for STL files served to the 3D viewer (#304).

STL files live on external drives; the viewer re-reads the raw file from the
drive every time it opens a model. This copies a file into a cache directory on
local storage (next to the DB) on first access and serves the local copy after,
so repeat opens never touch the slow drive. The cache key includes the source
mtime + size, so a replaced file is re-copied automatically.

The cache is best-effort: any failure falls back to the original path, so the
viewer never breaks because of a caching problem.
"""
import hashlib
import logging
import os
import shutil
import tempfile
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# Total bytes the cache is allowed to hold. STL files are large, so this is a
# coarse cap; the least-recently-used copies are evicted once it's exceeded.
CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


def stl_cache_dir() -> Path:
    """Return (and create) the STL cache directory on local storage.

    Lives next to the DB file (fast internal disk), mirroring thumbnails_dir.
    An in-memory DB (tests) caches under the system temp dir instead.
    """
    db_url = settings.database_url
    if "sqlite:///" in db_url:
        db_file = Path(db_url.split("sqlite:///", 1)[1])
    else:
        db_file = Path(db_url.split("sqlite://", 1)[1])
    if db_file.name == ":memory:":
        d = Path(tempfile.gettempdir()) / "stl_inventory_stl_cache"
    else:
        d = db_file.parent / "stl_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(src: Path, stat: os.stat_result) -> str:
    """Content-versioned key: a new mtime or size yields a new cache file."""
    raw = f"{src.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _prune(cache_dir: Path, keep: Path | None = None) -> None:
    """Evict least-recently-used cache files until under CACHE_MAX_BYTES."""
    try:
        entries = [
            (p, p.stat()) for p in cache_dir.glob("*.stl") if p.is_file()
        ]
    except OSError:
        return
    total = sum(st.st_size for _, st in entries)
    if total <= CACHE_MAX_BYTES:
        return
    # Oldest access time first; never evict the file we just produced.
    for p, st in sorted(entries, key=lambda e: e[1].st_atime):
        if total <= CACHE_MAX_BYTES:
            break
        if keep is not None and p == keep:
            continue
        try:
            p.unlink()
            total -= st.st_size
        except OSError:
            continue


def cached_stl(src: Path) -> Path:
    """Return a local cached copy of ``src``, copying it on a cache miss.

    Falls back to ``src`` itself on any error so serving never fails because of
    the cache.
    """
    try:
        stat = src.stat()
        cache_dir = stl_cache_dir()
        dest = cache_dir / f"{_cache_key(src, stat)}.stl"
        if dest.exists() and dest.stat().st_size == stat.st_size:
            # Mark as recently used for the LRU prune, then serve it.
            os.utime(dest, None)
            return dest

        # Copy via a temp file + atomic rename so a concurrent request never
        # serves a half-written file.
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        os.close(fd)
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
        _prune(cache_dir, keep=dest)
        return dest
    except OSError as e:
        logger.warning("STL cache miss-through for %s: %s", src, e)
        return src
