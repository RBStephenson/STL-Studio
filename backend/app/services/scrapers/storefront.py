"""
Storefront scrapers — given a creator's profile/store URL, return
a list of all their products with thumbnail + metadata.

Supported:
  MyMiniFactory  https://www.myminifactory.com/users/{username}
  Gumroad        https://{creator}.gumroad.com  or  gumroad.com/{creator}
  Cults3D        https://cults3d.com/en/users/{username}/creations
  Loot Studios   https://app.lootstudios.com/bundle-store/    (full catalog, one entry per bundle)
                 https://app.lootstudios.com/bundle/{slug}/  (one bundle, one entry per miniature)
"""
import re
import json
import logging
import asyncio
import httpx
from app.services.url_guard import guarded_async_client
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional

from app.services.scrapers.base import detect_site, MAX_REDIRECTS

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class StorefrontProduct:
    title: str
    source_url: str
    source_site: str
    external_id: Optional[str] = None
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None
    tags: list[str] = field(default_factory=list)


async def scrape_storefront(url: str, mmf_api_key: Optional[str] = None) -> list[StorefrontProduct]:
    site = detect_site(url)
    if site == "myminifactory":
        return await _scrape_mmf(url, mmf_api_key)
    if site == "gumroad":
        return await _scrape_gumroad(url)
    if site == "cults3d":
        return await _scrape_cults(url)
    if site == "loot-studios":
        return await _scrape_loot_studios(url)
    return []


# ---------------------------------------------------------------------------
# MyMiniFactory
# ---------------------------------------------------------------------------
async def _scrape_mmf(url: str, api_key: Optional[str] = None) -> list[StorefrontProduct]:
    """
    List a MMF user store's products.

    MMF renders listings client-side but embeds a JSON blob with all object IDs
    grouped by store category. We collect the unique IDs, then resolve each via
    the MMF adapter (``mmf.fetch``) — which uses the MMF REST API when a key is
    set and falls back to scraping the object page otherwise. This replaces the
    old per-object HTML JSON-LD regex with structured, more robust data.
    """
    # Local import avoids a package-init import cycle (mmf imports storefront).
    from app.services.scrapers import mmf

    async with guarded_async_client(timeout=20, headers=_HEADERS, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"MMF profile fetch failed: {e}")
            return []

    # Extract all object IDs from the embedded store JSON (script block that
    # has a "categories" key with nested "objects" arrays of integers).
    object_ids: list[int] = []
    seen: set[int] = set()
    for m in re.finditer(r'"objects":\[([0-9,]+)\]', r.text):
        for id_str in m.group(1).split(","):
            oid = int(id_str)
            if oid not in seen:
                seen.add(oid)
                object_ids.append(oid)

    if not object_ids:
        logger.warning("MMF: no object IDs found in store page — site structure may have changed")
        return []

    logger.info(f"MMF: found {len(object_ids)} unique object IDs, fetching details…")

    semaphore = asyncio.Semaphore(10)

    async def fetch_object(oid: int) -> StorefrontProduct | None:
        obj_url = f"https://www.myminifactory.com/object/3d-print-{oid}"
        async with semaphore:
            scraped = await mmf.fetch(obj_url, api_key=api_key)
        if not scraped or not scraped.title:
            return None
        return StorefrontProduct(
            title=scraped.title,
            source_url=scraped.source_url or obj_url,
            source_site="myminifactory",
            external_id=scraped.external_id or str(oid),
            thumbnail_url=scraped.thumbnail_url,
            description=scraped.description,
            tags=scraped.tags,
        )

    results = await asyncio.gather(*(fetch_object(oid) for oid in object_ids))
    products = [p for p in results if p is not None]
    logger.info(f"MMF: listed {len(products)} products successfully")
    return products


# ---------------------------------------------------------------------------
# Gumroad
# ---------------------------------------------------------------------------

# Gumroad's creator profile is an Inertia.js app. The initial HTML embeds the
# page's props as an HTML-escaped JSON blob on `<div id="app" data-page="…">`.
# Products live at props.sections[].search_results.products[], each carrying a
# name, permalink, canonical url and thumbnail_url — no per-product fetch needed.
#
# Each section embeds only its first page (~9 products) while search_results.total
# is the full count. The "load more" SPA calls a products-search endpoint scoped
# by the section id + the seller's external id; we page through it to recover the
# rest (#316):
#   GET {profile_base}/products/search?section_id={id}&user_id={creator_id}&from={offset}
# `from` is a 0-based offset into the section's results; the response mirrors the
# embedded product shape under "products".

_GUMROAD_PAGE_SIZE = 9      # products per search response (Gumroad's fixed page size)
_GUMROAD_MAX_PAGES = 200    # bound the per-section walk so a store/markup change can't loop forever
_GUMROAD_CONCURRENCY = 8    # parallel search requests in flight


async def _scrape_gumroad(url: str) -> list[StorefrontProduct]:
    """
    Scrape a Gumroad creator store.
    Works for https://creator.gumroad.com or https://gumroad.com/creator.
    """
    async with guarded_async_client(timeout=20, headers=_HEADERS, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
        try:
            r = await client.get(url.rstrip("/"))
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Gumroad profile fetch failed: {e}")
            return []
        final_url = str(r.url)
        html = r.text

        page = _gumroad_inertia_page(html)
        if page is None:
            logger.warning(
                "Gumroad: could not parse Inertia page data from profile — "
                "site structure may have changed"
            )
            return []

        props = page.get("props", {})
        creator_id = (props.get("creator_profile") or {}).get("external_id")
        search_base = _gumroad_origin(final_url)

        products: list[StorefrontProduct] = []
        seen: set[str] = set()
        for section in props.get("sections", []):
            results = section.get("search_results") or {}
            embedded = results.get("products") or []
            _gumroad_add_products(embedded, products, seen, url)

            section_id = section.get("id")
            total = results.get("total") or 0
            if creator_id and section_id and total > len(embedded):
                more = await _gumroad_fetch_more(
                    client, search_base, section_id, creator_id, total, len(embedded)
                )
                _gumroad_add_products(more, products, seen, url)

    if not products:
        logger.warning("Gumroad: no products found in profile page data")
    else:
        logger.info(f"Gumroad: scraped {len(products)} products")
    return products


def _gumroad_add_products(
    raw: list[dict],
    products: list[StorefrontProduct],
    seen: set[str],
    url: str,
) -> None:
    """Append parsed, de-duplicated products from a list of raw Gumroad dicts."""
    for prod in raw:
        permalink = prod.get("permalink")
        name = (prod.get("name") or "").strip()
        if not permalink or not name or permalink in seen:
            continue
        seen.add(permalink)
        products.append(StorefrontProduct(
            title=name,
            source_url=prod.get("url") or f"{url.rstrip('/')}/l/{permalink}",
            source_site="gumroad",
            external_id=permalink,
            thumbnail_url=prod.get("thumbnail_url"),
        ))


def _gumroad_origin(url: str) -> str:
    """scheme://host for the products-search endpoint (drops path/query)."""
    m = re.match(r"(https?://[^/]+)", url)
    return m.group(1) if m else url.rstrip("/")


async def _gumroad_fetch_more(
    client: httpx.AsyncClient,
    search_base: str,
    section_id: str,
    creator_id: str,
    total: int,
    start: int,
) -> list[dict]:
    """
    Page through a section's products-search endpoint beyond the embedded first
    page. Offsets are independent, so requests run concurrently (bounded by
    _GUMROAD_CONCURRENCY) and capped at _GUMROAD_MAX_PAGES per section.
    """
    end = min(total, start + _GUMROAD_MAX_PAGES * _GUMROAD_PAGE_SIZE)
    if end < total:
        logger.warning(
            f"Gumroad: section capped at {_GUMROAD_MAX_PAGES} pages "
            f"({end}/{total} products) — unusually large store."
        )
    offsets = list(range(start, end, _GUMROAD_PAGE_SIZE))
    semaphore = asyncio.Semaphore(_GUMROAD_CONCURRENCY)

    async def fetch_page(offset: int) -> list[dict]:
        params = {"section_id": section_id, "user_id": creator_id, "from": offset}
        async with semaphore:
            try:
                r = await client.get(f"{search_base}/products/search", params=params)
                r.raise_for_status()
                return r.json().get("products") or []
            except Exception as e:
                logger.error(f"Gumroad products-search (from={offset}) failed: {e}")
                return []

    pages = await asyncio.gather(*(fetch_page(o) for o in offsets))
    return [prod for page in pages for prod in page]


def _gumroad_inertia_page(html: str) -> Optional[dict]:
    """Parse the JSON props from a Gumroad Inertia page (<div id="app" data-page>)."""
    soup = BeautifulSoup(html, "html.parser")
    app = soup.find(id="app")
    raw = app.get("data-page") if app else None
    if not raw:
        return None
    try:
        # BeautifulSoup already unescapes HTML entities in attribute values.
        return json.loads(raw)
    except (ValueError, TypeError) as e:
        logger.error(f"Gumroad: data-page JSON parse failed: {e}")
        return None


# ---------------------------------------------------------------------------
# Cults3D
# ---------------------------------------------------------------------------
_CULTS_CREATION_RE = re.compile(
    r"cults3d\.com/\w+/3d-(?:model|printing-file|modelling)/([\w/-]+)", re.I
)
_CULTS_USER_RE = re.compile(r"cults3d\.com/[^/]+/users/([^/?#]+)", re.I)

_CULTS_MAX_PAGES = 50  # bound the ?page=N walk so a markup change can't loop forever (#218)
_CULTS_API_PAGE_SIZE = 50

_CULTS_STOREFRONT_QUERY = """
query CreatorCreations($query: String!, $creatorNick: String!, $limit: Int!, $offset: Int!) {
  creationsSearchBatch(
    query: $query
    creatorNick: $creatorNick
    limit: $limit
    offset: $offset
  ) {
    total
    results {
      name
      slug
      url
      shortUrl
      illustrationImageUrl
      tags
    }
  }
}
"""


async def _scrape_cults(url: str) -> list[StorefrontProduct]:
    api_products = await _scrape_cults_api(url)
    if api_products is not None:
        return api_products
    return await _scrape_cults_html(url)


async def _scrape_cults_api(url: str) -> list[StorefrontProduct] | None:
    """List a Cults3D creator's products through the official GraphQL API."""
    from app.services.scrapers import cults3d

    m = _CULTS_USER_RE.search(url)
    if not m:
        return None
    creator_nick = m.group(1)

    creds = cults3d._get_credentials()
    if not creds:
        logger.info("Cults3D API credentials not configured — storefront API skipped")
        return None

    username, api_key = creds
    headers = {
        "Authorization": cults3d._auth_header(username, api_key),
        "Content-Type": "application/json",
    }

    products: list[StorefrontProduct] = []
    seen: set[str] = set()
    offset = 0

    async with guarded_async_client(timeout=20) as client:
        for _ in range(_CULTS_MAX_PAGES):
            try:
                r = await client.post(
                    cults3d._GRAPHQL_URL,
                    headers=headers,
                    json={
                        "query": _CULTS_STOREFRONT_QUERY,
                        "variables": {
                            "query": "",
                            "creatorNick": creator_nick,
                            "limit": _CULTS_API_PAGE_SIZE,
                            "offset": offset,
                        },
                    },
                )
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                logger.error(f"Cults3D storefront API failed for {creator_nick!r}: {e}")
                return None

            errors = data.get("errors")
            if errors:
                logger.error(f"Cults3D storefront API errors for {creator_nick!r}: {errors}")
                return None

            batch = (data.get("data") or {}).get("creationsSearchBatch") or {}
            results = batch.get("results") or []
            for item in results:
                title = (item.get("name") or "").strip()
                product_url = item.get("url") or item.get("shortUrl") or ""
                slug = item.get("slug") or extract_cults_slug(product_url)
                if not title or not product_url or product_url in seen:
                    continue
                seen.add(product_url)
                products.append(StorefrontProduct(
                    title=title,
                    source_url=product_url,
                    source_site="cults3d",
                    external_id=slug,
                    thumbnail_url=item.get("illustrationImageUrl"),
                    tags=item.get("tags") or [],
                ))

            if len(results) < _CULTS_API_PAGE_SIZE:
                return products
            offset += _CULTS_API_PAGE_SIZE

    logger.warning(
        f"Cults3D: stopping API storefront listing at page cap ({_CULTS_MAX_PAGES}) "
        f"for {creator_nick!r}; found {len(products)} products."
    )
    return products


def extract_cults_slug(url: str) -> Optional[str]:
    m = _CULTS_CREATION_RE.search(url)
    return m.group(1) if m else None


async def _scrape_cults_html(url: str) -> list[StorefrontProduct]:
    """
    Scrape a Cults3D user creations page.
    Accepts any Cults3D profile URL — /3d-models, /creations, or bare profile.
    Paginates via ?page=N, capped at _CULTS_MAX_PAGES.
    """
    # Strip any stale /creations suffix; the modern URL pattern is /3d-models
    base = url.rstrip("/")
    if base.endswith("/creations"):
        base = base[: -len("/creations")]

    products: list[StorefrontProduct] = []
    page = 1

    async with guarded_async_client(timeout=20, headers=_HEADERS, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
        while True:
            await asyncio.sleep(0.5)  # polite
            try:
                r = await client.get(base, params={"page": page})
                r.raise_for_status()
            except Exception as e:
                logger.error(f"Cults3D storefront page {page} failed: {e}")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("article.crea")
            if not cards:
                break

            for card in cards:
                # Link + title: the anchor has both href and title attribute
                link = card.select_one(
                    "a[href*='/3d-model/'], a[href*='/3d-printing-file/'], a[href*='/3d-modelling/']"
                )
                if not link:
                    continue
                href = link.get("href", "")
                product_url = href if href.startswith("http") else f"https://cults3d.com{href}"

                # Title: try the drawer-title strong, then the link's title attribute
                title_el = card.select_one("strong.drawer-title, .tbox-title, h3, h2")
                title = (
                    title_el.get_text(strip=True)
                    if title_el
                    else link.get("title") or href
                )

                # Thumbnail: lazy-loaded images use data-src
                img_el = card.select_one("img[data-src], img[src]")
                thumb = (img_el.get("data-src") or img_el.get("src")) if img_el else None

                products.append(StorefrontProduct(
                    title=title,
                    source_url=product_url,
                    source_site="cults3d",
                    external_id=extract_cults_slug(product_url),
                    thumbnail_url=thumb,
                ))

            # Next page: span.paginate.next > a
            next_btn = soup.select_one("span.paginate.next a, a[rel='next']")
            if not next_btn:
                break
            if page >= _CULTS_MAX_PAGES:
                logger.warning(
                    f"Cults3D: stopping at page cap ({_CULTS_MAX_PAGES}) with "
                    f"{len(products)} products — next link still present, possible "
                    "markup change or an unusually large store."
                )
                break
            page += 1

    return products


# ---------------------------------------------------------------------------
# Loot Studios
# ---------------------------------------------------------------------------

async def _scrape_loot_studios(url: str) -> list[StorefrontProduct]:
    """
    Two modes depending on the URL:

    - Bundle store URL (bundle-store/) → GetMyLootsCache → one product per bundle,
      for matching against top-level bundle folders.
    - Specific bundle URL (bundle/slug/) → Load_ObjectExplorer → one product per
      miniature, for matching against individual model folders within a bundle.
    """
    from app.services.scrapers import loot_studios as ls

    bundle_slug = ls.extract_id(url)

    if bundle_slug is None:
        # Bundle store or other loot-studios URL — return the full catalog
        bundles = await ls.fetch_store_catalog()
        if not bundles:
            logger.warning("Loot Studios: GetMyLootsCache returned no bundles")
            return []
        return [
            StorefrontProduct(
                title=b["obj_title"],
                source_url=f"https://app.lootstudios.com/bundle/{b['obj_slug']}/",
                source_site="loot-studios",
                external_id=b["obj_slug"],
                thumbnail_url=b.get("obj_image") or None,
            )
            for b in bundles
        ]

    # Specific bundle — return individual miniatures
    minis = await ls.fetch_bundle_products(url)
    if not minis:
        logger.warning(f"Loot Studios: no miniatures found for {url}")
        return []

    return [
        StorefrontProduct(
            title=m.name,
            source_url=f"https://app.lootstudios.com/bundle/{bundle_slug}/",
            source_site="loot-studios",
            external_id=m.thumbnail_url.split("/")[-1].split(".")[0],
            thumbnail_url=m.thumbnail_url,
        )
        for m in minis
    ]
