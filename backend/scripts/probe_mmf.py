"""
One-off probe: does the MyMiniFactory API accept simple API-key auth?

Goal: find out whether we can use the cheap `?key=` query-string auth (or a
Bearer header) for object/search reads, or whether MMF now forces the full
OAuth 2.0 authorization-code flow. The answer decides how the real integration
in app/services/scrapers/mmf.py is wired.

This script imports nothing from the app and uses only the Python standard
library (urllib) — no pip install, no venv needed. Run it with bare Python.

Usage:
    python scripts/probe_mmf.py --key YOUR_API_KEY
    python scripts/probe_mmf.py --key YOUR_API_KEY --object 12345

If --object is omitted a known public object id is used. Exit code is 0 when at
least one auth style returns a usable 200 JSON body, 1 otherwise.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

# Set by main() from --insecure. Local TLS-interception proxies / AV (common on
# Windows) make the default CA bundle reject MMF's chain; this is a throwaway
# diagnostic, so allow skipping verification to learn the auth answer.
_SSL_CTX: ssl.SSLContext | None = None

API_BASE = "https://www.myminifactory.com/api/v2"

# A long-standing, public MMF object used as a harmless read target when the
# caller doesn't supply one. Any public object id works; override with --object.
DEFAULT_OBJECT_ID = "60156"

_HEADERS = {
    "User-Agent": "STL-Inventory-MMF-Probe/1.0",
    "Accept": "application/json",
}


def _attempt(label: str, url: str, params: dict, extra_headers: dict | None = None) -> bool:
    """Make one GET; print a one-line verdict; return True if it's a usable 200 JSON."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    headers = dict(_HEADERS)
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(full_url, headers=headers, method="GET")
    print(f"\n[{label}] GET {full_url}")
    try:
        with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
            status = resp.status
            ctype = resp.headers.get("content-type", "")
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        ctype = e.headers.get("content-type", "") if e.headers else ""
        body = e.read().decode("utf-8", errors="replace")
    except Exception as e:  # network / DNS / timeout
        print(f"    -> request failed: {e}")
        return False

    print(f"    status={status}  content-type={ctype or '(none)'}")
    if status == 200 and "json" in ctype.lower():
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            print("    -> 200 but body is not valid JSON")
            return False
        name = data.get("name") if isinstance(data, dict) else None
        keys = list(data)[:8] if isinstance(data, dict) else type(data).__name__
        print(f"    -> OK JSON. name={name!r}  top-level keys={keys}")
        return True

    snippet = body.strip().replace("\n", " ")[:200]
    print(f"    -> NOT usable. body: {snippet!r}")
    return False


def probe(key: str, object_id: str) -> bool:
    obj_url = f"{API_BASE}/objects/{object_id}"
    search_url = f"{API_BASE}/search"
    any_ok = False

    # 1) Object detail via ?key= query auth (the cheap path we hope works).
    any_ok |= _attempt("object via ?key=", obj_url, {"key": key})

    # 2) Object detail via Bearer header (OAuth access tokens use this).
    any_ok |= _attempt(
        "object via Bearer header", obj_url, {}, {"Authorization": f"Bearer {key}"}
    )

    # 3) Search via ?key= — confirms the same auth works for the search path
    #    we'd use to replace the HTML scraper.
    any_ok |= _attempt("search via ?key=", search_url, {"key": key, "q": "dragon", "per_page": 3})

    return any_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe MyMiniFactory API auth styles.")
    parser.add_argument("--key", required=True, help="MMF API key / access token to test")
    parser.add_argument(
        "--object",
        default=DEFAULT_OBJECT_ID,
        help=f"Object id to read (default: {DEFAULT_OBJECT_ID})",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Skip TLS verification (use if a local proxy/AV breaks the cert chain)",
    )
    args = parser.parse_args()

    if args.insecure:
        global _SSL_CTX
        _SSL_CTX = ssl._create_unverified_context()
        print("  (TLS verification disabled via --insecure)")

    print("Probing MyMiniFactory API ...")
    print(f"  base={API_BASE}")
    print(f"  object_id={args.object}")

    any_ok = probe(args.key, args.object)

    print("\n" + "=" * 60)
    if any_ok:
        print("RESULT: at least one auth style works. Simple-key path is viable.")
        print("        Use whichever attempt above returned 'OK JSON'.")
        return 0
    print("RESULT: no simple-key auth worked. Likely OAuth-only — full")
    print("        authorization-code flow needed. Tell Claude this outcome.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
