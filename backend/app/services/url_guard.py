"""SSRF guard for server-side fetches of user-supplied URLs (STUDIO-68).

The app runs on localhost and fetches URLs the user pastes (thumbnail images,
storefront pages). Without a guard, a URL like ``http://169.254.169.254/`` or
``http://127.0.0.1:8000/admin`` would make the server issue requests into the
user's own machine / internal network — a classic SSRF vector, made worse by
DNS rebinding (a public hostname that resolves to a private IP).

`assert_public_url` is the single chokepoint: it rejects non-http(s) schemes
and any host that resolves to a loopback / private / link-local / unique-local
/ reserved / multicast / unspecified address. `guarded_async_client` wraps an
``httpx.AsyncClient`` with a request event hook so the check also runs on every
redirect hop (the rebind window), not just the initial URL.

Note on residual DNS-rebind risk: we validate the resolved address(es) but do
not pin the connection to a validated IP, so a hostile resolver could in theory
return a public IP to the guard and a private IP to the socket. Closing that
fully needs connection-level pinning; for a single-user desktop app the resolve
-and-reject check removes the practical attack surface. Tracked for follow-up.
"""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx


class SSRFError(httpx.RequestError):
    """A URL was rejected because it is not a safe, public http(s) target.

    Subclasses ``httpx.RequestError`` (itself an ``httpx.HTTPError``) so that a
    block raised mid-request by the client event hook is caught by the scrapers'
    existing ``except httpx.HTTPError`` handlers rather than 500-ing. Callers
    that need to distinguish it (thumbnails) still catch ``SSRFError`` first."""


_ALLOWED_SCHEMES = ("http", "https")


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """True if `ip` is anything other than a routable public address.

    IPv4-mapped IPv6 (``::ffff:127.0.0.1``) is unwrapped first so an embedded
    private v4 address can't slip through the v6 checks."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolve_ips(host: str, port: int | None) -> list[ipaddress._BaseAddress]:
    """Resolve `host` to every address it maps to. A bare IP literal is parsed
    directly (no DNS). Raises SSRFError if the host can't be resolved."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SSRFError(f"Could not resolve host {host!r}") from e
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def assert_public_url(url: str) -> None:
    """Raise SSRFError unless `url` is an http(s) URL whose host resolves only to
    public addresses. All resolved addresses must be public — one private answer
    is enough to reject, so a multi-record host can't smuggle an internal IP."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(f"Blocked URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise SSRFError("URL has no host")
    port = parsed.port or (443 if scheme == "https" else 80)
    for ip in _resolve_ips(host, port):
        if _is_blocked_ip(ip):
            raise SSRFError(f"URL host {host!r} resolves to a non-public address")


async def _reject_private_requests(request: httpx.Request) -> None:
    """httpx request event hook — validates the initial URL and every redirect
    target before the request goes out."""
    assert_public_url(str(request.url))


def guarded_async_client(**kwargs) -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` that runs `assert_public_url` on every outgoing
    request (including redirect hops). Merges the SSRF hook with any request
    hooks the caller passes so nothing is silently dropped."""
    hooks = dict(kwargs.pop("event_hooks", None) or {})
    request_hooks = list(hooks.get("request", []))
    request_hooks.append(_reject_private_requests)
    hooks["request"] = request_hooks
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)
