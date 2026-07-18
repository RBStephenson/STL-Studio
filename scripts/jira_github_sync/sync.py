"""Daily two-way Jira <-> GitHub sync entry point (STUDIO-264).

Usage:
    python -m scripts.jira_github_sync.sync

Required environment variables:
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY
    GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo)

Optional:
    JIRA_GITHUB_SYNC_DRY_RUN=1  -- log decisions without writing to either side

Gating: this script is not run by the app itself (STL Studio is a local
desktop app; its DB isn't reachable from a GitHub Actions runner), so unlike
other STL Studio features it is NOT gated by an app_settings flag / Settings
toggle. It's gated by the `jira-github-sync.yml` workflow being enabled and
the `JIRA_GITHUB_SYNC_ENABLED` repo variable (checked in the workflow, not
here) -- see docs/jira_github_sync.md.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Callable

from .github_client import GitHubClient
from .jira_client import JiraClient
from .models import Action, NormalizedIssue, reconcile

_log = logging.getLogger("jira_github_sync")


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def sync_group(
    jira_items: list[NormalizedIssue],
    linked_github: dict[str, tuple],
    create: Callable,
    update: Callable,
    push_to_jira: Callable,
    dry_run: bool,
) -> None:
    """Reconcile one Jira issue-type group (issues, or epics) against its
    GitHub counterparts (issues, or milestones respectively)."""
    for jira in jira_items:
        entry = linked_github.get(jira.key)
        github, jsrc, ghsrc = entry if entry else (None, None, None)
        decision = reconcile(jira, github, jsrc, ghsrc)

        if decision.action == Action.NONE:
            continue
        _log.info("%s: %s", jira.key, decision.action.value)
        if dry_run:
            continue
        if decision.action == Action.CREATE_GITHUB:
            create(jira, decision.new_jsrc, decision.new_ghsrc)
        elif decision.action == Action.PUSH_JIRA_TO_GITHUB:
            update(github.gh_number, jira, decision.new_jsrc, decision.new_ghsrc)
        elif decision.action == Action.PUSH_GITHUB_TO_JIRA:
            push_to_jira(jira.key, github.title, github.description)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    dry_run = os.environ.get("JIRA_GITHUB_SYNC_DRY_RUN", "") == "1"

    jira = JiraClient(
        base_url=_env("JIRA_BASE_URL"),
        email=_env("JIRA_EMAIL"),
        api_token=_env("JIRA_API_TOKEN"),
        project_key=_env("JIRA_PROJECT_KEY"),
    )
    github = GitHubClient(repo=_env("GITHUB_REPOSITORY"), token=_env("GITHUB_TOKEN"))

    jira.log_identity()
    open_issues = jira.list_open_issues()
    open_epics = jira.list_open_epics()
    linked_issues = github.linked_issues()
    linked_milestones = github.linked_milestones()
    _log.info(
        "Fetched %d open Jira issues (%d already linked on GitHub), "
        "%d open Jira epics (%d already linked as milestones)",
        len(open_issues), len(linked_issues), len(open_epics), len(linked_milestones),
    )

    sync_group(
        open_issues,
        linked_issues,
        create=github.create_issue,
        update=github.update_issue,
        push_to_jira=jira.update_issue,
        dry_run=dry_run,
    )
    sync_group(
        open_epics,
        linked_milestones,
        create=github.create_milestone,
        update=github.update_milestone,
        push_to_jira=jira.update_issue,
        dry_run=dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
