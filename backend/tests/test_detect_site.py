"""
Tests for scraper site detection — including the open-fetch/SSRF guard.
"""
import pytest
from app.services.scrapers.base import detect_site


@pytest.mark.parametrize("url,expected", [
    ("https://cults3d.com/en/3d-model/x", "cults3d"),
    ("https://www.myminifactory.com/object/123", "myminifactory"),
    ("https://creator.gumroad.com/l/abc", "gumroad"),
    ("https://gumroad.com/creator", "gumroad"),
    ("cults3d.com/en/users/foo", "cults3d"),            # missing scheme still works
    ("https://app.lootstudios.com/bundle/elemental-revenge/", "loot-studios"),
    ("https://lootstudios.com/bundle/sky-pirates/", "loot-studios"),
])
def test_valid_sites(url, expected):
    assert detect_site(url) == expected


@pytest.mark.parametrize("url", [
    "https://cults3d.com.evil.com/path",          # look-alike subdomain
    "https://evil.com/?redirect=cults3d.com",      # domain only in query
    "https://evilgumroad.com/x",                   # domain as a substring of host
    "https://example.com/cults3d.com",             # domain only in path
    "http://169.254.169.254/latest/meta-data",     # cloud metadata IP
    "https://lootstudios.com.evil.com/bundle/x",   # loot studios look-alike
    "not a url",
    "",
])
def test_rejects_lookalikes_and_unknown(url):
    assert detect_site(url) is None
