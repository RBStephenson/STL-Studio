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
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
from typing import Optional

from app.services.scrapers.base import detect_site

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


async def scrape_storefront(url: str) -> list[StorefrontProduct]:
    site = detect_site(url)
    if site == "myminifactory":
        return await _scrape_mmf(url)
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
_MMF_ID_RE = re.compile(r"-(\d+)$")
_MMF_SKU_RE = re.compile(r"3DO(\d+)")

async def _scrape_mmf(url: str) -> list[StorefrontProduct]:
    """
    Scrape a MMF user store page.

    MMF renders product listings client-side, but embeds a JSON blob in the page
    that contains all object IDs grouped by store category.  We collect the unique
    IDs, then fetch each object page concurrently and pull the JSON-LD <script>
    (schema.org Product) for name / canonical URL / thumbnail — no auth required.
    """
    async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
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

    async def fetch_object(client: httpx.AsyncClient, oid: int) -> StorefrontProduct | None:
        obj_url = f"https://www.myminifactory.com/object/3d-print-{oid}"
        async with semaphore:
            try:
                r = await client.get(obj_url)
                r.raise_for_status()
            except Exception:
                return None

        for script_m in re.finditer(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            r.text, re.DOTALL | re.I
        ):
            try:
                d = json.loads(script_m.group(1))
            except Exception:
                continue
            if d.get("@type") != "Product":
                continue

            name = d.get("name", "").strip()
            canonical = d.get("url") or obj_url
            images = d.get("image") or []
            thumb = images[0] if isinstance(images, list) and images else (images or None)
            sku = d.get("sku", "")
            sku_m = _MMF_SKU_RE.match(sku)
            ext_id = sku_m.group(1) if sku_m else str(oid)

            if not name:
                return None
            return StorefrontProduct(
                title=name,
                source_url=canonical,
                source_site="myminifactory",
                external_id=ext_id,
                thumbnail_url=thumb,
            )
        return None

    async with httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
        tasks = [fetch_object(client, oid) for oid in object_ids]
        results = await asyncio.gather(*tasks)

    products = [p for p in results if p is not None]
    logger.info(f"MMF: scraped {len(products)} products successfully")
    return products


# ---------------------------------------------------------------------------
# Gumroad
# ---------------------------------------------------------------------------

# Gumroad is a client-side React app — no product HTML in the initial page.
# However, GET /creator with Accept: application/json returns a list of
# permalink slugs. We then fetch each product page concurrently to extract
# title + og:image from server-rendered meta tags.
_GUMROAD_MAX_PRODUCTS = 200  # cap to keep response time reasonable

async def _scrape_gumroad(url: str) -> list[StorefrontProduct]:
    """
    Scrape a Gumroad creator store.
    Works for https://creator.gumroad.com or https://gumroad.com/creator.
    """
    # Normalise: we always want the subdomain form for the JSON API
    base_url = url.rstrip("/")

    json_headers = {**_HEADERS, "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=20, headers=json_headers, follow_redirects=True) as client:
        try:
            r = await client.get(base_url)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"Gumroad profile fetch failed: {e}")
            return []

    slugs: list[str] = data.get("links", [])
    if not slugs:
        logger.warning("Gumroad: no permalink slugs found in profile response")
        return []

    # Derive the store base so product URLs stay on the creator's subdomain
    # (some creators have custom domains — use the final URL from the profile)
    slugs = slugs[:_GUMROAD_MAX_PRODUCTS]
    logger.info(f"Gumroad: fetching {len(slugs)} product pages (of {len(data.get('links', []))} total)")

    semaphore = asyncio.Semaphore(20)

    async def fetch_product(client: httpx.AsyncClient, slug: str) -> StorefrontProduct | None:
        product_url = f"{base_url}/l/{slug}"
        async with semaphore:
            try:
                r = await client.get(product_url)
                r.raise_for_status()
            except Exception:
                return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Title: prefer og:title, fall back to <title> (strips "| Gumroad" suffix)
        og_title = soup.find("meta", property="og:title")
        title = (og_title.get("content") if og_title else None) or ""
        if not title:
            t = soup.find("title")
            title = t.get_text(strip=True) if t else ""
        # Strip common Gumroad suffixes
        for suffix in [" | Gumroad", " - Gumroad", " by "]:
            if suffix in title:
                title = title.split(suffix)[0].strip()
        if not title:
            return None

        # Thumbnail from og:image
        og_image = soup.find("meta", property="og:image")
        thumb = og_image.get("content") if og_image else None

        return StorefrontProduct(
            title=title,
            source_url=product_url,
            source_site="gumroad",
            external_id=slug,
            thumbnail_url=thumb,
        )

    async with httpx.AsyncClient(timeout=15, headers=_HEADERS, follow_redirects=True) as client:
        tasks = [fetch_product(client, slug) for slug in slugs]
        results = await asyncio.gather(*tasks)

    products = [p for p in results if p is not None]
    logger.info(f"Gumroad: scraped {len(products)} products successfully")
    return products


# ---------------------------------------------------------------------------
# Cults3D
# ---------------------------------------------------------------------------
_CULTS_CREATION_RE = re.compile(
    r"cults3d\.com/\w+/3d-(?:model|printing-file|modelling)/([\w/-]+)", re.I
)

async def _scrape_cults(url: str) -> list[StorefrontProduct]:
    """
    Scrape a Cults3D user creations page.
    Accepts any Cults3D profile URL — /3d-models, /creations, or bare profile.
    Paginates via ?page=N.
    """
    # Strip any stale /creations suffix; the modern URL pattern is /3d-models
    base = url.rstrip("/")
    if base.endswith("/creations"):
        base = base[: -len("/creations")]

    products: list[StorefrontProduct] = []
    page = 1

    async with httpx.AsyncClient(timeout=20, headers=_HEADERS, follow_redirects=True) as client:
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

                m = _CULTS_CREATION_RE.search(product_url)
                products.append(StorefrontProduct(
                    title=title,
                    source_url=product_url,
                    source_site="cults3d",
                    external_id=m.group(1) if m else None,
                    thumbnail_url=thumb,
                ))

            # Next page: span.paginate.next > a
            next_btn = soup.select_one("span.paginate.next a, a[rel='next']")
            if not next_btn:
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
