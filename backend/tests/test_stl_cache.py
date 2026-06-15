"""Tests for the local STL byte cache (#304)."""
import os

import pytest

from app.services import stl_cache


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    d = tmp_path / "cache"
    d.mkdir()
    monkeypatch.setattr(stl_cache, "stl_cache_dir", lambda: d)
    return d


def _write_stl(p, body=b"solid\nendsolid\n"):
    p.write_bytes(body)
    return p


class TestCachedStl:
    def test_copies_to_cache_on_miss(self, tmp_path, cache_dir):
        src = _write_stl(tmp_path / "model.stl")
        cached = stl_cache.cached_stl(src)

        assert cached.parent == cache_dir
        assert cached != src
        assert cached.read_bytes() == src.read_bytes()

    def test_second_call_reuses_same_file(self, tmp_path, cache_dir):
        src = _write_stl(tmp_path / "model.stl")
        first = stl_cache.cached_stl(src)
        second = stl_cache.cached_stl(src)

        assert first == second
        assert len(list(cache_dir.glob("*.stl"))) == 1

    def test_changed_source_produces_new_cache_entry(self, tmp_path, cache_dir):
        src = tmp_path / "model.stl"
        _write_stl(src, b"solid A\nendsolid A\n")
        first = stl_cache.cached_stl(src)

        # Replace with different content + a newer mtime.
        _write_stl(src, b"solid BBBB\nendsolid BBBB\n")
        os.utime(src, (src.stat().st_atime, src.stat().st_mtime + 10))
        second = stl_cache.cached_stl(src)

        assert first != second
        assert second.read_bytes() == src.read_bytes()

    def test_missing_source_falls_back_to_original(self, tmp_path, cache_dir):
        missing = tmp_path / "gone.stl"
        # No exception — returns the original path so the caller can 404/serve.
        assert stl_cache.cached_stl(missing) == missing

    def test_prune_evicts_when_over_cap(self, tmp_path, cache_dir, monkeypatch):
        monkeypatch.setattr(stl_cache, "CACHE_MAX_BYTES", 30)
        for i in range(4):
            src = _write_stl(tmp_path / f"m{i}.stl", b"X" * 20)
            stl_cache.cached_stl(src)

        # Cap is 30 bytes and each copy is 20, so the cache can't hold them all.
        remaining = list(cache_dir.glob("*.stl"))
        assert sum(p.stat().st_size for p in remaining) <= 30
