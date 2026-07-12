"""Tests for the Reorganize preview stat cache (STUDIO-187).

Editing a resolved-field override re-previews the WHOLE manifest (collision
detection is inherently global), but a file's on-disk stat never depends on
override values, so re-stat'ing every file on every keystroke is pure waste.
These tests prove the cache actually avoids redundant os.stat calls, that it
doesn't change what a manifest reports, and that it expires so a real
on-disk change is eventually picked back up.
"""
import app.services.reorganize as reorg
from app.models import Creator, ScanRoot
from tests.conftest import make_creator, make_model, make_stl_file


def _root(db, tmp_path):
    db.add(ScanRoot(path=str(tmp_path), enabled=True))
    db.commit()


def _get_creator(db, name):
    existing = db.query(Creator).filter_by(name=name).first()
    return existing or make_creator(db, name=name)


def _model_with_file(db, tmp_path, creator_name="Abe3D", character="Joker",
                      title="Bust", filename="head.stl"):
    folder = tmp_path / creator_name / character / title
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / filename
    f.write_bytes(b"solid\nendsolid\n")
    creator = _get_creator(db, creator_name)
    m = make_model(db, creator, name=title, character=character)
    m.folder_path = str(folder)
    m.title = title
    m.auto_tags = []
    db.commit()
    make_stl_file(db, m, filename=filename, path=str(f))
    db.commit()
    return m, f


class TestStatCache:
    def setup_method(self):
        reorg._clear_stat_cache()

    def test_second_call_within_ttl_avoids_a_real_stat(self, db, tmp_path, monkeypatch):
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)

        calls = {"n": 0}
        real_stat_file = reorg._stat_file

        def _counting_stat_file(path):
            calls["n"] += 1
            return real_stat_file(path)

        monkeypatch.setattr(reorg, "_stat_file", _counting_stat_file)

        reorg.build_manifest(db, None)
        assert calls["n"] == 1
        reorg.build_manifest(db, None)
        # Second build within the TTL window must not hit the filesystem again.
        assert calls["n"] == 1

    def test_cache_expires_after_ttl_and_picks_up_a_real_change(self, db, tmp_path, monkeypatch):
        _root(db, tmp_path)
        m, f = _model_with_file(db, tmp_path)

        fake_now = [0.0]
        monkeypatch.setattr(reorg.time, "monotonic", lambda: fake_now[0])

        first = reorg.build_manifest(db, None)
        size_before = first.entries[0].files[0].size_bytes

        f.write_bytes(b"solid\nendsolid\nmore data now\n")
        fake_now[0] += reorg._STAT_CACHE_TTL + 0.1

        second = reorg.build_manifest(db, None)
        assert second.entries[0].files[0].size_bytes != size_before

    def test_cache_hit_reports_identical_stat_data_to_a_fresh_stat(self, db, tmp_path):
        """The cache must not change *what* the manifest reports — only how
        expensively it's computed (STUDIO-187 non-goal: no behavior change)."""
        _root(db, tmp_path)
        _model_with_file(db, tmp_path)

        first = reorg.build_manifest(db, None)
        second = reorg.build_manifest(db, None)

        f1, f2 = first.entries[0].files[0], second.entries[0].files[0]
        assert (f1.size_bytes, f1.mtime_ns, f1.missing_file) == (f2.size_bytes, f2.mtime_ns, f2.missing_file)

    def test_unrelated_model_edit_does_not_restat_other_models(self, db, tmp_path, monkeypatch):
        """The scenario the ticket was filed for: resolving one row's override
        must not re-stat every other model's files."""
        _root(db, tmp_path)
        _model_with_file(db, tmp_path, creator_name="Abe3D", title="Bust")
        _model_with_file(db, tmp_path, creator_name="Zeta3D", title="Rogue")

        stat_calls: list[str] = []
        real_stat_file = reorg._stat_file

        def _tracking_stat_file(path):
            stat_calls.append(path)
            return real_stat_file(path)

        monkeypatch.setattr(reorg, "_stat_file", _tracking_stat_file)

        reorg.build_manifest(db, None)
        assert len(stat_calls) == 2  # one per model's file, first build

        # Simulate resolving an override on just one model — a second full
        # preview build (same overrides API surface as previewWithOverrides).
        reorg.build_manifest(db, None, overrides={999: {"creator": "Doesn't Matter"}})
        assert len(stat_calls) == 2  # no new stat calls — both files served from cache
