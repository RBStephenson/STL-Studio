"""Tests for GET /reorganize/template-preview (STUDIO-401).

The anti-drift assertions are the ones that matter. This endpoint exists to
render the SAME destinations `build_manifest` would, minus the filesystem work
— a cheap preview that quietly disagreed with the real preview would be worse
than no preview at all, because the user would iterate against a lie.

So the drift check runs against `build_manifest` itself rather than against
hard-coded expected paths, and it covers the *glue* cases (root scoping, inbox
source mappings, both slugify modes), not just a happy path. A drift test that
only exercises one library-model-under-one-root would pass while the endpoint
diverged on everything that actually varies.
"""
import os

import pytest

from app.models import (
    AppSetting,
    Creator,
    ImportSourceMapping,
    Model,
    ReorganizeManifest,
    ScanRoot,
)
from app.services import reorganize
from app.services.reorganize_template import ReorganizeTemplateError
from app.utils import utcnow
from tests.conftest import make_creator, make_model, make_stl_file


def _root(db, path, *, name=None):
    r = ScanRoot(path=str(path).replace("\\", "/"), enabled=True,
                 layout="{creator}/{character}/{title}", name=name, is_writable=True)
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def _get_creator(db, name):
    """Creator.name is unique, so multi-model tests must reuse."""
    existing = db.query(Creator).filter_by(name=name).first()
    return existing or make_creator(db, name=name)


def _model(db, root_path, creator_name="Abe3D", character="Joker", title="Bust",
           auto_tags=None, with_file=True):
    folder = os.path.join(str(root_path), creator_name, character or "loose", title)
    os.makedirs(folder, exist_ok=True)
    creator = _get_creator(db, creator_name)
    m = make_model(db, creator, name=title, character=character)
    m.folder_path = folder.replace("\\", "/")
    m.title = title
    m.auto_tags = auto_tags or []
    db.commit()
    if with_file:
        p = os.path.join(folder, "head.stl")
        with open(p, "wb") as fh:
            fh.write(b"solid\nendsolid\n")
        make_stl_file(db, m, filename="head.stl", path=p.replace("\\", "/"))
        db.commit()
    return m


def _inbox_model(db, folder, *, creator=None, character=None, title=None):
    m = Model(name=title or "m", folder_path=str(folder).replace("\\", "/"),
              creator_id=creator.id if creator else None, character=character,
              title=title, tags=[], auto_tags=[], is_inbox=True,
              created_at=utcnow(), updated_at=utcnow())
    db.add(m)
    db.commit()
    return m


def _set_setting(db, key, value):
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def _assert_no_drift(db, template, *, root_id=None, slugify_all=False):
    """Every sample must match build_manifest's entry for the same model.

    Compared field by field against the real builder rather than against
    expected strings, so this stays true as the grammar evolves — the point is
    that the two agree, not what they agree on.
    """
    preview = reorganize.build_template_preview(
        db, template, root_id, limit=50, slugify_all=slugify_all,
    )
    manifest = reorganize.build_manifest(
        db, template, root_id, slugify_all=slugify_all,
    )
    by_id = {e.model_id: e for e in manifest.entries}

    assert preview.samples, "no samples rendered — the drift check would be vacuous"
    assert preview.template == manifest.template
    for s in preview.samples:
        e = by_id[s.model_id]
        assert s.proposed_dir == e.proposed_dir, f"proposed_dir drift on model {s.model_id}"
        assert s.source_dir == e.source_dir, f"source_dir drift on model {s.model_id}"
        assert s.unclassifiable == e.unclassifiable, f"unclassifiable drift on {s.model_id}"
        assert s.missing_fields == e.missing_fields, f"missing_fields drift on {s.model_id}"
        assert s.over_length == e.over_length, f"over_length drift on {s.model_id}"
        assert s.reserved_name == e.reserved_name, f"reserved_name drift on {s.model_id}"
    return preview


class TestAntiDrift:
    def test_matches_build_manifest_with_slugify_off(self, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path)
        _assert_no_drift(db, "{creator}/{character}/{title}", slugify_all=False)

    def test_matches_build_manifest_with_slugify_on(self, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path, creator_name="Abe 3D Studios", title="Big Bust")
        _assert_no_drift(db, "{creator}/{character}/{title}", slugify_all=True)

    def test_matches_under_root_scoping(self, db, tmp_path):
        """The root-scoped filter is separator- and casefold-sensitive; a second
        copy of it in the endpoint is exactly where a preview would diverge."""
        a = _root(db, tmp_path / "A", name="A")
        _root(db, tmp_path / "B", name="B")
        in_a = _model(db, tmp_path / "A", creator_name="Abe3D")
        in_b = _model(db, tmp_path / "B", creator_name="Zed3D")

        preview = _assert_no_drift(db, "{creator}/{character}/{title}", root_id=a.id)
        ids = {s.model_id for s in preview.samples}
        assert in_a.id in ids
        assert in_b.id not in ids, "a model under another root leaked into a scoped preview"

    def test_matches_for_inbox_model_with_a_source_mapping(self, db, tmp_path):
        """An inbox model anchors at its MAPPED library, not the primary root.
        Re-deriving that resolution in the endpoint is the subtlest drift risk
        in the whole feature, because it only shows up on mapped sources."""
        a = _root(db, tmp_path / "A", name="A")  # primary (lowest id)
        b = _root(db, tmp_path / "B", name="B")
        src = os.path.realpath(str(tmp_path / "inbox")).replace("\\", "/")
        db.add(ImportSourceMapping(source_path=src, library_id=b.id))
        db.commit()
        creator = _get_creator(db, "Abe3D")
        m = _inbox_model(db, os.path.join(src, "Bust"), creator=creator,
                         character="Joker", title="Bust")

        preview = _assert_no_drift(db, "{creator}/{character}/{title}")
        sample = next(s for s in preview.samples if s.model_id == m.id)
        assert sample.proposed_dir.startswith(b.path), "did not anchor at the mapped library"
        assert not sample.proposed_dir.startswith(a.path)

    def test_matches_when_an_optional_token_drops(self, db, tmp_path):
        """STUDIO-407's optional-token drop has to survive the shared render
        path, not just build_manifest's copy of it."""
        _root(db, tmp_path)
        _model(db, tmp_path, auto_tags=[])  # no scale tag -> {scale?} drops
        preview = _assert_no_drift(db, "{creator}/{scale?}/{title}")
        assert all("Unknown Scale" not in s.proposed_dir for s in preview.samples)

    def test_matches_on_an_unclassifiable_model(self, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path, character=None)
        preview = _assert_no_drift(db, "{creator}/{character}/{title}")
        assert any(s.unclassifiable and s.missing_fields == ["character"]
                   for s in preview.samples)


class TestDestinationContainment:
    def test_hostile_field_values_cannot_escape_the_scan_root(self, db, tmp_path):
        """Pins the containment PROPERTY, not the redundant line that backs it.

        `_render_destination` re-checks that the assembled path stays under its
        anchor even though it just built it from the anchor. Deleting that
        re-check fails nothing — measured, not assumed — because
        `sanitize_segment` is the actual barrier: it turns ".." into "_" and
        every separator and drive letter into "_", so no rendered segment can
        climb out. The re-check is defence in depth behind it.

        Reaching that line would mean monkeypatching sanitize_segment, which
        tests the mock rather than the product. So this asserts the guarantee
        both layers exist to provide, through the real API, with the values an
        attacker would actually try. Folder paths are kept benign on purpose —
        creating a real directory named "../../etc" would write outside tmp_path.
        """
        root = _root(db, tmp_path)
        hostile = ["../../etc", "..", "C:\\Windows", "/abs/path", "a/../../b"]
        for i, bad in enumerate(hostile):
            folder = os.path.join(str(tmp_path), "safe", f"T{i}")
            os.makedirs(folder, exist_ok=True)
            m = make_model(db, _get_creator(db, bad), name=f"T{i}", character=bad)
            m.folder_path = folder.replace("\\", "/")
            m.title = f"T{i}"
            m.auto_tags = []
            db.commit()

        preview = reorganize.build_template_preview(
            db, "{creator}/{character}/{title}", limit=50,
        )

        assert len(preview.samples) == len(hostile)
        for s in preview.samples:
            assert s.proposed_dir.startswith(root.path + "/"), s.proposed_dir
            assert "/../" not in s.proposed_dir + "/", s.proposed_dir


class TestNoFilesystemWork:
    def test_performs_no_stat_calls(self, client, db, tmp_path, monkeypatch):
        """Cheapness is the entire premise, so it gets asserted rather than
        assumed. The cache is cleared first: a warm cache from an earlier call
        would let a stat-ing implementation pass this green."""
        _root(db, tmp_path)
        _model(db, tmp_path)
        reorganize._clear_stat_cache()

        def _boom(*args, **kwargs):
            raise AssertionError("template-preview must not touch the filesystem")

        monkeypatch.setattr(reorganize, "_stat_file", _boom)
        monkeypatch.setattr(reorganize, "_stat_file_cached", _boom)

        r = client.get("/reorganize/template-preview")
        assert r.status_code == 200
        assert r.json()["samples"]

    def test_persists_no_manifest_row(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path)
        before = db.query(ReorganizeManifest).count()

        assert client.get("/reorganize/template-preview").status_code == 200

        assert db.query(ReorganizeManifest).count() == before == 0

    def test_never_queries_stl_files(self, db, tmp_path):
        """Not style: eager-loading file rows here would make a deliberately
        cheap endpoint an N+1 across the whole library.

        This counts the SQL actually issued, because nothing in the RESULT
        changes either way — the rendering never reads a file row, so the
        samples come back identical whether or not they were loaded. An
        earlier version of this test called `_models_for_scope` directly with
        `with_files=False` and so asserted its own argument; it passed under a
        mutation that made the endpoint eager-load, which is the wrong answer.
        """
        from sqlalchemy import event

        _root(db, tmp_path)
        for i in range(3):
            _model(db, tmp_path, creator_name=f"Creator{i}", title=f"Bust{i}")

        touched: list[str] = []

        def _record(conn, cursor, statement, params, context, executemany):
            if "stl_files" in " ".join(statement.lower().split()):
                touched.append(statement.strip().split("\n")[0])

        engine = db.get_bind()
        event.listen(engine, "before_cursor_execute", _record)
        try:
            reorganize.build_template_preview(db, "{creator}/{character}/{title}", limit=3)
        finally:
            event.remove(engine, "before_cursor_execute", _record)

        assert touched == [], (
            "template-preview must not read stl_files at all; got:\n  " + "\n  ".join(touched)
        )


class TestValidation:
    def test_malformed_template_returns_400_with_the_parse_message(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path)

        r = client.get("/reorganize/template-preview", params={"template": "{bogus}"})

        assert r.status_code == 400
        with pytest.raises(ReorganizeTemplateError) as exc:
            reorganize.build_manifest(db, "{bogus}")
        assert r.json()["detail"] == str(exc.value), "400 body drifted from the real parse error"

    def test_all_optional_template_is_rejected(self, client, db, tmp_path):
        """STUDIO-407 rejects a template that could render to nothing; the
        preview must refuse it too rather than showing empty paths."""
        _root(db, tmp_path)
        _model(db, tmp_path)
        r = client.get("/reorganize/template-preview", params={"template": "{creator?}"})
        assert r.status_code == 400

    def test_limit_is_bounded(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path)
        assert client.get("/reorganize/template-preview", params={"limit": 0}).status_code == 422
        assert client.get("/reorganize/template-preview", params={"limit": 51}).status_code == 422


class TestSampling:
    def test_includes_an_unclassifiable_model_even_when_it_sorts_last(self, db, tmp_path):
        """The ticket's point: the user should see the failure mode BEFORE
        committing to a template, so a plain LIMIT 5 would defeat the feature."""
        _root(db, tmp_path)
        for i in range(5):
            _model(db, tmp_path, creator_name=f"Creator{i}", title=f"Bust{i}")
        broken = _model(db, tmp_path, creator_name="Last", character=None, title="Nameless")

        preview = reorganize.build_template_preview(db, "{creator}/{character}/{title}", limit=3)

        assert len(preview.samples) == 3
        assert broken.id in {s.model_id for s in preview.samples}
        assert sum(1 for s in preview.samples if s.unclassifiable) == 1

    def test_returns_limit_classifiable_when_none_are_broken(self, db, tmp_path):
        _root(db, tmp_path)
        for i in range(5):
            _model(db, tmp_path, creator_name=f"Creator{i}", title=f"Bust{i}")

        preview = reorganize.build_template_preview(db, "{creator}/{character}/{title}", limit=3)

        assert len(preview.samples) == 3
        assert not any(s.unclassifiable for s in preview.samples)

    def test_samples_come_back_in_model_id_order(self, db, tmp_path):
        _root(db, tmp_path)
        for i in range(4):
            _model(db, tmp_path, creator_name=f"Creator{i}", title=f"Bust{i}")
        _model(db, tmp_path, creator_name="Broken", character=None, title="Nameless")

        ids = [s.model_id for s in
               reorganize.build_template_preview(db, "{creator}/{character}/{title}", limit=4).samples]
        assert ids == sorted(ids)

    def test_empty_library_returns_no_samples(self, client, db, tmp_path):
        _root(db, tmp_path)
        r = client.get("/reorganize/template-preview")
        assert r.status_code == 200
        assert r.json()["samples"] == []


class TestPackageMode:
    def test_package_mode_is_surfaced_because_it_ignores_the_template(self, client, db, tmp_path):
        """With package mode on, _build_package_entries never receives the
        template at all — it places by {creator}/{character} plus the package
        folder name. Rendering the template anyway without saying so would be
        actively misleading, so the response carries the flag."""
        _root(db, tmp_path)
        _model(db, tmp_path)
        _set_setting(db, "reorganize_package_mode_enabled", True)

        body = client.get("/reorganize/template-preview").json()

        assert body["package_mode"] is True

    def test_package_mode_off_by_default(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path)
        assert client.get("/reorganize/template-preview").json()["package_mode"] is False


class TestEndpoint:
    def test_returns_the_documented_sample_shape(self, client, db, tmp_path):
        _root(db, tmp_path)
        m = _model(db, tmp_path)

        body = client.get("/reorganize/template-preview").json()

        assert body["template"] == "{creator}/{character}/{title}"
        sample = next(s for s in body["samples"] if s["model_id"] == m.id)
        assert set(sample) == {
            "model_id", "model_name", "source_dir", "proposed_dir",
            "unclassifiable", "missing_fields", "over_length", "reserved_name",
        }

    def test_falls_back_to_the_stored_template(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path)
        _set_setting(db, "reorganize_template", "{creator}/{title}")

        assert client.get("/reorganize/template-preview").json()["template"] == "{creator}/{title}"

    def test_explicit_template_beats_the_stored_one(self, client, db, tmp_path):
        _root(db, tmp_path)
        _model(db, tmp_path)
        _set_setting(db, "reorganize_template", "{creator}/{title}")

        body = client.get("/reorganize/template-preview",
                          params={"template": "{creator}/{character}"}).json()
        assert body["template"] == "{creator}/{character}"

    def test_is_not_gated_by_reorganize_enabled(self, client, db, tmp_path):
        """reorganize_enabled gates apply and undo — the operations that touch
        disk — not read-only rendering. Both /preview endpoints are ungated and
        this matches them; pinned so a future flag sweep doesn't 'fix' it."""
        _root(db, tmp_path)
        _model(db, tmp_path)
        _set_setting(db, "reorganize_enabled", False)

        assert client.get("/reorganize/template-preview").status_code == 200
