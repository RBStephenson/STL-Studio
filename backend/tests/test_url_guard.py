"""SSRF guard unit tests (STUDIO-68).

Covers scheme rejection, IP-literal classification (v4/v6/mapped), DNS
resolution via a monkeypatched getaddrinfo, and the httpx client event hook.
"""
import socket

import httpx
import pytest

from app.services import url_guard
from app.services.url_guard import (
    SSRFError,
    assert_public_url,
    guarded_async_client,
)


def _fake_getaddrinfo(*ips):
    """Build a getaddrinfo stand-in returning the given IP strings."""
    def _inner(host, port, *args, **kwargs):
        fam = socket.AF_INET6 if ":" in ips[0] else socket.AF_INET
        return [(fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port)) for ip in ips]
    return _inner


# --- scheme / shape -------------------------------------------------------

@pytest.mark.parametrize("url", [
    "ftp://example.com/x",
    "file:///etc/passwd",
    "gopher://example.com",
    "//example.com/x",          # no scheme
])
def test_non_http_schemes_rejected(url):
    with pytest.raises(SSRFError):
        assert_public_url(url)


def test_missing_host_rejected():
    with pytest.raises(SSRFError):
        assert_public_url("http://")


# --- IP literals (no DNS) -------------------------------------------------

@pytest.mark.parametrize("host", [
    "127.0.0.1",            # loopback
    "10.0.0.5",             # RFC1918
    "192.168.1.10",         # RFC1918
    "172.16.9.9",           # RFC1918
    "169.254.169.254",      # link-local (cloud metadata)
    "0.0.0.0",              # unspecified
    "[::1]",                # IPv6 loopback
    "[fc00::1]",            # IPv6 unique-local
    "[fe80::1]",            # IPv6 link-local
    "[::ffff:127.0.0.1]",   # IPv4-mapped loopback
])
def test_private_ip_literals_rejected(host):
    with pytest.raises(SSRFError):
        assert_public_url(f"http://{host}/path")


@pytest.mark.parametrize("host", ["1.1.1.1", "8.8.8.8", "[2606:4700:4700::1111]"])
def test_public_ip_literals_allowed(host):
    assert_public_url(f"https://{host}/path")   # does not raise


# --- DNS resolution -------------------------------------------------------

def test_hostname_resolving_to_private_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("10.1.2.3"))
    with pytest.raises(SSRFError):
        assert_public_url("http://sneaky.example.com/")


def test_hostname_resolving_to_public_allowed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    assert_public_url("http://example.com/")


def test_any_private_answer_rejects(monkeypatch):
    # A host that returns both a public and a private record must be rejected —
    # the private answer is enough to abuse.
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34", "127.0.0.1"))
    with pytest.raises(SSRFError):
        assert_public_url("http://mixed.example.com/")


def test_unresolvable_host_rejected(monkeypatch):
    def _boom(*a, **k):
        raise socket.gaierror("nope")
    monkeypatch.setattr(socket, "getaddrinfo", _boom)
    with pytest.raises(SSRFError):
        assert_public_url("http://does-not-exist.invalid/")


# --- httpx client hook ----------------------------------------------------

@pytest.mark.anyio
async def test_hook_rejects_private_request():
    with pytest.raises(SSRFError):
        await url_guard._reject_private_requests(httpx.Request("GET", "http://127.0.0.1/"))


@pytest.mark.anyio
async def test_hook_allows_public_request(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo("93.184.216.34"))
    # Must not raise.
    await url_guard._reject_private_requests(httpx.Request("GET", "http://example.com/"))


def test_guarded_client_preserves_caller_request_hooks():
    async def _other_hook(request):  # pragma: no cover - identity check only
        return None

    client = guarded_async_client(event_hooks={"request": [_other_hook]})
    try:
        hooks = client.event_hooks["request"]
        assert _other_hook in hooks
        assert url_guard._reject_private_requests in hooks
    finally:
        # AsyncClient created outside an event loop; close the sync way.
        import anyio
        anyio.run(client.aclose)


def test_ssrf_error_is_httpx_error():
    # So scrapers' `except httpx.HTTPError` catches a mid-request block.
    assert issubclass(SSRFError, httpx.HTTPError)
