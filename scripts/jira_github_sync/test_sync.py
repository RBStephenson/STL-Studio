"""Unit tests for the Jira<->GitHub reconcile decision and sync loop.

No network: models.reconcile is pure, and sync_group is exercised with fake
create/update/push callables recording what they were called with.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from jira_github_sync.models import Action, NormalizedIssue, content_hash, reconcile
from jira_github_sync.sync import sync_group

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
