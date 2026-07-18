"""Unit tests for the Jira<->GitHub reconcile decision and sync loop.

No network: models.reconcile is pure, and sync_group is exercised with fake
create/update/push callables recording what they were called with.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jira_github_sync.models import (
    Action,
    NormalizedIssue,
    content_hash,
    github_import_description,
    issue_type_for_labels,
    reconcile,
)
from jira_github_sync.sync import (
    _flag_enabled,
    create_jira_from_github,
    sync_group,
    update_linked_github,
)

NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(days=1)
LATER = NOW + timedelta(days=1)


def _issue(title="Title", description="Desc", status="To Do", updated=NOW, **kw):
    return NormalizedIssue(
        key="STUDIO-1", title=title, description=description, status=status, updated=updated, **kw
    )


def test_no_github_counterpart_creates():
    jira = _issue()
    decision = reconcile(jira, None, None, None)
    assert decision.action == Action.CREATE_GITHUB
    assert decision.new_jsrc == decision.new_ghsrc == content_hash("Title", "Desc", "To Do")


def test_unchanged_both_sides_is_noop():
    jira = _issue()
    github = _issue(gh_number=5)
    h = content_hash("Title", "Desc", "To Do")
    decision = reconcile(jira, github, h, h)
    assert decision.action == Action.NONE
    assert decision.new_jsrc == h and decision.new_ghsrc == h


def test_jira_only_change_pushes_to_github():
    stored_hash = content_hash("Old title", "Desc", "To Do")
    jira = _issue(title="New title")
    github = _issue(title="Old title", gh_number=5)
    decision = reconcile(jira, github, stored_hash, stored_hash)
    assert decision.action == Action.PUSH_JIRA_TO_GITHUB


def test_github_only_change_pushes_to_jira():
    stored_hash = content_hash("Title", "Desc", "To Do")
    jira = _issue()
    github = _issue(title="Edited on GitHub", gh_number=5)
    decision = reconcile(jira, github, stored_hash, stored_hash)
    assert decision.action == Action.PUSH_GITHUB_TO_JIRA


def test_conflict_uses_last_write_wins_by_timestamp():
    stored_hash = content_hash("Title", "Desc", "To Do")
    jira = _issue(title="Jira edit", updated=LATER)
    github = _issue(title="GitHub edit", updated=EARLIER, gh_number=5)
    decision = reconcile(jira, github, stored_hash, stored_hash)
    assert decision.action == Action.PUSH_JIRA_TO_GITHUB

    jira2 = _issue(title="Jira edit", updated=EARLIER)
    github2 = _issue(title="GitHub edit", updated=LATER, gh_number=5)
    decision2 = reconcile(jira2, github2, stored_hash, stored_hash)
    assert decision2.action == Action.PUSH_GITHUB_TO_JIRA


def test_sync_group_calls_create_for_new_jira_issue():
    calls = {}
    sync_group(
        [_issue()],
        {},
        create=lambda jira, jsrc, ghsrc: calls.setdefault("create", (jira.key, jsrc, ghsrc)),
        update=lambda *a: pytest.fail("update should not be called"),
        push_to_jira=lambda *a: pytest.fail("push_to_jira should not be called"),
        dry_run=False,
    )
    assert calls["create"][0] == "STUDIO-1"


def test_sync_group_dry_run_makes_no_calls():
    sync_group(
        [_issue()],
        {},
        create=lambda *a: pytest.fail("dry run must not create"),
        update=lambda *a: pytest.fail("dry run must not update"),
        push_to_jira=lambda *a: pytest.fail("dry run must not push"),
        dry_run=True,
    )


def test_sync_group_pushes_github_edit_to_jira():
    stored_hash = content_hash("Title", "Desc", "To Do")
    github = _issue(title="Edited on GitHub", gh_number=42)
    calls = {}
    sync_group(
        [_issue()],
        {"STUDIO-1": (github, stored_hash, stored_hash)},
        create=lambda *a: pytest.fail("should not create"),
        update=lambda *a: pytest.fail("should not update github"),
        push_to_jira=lambda key, title, desc: calls.setdefault("push", (key, title, desc)),
        dry_run=False,
    )
    assert calls["push"] == ("STUDIO-1", "Edited on GitHub", "Desc")


# --- reverse direction: GitHub -> Jira creation (STUDIO-269) ---------------

def test_github_import_description():
    assert github_import_description("Body", "http://x/1", "alice") == (
        "Imported from GitHub: http://x/1 (reported by @alice)\n\nBody"
    )
    # no reporter -> no attribution suffix
    assert github_import_description("Body", "http://x/1", "") == (
        "Imported from GitHub: http://x/1\n\nBody"
    )
    # empty body -> header only, no trailing blank lines
    assert github_import_description("", "http://x/1", "bob") == (
        "Imported from GitHub: http://x/1 (reported by @bob)"
    )


def test_issue_type_for_labels():
    assert issue_type_for_labels([]) == "Task"
    assert issue_type_for_labels(["documentation"]) == "Task"
    assert issue_type_for_labels(["Bug"]) == "Bug"  # case-insensitive
    assert issue_type_for_labels(["enhancement"]) == "Story"
    assert issue_type_for_labels(["feature"]) == "Story"
    # bug wins over story-ish labels when both present
    assert issue_type_for_labels(["enhancement", "bug"]) == "Bug"


class _FakeJira:
    def __init__(self, issues=None):
        self.created = []
        self.remote_links = []
        self._issues = issues or {}

    def create_issue(self, title, description, issue_type):
        self.created.append((title, description, issue_type))
        return f"STUDIO-{100 + len(self.created)}"

    def add_remote_link(self, key, url, title):
        self.remote_links.append((key, url, title))

    def get_issue(self, key):
        resp = self._issues.get(key)
        if resp is None:
            raise RuntimeError(f"no such issue {key}")
        return resp


class _FakeGitHub:
    def __init__(self, candidates=None, mark_raises=False, linked=None):
        self._candidates = candidates or []
        self.marked = []
        self._mark_raises = mark_raises
        self._linked = linked or {}
        self.status_applied = []

    def unlinked_open_issues(self):
        return self._candidates

    def mark_issue(self, number, description, status, key, jsrc, ghsrc):
        if self._mark_raises:
            raise RuntimeError("boom")
        self.marked.append((number, description, status, key, jsrc, ghsrc))

    def linked_issues(self):
        return self._linked

    def apply_status(self, number, description, status, key, jsrc, ghsrc, state=None):
        self.status_applied.append(
            {"number": number, "status": status, "key": key, "state": state}
        )


def _candidate(number=7, title="From GitHub", body="Body", labels=None,
               url="https://github.com/o/r/issues/7", reporter="alice"):
    return {
        "number": number, "title": title, "body": body, "labels": labels or [],
        "url": url, "reporter": reporter,
    }


def test_create_jira_from_github_creates_marks_and_backlinks():
    jira, github = _FakeJira(), _FakeGitHub([_candidate(labels=["bug"])])
    create_jira_from_github(jira, github, dry_run=False)

    # Jira issue created with the provenance header prepended to the body.
    title, desc, issue_type = jira.created[0]
    assert (title, issue_type) == ("From GitHub", "Bug")
    assert desc == "Imported from GitHub: https://github.com/o/r/issues/7 (reported by @alice)\n\nBody"

    # Web link back to the GitHub issue.
    assert jira.remote_links == [
        ("STUDIO-101", "https://github.com/o/r/issues/7", "GitHub #7: From GitHub")
    ]

    # Marker written back with side-specific hashes (Jira desc has the header,
    # GitHub body does not) so a future forward run sees no phantom diff.
    number, _d, status, key, jsrc, ghsrc = github.marked[0]
    assert (number, key, status) == (7, "STUDIO-101", "To Do")
    assert ghsrc == content_hash("From GitHub", "Body", "To Do")
    assert jsrc == content_hash("From GitHub", desc, "To Do")
    assert jsrc != ghsrc


def test_create_jira_from_github_dry_run_does_nothing():
    jira, github = _FakeJira(), _FakeGitHub([_candidate()])
    create_jira_from_github(jira, github, dry_run=True)
    assert jira.created == []
    assert github.marked == []


def test_create_jira_from_github_no_candidates():
    jira, github = _FakeJira(), _FakeGitHub([])
    create_jira_from_github(jira, github, dry_run=False)
    assert jira.created == []


def test_create_jira_from_github_marker_failure_is_swallowed():
    # A failed marker write-back must not crash the whole run; the Jira issue
    # was still created and the error is logged for manual repair.
    jira, github = _FakeJira(), _FakeGitHub([_candidate()], mark_raises=True)
    create_jira_from_github(jira, github, dry_run=False)
    assert len(jira.created) == 1


# --- scoped Jira -> GitHub status back-update (STUDIO-273) ------------------

def _jira_resp(summary="From GitHub", description="Body", status="In Progress", category="indeterminate"):
    return {
        "summary": summary, "description": description,
        "status_name": status, "status_category": category,
    }


def _linked_entry(status="To Do", gh_state="open", number=7, jsrc="j", ghsrc="g"):
    issue = _issue(status=status, gh_number=number, gh_state=gh_state)
    return {"STUDIO-1": (issue, jsrc, ghsrc)}


def test_update_linked_github_pushes_status_change():
    github = _FakeGitHub(linked=_linked_entry(status="To Do", gh_state="open"))
    jira = _FakeJira(issues={"STUDIO-1": _jira_resp(status="In Progress", category="indeterminate")})
    update_linked_github(jira, github, dry_run=False)
    assert len(github.status_applied) == 1
    call = github.status_applied[0]
    assert call["status"] == "In Progress"
    assert call["state"] is None  # not done -> no state change from open


def test_update_linked_github_closes_on_done():
    github = _FakeGitHub(linked=_linked_entry(status="In Progress", gh_state="open"))
    jira = _FakeJira(issues={"STUDIO-1": _jira_resp(status="Done", category="done")})
    update_linked_github(jira, github, dry_run=False)
    assert github.status_applied[0]["state"] == "closed"


def test_update_linked_github_reopens_when_reverted():
    github = _FakeGitHub(linked=_linked_entry(status="Done", gh_state="closed"))
    jira = _FakeJira(issues={"STUDIO-1": _jira_resp(status="To Do", category="new")})
    update_linked_github(jira, github, dry_run=False)
    assert github.status_applied[0]["state"] == "open"


def test_update_linked_github_noop_when_unchanged():
    # GH already shows In Progress + open, Jira still In Progress (not done).
    github = _FakeGitHub(linked=_linked_entry(status="In Progress", gh_state="open"))
    jira = _FakeJira(issues={"STUDIO-1": _jira_resp(status="In Progress", category="indeterminate")})
    update_linked_github(jira, github, dry_run=False)
    assert github.status_applied == []


def test_update_linked_github_dry_run_makes_no_writes():
    github = _FakeGitHub(linked=_linked_entry(status="To Do", gh_state="open"))
    jira = _FakeJira(issues={"STUDIO-1": _jira_resp(status="Done", category="done")})
    update_linked_github(jira, github, dry_run=True)
    assert github.status_applied == []


def test_update_linked_github_skips_missing_jira_issue():
    # Jira key 404s (deleted) -> skip, don't crash.
    github = _FakeGitHub(linked=_linked_entry())
    jira = _FakeJira(issues={})  # get_issue raises
    update_linked_github(jira, github, dry_run=False)
    assert github.status_applied == []


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
        ("false", False), ("off", False), ("0", False), ("no", False), ("", False),
    ],
)
def test_flag_enabled(monkeypatch, value, expected):
    monkeypatch.setenv("SOME_FLAG", value)
    assert _flag_enabled("SOME_FLAG") is expected


def test_flag_enabled_unset(monkeypatch):
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert _flag_enabled("SOME_FLAG") is False
