"""Minimal Jira Cloud REST v3 client (stdlib only, no extra CI dependency).

Only the operations the sync needs: list open STUDIO epics/issues, and push a
title/description update back onto an existing issue. This script never
creates Jira issues -- Jira is the system of record for issue creation (see
project CLAUDE.md); GitHub only ever gets issues Jira already has.

Uses /rest/api/3/search/jql (cursor-paginated via nextPageToken) since
/rest/api/2/search was retired (HTTP 410) -- see
https://developer.atlassian.com/changelog/#CHANGE-2046. v3 fields, including
`description`, are Atlassian Document Format (ADF); _adf_to_text /
_text_to_adf convert between that and the plain text the rest of this sync
works with.
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .models import NormalizedIssue

_log = logging.getLogger("jira_github_sync")

_JQL_EPICS = 'project = {project} AND issuetype = Epic AND statusCategory != Done ORDER BY key'
_JQL_ISSUES = (
    'project = {project} AND issuetype not in (Epic, Sub-task) '
    'AND statusCategory != Done ORDER BY key'
)


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str, project_key: str):
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        token = base64.b64encode(f"{email}:{api_token}".encode("utf-8")).decode("ascii")
        self._auth_header = f"Basic {token}"

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth_header)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Jira {method} {path} failed ({exc.code}): {detail}") from exc

    def log_identity(self) -> None:
        """Log which account the API token actually authenticates as.

        Basic auth resolves identity from the token, not the email field, so a
        token minted under the wrong account silently returns empty result
        sets (no 401) for projects that account can't see. This makes the real
        acting account visible in the run log.
        """
        try:
            me = self._request("GET", "/rest/api/3/myself")
        except RuntimeError as exc:
            _log.warning("Could not resolve token identity via /myself: %s", exc)
            return
        _log.info(
            "Jira token authenticates as: %s <%s> (accountId=%s, accountType=%s)",
            me.get("displayName", "?"),
            me.get("emailAddress", "?"),
            me.get("accountId", "?"),
            me.get("accountType", "?"),
        )

    def _search(self, jql: str, is_epic: bool) -> list[NormalizedIssue]:
        issues: list[NormalizedIssue] = []
        next_token: str | None = None
        while True:
            body = {
                "jql": jql,
                "maxResults": 100,
                "fields": ["summary", "description", "status", "updated"],
            }
            if next_token:
                body["nextPageToken"] = next_token
            result = self._request("POST", "/rest/api/3/search/jql", body)
            for raw in result.get("issues", []):
                fields = raw["fields"]
                issues.append(
                    NormalizedIssue(
                        key=raw["key"],
                        title=fields.get("summary") or "",
                        description=_adf_to_text(fields.get("description")),
                        status=fields.get("status", {}).get("name", ""),
                        updated=_parse_jira_timestamp(fields["updated"]),
                        is_epic=is_epic,
                    )
                )
            next_token = result.get("nextPageToken")
            if not next_token or not result.get("issues"):
                break
        return issues

    def list_open_epics(self) -> list[NormalizedIssue]:
        return self._search(_JQL_EPICS.format(project=self.project_key), is_epic=True)

    def list_open_issues(self) -> list[NormalizedIssue]:
        return self._search(_JQL_ISSUES.format(project=self.project_key), is_epic=False)

    def update_issue(self, key: str, title: str, description: str) -> None:
        self._request(
            "PUT",
            f"/rest/api/3/issue/{key}",
            {"fields": {"summary": title, "description": _text_to_adf(description)}},
        )


def _parse_jira_timestamp(value: str) -> datetime:
    # Jira returns e.g. "2026-07-18T14:03:00.000-0400"; normalize the bare
    # numeric UTC offset (no colon) that datetime.fromisoformat rejects.
    if len(value) >= 5 and value[-5] in "+-" and value[-3] != ":":
        value = f"{value[:-2]}:{value[-2:]}"
    dt = datetime.fromisoformat(value)
    return dt.astimezone(timezone.utc)


def _adf_to_text(doc: dict | None) -> str:
    """Flatten an Atlassian Document Format node tree to plain text.

    Good enough for diffing/mirroring purposes -- this sync doesn't need to
    round-trip rich formatting, just detect and carry forward edits.
    """
    if not doc:
        return ""

    lines: list[str] = []

    def walk(node: dict, buf: list[str]) -> None:
        if node.get("type") == "text":
            buf.append(node.get("text", ""))
            return
        for child in node.get("content", []) or []:
            walk(child, buf)

    for block in doc.get("content", []) or []:
        buf: list[str] = []
        walk(block, buf)
        lines.append("".join(buf))
    return "\n".join(lines).strip()


def _text_to_adf(text: str) -> dict:
    """Wrap plain text as one ADF paragraph per non-empty line."""
    paragraphs = [line for line in text.splitlines()] or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": line}] if line else [],
            }
            for line in paragraphs
        ],
    }
