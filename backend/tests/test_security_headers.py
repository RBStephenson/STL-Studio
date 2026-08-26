"""Security response headers on the browser-served paths (STUDIO-370).

Two servers emit HTML for this application and neither is Electron: nginx
serves the SPA on the Docker path, and the standalone one-file binary serves it
from FastAPI's own StaticFiles mount. Before STUDIO-370 both were bare - no CSP,
no X-Frame-Options, no nosniff - while `desktop/src/csp.ts` protected the
desktop window only.

`app.services.security_headers` is the single source of truth. nginx cannot
read Python, so `frontend/nginx.conf.template` holds a derived copy; the
"nginx template" tests below are the stated owner of that duplication and pin
the two character-for-character.
"""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.security_headers import (
    BROWSER_PATH_HEADERS,
    CSP_HEADER_NAME,
    build_csp_header,
    security_headers,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
NGINX_TEMPLATE = REPOSITORY_ROOT / "frontend/nginx.conf.template"

LOCAL_ORIGIN = {"Origin": "http://localhost:3000"}
EVIL_ORIGIN = {"Origin": "https://evil.example"}


def _directive(name: str) -> str | None:
    prefix = f"{name} "
    return next(
        (d for d in build_csp_header().split("; ") if d == name or d.startswith(prefix)),
        None,
    )


# ---------------------------------------------------------------------------
# The policy itself
# ---------------------------------------------------------------------------

def test_script_src_stays_strict():
    # The directive that actually contains an XSS reaching the guide-HTML sinks
    # via dangerouslySetInnerHTML, if DOMPurify is ever bypassed.
    assert _directive("script-src") == "script-src 'self'"


def test_framing_is_denied_two_ways():
    # frame-ancestors for modern clients, X-Frame-Options for older ones.
    assert _directive("frame-ancestors") == "frame-ancestors 'none'"
    assert BROWSER_PATH_HEADERS["X-Frame-Options"] == "DENY"


def test_remote_https_images_stay_allowed():
    # Scraped storefront thumbnails render straight from arbitrary CDNs.
    # Tightening this to 'self' silently blanks the gallery - CSP violations
    # are console-only, so nothing fails loudly.
    assert "https:" in (_directive("img-src") or "")


def test_inline_styles_stay_allowed():
    # React inline style={{}} and three/drei both emit inline styles.
    assert "'unsafe-inline'" in (_directive("style-src") or "")


def test_no_hsts_is_emitted():
    # Plenty of deployments are plain HTTP on a LAN; HSTS would lock the user
    # out of their own instance with no way back.
    assert not any("strict-transport" in name.lower() for name in security_headers())


def test_policy_survives_envsubst():
    # The nginx template is run through the nginx image's envsubst at container
    # start. A `$` anywhere in the policy would be eaten as a variable and the
    # header would ship silently truncated.
    assert "$" not in build_csp_header()


# ---------------------------------------------------------------------------
# Middleware behaviour through the app
# ---------------------------------------------------------------------------

def test_api_response_carries_every_security_header(client):
    r = client.get("/models/stats")
    assert r.status_code == 200
    for name, value in security_headers().items():
        assert r.headers[name] == value


def test_exactly_one_csp_header_is_sent(client):
    # Browsers INTERSECT multiple CSP headers rather than letting the last one
    # win, so a duplicate is not harmless - it silently tightens the policy.
    r = client.get("/models/stats")
    assert len(r.headers.get_list(CSP_HEADER_NAME)) == 1


def test_headers_land_on_the_write_guard_rejection(client):
    # Proves the middleware is registered OUTSIDE _block_cross_origin_writes:
    # this 403 never reaches a route, so an inner middleware would miss it.
    r = client.post("/database/reset", headers=EVIL_ORIGIN)
    assert r.status_code == 403
    assert r.headers[CSP_HEADER_NAME] == build_csp_header()


def test_headers_land_on_a_cors_preflight(client):
    # CORSMiddleware answers preflights itself without calling downstream.
    r = client.options(
        "/models/stats",
        headers={**LOCAL_ORIGIN, "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers[CSP_HEADER_NAME] == build_csp_header()


def test_headers_land_on_a_404(client):
    r = client.get("/no-such-route")
    assert r.status_code == 404
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_headers_land_on_the_standalone_static_mount(tmp_path):
    """The standalone binary's real shape: create_app + a StaticFiles mount.

    The mount is added after create_app returns and is not an APIRoute, so a
    router-level dependency would never see it - middleware is what covers it.
    """
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")

    from fastapi.staticfiles import StaticFiles

    app = create_app(api_prefix="/api")
    app.mount("/", StaticFiles(directory=str(dist), html=True), name="static")

    # No `with`: the lifespan (startup migrations) is irrelevant here and would
    # touch a real database.
    r = TestClient(app, base_url="http://localhost").get("/")

    assert r.status_code == 200
    for name, value in security_headers().items():
        assert r.headers[name] == value


# ---------------------------------------------------------------------------
# nginx template - the derived copy, pinned to the canonical one
# ---------------------------------------------------------------------------

def _location_block(config: str, path: str) -> str:
    start = config.index(f"location {path} {{")
    depth, index = 0, start
    while index < len(config):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[start : index + 1]
        index += 1
    raise AssertionError(f"unterminated `location {path}` block")


def _add_headers(block: str) -> dict[str, str]:
    return {
        name: value
        for name, value in re.findall(r'add_header\s+(\S+)\s+"([^"]*)"', block)
    }


def test_nginx_spa_policy_matches_the_canonical_one():
    """The stated owner of the nginx/Python duplication.

    If this fails, someone changed the policy in one place. The Python module
    is canonical; regenerate the nginx values from it.
    """
    block = _location_block(NGINX_TEMPLATE.read_text(encoding="utf-8"), "/")
    assert _add_headers(block) == security_headers()


def test_nginx_headers_are_marked_always():
    # Without `always`, nginx drops add_header on non-2xx/3xx responses - so
    # every error page would ship unprotected.
    block = _location_block(NGINX_TEMPLATE.read_text(encoding="utf-8"), "/")
    lines = [line for line in block.splitlines() if line.lstrip().startswith("add_header")]
    # Guard against passing vacuously if the directives ever go missing.
    assert len(lines) == len(security_headers())
    for line in lines:
        assert line.rstrip().endswith("always;"), line


def test_nginx_does_not_stamp_the_proxied_api_paths():
    """/api/ is proxied from the backend, which sends its own copy.

    Stamping in both places would put two CSP headers on the same response, and
    browsers intersect them into a policy nobody wrote.
    """
    config = NGINX_TEMPLATE.read_text(encoding="utf-8")
    for path in ("/api/", "= /api/database/restore"):
        assert not _add_headers(_location_block(config, path))


def test_nginx_sets_no_headers_at_server_level():
    # Server-level add_header would inherit into the /api/ locations, which is
    # the same double-stamping trap by another route.
    config = NGINX_TEMPLATE.read_text(encoding="utf-8")
    outside = config
    for path in ("/", "/api/", "= /api/database/restore"):
        outside = outside.replace(_location_block(config, path), "")
    assert "add_header" not in outside


def test_nginx_emits_no_hsts():
    # Directives only, not prose - the template carries a comment explaining
    # why HSTS is deliberately absent, and grepping the raw text would match it.
    directives = re.findall(r"^\s*add_header\s+(\S+)", NGINX_TEMPLATE.read_text(encoding="utf-8"), re.M)
    assert not any(name.lower() == "strict-transport-security" for name in directives)
