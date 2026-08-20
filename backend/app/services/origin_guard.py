"""Origin/Host trust check for browser-originated requests (#213, STUDIO-263).

The API binds to 127.0.0.1 with no auth, so this trust check is the only
defense against another page in the user's browser firing requests at the
local backend. Extracted from `app.main` into its own module so both the
global write-request middleware and router-scoped read guards (STUDIO-263)
can share one chokepoint without a circular import — `app.main` imports the
routers, so a router can't import back from `app.main`.

"Trusted" is localhost/127.0.0.1/::1, plus any hostnames in TRUSTED_HOSTS
(for reverse-proxy deploys on a custom domain).
"""
from urllib.parse import urlsplit

from app.config import settings as app_settings

_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def is_trusted_hostname(hostname: str | None) -> bool:
    if hostname is None:
        return False
    h = hostname.lower()
    return h in _LOCAL_HOSTNAMES or h in app_settings.trusted_host_list


def origin_is_trusted(origin: str) -> bool:
    return is_trusted_hostname(urlsplit(origin).hostname)


def host_is_trusted(host: str) -> bool:
    # Host is "name[:port]" or "[v6addr][:port]" — parse as a netloc.
    try:
        return is_trusted_hostname(urlsplit(f"//{host}").hostname)
    except ValueError:
        return False
