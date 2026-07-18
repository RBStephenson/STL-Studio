"""Minimal GitHub REST v3 client (stdlib only).

Epics become milestones, everything else becomes an issue. Neither type has a
Jira-native way to carry the linkage, so both carry a hidden HTML-comment
marker (see models.marker) in their body/description, plus a plain
"**Jira status:** X" line used as the mirrored status field (issues keep
native GH open/closed state under human control -- see STUDIO-264 notes on
not auto-closing).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from datetime import datetime

from .models import NormalizedIssue, marker, parse_marker, strip_marker

_STATUS_LINE_RE = re.compile(r"\*\*Jira status:\*\*\s*(?P<status>.+)")


class GitHubClient:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self._token = token

    def _request(self, method: str, path: str, body: dict | None = None) -> object:
        url = f"https://api.github.com/repos/{self.repo}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub {method} {path} failed ({exc.code}): {detail}") from exc

    def _paginated(self, path: str, params: str) -> list[dict]:
        items: list[dict] = []
        page = 1
        while True:
            batch = self._request("GET", f"{path}?{params}&per_page=100&page={page}")
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return items

    def _linked(self, raw_items: list[dict], body_field: str, is_epic: bool) -> dict[str, tuple]:
        """key -> (NormalizedIssue, stored_jsrc, stored_ghsrc)."""
        linked: dict[str, tuple] = {}
        for raw in raw_items:
            body = raw.get(body_field) or ""
            info = parse_marker(body)
            if not info:
                continue
            status_match = _STATUS_LINE_RE.search(body)
            status = status_match.group("status").strip() if status_match else ""
            description = strip_marker(body)
            description = _STATUS_LINE_RE.sub("", description).rstrip()
            issue = NormalizedIssue(
                key=info["key"],
                title=raw.get("title") or "",
                description=description,
                status=status,
                updated=datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00")),
                is_epic=is_epic,
                gh_number=raw["number"],
            )
            linked[info["key"]] = (issue, info["jsrc"], info["ghsrc"])
        return linked

    def linked_milestones(self) -> dict[str, tuple]:
        raw = self._paginated("/milestones", "state=all")
        return self._linked(raw, "description", is_epic=True)

    def linked_issues(self) -> dict[str, tuple]:
        raw = self._paginated("/issues", "state=all")
        raw = [r for r in raw if "pull_request" not in r]
        return self._linked(raw, "body", is_epic=False)

    @staticmethod
    def _body(description: str, status: str, key: str, jsrc: str, ghsrc: str) -> str:
        return f"{description}\n\n**Jira status:** {status}\n\n{marker(key, jsrc, ghsrc)}"

    def create_milestone(self, jira: NormalizedIssue, jsrc: str, ghsrc: str) -> None:
        self._request(
            "POST",
            "/milestones",
            {"title": jira.title, "description": self._body(jira.description, jira.status, jira.key, jsrc, ghsrc)},
        )

    def update_milestone(self, number: int, jira: NormalizedIssue, jsrc: str, ghsrc: str) -> None:
        self._request(
            "PATCH",
            f"/milestones/{number}",
            {"title": jira.title, "description": self._body(jira.description, jira.status, jira.key, jsrc, ghsrc)},
        )

    def create_issue(self, jira: NormalizedIssue, jsrc: str, ghsrc: str) -> None:
        self._request(
            "POST",
            "/issues",
            {"title": jira.title, "body": self._body(jira.description, jira.status, jira.key, jsrc, ghsrc)},
        )

    def update_issue(self, number: int, jira: NormalizedIssue, jsrc: str, ghsrc: str) -> None:
        self._request(
            "PATCH",
            f"/issues/{number}",
            {"title": jira.title, "body": self._body(jira.description, jira.status, jira.key, jsrc, ghsrc)},
        )
