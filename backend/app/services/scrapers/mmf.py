"""
MyMiniFactory adapter.

Two paths, API-first:

  * When an ``api_key`` is supplied we call the MMF REST API
    (``/api/v2/objects/{id}`` and ``/api/v2/search``) with simple ``?key=``
    query auth. This returns structured JSON — reliable fields, no selector
    guessing. Confirmed working for *public* reads; private data (collections,
    likes, ``is_saved``) would need the OAuth ``basic`` scope instead.
  * Without a key — or if an API call fails — we fall back to scraping the
    product page (Open Graph tags + JSON-LD + HTML), which needs no auth.

Callers resolve the key (DB-stored secret, falling back to env) and pass it in;
register an app at MMF Settings -> Developer to obtain one.
"""
import re
import json
import logging
import httpx  # noqa: F401 — patched as `mmf.httpx.AsyncClient` by the test suite
from app.services.url_guard import guarded_async_client
from bs4 import BeautifulSoup
from typing import Optional

from app.services.scrapers.base import ScrapedModel, SearchResult, MAX_REDIRECTS

logger = logging.getLogger(__name__)

SITE = "myminifactory"
BASE = "https://www.myminifactory.com"
API_BASE = "https://www.myminifactory.com/api/v2"

# MMF serves each gallery image at several sizes; prefer the largest usable URL.
_IMAGE_SIZE_PREFERENCE = ("large", "standard", "original", "thumbnail", "tiny")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# https://www.myminifactory.com/object/3d-print-some-model-name-12345
_URL_RE = re.compile(r"myminifactory\.com/object/([\w-]+)", re.I)
_ID_FROM_SLUG_RE = re.compile(r"-(\d+)$")


def extract_id(url: str) -> Optional[str]:
    m = _URL_RE.search(url)
    if not m:
        return None
    slug = m.group(1)
    # ID is the trailing number in the slug
    id_m = _ID_FROM_SLUG_RE.search(slug)
    return id_m.group(1) if id_m else slug


async def fetch(url: str, api_key: Optional[str] = None) -> Optional[ScrapedModel]:
    # API-first: structured JSON beats selector-scraping when a key is set and
    # we can resolve the numeric object id from the URL.
    object_id = extract_id(url)
    if api_key and object_id and object_id.isdigit():
        obj = await _api_get(f"/objects/{object_id}", api_key=api_key)
        if obj:
            model = _parse_api(obj, fallback_url=url)
            if model:
                return model
        logger.info(f"MMF API fetch miss for object {object_id}; falling back to scrape")

    async with guarded_async_client(
        timeout=20,
        headers=_HEADERS,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    ) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text
            final_url = str(r.url)
        except Exception as e:
            logger.error(f"MMF fetch({url}) failed: {e}")
            return None

    return _parse(html, final_url)


async def search(query: str, limit: int = 12, api_key: Optional[str] = None) -> list[SearchResult]:
    # API-first: the search endpoint returns full object records, which carry
    # the fields SearchResult needs without scraping fragile result cards.
    if api_key:
        data = await _api_get("/search", params={"q": query, "per_page": limit}, api_key=api_key)
        if data is not None:
            results = []
            for item in (data.get("items") or [])[:limit]:
                model = _parse_api(item)
                if not model:
                    continue
                results.append(SearchResult(
                    title=model.title or model.source_url,
                    source_url=model.source_url,
                    source_site=SITE,
                    external_id=model.external_id,
                    creator_name=model.creator_name,
                    thumbnail_url=model.thumbnail_url,
                    like_count=model.like_count,
                ))
            return results
        logger.info(f"MMF API search miss for {query!r}; falling back to scrape")

    async with guarded_async_client(
        timeout=20,
        headers=_HEADERS,
        follow_redirects=True,
        max_redirects=MAX_REDIRECTS,
    ) as client:
        try:
            r = await client.get(
                f"{BASE}/search",
                params={"q": query, "type": "objects"},
            )
            r.raise_for_status()
            html = r.text
        except Exception as e:
            logger.error(f"MMF search({query!r}) failed: {e}")
            return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # MMF search results — card selectors may need tuning as their HTML evolves
    for card in soup.select(".object-card, [class*='object-card'], article[data-id]")[:limit]:
        link = card.select_one("a[href*='/object/']")
        if not link:
            continue
        href = link.get("href", "")
        product_url = href if href.startswith("http") else f"{BASE}{href}"
        title_el = card.select_one("h3, h2, .object-name, [class*='name']")
        img_el = card.select_one("img[src], img[data-src]")
        thumb = (img_el.get("src") or img_el.get("data-src")) if img_el else None
        creator_el = card.select_one("[class*='designer'], [class*='creator'], [class*='author']")
        like_el = card.select_one("[class*='like'], [class*='heart']")
        like_count = None
        if like_el:
            m = re.search(r"\d+", like_el.get_text())
            if m:
                like_count = int(m.group())
        results.append(SearchResult(
            title=title_el.get_text(strip=True) if title_el else product_url,
            source_url=product_url,
            source_site=SITE,
            external_id=extract_id(product_url),
            creator_name=creator_el.get_text(strip=True) if creator_el else None,
            thumbnail_url=thumb,
            like_count=like_count,
        ))
    return results


async def _api_get(path: str, api_key: str, params: Optional[dict] = None) -> Optional[dict]:
    """GET an MMF API path with ?key= auth. Returns parsed JSON or None on error."""
    query = {"key": api_key, **(params or {})}
    async with guarded_async_client(timeout=20, headers=_HEADERS, follow_redirects=True, max_redirects=MAX_REDIRECTS) as client:
        try:
            r = await client.get(f"{API_BASE}{path}", params=query)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"MMF API GET {path} failed: {e}")
            return None


def _image_urls(obj: dict) -> list[str]:
    """Best-resolution URL per gallery image, primary image first."""
    images = obj.get("images") or []
    # Primary first so the chosen thumbnail matches MMF's own cover choice.
    images = sorted(images, key=lambda im: not im.get("is_primary"))
    urls: list[str] = []
    for im in images:
        for size in _IMAGE_SIZE_PREFERENCE:
            url = (im.get(size) or {}).get("url")
            if url:
                if url not in urls:
                    urls.append(url)
                break
    return urls


def _parse_api(obj: dict, fallback_url: Optional[str] = None) -> Optional[ScrapedModel]:
    """Map an MMF API object record to ScrapedModel.

    Shared by object-detail fetch and search (search items carry the same
    object schema).
    """
    name = (obj.get("name") or "").strip()
    if not name:
        return None

    designer = obj.get("designer") or {}
    categories = (obj.get("categories") or {}).get("items") or []
    images = _image_urls(obj)

    obj_id = obj.get("id")
    return ScrapedModel(
        title=name,
        description=(obj.get("description") or "").strip() or None,
        source_url=obj.get("url") or fallback_url,
        source_site=SITE,
        external_id=str(obj_id) if obj_id is not None else None,
        creator_name=(designer.get("name") or "").strip() or None,
        creator_url=designer.get("profile_url") or None,
        thumbnail_url=images[0] if images else None,
        image_urls=images,
        tags=[t for t in (obj.get("tags") or []) if t],
        category=(categories[0].get("name") if categories else None),
        license=(obj.get("license") or "").strip() or None,
        like_count=obj.get("likes"),
        # MMF exposes views, not downloads — don't conflate the two.
        download_count=None,
        make_count=len(obj.get("prints") or []) or None,
    )


def _parse(html: str, url: str) -> Optional[ScrapedModel]:
    soup = BeautifulSoup(html, "html.parser")

    def og(prop: str) -> Optional[str]:
        tag = soup.find("meta", property=f"og:{prop}")
        return tag["content"].strip() if tag and tag.get("content") else None

    def meta_name(name: str) -> Optional[str]:
        tag = soup.find("meta", attrs={"name": name})
        return tag["content"].strip() if tag and tag.get("content") else None

    title = og("title") or meta_name("title") or _text(soup, ["h1"])
    description = og("description") or meta_name("description")
    thumbnail_url = og("image")

    images: list[str] = []
    tags: list[str] = []
    creator_name: Optional[str] = None
    creator_url: Optional[str] = None
    license_str: Optional[str] = None
    like_count: Optional[int] = None
    download_count: Optional[int] = None
    make_count: Optional[int] = None
    category: Optional[str] = None

    # JSON-LD (MMF includes structured data)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            if isinstance(ld, list):
                ld = ld[0]
            t = ld.get("@type", "")
            if t in ("Product", "CreativeWork", "3DModel", "Thing"):
                title = title or ld.get("name")
                description = description or ld.get("description")
                author = ld.get("author") or ld.get("creator") or {}
                if isinstance(author, dict):
                    creator_name = creator_name or author.get("name")
                    creator_url = creator_url or author.get("url")
                imgs = ld.get("image") or []
                if isinstance(imgs, str):
                    imgs = [imgs]
                for img in imgs:
                    src = img if isinstance(img, str) else img.get("url", "")
                    if src and src not in images:
                        images.append(src)
                license_str = license_str or ld.get("license")
        except Exception:
            pass

    # Creator from page HTML
    if not creator_name:
        creator_name = _text(soup, [
            ".designer-name",
            "[class*='designer'] a",
            "[class*='creator'] a",
            "[itemprop='author'] [itemprop='name']",
        ])

    # Tags
    for tag_el in soup.select("[class*='tag'] a, .tags a, [rel='tag']"):
        t = tag_el.get_text(strip=True)
        if t and t not in tags:
            tags.append(t)

    # Category
    breadcrumb = soup.select(".breadcrumb a, [class*='breadcrumb'] a")
    if len(breadcrumb) > 1:
        category = breadcrumb[-1].get_text(strip=True)

    # Stats
    for stat in soup.select("[class*='stat'], [class*='count'], [class*='like'], [class*='download']"):
        text = stat.get_text(strip=True).lower()
        n_m = re.search(r"[\d,]+", text)
        if not n_m:
            continue
        n = int(n_m.group().replace(",", ""))
        if "like" in text or "heart" in text or "love" in text:
            like_count = n
        elif "download" in text:
            download_count = n
        elif "make" in text or "print" in text:
            make_count = n

    # Gallery images
    for img in soup.select(".gallery img, [class*='gallery'] img, [class*='picture'] img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy")
        if src and src.startswith("http") and src not in images:
            images.append(src)

    if thumbnail_url and thumbnail_url not in images:
        images.insert(0, thumbnail_url)
    images = [i for i in images if i and i.startswith("http")]

    if not title:
        return None

    return ScrapedModel(
        title=title,
        description=description,
        source_url=url,
        source_site=SITE,
        external_id=extract_id(url),
        creator_name=creator_name,
        creator_url=creator_url,
        thumbnail_url=images[0] if images else thumbnail_url,
        image_urls=images,
        tags=tags,
        category=category,
        license=license_str,
        like_count=like_count,
        download_count=download_count,
        make_count=make_count,
    )


def _text(soup: BeautifulSoup, selectors: list[str]) -> Optional[str]:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            return el.get_text(strip=True) or None
    return None
