"""
Tests for the localhost CSRF protection middleware (issue #213).

The API binds to 127.0.0.1, but any web page can still fire requests at
http://localhost:<port>. State-changing methods must therefore present a
local Origin (when one is sent at all) and a local Host header.
"""
from app.main import _host_is_local, _origin_is_local


EVIL_ORIGIN = {"Origin": "https://evil.example"}


# ---------------------------------------------------------------------------
# Middleware behavior through the app
# ---------------------------------------------------------------------------

def test_cross_origin_post_is_rejected(client):
    r = client.post("/database/reset", headers=EVIL_ORIGIN)
    assert r.status_code == 403
    assert "Cross-origin" in r.json()["detail"]


def test_cross_origin_patch_and_delete_are_rejected(client):
    assert client.patch("/models/1", json={}, headers=EVIL_ORIGIN).status_code == 403
    assert client.delete("/collections/1", headers=EVIL_ORIGIN).status_code == 403


def test_null_origin_is_rejected(client):
    # "null" Origin = sandboxed iframe / file:// page, not the local frontend.
    r = client.post("/database/reset", headers={"Origin": "null"})
    assert r.status_code == 403


def test_local_origin_post_is_allowed(client):
    # http://localhost:3000 is the dev frontend; must pass the middleware.
    r = client.post("/scan/cancel", headers={"Origin": "http://localhost:3000"})
    assert r.status_code != 403


def test_post_without_origin_is_allowed(client):
    # curl / local scripts send no Origin header.
    r = client.post("/scan/cancel")
    assert r.status_code != 403


def test_non_local_host_is_rejected_dns_rebinding(client):
    # DNS rebinding: browser sends the attacker domain in Origin+Host.
    r = client.post("/scan/cancel", headers={"Host": "rebind.evil.example"})
    assert r.status_code == 403
    assert "Host" in r.json()["detail"]


def test_cross_origin_get_is_not_blocked(client):
    # Reads are left to CORS (no Access-Control-Allow-Origin = unreadable).
    r = client.get("/models/stats", headers=EVIL_ORIGIN)
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# open-folder is no longer a GET (side effect on GET = <img>-tag triggerable)
# ---------------------------------------------------------------------------

def test_open_folder_get_is_gone(client):
    assert client.get("/files/open-folder?path=/tmp").status_code == 405


def test_open_folder_is_post(client):
    # 403 would mean blocked; anything else (501 no GUI in CI, 404, 200) means
    # the route exists as POST and passed the middleware.
    r = client.post("/files/open-folder?path=/tmp")
    assert r.status_code != 405
    assert r.status_code != 403


# ---------------------------------------------------------------------------
# Helper edge cases
# ---------------------------------------------------------------------------

def test_origin_is_local():
    assert _origin_is_local("http://localhost:3000")
    assert _origin_is_local("http://127.0.0.1:8484")
    assert _origin_is_local("http://[::1]:8484")
    assert not _origin_is_local("https://evil.example")
    assert not _origin_is_local("https://localhost.evil.example")
    assert not _origin_is_local("null")
    assert not _origin_is_local("")


def test_host_is_local():
    assert _host_is_local("localhost")
    assert _host_is_local("localhost:8484")
    assert _host_is_local("127.0.0.1:8000")
    assert _host_is_local("[::1]:8484")
    assert not _host_is_local("testserver")
    assert not _host_is_local("rebind.evil.example")
    assert not _host_is_local("localhost.evil.example:80")
    assert not _host_is_local("")
