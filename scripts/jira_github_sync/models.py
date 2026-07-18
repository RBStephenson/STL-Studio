"""Normalized issue shape + pure reconciliation logic (no network calls).

Kept separate from the API clients so the reconcile decision can be unit
tested without mocking HTTP.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

MARKER_RE = re.compile(
    r"<!--\s*jira-sync\s+key=(?P<key>\S+)\s+jsrc=(?P<jsrc>[0-9a-f]{8})\s+ghsrc=(?P<ghsrc>[0-9a-f]{8})\s*-->"
)


def marker(key: str, jsrc: str, ghsrc: str) -> str:
    return f"<!-- jira-sync key={key} jsrc={jsrc} ghsrc={ghsrc} -->"


def parse_marker(body: str) -> dict | None:
    match = MARKER_RE.search(body or "")
    if not match:
        return None
    return match.groupdict()


def strip_marker(body: str) -> str:
    return MARKER_RE.sub("", body or "").rstrip()


def content_hash(title: str, description: str, status: str) -> str:
    payload = f"{title}\x00{description}\x00{status}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:8]


@dataclass(frozen=True)
class NormalizedIssue:
    """One item (Jira issue/epic or GitHub issue/milestone), side-agnostic."""

    key: str  # Jira key (e.g. STUDIO-123) for both sides once linked
    title: str
    description: str
    status: str  # free-text status label, e.g. "In Progress" / "Done"
    updated: datetime
    is_epic: bool = False
    gh_number: int | None = None  # GitHub issue/milestone number, once linked


class Action(str, Enum):
    NONE = "none"
    CREATE_GITHUB = "create_github"
    PUSH_JIRA_TO_GITHUB = "push_jira_to_github"
    PUSH_GITHUB_TO_JIRA = "push_github_to_jira"


@dataclass(frozen=True)
class Decision:
    action: Action
    new_jsrc: str | None = None
    new_ghsrc: str | None = None


def reconcile(
    jira: NormalizedIssue,
    github: NormalizedIssue | None,
    stored_jsrc: str | None,
    stored_ghsrc: str | None,
) -> Decision:
    """Decide what to sync for a single Jira<->GitHub pair.

    No paired GitHub item yet -> create it. Otherwise compare each side's
    current content hash against what was last synced: whichever side's hash
    moved away from the stored value has "changed since last sync" and wins.
    If both moved (edited on both sides between runs), Jira's `updated`
    timestamp vs GitHub's decides the winner (last-write-wins), per STUDIO-264.
    """
    jira_hash = content_hash(jira.title, jira.description, jira.status)

    if github is None:
        return Decision(Action.CREATE_GITHUB, new_jsrc=jira_hash, new_ghsrc=jira_hash)

    gh_hash = content_hash(github.title, github.description, github.status)
    jira_changed = stored_jsrc is None or jira_hash != stored_jsrc
    gh_changed = stored_ghsrc is None or gh_hash != stored_ghsrc

    if not jira_changed and not gh_changed:
        return Decision(Action.NONE, new_jsrc=stored_jsrc, new_ghsrc=stored_ghsrc)

    if jira_changed and gh_changed:
        jira_wins = jira.updated >= github.updated
    else:
        jira_wins = jira_changed

    if jira_wins:
        return Decision(Action.PUSH_JIRA_TO_GITHUB, new_jsrc=jira_hash, new_ghsrc=jira_hash)
    return Decision(Action.PUSH_GITHUB_TO_JIRA, new_jsrc=gh_hash, new_ghsrc=gh_hash)


# GitHub label (lower-cased) -> Jira issue type, for reverse (GitHub->Jira)
# creation. Anything unmapped becomes a Task.
_LABEL_TO_TYPE = {
    "bug": "Bug",
    "enhancement": "Story",
    "feature": "Story",
    "story": "Story",
}
DEFAULT_ISSUE_TYPE = "Task"


def github_import_description(body: str, url: str, reporter: str) -> str:
    """Prepend a provenance line pointing back at the source GitHub issue.

    Kept as a pure helper so the exact text (which feeds the marker hash) is
    unit-testable and stays in lockstep between create-time and any later
    reconcile.
    """
    who = f" (reported by @{reporter})" if reporter else ""
    header = f"Imported from GitHub: {url}{who}"
    return f"{header}\n\n{body}" if body else header


def issue_type_for_labels(labels: list[str]) -> str:
    """Pick a Jira issue type from GitHub label names (Task if none match).

    "bug" wins over story-ish labels when both are present, since a bug is the
    more specific/actionable classification.
    """
    lowered = {label.lower() for label in labels}
    if "bug" in lowered:
        return "Bug"
    for label in lowered:
        if label in _LABEL_TO_TYPE:
            return _LABEL_TO_TYPE[label]
    return DEFAULT_ISSUE_TYPE
