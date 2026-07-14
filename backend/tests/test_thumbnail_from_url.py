"""
Tests for server-side thumbnail download: the thumbnails service, the
/models/{id}/thumbnail/from-url endpoint, the thumbnail handling in
/scrape/apply and PATCH /models/{id}, and image cache revalidation.
"""
import httpx
import pytest

from tests.conftest import make_creator, make_model

import app.services.thumbnails as thumbnails
from app.services.thumbnails import ThumbnailDownloadError, download_gallery_images, download_thumbnail

PNG_BYTES = b"\x89PNG\r\n\x1a\nfakepngdata"
JPEG_BYTES = b"\xff\xd8\xff\xe0fakejpegdata"


@pytest.fixture()
def thumb_dir(tmp_path, monkeypatch):
    """Isolate the thumbnails directory to this test."""
    d = tmp_path / "thumbnails"
    d.mkdir()
    monkeypatch.setattr(thumbnails, "thumbnails_dir", lambda: d)
    return d


@pytest.fixture()
def gallery_dir(tmp_path, monkeypatch):
    """Isolate the fetched-gallery-image directory to this test (#1028)."""
    d = tmp_path / "gallery_images"
    d.mkdir()
    monkeypatch.setattr(thumbnails, "gallery_images_dir", lambda: d)
    return d


# Captured at import time so repeated mock_http calls in one test don't wrap
# an already-patched factory (the service and this module share the httpx
# module object).
_REAL_ASYNC_CLIENT = httpx.AsyncClient


def mock_http(monkeypatch, handler):
    """Route the service's httpx.AsyncClient through a MockTransport."""
    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return _REAL_ASYNC_CLIENT(**kwargs)

    monkeypatch.setattr(thumbnails.httpx, "AsyncClient", factory)
    # The SSRF guard (STUDIO-68) resolves the host before fetching; the fake
    # test URLs have no DNS, so point the guard at a public IP. HTTP itself is
    # mocked above, so no real request goes out.
    import socket
    from app.services import url_guard
    monkeypatch.setattr(
        url_guard.socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 0))],
    )


# ---------------------------------------------------------------------------
# download_thumbnail service
# ---------------------------------------------------------------------------

class TestDownloadThumbnail:
    @pytest.mark.anyio
    async def test_saves_png_from_content_type(self, thumb_dir, monkeypatch):
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        out = await download_thumbnail(42, "https://cdn.example.com/img")
        assert out == thumb_dir / "42.png"
        assert out.read_bytes() == PNG_BYTES

    @pytest.mark.anyio
    async def test_removes_stale_file_with_other_extension(self, thumb_dir, monkeypatch):
        stale = thumb_dir / "42.png"
        stale.write_bytes(b"old")
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"}))

        out = await download_thumbnail(42, "https://cdn.example.com/img")
        assert out == thumb_dir / "42.jpg"
        assert not stale.exists()

    @pytest.mark.anyio
    async def test_generic_content_type_without_image_extension_rejected(self, thumb_dir, monkeypatch):
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "application/octet-stream"}))

        with pytest.raises(ThumbnailDownloadError):
            await download_thumbnail(1, "https://cdn.example.com/download")

    @pytest.mark.anyio
    async def test_falls_back_to_url_extension(self, thumb_dir, monkeypatch):
        """Some CDNs send a generic content type — trust the URL extension."""
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "application/octet-stream"}))

        out = await download_thumbnail(1, "https://cdn.example.com/render.webp")
        assert out.suffix == ".webp"

    @pytest.mark.anyio
    async def test_rejects_non_http_scheme(self, thumb_dir):
        with pytest.raises(ThumbnailDownloadError, match="http"):
            await download_thumbnail(1, "file:///etc/passwd")

    @pytest.mark.anyio
    async def test_rejects_html_with_no_preview_image(self, thumb_dir, monkeypatch):
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=b"<html><head></head></html>",
            headers={"content-type": "text/html"}))
        with pytest.raises(ThumbnailDownloadError, match="preview image"):
            await download_thumbnail(1, "https://example.com/page")

    @pytest.mark.anyio
    async def test_follows_html_to_og_image(self, thumb_dir, monkeypatch):
        """#285: a product-page URL (text/html) should resolve to its og:image
        and download that — this is what the user's Gumroad link does."""
        def handler(req):
            if req.url.path == "/preview.png":
                return httpx.Response(200, content=PNG_BYTES,
                                      headers={"content-type": "image/png"})
            html = (
                b'<html><head>'
                b'<meta property="og:image" content="https://cdn.example.com/preview.png">'
                b'</head></html>'
            )
            return httpx.Response(200, content=html,
                                  headers={"content-type": "text/html; charset=utf-8"})
        mock_http(monkeypatch, handler)

        out = await download_thumbnail(7, "https://creator.gumroad.com/l/dphoenix")
        assert out == thumb_dir / "7.png"
        assert out.read_bytes() == PNG_BYTES

    @pytest.mark.anyio
    async def test_resolves_relative_og_image(self, thumb_dir, monkeypatch):
        """A relative og:image is resolved against the page's own URL."""
        def handler(req):
            if req.url.path == "/img/preview.jpg":
                return httpx.Response(200, content=JPEG_BYTES,
                                      headers={"content-type": "image/jpeg"})
            html = (
                b'<html><head>'
                b'<meta property="og:image" content="/img/preview.jpg">'
                b'</head></html>'
            )
            return httpx.Response(200, content=html,
                                  headers={"content-type": "text/html"})
        mock_http(monkeypatch, handler)

        out = await download_thumbnail(8, "https://store.example.com/l/widget")
        assert out == thumb_dir / "8.jpg"

    @pytest.mark.anyio
    async def test_does_not_follow_html_twice(self, thumb_dir, monkeypatch):
        """The extracted image URL is fetched with following disabled, so an
        og:image that itself points at HTML errors rather than looping."""
        def handler(req):
            html = (
                b'<html><head>'
                b'<meta property="og:image" content="https://example.com/another-page">'
                b'</head></html>'
            )
            return httpx.Response(200, content=html,
                                  headers={"content-type": "text/html"})
        mock_http(monkeypatch, handler)

        with pytest.raises(ThumbnailDownloadError, match="did not return an image"):
            await download_thumbnail(1, "https://example.com/page")

    @pytest.mark.anyio
    async def test_rejects_http_error_status(self, thumb_dir, monkeypatch):
        mock_http(monkeypatch, lambda req: httpx.Response(404))
        with pytest.raises(ThumbnailDownloadError, match="404"):
            await download_thumbnail(1, "https://example.com/gone.png")

    @pytest.mark.anyio
    async def test_rejects_oversize_body(self, thumb_dir, monkeypatch):
        monkeypatch.setattr(thumbnails, "MAX_BYTES", 8)
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=b"x" * 64, headers={"content-type": "image/png"}))
        with pytest.raises(ThumbnailDownloadError, match="large"):
            await download_thumbnail(1, "https://example.com/huge.png")

    @pytest.mark.anyio
    async def test_network_error_wrapped(self, thumb_dir, monkeypatch):
        def boom(req):
            raise httpx.ConnectError("connection refused")
        mock_http(monkeypatch, boom)
        with pytest.raises(ThumbnailDownloadError, match="fetch"):
            await download_thumbnail(1, "https://example.com/img.png")

    @pytest.mark.anyio
    async def test_rejects_empty_body(self, thumb_dir, monkeypatch):
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=b"", headers={"content-type": "image/png"}))
        with pytest.raises(ThumbnailDownloadError, match="empty"):
            await download_thumbnail(1, "https://example.com/img.png")


# ---------------------------------------------------------------------------
# download_gallery_images service (#1028)
# ---------------------------------------------------------------------------

class TestDownloadGalleryImages:
    @pytest.mark.anyio
    async def test_downloads_each_url_to_its_own_indexed_file(self, gallery_dir, monkeypatch):
        def handler(req):
            body = PNG_BYTES if req.url.path == "/a.png" else JPEG_BYTES
            ctype = "image/png" if req.url.path == "/a.png" else "image/jpeg"
            return httpx.Response(200, content=body, headers={"content-type": ctype})
        mock_http(monkeypatch, handler)

        out = await download_gallery_images(5, [
            "https://cdn.example.com/a.png", "https://cdn.example.com/b.jpg",
        ])
        assert out == [str(gallery_dir / "5_0.png"), str(gallery_dir / "5_1.jpg")]
        assert (gallery_dir / "5_0.png").read_bytes() == PNG_BYTES
        assert (gallery_dir / "5_1.jpg").read_bytes() == JPEG_BYTES

    @pytest.mark.anyio
    async def test_caps_at_given_limit(self, gallery_dir, monkeypatch):
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        urls = [f"https://cdn.example.com/{i}.png" for i in range(5)]
        out = await download_gallery_images(9, urls, cap=2)
        assert len(out) == 2

    @pytest.mark.anyio
    async def test_one_failure_does_not_block_the_rest(self, gallery_dir, monkeypatch):
        def handler(req):
            if req.url.path == "/bad.png":
                return httpx.Response(403)
            return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
        mock_http(monkeypatch, handler)

        out = await download_gallery_images(3, [
            "https://cdn.example.com/bad.png", "https://cdn.example.com/good.png",
        ])
        # Only the successful one is saved, and it still gets its own slot's
        # index — no attempt to renumber around the gap.
        assert out == [str(gallery_dir / "3_1.png")]

    @pytest.mark.anyio
    async def test_clears_stale_files_from_a_previous_call(self, gallery_dir, monkeypatch):
        stale = gallery_dir / "4_0.png"
        stale.write_bytes(b"old")
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"}))

        out = await download_gallery_images(4, ["https://cdn.example.com/new.jpg"])
        assert out == [str(gallery_dir / "4_0.jpg")]
        assert not stale.exists()


# ---------------------------------------------------------------------------
# POST /models/{id}/thumbnail/from-url
# ---------------------------------------------------------------------------

class TestFromUrlEndpoint:
    def test_success_sets_path_and_clears_url(self, client, db, thumb_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator)
        model.thumbnail_url = "https://old.example.com/old.png"
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.post(f"/models/{model.id}/thumbnail/from-url",
                           json={"url": "https://cdn.example.com/new.png"})
        assert resp.status_code == 200
        assert resp.json()["downloaded"] is True

        db.refresh(model)
        assert model.thumbnail_path == str(thumb_dir / f"{model.id}.png")
        assert model.thumbnail_url is None

    def test_download_failure_falls_back_to_storing_url(self, client, db, thumb_dir, monkeypatch):
        """#285: a failed server-side download must not dead-end. Mirroring the
        edit screen (PATCH /models/{id}), it stores the bare URL and clears the
        stale path so the UI can still try to render it, and flags downloaded=False."""
        creator = make_creator(db)
        model = make_model(db, creator, thumbnail_path="/somewhere/local.png")
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(403))

        resp = client.post(f"/models/{model.id}/thumbnail/from-url",
                           json={"url": "https://cdn.example.com/blocked.png"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["downloaded"] is False
        assert "403" in body["detail"]

        db.refresh(model)
        assert model.thumbnail_url == "https://cdn.example.com/blocked.png"
        assert model.thumbnail_path is None

    def test_unknown_model_returns_404(self, client, thumb_dir):
        resp = client.post("/models/99999/thumbnail/from-url",
                           json={"url": "https://cdn.example.com/img.png"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /models/{id}/thumbnail/upload — shares the same stale-file cleanup
# ---------------------------------------------------------------------------

class TestUploadThumbnailCleanup:
    def test_upload_purges_stale_other_extension(self, client, db, thumb_dir):
        creator = make_creator(db)
        model = make_model(db, creator)
        db.commit()

        stale = thumb_dir / f"{model.id}.jpg"
        stale.write_bytes(b"old downloaded thumb")

        resp = client.post(
            f"/models/{model.id}/thumbnail/upload",
            files={"file": ("capture.png", PNG_BYTES, "image/png")},
        )
        assert resp.status_code == 200
        assert (thumb_dir / f"{model.id}.png").exists()
        assert not stale.exists()


# ---------------------------------------------------------------------------
# POST /scrape/apply/{id} — thumbnail handling
# ---------------------------------------------------------------------------

class TestScrapeApplyThumbnail:
    def test_download_success_sets_local_path(self, client, db, thumb_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator, thumbnail_path="/somewhere/local.png")
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=JPEG_BYTES, headers={"content-type": "image/jpeg"}))

        resp = client.post(f"/scrape/apply/{model.id}",
                           json={"thumbnail_url": "https://cdn.example.com/art.jpg"})
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_path == str(thumb_dir / f"{model.id}.jpg")
        assert model.thumbnail_url is None

    def test_download_failure_stores_url_and_clears_path(self, client, db, thumb_dir, monkeypatch):
        """Regression for #189: the old code stored the URL but left the local
        path in place, and the UI shows the path first — so applying web
        metadata appeared to do nothing."""
        creator = make_creator(db)
        model = make_model(db, creator, thumbnail_path="/somewhere/local.png")
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(403))

        resp = client.post(f"/scrape/apply/{model.id}",
                           json={"thumbnail_url": "https://cdn.example.com/blocked.jpg"})
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_url == "https://cdn.example.com/blocked.jpg"
        assert model.thumbnail_path is None


# ---------------------------------------------------------------------------
# POST /scrape/apply/{id} — gallery image handling (#1028)
# ---------------------------------------------------------------------------

class TestScrapeApplyGallery:
    def test_image_urls_downloaded_when_gallery_empty(self, client, db, thumb_dir, gallery_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator)
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.post(f"/scrape/apply/{model.id}", json={
            "image_urls": ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"],
        })
        assert resp.status_code == 200

        db.refresh(model)
        assert model.image_paths == [
            str(gallery_dir / f"{model.id}_0.png"),
            str(gallery_dir / f"{model.id}_1.png"),
        ]

    def test_image_urls_downloaded_even_when_gallery_already_has_non_fetched_images(
        self, client, db, thumb_dir, gallery_dir, monkeypatch,
    ):
        """#1028: no fill-only-when-empty gate — a scan-discovered image
        already in the gallery must not block fetching the rest."""
        creator = make_creator(db)
        model = make_model(db, creator)
        model.image_paths = ["/library/existing.jpg"]
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.post(f"/scrape/apply/{model.id}", json={
            "image_urls": ["https://cdn.example.com/a.png"],
        })
        assert resp.status_code == 200

        db.refresh(model)
        assert model.image_paths == ["/library/existing.jpg", str(gallery_dir / f"{model.id}_0.png")]

    def test_refetch_replaces_previously_fetched_images_only(self, client, db, thumb_dir, gallery_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator)
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        # First fetch: two images.
        client.post(f"/scrape/apply/{model.id}", json={
            "image_urls": ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"],
        })
        db.refresh(model)
        assert len(model.image_paths) == 2

        # A scan-discovered image lands in the gallery independently.
        model.image_paths = model.image_paths + ["/library/scanned.jpg"]
        db.commit()

        # Second fetch: source page now only has one image.
        resp = client.post(f"/scrape/apply/{model.id}", json={
            "image_urls": ["https://cdn.example.com/c.png"],
        })
        assert resp.status_code == 200

        db.refresh(model)
        # The stale second fetched file is gone; the scanned one survives.
        assert model.image_paths == ["/library/scanned.jpg", str(gallery_dir / f"{model.id}_0.png")]


# ---------------------------------------------------------------------------
# POST /scrape/apply-images/{id} — for the Edit Metadata panel's own inline
# Fetch/Apply, which never goes through /scrape/apply at all (#1028)
# ---------------------------------------------------------------------------

class TestScrapeApplyImages:
    def test_downloads_and_fills_empty_gallery(self, client, db, gallery_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator)
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.post(f"/scrape/apply-images/{model.id}", json={
            "image_urls": ["https://cdn.example.com/a.png", "https://cdn.example.com/b.png"],
        })
        assert resp.status_code == 200
        assert resp.json()["image_paths"] == [
            str(gallery_dir / f"{model.id}_0.png"),
            str(gallery_dir / f"{model.id}_1.png"),
        ]

        db.refresh(model)
        assert model.image_paths == [
            str(gallery_dir / f"{model.id}_0.png"),
            str(gallery_dir / f"{model.id}_1.png"),
        ]

    def test_downloads_even_when_gallery_already_has_non_fetched_images(self, client, db, gallery_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator)
        model.image_paths = ["/library/existing.jpg"]
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.post(f"/scrape/apply-images/{model.id}", json={
            "image_urls": ["https://cdn.example.com/a.png"],
        })
        assert resp.status_code == 200

        db.refresh(model)
        assert model.image_paths == ["/library/existing.jpg", str(gallery_dir / f"{model.id}_0.png")]

    def test_does_not_touch_other_fields(self, client, db, gallery_dir, monkeypatch):
        """This endpoint exists precisely because the Edit Metadata panel
        writes every other field itself — it must never overwrite title/
        description/etc, unlike /scrape/apply."""
        creator = make_creator(db)
        model = make_model(db, creator)
        model.title = "Kept Title"
        model.description = "Kept description"
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.post(f"/scrape/apply-images/{model.id}", json={
            "image_urls": ["https://cdn.example.com/a.png"],
        })
        assert resp.status_code == 200

        db.refresh(model)
        assert model.title == "Kept Title"
        assert model.description == "Kept description"

    def test_unknown_model_returns_404(self, client, gallery_dir):
        resp = client.post("/scrape/apply-images/999999", json={"image_urls": []})
        assert resp.status_code == 404

    def test_empty_image_urls_is_a_no_op(self, client, db, gallery_dir):
        creator = make_creator(db)
        model = make_model(db, creator)
        db.commit()

        resp = client.post(f"/scrape/apply-images/{model.id}", json={"image_urls": []})
        assert resp.status_code == 200
        assert resp.json()["image_paths"] == []


# ---------------------------------------------------------------------------
# PATCH /models/{id} — thumbnail_url handling in the metadata editor
# ---------------------------------------------------------------------------

class TestUpdateModelThumbnail:
    def test_changed_url_is_downloaded(self, client, db, thumb_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator, thumbnail_path="/somewhere/local.png")
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.patch(f"/models/{model.id}",
                            json={"thumbnail_url": "https://cdn.example.com/new.png"})
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_path == str(thumb_dir / f"{model.id}.png")
        assert model.thumbnail_url is None

    def test_unchanged_url_leaves_path_alone(self, client, db, thumb_dir, monkeypatch):
        """The editor resubmits the whole form — an unchanged thumbnail_url
        must not re-download or clobber the local thumbnail."""
        creator = make_creator(db)
        model = make_model(db, creator, thumbnail_path="/somewhere/local.png")
        model.thumbnail_url = "https://cdn.example.com/same.png"
        db.commit()

        def fail(req):
            raise AssertionError("should not fetch an unchanged URL")
        mock_http(monkeypatch, fail)

        resp = client.patch(f"/models/{model.id}",
                            json={"thumbnail_url": "https://cdn.example.com/same.png",
                                  "title": "New Title"})
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_path == "/somewhere/local.png"
        assert model.title == "New Title"

    def test_download_failure_clears_path_keeps_url(self, client, db, thumb_dir, monkeypatch):
        creator = make_creator(db)
        model = make_model(db, creator, thumbnail_path="/somewhere/local.png")
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(500))

        resp = client.patch(f"/models/{model.id}",
                            json={"thumbnail_url": "https://cdn.example.com/flaky.png"})
        assert resp.status_code == 200

        db.refresh(model)
        assert model.thumbnail_url == "https://cdn.example.com/flaky.png"
        assert model.thumbnail_path is None


# ---------------------------------------------------------------------------
# /files/image cache revalidation (#186)
# ---------------------------------------------------------------------------

class TestBatchFromUrlEndpoint:
    """POST /models/group/thumbnail/from-url — one image, fanned out to a group (#184)."""

    def test_fans_one_image_out_to_all_members(self, client, db, thumb_dir, monkeypatch):
        creator = make_creator(db)
        a = make_model(db, creator, name="A")
        b = make_model(db, creator, name="B")
        b.thumbnail_url = "https://old.example.com/old.png"
        db.commit()

        calls = {"n": 0}

        def handler(req):
            calls["n"] += 1
            return httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
        mock_http(monkeypatch, handler)

        resp = client.post(
            "/models/group/thumbnail/from-url",
            json={"model_ids": [a.id, b.id], "url": "https://cdn.example.com/group.png"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["downloaded"] is True
        assert sorted(body["updated"]) == sorted([a.id, b.id])
        assert body["missing"] == []
        # Fetched ONCE, written per member.
        assert calls["n"] == 1

        db.refresh(a); db.refresh(b)
        assert a.thumbnail_path == str(thumb_dir / f"{a.id}.png")
        assert b.thumbnail_path == str(thumb_dir / f"{b.id}.png")
        assert b.thumbnail_url is None
        assert (thumb_dir / f"{a.id}.png").read_bytes() == PNG_BYTES
        assert (thumb_dir / f"{b.id}.png").read_bytes() == PNG_BYTES

    def test_download_failure_stores_url_on_all_members(self, client, db, thumb_dir, monkeypatch):
        creator = make_creator(db)
        a = make_model(db, creator, name="A", thumbnail_path="/somewhere/a.png")
        b = make_model(db, creator, name="B", thumbnail_path="/somewhere/b.png")
        db.commit()

        mock_http(monkeypatch, lambda req: httpx.Response(403))

        resp = client.post(
            "/models/group/thumbnail/from-url",
            json={"model_ids": [a.id, b.id], "url": "https://cdn.example.com/blocked.png"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["downloaded"] is False
        assert "403" in body["detail"]

        db.refresh(a); db.refresh(b)
        for m in (a, b):
            assert m.thumbnail_url == "https://cdn.example.com/blocked.png"
            assert m.thumbnail_path is None

    def test_missing_ids_reported_others_updated(self, client, db, thumb_dir, monkeypatch):
        creator = make_creator(db)
        m = make_model(db, creator, name="M")
        db.commit()
        mock_http(monkeypatch, lambda req: httpx.Response(
            200, content=PNG_BYTES, headers={"content-type": "image/png"}))

        resp = client.post(
            "/models/group/thumbnail/from-url",
            json={"model_ids": [m.id, 999999], "url": "https://cdn.example.com/x.png"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["updated"] == [m.id]
        assert data["missing"] == [999999]

    def test_empty_ids_is_400(self, client, thumb_dir):
        resp = client.post(
            "/models/group/thumbnail/from-url",
            json={"model_ids": [], "url": "https://cdn.example.com/x.png"},
        )
        assert resp.status_code == 400

    def test_409_when_scan_running(self, client, db, thumb_dir, monkeypatch):
        from app.services import scanner
        creator = make_creator(db)
        m = make_model(db, creator, name="M")
        db.commit()

        monkeypatch.setattr(scanner, "get_status", lambda: {"running": True})
        resp = client.post(
            "/models/group/thumbnail/from-url",
            json={"model_ids": [m.id], "url": "https://cdn.example.com/x.png"},
        )
        assert resp.status_code == 409


class TestImageCacheControl:
    def test_serve_image_sends_no_cache(self, client, tmp_path, monkeypatch):
        import app.routers.files as files_module
        monkeypatch.setattr(files_module, "_allowed_roots", lambda: [tmp_path])

        img = tmp_path / "thumb.png"
        img.write_bytes(PNG_BYTES)

        resp = client.get("/files/image", params={"path": str(img)})
        assert resp.status_code == 200
        assert resp.headers.get("cache-control") == "no-cache"
