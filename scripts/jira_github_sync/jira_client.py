"""Minimal Jira Cloud REST v2 client (stdlib only, no extra CI dependency).

Only the operations the sync needs: list open STUDIO epics/issues, and push a
title/description/status-label update back onto an existing issue. This script
never creates Jira issues -- Jira is the system of record for issue creation
(see project CLAUDE.md); GitHub only ever gets issues Jira already has.
"""
from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .models import NormalizedIssue

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

    def _search(self, jql: str, is_epic: bool) -> list[NormalizedIssue]:
        issues: list[NormalizedIssue] = []
        start_at = 0
        while True:
            result = self._request(
                "POST",
                "/rest/api/2/search",
                {
                    "jql": jql,
                    "startAt": start_at,
                    "maxResults": 100,
                    "fields": ["summary", "description", "status", "updated"],
                },
            )
            for raw in result.get("issues", []):
                fields = raw["fields"]
                issues.append(
                    NormalizedIssue(
                        key=raw["key"],
                        title=fields.get("summary") or "",
                        description=fields.get("description") or "",
                        status=fields.get("status", {}).get("name", ""),
                        updated=_parse_jira_timestamp(fields["updated"]),
                        is_epic=is_epic,
                    )
                )
            start_at += len(result.get("issues", []))
            if start_at >= result.get("total", 0) or not result.get("issues"):
                break
        return issues

    def list_open_epics(self) -> list[NormalizedIssue]:
        return self._search(_JQL_EPICS.format(project=self.project_key), is_epic=True)

    def list_open_issues(self) -> list[NormalizedIssue]:
        return self._search(_JQL_ISSUES.format(project=self.project_key), is_epic=False)

    def update_issue(self, key: str, title: str, description: str) -> None:
        self._request(
            "PUT",
            f"/rest/api/2/issue/{key}",
            {"fields": {"summary": title, "description": description}},
        )


def _parse_jira_timestamp(value: str) -> datetime:
    # Jira returns e.g. "2026-07-18T14:03:00.000-0400"; normalize the bare
    # numeric UTC offset (no colon) that datetime.fromisoformat rejects.
    if len(value) >= 5 and value[-5] in "+-" and value[-3] != ":":
        value = f"{value[:-2]}:{value[-2:]}"
    dt = datetime.fromisoformat(value)
    return dt.astimezone(timezone.utc)
