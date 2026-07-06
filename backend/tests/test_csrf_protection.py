"""
Tests for the write-request origin/host guard middleware (issue #213).

The API binds to 127.0.0.1, but any web page can still fire requests at
http://localhost:<port>. State-changing methods must therefore present a
trusted Origin (when one is sent at all) and a trusted Host header. "Trusted"
is localhost plus any hostnames in TRUSTED_HOSTS (for reverse-proxy deploys).
"""
from app.config import settings as app_settings
from app.main import _host_is_trusted, _origin_is_trusted


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


def test_open_folder_is_post(client, tmp_path):
    # Register a scan root so _is_safe_path passes; then verify CSRF didn't
    # block the request (which would set detail="Cross-origin request blocked").
    client.post("/scan/roots", json={"path": str(tmp_path), "layout": "{creator}"})
    r = client.post(f"/files/open-folder?path={tmp_path}")
    assert r.status_code != 405
    if r.status_code == 403:
        assert "Cross-origin" not in r.json().get("detail", "")


# ---------------------------------------------------------------------------
# Helper edge cases
# ---------------------------------------------------------------------------

def test_origin_is_trusted():
    assert _origin_is_trusted("http://localhost:3000")
    assert _origin_is_trusted("http://127.0.0.1:8484")
    assert _origin_is_trusted("http://[::1]:8484")
    assert not _origin_is_trusted("https://evil.example")
    assert not _origin_is_trusted("https://localhost.evil.example")
    assert not _origin_is_trusted("null")
    assert not _origin_is_trusted("")


def test_host_is_trusted():
    assert _host_is_trusted("localhost")
    assert _host_is_trusted("localhost:8484")
    assert _host_is_trusted("127.0.0.1:8000")
    assert _host_is_trusted("[::1]:8484")
    assert not _host_is_trusted("testserver")
    assert not _host_is_trusted("rebind.evil.example")
    assert not _host_is_trusted("localhost.evil.example:80")
    assert not _host_is_trusted("")


# ---------------------------------------------------------------------------
# TRUSTED_HOSTS — running behind a reverse proxy on a custom domain
# ---------------------------------------------------------------------------

def test_trusted_hosts_allows_configured_origin_and_host(monkeypatch):
    monkeypatch.setattr(app_settings, "trusted_hosts", "stl.pagden.us")
    # Matched by hostname, regardless of scheme or port.
    assert _origin_is_trusted("https://stl.pagden.us")
    assert _host_is_trusted("stl.pagden.us")
    assert _host_is_trusted("stl.pagden.us:443")
    # localhost still trusted; unrelated domains still rejected.
    assert _origin_is_trusted("http://localhost:3000")
    assert not _origin_is_trusted("https://evil.example")
    assert not _host_is_trusted("evil.example")


def test_trusted_host_write_is_allowed_through_middleware(client, monkeypatch):
    monkeypatch.setattr(app_settings, "trusted_hosts", "stl.pagden.us")
    r = client.post(
        "/scan/cancel",
        headers={"Origin": "https://stl.pagden.us", "Host": "stl.pagden.us"},
    )
    assert r.status_code != 403


def test_untrusted_host_still_blocked_when_trusted_hosts_set(client, monkeypatch):
    # Configuring one domain must not open the guard to others.
    monkeypatch.setattr(app_settings, "trusted_hosts", "stl.pagden.us")
    r = client.post("/database/reset", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert "Cross-origin" in r.json()["detail"]
