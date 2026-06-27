"""Set store page + fetch & apply metadata to selected variants (#545)."""
import pytest

from app.models import Model
from app.services.scrapers.base import ScrapedModel


def _model(db, name):
    m = Model(name=name, folder_path=f"/lib/{name}")
    db.add(m)
    db.commit()
    return m


def _mock_scraper(monkeypatch, *, site, preview):
    import app.services.scrapers as scrapers

    async def fake_fetch(url, mmf_api_key=None):
        return preview
    monkeypatch.setattr(scrapers, "detect_site", lambda url: site)
    monkeypatch.setattr(scrapers, "fetch_url", fake_fetch)


def test_scrapes_once_and_applies_to_all(client, db, monkeypatch):
    a, b = _model(db, "a"), _model(db, "b")
    _mock_scraper(
        monkeypatch,
        site="gumroad",
        preview=ScrapedModel(
            title="Ada Wong", description="resin kit",
            source_site="gumroad", thumbnail_url=None,  # no download in tests
        ),
    )

    r = client.post("/scrape/apply-group", json={
        "model_ids": [a.id, b.id], "url": "https://x.gumroad.com/l/ada",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scraped"] is True
    assert body["applied"] == 2
    assert body["source_site"] == "gumroad"

    for m in (a, b):
        db.refresh(m)
        assert m.title == "Ada Wong"
        assert m.source_url == "https://x.gumroad.com/l/ada"
        assert m.source_site == "gumroad"


def test_unsupported_site_sets_url_only(client, db, monkeypatch):
    a = _model(db, "a")
    _mock_scraper(monkeypatch, site=None, preview=None)

    r = client.post("/scrape/apply-group", json={
        "model_ids": [a.id], "url": "https://www.patreon.com/somecreator",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["scraped"] is False
    assert body["source_site"] == "patreon.com"  # host label fallback

    db.refresh(a)
    assert a.source_url == "https://www.patreon.com/somecreator"
    assert a.source_site == "patreon.com"
    assert a.title is None  # nothing scraped to apply


def test_reports_missing_ids(client, db, monkeypatch):
    a = _model(db, "a")
    _mock_scraper(monkeypatch, site="gumroad",
                  preview=ScrapedModel(title="T", thumbnail_url=None))

    r = client.post("/scrape/apply-group", json={
        "model_ids": [a.id, 9999], "url": "https://x.gumroad.com/l/t",
    })
    assert r.status_code == 200
    assert r.json()["missing"] == [9999]
    assert r.json()["applied"] == 1


def test_empty_ids_rejected(client, db):
    assert client.post("/scrape/apply-group", json={"model_ids": [], "url": "https://x.gumroad.com/l/t"}).status_code == 400


def test_blank_url_rejected(client, db):
    a = _model(db, "a")
    assert client.post("/scrape/apply-group", json={"model_ids": [a.id], "url": "  "}).status_code == 400
