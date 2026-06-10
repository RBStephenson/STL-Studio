"""PaintRack CSV import with diff preview (#242) and lossless export (#243).

The fixture below is synthetic but mirrors every quirk observed in real
PaintRack exports: empty Paint Class (Pro Acryl's base line), empty SKU
(Dirty Down), trailing-space SKU (FW Inks), the "17|18 ml" size variant,
and Count > 1.
"""
import pytest

from app.painting.models import Paint, PaintBrand, PaintLine
from app.painting.services import inventory

HEADER = "Brand,SKU,Paint Name,Paint Class,Size,Count"

CSV_V1 = "\n".join([
    HEADER,
    "Army Painter,WP3001,Matt Black,Warpaints Fanatic,18 ml,1",
    "Army Painter,WP3191,Shining Silver,Warpaints Fanatic,18 ml,1",
    "Army Painter,WP2010,Blood Red,Speedpaint,18 ml,1",
    "Pro Acryl,MPA-002,Coal Black,,22 ml,1",            # empty class
    "Pro Acryl,MPA-F01,Fluorescent Red,Fluorescent,22 ml,1",
    "Pro Acryl,MPAP-002,Black,PRIME,120 ml,2",          # count > 1
    "Pro Acryl,MWP-01,Titanium White,Weathering Pigments,37 ml,1",
    "Pro Acryl,MPA-T05,Concrete,Basing Textures,120 ml,1",
    "Pro Acryl,MPAM-001,Glaze & Wash Medium,,120 ml,1",
    "FW Inks,028 ,Black (India),Acrylic,1 oz,1",        # trailing-space SKU
    "Dirty Down,,Rust,,25 ml,1",                        # empty SKU
    "Vallejo,70.861,Glossy Black,Model Color,17|18 ml,1",
]) + "\n"


def _upload(client, path, csv_text, **form):
    return client.post(
        path,
        files={"file": ("paintRack_export.csv", csv_text.encode("utf-8"), "text/csv")},
        data=form,
    )


def _import_all(client, csv_text=CSV_V1):
    r = _upload(client, "/painting/inventory/import/confirm", csv_text,
                apply_removed="true")
    assert r.status_code == 200, r.text
    return r.json()


class TestParser:
    def test_parses_rows_and_strips(self):
        rows = inventory.parse_paintrack_csv(CSV_V1)
        assert len(rows) == 12
        fw = next(r for r in rows if r.brand == "FW Inks")
        assert fw.code == "028"          # trailing space stripped
        dd = next(r for r in rows if r.brand == "Dirty Down")
        assert dd.code == "" and dd.paint_class == ""
        prime = next(r for r in rows if r.code == "MPAP-002")
        assert prime.count == 2
        vallejo = next(r for r in rows if r.brand == "Vallejo")
        assert vallejo.size == "17|18 ml"

    def test_tolerates_bom(self):
        rows = inventory.parse_paintrack_csv("﻿" + CSV_V1)
        assert len(rows) == 12

    def test_rejects_wrong_header(self):
        with pytest.raises(inventory.PaintRackFormatError):
            inventory.parse_paintrack_csv("Name,Code\nx,y\n")

    def test_rejects_non_numeric_count(self):
        bad = HEADER + "\nBrand X,1,Paint,Class,1 ml,lots\n"
        with pytest.raises(inventory.PaintRackFormatError):
            inventory.parse_paintrack_csv(bad)

    def test_rejects_wrong_column_count(self):
        bad = HEADER + "\nBrand X,1,Paint\n"
        with pytest.raises(inventory.PaintRackFormatError):
            inventory.parse_paintrack_csv(bad)


class TestFinishInference:
    @pytest.mark.parametrize("brand,cls,name,expected", [
        ("Army Painter", "Warpaints Fanatic", "Matt Black", "matte"),
        ("Army Painter", "Warpaints Fanatic", "Shining Silver", "metallic"),
        ("Army Painter", "Warpaints Fanatic", "Dark Tone", "wash"),
        ("Army Painter", "Speedpaint", "Blood Red", "wash"),
        ("Citadel", "Shade", "Nuln Oil", "wash"),
        ("Pro Acryl", "", "Coal Black", "matte"),
        ("Pro Acryl", "Fluorescent", "Fluorescent Red", "fluor"),
        ("Pro Acryl", "PRIME", "Black", "primer"),
        ("Pro Acryl", "Weathering Pigments", "Titanium White", "pigment"),
        ("Pro Acryl", "Basing Textures", "Concrete", "texture"),
        ("Pro Acryl", "", "Glaze & Wash Medium", "medium"),
        ("Pro Acryl", "Transparent", "Transparent Red", "ink"),
        ("FW Inks", "Acrylic", "Black (India)", "ink"),
        ("Villainy Ink", "", "Sector Rust", "ink"),
        ("Vallejo", "Metal Color", "Duraluminium", "metallic"),
        ("Turbo Dork", "Turboshift", "Galaxia", "metallic"),
        ("Army Painter", "Air Primer", "Matt Grey", "primer"),
        ("Mr. Hobby", "Putty/Cement", "Mr. Dissolved Putty", "medium"),
    ])
    def test_inference(self, brand, cls, name, expected):
        assert inventory.infer_finish(brand, cls, name) == expected


class TestImportPreview:
    def test_preview_reports_added_and_writes_nothing(self, client, db):
        r = _upload(client, "/painting/inventory/import", CSV_V1)
        assert r.status_code == 200
        body = r.json()
        assert body["summary"] == {"rows": 12, "added": 12, "changed": 0, "removed": 0}
        assert db.query(Paint).count() == 0  # preview never writes

    def test_preview_rejects_malformed_file(self, client):
        r = _upload(client, "/painting/inventory/import", "Nope,Nope\n1,2\n")
        assert r.status_code == 422


class TestImportConfirm:
    def test_applies_adds_and_is_idempotent(self, client, db):
        result = _import_all(client)
        assert result["applied"] == {"added": 12, "changed": 0, "removed": 0}
        assert db.query(Paint).count() == 12
        # Brands and lines created on the fly; empty class is a real line.
        pro = db.query(PaintBrand).filter(PaintBrand.name == "Pro Acryl").one()
        line_names = {l.name for l in pro.lines}
        assert "" in line_names and "PRIME" in line_names

        # Re-importing the identical file is a no-op.
        r = _upload(client, "/painting/inventory/import", CSV_V1)
        assert r.json()["summary"] == {"rows": 12, "added": 0, "changed": 0, "removed": 0}

    def test_imported_finish_and_matchable_derived(self, client, db):
        _import_all(client)
        silver = db.query(Paint).filter(Paint.name == "Shining Silver").one()
        assert silver.finish == "metallic" and silver.matchable is False
        black = db.query(Paint).filter(Paint.code == "WP3001").one()
        assert black.finish == "matte" and black.matchable is True

    def test_changed_rows_previewed_and_applied(self, client, db):
        _import_all(client)
        v2 = CSV_V1.replace(
            "Pro Acryl,MPAP-002,Black,PRIME,120 ml,2",
            "Pro Acryl,MPAP-002,Black,PRIME,120 ml,3",
        ).replace(
            "Army Painter,WP3001,Matt Black,Warpaints Fanatic,18 ml,1",
            "Army Painter,WP3001,Matte Black,Warpaints Fanatic,18 ml,1",
        )
        preview = _upload(client, "/painting/inventory/import", v2).json()
        assert preview["summary"]["changed"] == 2
        changes = {c["code"]: c["changes"] for c in preview["changed"]}
        assert changes["MPAP-002"]["count"] == {"from": 2, "to": 3}
        assert changes["WP3001"]["name"]["to"] == "Matte Black"

        _import_all(client, v2)
        assert db.query(Paint).filter(Paint.code == "MPAP-002").one().count == 3

    def test_removed_only_targets_imported_paints(self, client, db):
        _import_all(client)
        # A manually added paint must never show up as removed.
        line = db.query(PaintLine).first()
        db.add(Paint(paint_line_id=line.id, code="MANUAL-1", name="My Mix",
                     finish="matte", matchable=True, source="manual"))
        db.commit()

        v2 = CSV_V1.replace("Dirty Down,,Rust,,25 ml,1\n", "")
        preview = _upload(client, "/painting/inventory/import", v2).json()
        assert preview["summary"]["removed"] == 1
        assert preview["removed"][0]["name"] == "Rust"

        # Confirm without apply_removed keeps it; with it, deletes it.
        _upload(client, "/painting/inventory/import/confirm", v2)
        assert db.query(Paint).filter(Paint.name == "Rust").count() == 1
        _upload(client, "/painting/inventory/import/confirm", v2, apply_removed="true")
        assert db.query(Paint).filter(Paint.name == "Rust").count() == 0
        assert db.query(Paint).filter(Paint.code == "MANUAL-1").count() == 1


class TestExport:
    def test_export_round_trips_to_empty_diff(self, client, db):
        _import_all(client)
        r = client.get("/painting/inventory/export.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        exported = r.text
        assert exported.splitlines()[0] == HEADER

        preview = _upload(client, "/painting/inventory/import", exported).json()
        assert preview["summary"]["added"] == 0
        assert preview["summary"]["changed"] == 0
        assert preview["summary"]["removed"] == 0

    def test_export_restores_empty_sku(self, client):
        _import_all(client)
        exported = client.get("/painting/inventory/export.csv").text
        assert "Dirty Down,,Rust,,25 ml,1" in exported
