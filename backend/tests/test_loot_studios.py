"""
Tests for the Loot Studios scraper.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.scrapers.loot_studios import (
    extract_id, _extract_bnd_id, _parse_bundle, _parse_miniatures, SITE
)
from app.services.scrapers.base import detect_site


# ---------------------------------------------------------------------------
# detect_site integration
# ---------------------------------------------------------------------------

class TestDetectSite:
    @pytest.mark.parametrize("url", [
        "https://app.lootstudios.com/bundle/elemental-revenge/",
        "https://app.lootstudios.com/bundle/chaos-warriors",
        "https://lootstudios.com/bundle/some-set/",
    ])
    def test_loot_studios_urls_detected(self, url):
        assert detect_site(url) == "loot-studios"

    @pytest.mark.parametrize("url", [
        "https://lootstudios.com.evil.com/bundle/foo",
        "https://evil.com/?x=lootstudios.com",
    ])
    def test_lookalikes_rejected(self, url):
        assert detect_site(url) is None

    def test_store_listing_still_detected(self):
        # Store listing URL is still on lootstudios.com, so detect_site returns loot-studios
        # but extract_id returns None (no /bundle/{slug} pattern)
        assert detect_site("https://app.lootstudios.com/bundle-store/") == "loot-studios"
        assert extract_id("https://app.lootstudios.com/bundle-store/") is None


# ---------------------------------------------------------------------------
# extract_id
# ---------------------------------------------------------------------------

class TestExtractId:
    @pytest.mark.parametrize("url,expected", [
        ("https://app.lootstudios.com/bundle/elemental-revenge/", "elemental-revenge"),
        ("https://app.lootstudios.com/bundle/chaos-warriors-2024", "chaos-warriors-2024"),
        ("https://lootstudios.com/bundle/sky-pirates/", "sky-pirates"),
    ])
    def test_extracts_slug(self, url, expected):
        assert extract_id(url) == expected

    @pytest.mark.parametrize("url", [
        "https://app.lootstudios.com/bundle-store/",
        "https://app.lootstudios.com/",
        "https://example.com/other/page",
    ])
    def test_returns_none_for_non_bundle_urls(self, url):
        assert extract_id(url) is None


# ---------------------------------------------------------------------------
# _extract_bnd_id
# ---------------------------------------------------------------------------

class TestExtractBndId:
    def test_extracts_from_inline_script(self):
        html = '''<script>AsyncObjectExplorer('#Async_ObjectExplorer',{"user":0,"bndId":878194,"mntId":0,"objType":"bundle"});</script>'''
        assert _extract_bnd_id(html) == "878194"

    def test_returns_none_when_absent(self):
        assert _extract_bnd_id("<html><body>No bundle here</body></html>") is None


# ---------------------------------------------------------------------------
# _parse_bundle
# ---------------------------------------------------------------------------

_BUNDLE_HTML = """
<html>
<body>
  <h1>Elemental Revenge</h1>
  <img src="https://app.lootstudios.com/wp-content/uploads/2024/01/cover.jpg" />
  <div class="tags">
    <a class="tag">Fantasy</a>
    <a class="tag">Dragons</a>
  </div>
</body>
</html>
"""

_BUNDLE_NO_H1_HTML = "<html><body><p>No title here</p></body></html>"


class TestParseBundle:
    def test_extracts_title(self):
        result = _parse_bundle(_BUNDLE_HTML, "https://app.lootstudios.com/bundle/elemental-revenge/")
        assert result is not None
        assert result.title == "Elemental Revenge"

    def test_extracts_thumbnail_from_wp_content(self):
        result = _parse_bundle(_BUNDLE_HTML, "https://app.lootstudios.com/bundle/elemental-revenge/")
        assert result.thumbnail_url == "https://app.lootstudios.com/wp-content/uploads/2024/01/cover.jpg"

    def test_extracts_tags(self):
        result = _parse_bundle(_BUNDLE_HTML, "https://app.lootstudios.com/bundle/elemental-revenge/")
        assert "Fantasy" in result.tags
        assert "Dragons" in result.tags

    def test_creator_is_always_loot_studios(self):
        result = _parse_bundle(_BUNDLE_HTML, "https://app.lootstudios.com/bundle/elemental-revenge/")
        assert result.creator_name == "Loot Studios"

    def test_site_key(self):
        result = _parse_bundle(_BUNDLE_HTML, "https://app.lootstudios.com/bundle/elemental-revenge/")
        assert result.source_site == SITE

    def test_external_id_from_slug(self):
        result = _parse_bundle(_BUNDLE_HTML, "https://app.lootstudios.com/bundle/elemental-revenge/")
        assert result.external_id == "elemental-revenge"

    def test_returns_none_when_no_title(self):
        result = _parse_bundle(_BUNDLE_NO_H1_HTML, "https://app.lootstudios.com/bundle/empty/")
        assert result is None


# ---------------------------------------------------------------------------
# _parse_miniatures
# ---------------------------------------------------------------------------

_MINI_LISTING_HTML = """
<section id="allMinis">
  <img alt="Katra Umeldahn"
       src="https://assets.loot-studios.com/app/ElementalRevenge/FN2605AC01.png?v=123" />
  <img alt="Almira, Sky Voice"
       src="https://assets.loot-studios.com/app/ElementalRevenge/FN2605AC03.png" />
  <img alt=""
       src="https://app.lootstudios.com/wp-content/uploads/2026/04/HEROES.png" />
  <img alt="Curupira"
       src="https://assets.loot-studios.com/app/ElementalRevenge/FN2605AC04.png" />
</section>
"""


class TestParseMiniatures:
    def test_extracts_miniature_names(self):
        minis = _parse_miniatures(_MINI_LISTING_HTML, "ElementalRevenge")
        names = [m.name for m in minis]
        assert "Katra Umeldahn" in names
        assert "Almira, Sky Voice" in names
        assert "Curupira" in names

    def test_skips_tab_nav_images(self):
        minis = _parse_miniatures(_MINI_LISTING_HTML, "ElementalRevenge")
        # HEROES.png is a tab navigation image — empty alt, wp-content URL
        assert all("HEROES" not in m.thumbnail_url for m in minis)

    def test_skips_empty_alt(self):
        minis = _parse_miniatures(_MINI_LISTING_HTML, "ElementalRevenge")
        assert all(m.name for m in minis)

    def test_strips_tracking_params_from_cdn_url(self):
        minis = _parse_miniatures(_MINI_LISTING_HTML, "ElementalRevenge")
        katra = next(m for m in minis if m.name == "Katra Umeldahn")
        assert "?v=123" not in katra.thumbnail_url
        assert katra.thumbnail_url.endswith(".png")

    def test_count(self):
        minis = _parse_miniatures(_MINI_LISTING_HTML, "ElementalRevenge")
        assert len(minis) == 3

    def test_bundle_slug_attached(self):
        minis = _parse_miniatures(_MINI_LISTING_HTML, "ElementalRevenge")
        assert all(m.bundle_slug == "ElementalRevenge" for m in minis)


# ---------------------------------------------------------------------------
# fetch (mocked HTTP)
# ---------------------------------------------------------------------------

class TestFetch:
    def test_returns_none_on_http_error(self):
        from app.services.scrapers.loot_studios import fetch
        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get.side_effect = Exception("connection refused")
            mock_cls.return_value = mock_client
            result = asyncio.run(fetch("https://app.lootstudios.com/bundle/test/"))
        assert result is None

    def test_returns_scraped_model_on_success(self):
        from app.services.scrapers.loot_studios import fetch
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = _BUNDLE_HTML
        mock_resp.url = "https://app.lootstudios.com/bundle/elemental-revenge/"

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_cls.return_value = mock_client
            result = asyncio.run(fetch("https://app.lootstudios.com/bundle/elemental-revenge/"))

        assert result is not None
        assert result.title == "Elemental Revenge"
        assert result.creator_name == "Loot Studios"


# ---------------------------------------------------------------------------
# fetch_bundle_products (mocked HTTP)
# ---------------------------------------------------------------------------

_PAGE_WITH_BND_ID = '''
<html><body>
<script>AsyncObjectExplorer('#x',{"user":0,"bndId":878194,"mntId":0,"objType":"bundle"});</script>
</body></html>
'''


class TestFetchBundleProducts:
    def test_returns_empty_when_no_bnd_id(self):
        from app.services.scrapers.loot_studios import fetch_bundle_products
        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = "<html><body>no id here</body></html>"
        page_resp.url = "https://app.lootstudios.com/bundle/test/"

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=page_resp)
            mock_cls.return_value = mock_client
            result = asyncio.run(fetch_bundle_products("https://app.lootstudios.com/bundle/test/"))

        assert result == []

    def test_returns_miniatures_on_success(self):
        from app.services.scrapers.loot_studios import fetch_bundle_products
        page_resp = MagicMock()
        page_resp.raise_for_status = MagicMock()
        page_resp.text = _PAGE_WITH_BND_ID
        page_resp.url = "https://app.lootstudios.com/bundle/elemental-revenge/"

        ajax_resp = MagicMock()
        ajax_resp.raise_for_status = MagicMock()
        ajax_resp.text = _MINI_LISTING_HTML

        with patch("httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=page_resp)
            mock_client.post = AsyncMock(return_value=ajax_resp)
            mock_cls.return_value = mock_client
            result = asyncio.run(fetch_bundle_products("https://app.lootstudios.com/bundle/elemental-revenge/"))

        assert len(result) == 3
        assert result[0].name == "Katra Umeldahn"
