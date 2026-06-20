"""XSS-vector coverage for guide-content sanitization (#440)."""

import pytest

from app.painting.services.sanitize import (
    sanitize_css, sanitize_html, sanitize_url,
)
from app.painting.services.importing import import_guide_html


class TestSanitizeHtml:
    @pytest.mark.parametrize("payload", [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<a href=\"javascript:alert(1)\">click</a>",
        "<div onclick=\"steal()\">x</div>",
        "<iframe src=\"http://evil\"></iframe>",
        "<svg/onload=alert(1)>",
        "<p style=\"background:url(javascript:alert(1))\">x</p>",
    ])
    def test_strips_active_content(self, payload):
        out = sanitize_html(payload)
        lowered = out.lower()
        assert "<script" not in lowered
        assert "onerror" not in lowered
        assert "onclick" not in lowered
        assert "onload" not in lowered
        assert "javascript:" not in lowered
        assert "<iframe" not in lowered
        assert "style=" not in lowered

    def test_preserves_safe_formatting(self):
        out = sanitize_html("<strong>Bold</strong> and <em>italic</em>")
        assert "<strong>Bold</strong>" in out
        assert "<em>italic</em>" in out

    def test_preserves_safe_links_and_forces_rel(self):
        out = sanitize_html('<a href="https://example.com">link</a>')
        assert 'href="https://example.com"' in out
        assert "noopener" in out and "noreferrer" in out

    def test_keeps_class_for_raw_block_styling(self):
        out = sanitize_html('<div class="tier-card">x</div>')
        assert 'class="tier-card"' in out

    def test_empty_input(self):
        assert sanitize_html(None) == ""
        assert sanitize_html("") == ""


class TestSanitizeUrl:
    @pytest.mark.parametrize("url", [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "//evil.example.com",
        "java\tscript:alert(1)",
    ])
    def test_rejects_unsafe(self, url):
        assert sanitize_url(url) is None

    @pytest.mark.parametrize("url", [
        "https://example.com/p",
        "http://example.com",
        "mailto:a@b.com",
        "/relative/path",
        "#anchor",
    ])
    def test_allows_safe(self, url):
        assert sanitize_url(url) == url

    def test_empty(self):
        assert sanitize_url(None) is None
        assert sanitize_url("") is None


class TestSanitizeCss:
    @pytest.mark.parametrize("css", [
        "</style><script>alert(1)</script>",
        "@import url('http://evil/x.css');",
        "body{width:expression(alert(1))}",
        ".x{background:url(javascript:alert(1))}",
        "/* --> */ <script>",
    ])
    def test_neutralizes_vectors(self, css):
        out = sanitize_css(css).lower()
        assert "<" not in out and ">" not in out
        assert "@import" not in out
        assert "expression(" not in out
        assert "javascript:" not in out
        assert "script" not in out or "<script" not in out

    def test_preserves_plain_css(self):
        css = ".guide-reader{color:#fff;background:#101010}"
        assert sanitize_css(css) == css

    def test_empty(self):
        assert sanitize_css(None) == ""


class TestImporterSanitizes:
    """End-to-end: malicious markup is sanitized in the produced draft."""

    def _resolver(self, *_a, **_k):
        return None

    def test_step_body_script_stripped(self):
        html = """
        <div class="hero"><h1><span>T</span></h1></div>
        <div class="tab-content" id="t1">
          <div class="step"><h3>Step</h3>
            <p>Base <script>alert(1)</script><img src=x onerror=alert(1)> coat</p>
          </div>
        </div>
        """
        draft, _ = import_guide_html(html, slug="g", resolve_paint=self._resolver)
        body = draft["tabs"][0]["phases"][0]["steps"][0]["body"].lower()
        assert "<script" not in body
        assert "onerror" not in body
        assert "base" in body and "coat" in body

    def test_head_style_breakout_neutralized(self):
        html = """
        <style>.guide-reader{color:#fff}</style>
        <div class="hero"><h1><span>T</span></h1></div>
        <div class="tab-content" id="t1"></div>
        """
        draft, _ = import_guide_html(html, slug="g", resolve_paint=self._resolver)
        assert draft.get("head_style") == ".guide-reader{color:#fff}"

    def test_credit_javascript_href_dropped(self):
        html = """
        <div class="hero"><h1><span>T</span></h1>
          <div class="creator-credit">Figure by <strong>A</strong>
            <a href="javascript:alert(1)">link</a></div>
        </div>
        <div class="tab-content" id="t1"></div>
        """
        draft, _ = import_guide_html(html, slug="g", resolve_paint=self._resolver)
        assert "url" not in draft.get("creator_credit", {})
