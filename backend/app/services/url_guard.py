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
import ssl
import socket
from urllib.parse import urlparse

import httpx
import truststore


class SSRFError(httpx.RequestError):
    """A URL was rejected because it is not a safe, public http(s) target.

    Subclasses ``httpx.RequestError`` (itself an ``httpx.HTTPError``) so that a
    block raised mid-request by the client event hook is caught by the scrapers'
    existing ``except httpx.HTTPError`` handlers rather than 500-ing. Callers
    that need to distinguish it (thumbnails) still catch ``SSRFError`` first."""


_ALLOWED_SCHEMES = ("http", "https")


def _is_blocked_ip(ip: ipaddress._BaseAddress, *, allow_private: bool = False) -> bool:
    """True if `ip` is anything other than a routable public address.

    IPv4-mapped IPv6 (``::ffff:127.0.0.1``) is unwrapped first so an embedded
    private v4 address can't slip through the v6 checks.

    With ``allow_private=True`` (for user-configured local AI endpoints —
    Ollama/LM Studio typically listen on loopback or a LAN address), private
    and loopback addresses are permitted, but link-local (which covers the
    ``169.254.169.254`` cloud metadata address), multicast, reserved, and
    unspecified addresses are still blocked. IPv6 loopback (``::1``) is
    exempted from the reserved check specifically — stdlib's ``is_reserved``
    classifies it as reserved *and* loopback simultaneously."""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if allow_private:
        return (
            ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or (ip.is_reserved and not ip.is_loopback)
        )
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


def assert_public_url(url: str, *, allow_private: bool = False) -> None:
    """Raise SSRFError unless `url` is an http(s) URL whose host resolves only to
    safe addresses. All resolved addresses must pass — one bad answer is enough
    to reject, so a multi-record host can't smuggle an internal IP.

    ``allow_private=True`` permits loopback/private-network targets (for
    user-configured local AI endpoints) while still blocking link-local
    (cloud metadata), multicast, reserved, and unspecified addresses."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFError(f"Blocked URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise SSRFError("URL has no host")
    port = parsed.port or (443 if scheme == "https" else 80)
    for ip in _resolve_ips(host, port):
        if _is_blocked_ip(ip, allow_private=allow_private):
            raise SSRFError(f"URL host {host!r} resolves to a non-public address")


async def _reject_private_requests(request: httpx.Request) -> None:
    """httpx request event hook — validates the initial URL and every redirect
    target before the request goes out."""
    assert_public_url(str(request.url))


async def _reject_unsafe_requests_allow_private(request: httpx.Request) -> None:
    """Same as `_reject_private_requests` but permits loopback/private hosts,
    for clients that talk to user-configured local AI endpoints."""
    assert_public_url(str(request.url), allow_private=True)


def _system_ssl_context() -> ssl.SSLContext:
    """Return an SSL context backed by the operating system certificate store."""
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def guarded_async_client(*, allow_private: bool = False, **kwargs) -> httpx.AsyncClient:
    """An ``httpx.AsyncClient`` that runs `assert_public_url` on every outgoing
    request (including redirect hops). Merges the SSRF hook with any request
    hooks the caller passes so nothing is silently dropped.

    Uses the operating system trust store by default because desktop Windows
    installs may trust certificates that certifi does not.

    ``allow_private=True`` permits loopback/private targets, for clients that
    talk to user-configured local AI endpoints.
    """
    hooks = dict(kwargs.pop("event_hooks", None) or {})
    request_hooks = list(hooks.get("request", []))
    hook = _reject_unsafe_requests_allow_private if allow_private else _reject_private_requests
    request_hooks.append(hook)
    hooks["request"] = request_hooks
    kwargs.setdefault("verify", _system_ssl_context())
    return httpx.AsyncClient(event_hooks=hooks, **kwargs)
