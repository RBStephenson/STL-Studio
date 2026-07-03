"""
STUDIO-31: scraper HTTP clients must cap redirect following to bound an SSRF
redirect chain (a malicious storefront bouncing us toward localhost / internal
addresses, or an infinite loop).

Rather than assert construction kwargs on every scraper, this drives a real
httpx.AsyncClient configured exactly as the scrapers configure it — with the
shared base.MAX_REDIRECTS cap — against a MockTransport that always redirects,
and proves httpx aborts at the cap instead of following unbounded.
"""
import asyncio

import httpx
import pytest

from app.services.scrapers.base import MAX_REDIRECTS


def _always_redirect_transport(counter: dict):
    """Every request gets a 307 to the next hop — an unbounded redirect chain."""
    def handler(request: httpx.Request) -> httpx.Response:
        counter["hops"] = counter.get("hops", 0) + 1
        nxt = f"https://example.test/hop/{counter['hops']}"
        return httpx.Response(307, headers={"Location": nxt})
    return httpx.MockTransport(handler)


def _chain_then_ok_transport(length: int):
    """`length` redirects, then a 200 — a finite legitimate chain."""
    state = {"hops": 0}
    def handler(request: httpx.Request) -> httpx.Response:
        if state["hops"] < length:
            state["hops"] += 1
            return httpx.Response(307, headers={"Location": f"https://example.test/h/{state['hops']}"})
        return httpx.Response(200, text="ok")
    return httpx.MockTransport(handler)


def test_max_redirects_constant_is_five():
    # Pin the value the SSRF hardening promised; a silent bump to httpx's
    # default (20) would reopen the chain.
    assert MAX_REDIRECTS == 5


def test_unbounded_chain_aborts_at_cap():
    counter: dict = {}

    async def go():
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            transport=_always_redirect_transport(counter),
        ) as client:
            await client.get("https://example.test/start")

    with pytest.raises(httpx.TooManyRedirects):
        asyncio.run(go())

    # Original request + MAX_REDIRECTS follows, then the next 307 trips the cap.
    assert counter["hops"] == MAX_REDIRECTS + 1


def test_chain_within_cap_succeeds():
    async def go():
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=MAX_REDIRECTS,
            transport=_chain_then_ok_transport(MAX_REDIRECTS),
        ) as client:
            return await client.get("https://example.test/start")

    resp = asyncio.run(go())
    assert resp.status_code == 200
    assert resp.text == "ok"
