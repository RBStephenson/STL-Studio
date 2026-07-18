"""Daily two-way Jira <-> GitHub sync entry point (STUDIO-264).

Usage:
    python -m scripts.jira_github_sync.sync

Required environment variables:
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, JIRA_PROJECT_KEY
    GITHUB_TOKEN, GITHUB_REPOSITORY (owner/repo)

Optional direction flags (both off by default; neither on => no-op):
    JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB  -- forward: mirror Jira -> GitHub
    JIRA_GITHUB_SYNC_CREATE_JIRA       -- reverse: create Jira from GitHub issues
    JIRA_GITHUB_SYNC_DRY_RUN=1         -- log decisions without writing anywhere

Gating: this script is not run by the app itself (STL Studio is a local
desktop app; its DB isn't reachable from a GitHub Actions runner), so unlike
other STL Studio features it is NOT gated by an app_settings flag / Settings
toggle. The `jira-github-sync.yml` workflow gates the whole run on the
`JIRA_GITHUB_SYNC_ENABLED` repo variable; the two direction flags above then
select which way(s) data flows. Forward mirroring publishes Jira issues to
GitHub, so on a public repo keep it off unless every open Jira issue is safe
to disclose -- see docs/jira_github_sync.md.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Callable

from .github_client import GitHubClient
from .jira_client import JiraClient
from .models import (
    Action,
    NormalizedIssue,
    content_hash,
    github_import_description,
    issue_type_for_labels,
    reconcile,
)

_log = logging.getLogger("jira_github_sync")

# Status a freshly-created Jira issue lands in (project workflow initial state).
_NEW_JIRA_STATUS = "To Do"


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


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


def create_jira_from_github(jira: JiraClient, github: GitHubClient, dry_run: bool) -> None:
    """Reverse direction: mirror GitHub-originated issues into Jira.

    Only open, non-PR GitHub issues without a jira-sync marker qualify (the
    sync's own creations always carry one). After creating the Jira issue, the
    GitHub issue is stamped with the marker so the next run links the pair
    instead of creating a second Jira issue.
    """
    candidates = github.unlinked_open_issues()
    _log.info("Found %d unlinked open GitHub issue(s) to mirror into Jira", len(candidates))
    for gh in candidates:
        issue_type = issue_type_for_labels(gh["labels"])
        _log.info("GitHub #%d -> create Jira %s: %s", gh["number"], issue_type, gh["title"])
        if dry_run:
            continue
        # The Jira description carries an import-provenance header; the GitHub
        # body does not. Hash each side against its own content so a later
        # forward-mirror run doesn't see a phantom diff (reconcile compares
        # jsrc/ghsrc independently).
        jira_desc = github_import_description(gh["body"], gh["url"], gh["reporter"])
        key = jira.create_issue(gh["title"], jira_desc, issue_type)
        jsrc = content_hash(gh["title"], jira_desc, _NEW_JIRA_STATUS)
        ghsrc = content_hash(gh["title"], gh["body"], _NEW_JIRA_STATUS)
        if gh["url"]:
            try:
                jira.add_remote_link(key, gh["url"], f"GitHub #{gh['number']}: {gh['title']}")
            except RuntimeError:
                _log.warning("Created Jira %s but could not add the GitHub web link", key)
        try:
            github.mark_issue(
                gh["number"], gh["body"], _NEW_JIRA_STATUS, key, jsrc, ghsrc
            )
        except RuntimeError:
            _log.error(
                "Created Jira %s from GitHub #%d but FAILED to write the link marker "
                "back to GitHub -- a duplicate Jira issue may be created on the next "
                "run. Manually add '<!-- jira-sync key=%s jsrc=%s ghsrc=%s -->' to "
                "GitHub issue #%d to prevent this.",
                key, gh["number"], key, jsrc, ghsrc, gh["number"],
            )


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

    # Both directions are independently opt-in. With neither flag set the run
    # is a no-op. IMPORTANT: forward mirroring publishes Jira issues to GitHub,
    # which leaks internal/private tickets if the repo is public -- so it is
    # off by default and must be turned on deliberately (see docs).
    if _flag_enabled("JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB"):
        _mirror_jira_to_github(jira, github, dry_run)
    else:
        _log.info(
            "Forward mirroring (Jira->GitHub) disabled; set "
            "JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB=true to enable"
        )

    if _flag_enabled("JIRA_GITHUB_SYNC_CREATE_JIRA"):
        create_jira_from_github(jira, github, dry_run)
    else:
        _log.info(
            "Reverse creation (GitHub->Jira) disabled; set "
            "JIRA_GITHUB_SYNC_CREATE_JIRA=true to enable"
        )

    return 0


def _mirror_jira_to_github(jira: JiraClient, github: GitHubClient, dry_run: bool) -> None:
    """Forward direction: mirror open Jira issues/epics out to GitHub
    issues/milestones. Publishes Jira content to GitHub -- keep off for public
    repos unless every open Jira issue is safe to disclose."""
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


if __name__ == "__main__":
    sys.exit(main())
