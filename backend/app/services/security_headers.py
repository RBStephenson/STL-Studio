"""Security response headers for the browser-served deployments (STUDIO-370).

STUDIO-258 put a Content-Security-Policy on the *Electron session layer*
(`desktop/src/csp.ts`), which protects the desktop window and nothing else.
Every other way of reaching this application - the Docker deployment behind
nginx, the standalone one-file binary, and the API itself - was served with no
CSP, no `X-Frame-Options` and no `X-Content-Type-Options`.

The browser path is weaker than the Electron one on every point that let
STUDIO-258 be judged defence-in-depth: it is reachable over a network rather
than bound to a loopback sidecar, the client is a general-purpose browser
carrying the user's other tabs and extensions, and nothing stopped the
unauthenticated UI from being framed. The untrusted-content sinks are identical
- scraped storefront metadata and imported painting guides reach
`dangerouslySetInnerHTML` in `GuideReader` - and `script-src 'self'` is the
layer that survives a DOMPurify bypass. On the browser path that layer was
simply absent.

**This module is the single source of truth for the browser-path policy.** The
directives below are the same set `desktop/src/csp.ts` validated against the
real production `frontend/dist` bundle, so they are known-good for this
frontend rather than guessed. nginx cannot read Python, so
`frontend/nginx.conf.template` carries a derived copy of the header values;
`tests/test_security_headers.py` pins the two character-for-character, which is
what stops that copy rotting silently. Change the policy here and that test
names every other place that has to follow.
"""
from collections.abc import Awaitable, Callable

from starlette.requests import Request
from starlette.responses import Response

# Kept byte-identical to desktop/src/csp.ts::CSP_DIRECTIVES. Each relaxation is
# required by a real rendering path and was derived from actual usage (see
# STUDIO-258 / PR #1250); tightening one silently breaks a feature, because CSP
# violations are console-only.
CSP_DIRECTIVES: tuple[str, ...] = (
    "default-src 'self'",
    # No inline scripts in the Vite build, so this can stay strict - it is the
    # directive that actually contains an XSS via the sanitized guide-HTML sinks.
    "script-src 'self'",
    # React inline `style={{}}` and three/drei both emit inline styles.
    "style-src 'self' 'unsafe-inline'",
    # Scraped storefront thumbnails render straight from arbitrary CDNs
    # (FindOnWeb, MetadataEditor, StorefrontEnrich), so remote https is required.
    "img-src 'self' data: blob: https:",
    "media-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    # No worker-src: the bundle constructs no workers, so default-src governs.
    "object-src 'none'",
    "frame-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
)

CSP_HEADER_NAME = "Content-Security-Policy"


def build_csp_header() -> str:
    return "; ".join(CSP_DIRECTIVES)


# Headers with no Electron equivalent, because Electron's renderer is not a
# general-purpose browser. `X-Frame-Options` duplicates `frame-ancestors 'none'`
# for clients too old to honour the CSP directive.
#
# Deliberately no Strict-Transport-Security: plenty of deployments are plain
# HTTP on a LAN, where HSTS would lock the user out of their own instance.
BROWSER_PATH_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def security_headers() -> dict[str, str]:
    """Every security header this application emits, name -> value."""
    return {CSP_HEADER_NAME: build_csp_header(), **BROWSER_PATH_HEADERS}


async def apply_security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Stamp the security headers onto every response leaving the app.

    Registered last in `create_app`, which makes it the *outermost* middleware
    (Starlette builds the stack so the most recently added wraps the rest), so
    it also covers responses the inner layers short-circuit - the write-origin
    guard's 403s and CORS preflight replies - not just routed ones. Being
    middleware rather than a router dependency is also what covers the
    standalone binary's `StaticFiles` mount and its SPA-fallback `FileResponse`,
    neither of which is an APIRoute.

    Assignment replaces rather than appends: browsers *intersect* multiple CSP
    headers instead of letting the last one win, so a second policy from
    anywhere downstream could silently tighten this one and break rendering
    with only a console message to show for it. Same strip-and-replace reasoning
    as `desktop/src/csp.ts::applyCspHeaders`.
    """
    response = await call_next(request)
    for name, value in security_headers().items():
        response.headers[name] = value
    return response
