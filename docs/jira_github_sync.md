# Jira <-> GitHub Sync (STUDIO-264)

Jira (project `STUDIO`) is the system of record. This sync exists purely for
GitHub-side visibility, and to let edits made directly on GitHub issues flow
back into Jira instead of being silently lost.

## What syncs

| Jira | GitHub | Notes |
|---|---|---|
| Epic | Milestone | |
| Story / Task / Bug | Issue | Sub-tasks are skipped (too granular for GH) |

Only **open** (non-`Done`-category) Jira epics/issues are considered.

Fields synced: title (`summary`), description, and a mirrored
`**Jira status:** <status>` line in the GitHub body. GitHub issue/milestone
**open/closed state is never touched by the sync** — closing is left to
humans on the GitHub side, so a stale sync run can't reopen or close
something a maintainer already dealt with.

## Creation direction

New items are only ever created in Jira, then mirrored to GitHub. The sync
never creates a Jira issue from a GitHub-only issue — that would fight the
Jira-is-SoT convention in the project's `.claude/CLAUDE.md`. If someone opens
an issue directly on GitHub, it's simply not touched by this sync (no marker,
no match).

## Conflict resolution

Each linked GitHub item carries a hidden marker in its body:

```html
<!-- jira-sync key=STUDIO-123 jsrc=1a2b3c4d ghsrc=5e6f7a8b -->
```

`jsrc`/`ghsrc` are content hashes captured at the last successful sync. Each
run:

1. Recompute the current content hash for both the Jira issue and its linked
   GitHub item.
2. If neither hash moved since the stored value, do nothing.
3. If only one side moved, push that side's content to the other.
4. If **both** moved (edited on both sides between runs), Jira's `updated`
   timestamp vs. GitHub's `updated_at` decides the winner (last-write-wins).

This is a plain content-hash check, not a timestamp check, for the common
case — it avoids clock-skew false positives and avoids re-pushing content the
sync itself just wrote.

## Gating

STL Studio is a local desktop app (Electron); its database is not reachable
from a GitHub Actions runner, so this feature does **not** follow the
project's usual `<feature>_enabled` app-settings/Settings-tab pattern — there
is no in-app toggle for it.

Instead, gating is entirely on the GitHub side:

- The workflow (`.github/workflows/jira-github-sync.yml`) only runs its `sync`
  job when the repo variable `JIRA_GITHUB_SYNC_ENABLED` is `"true"`.
- To turn the sync off entirely, either flip that variable to `"false"` or
  disable the workflow (`gh workflow disable jira-github-sync.yml`).

## Required GitHub Actions configuration

**Repository variables** (Settings -> Secrets and variables -> Actions -> Variables):

- `JIRA_GITHUB_SYNC_ENABLED` = `true`
- `JIRA_BASE_URL` = `https://rbrentstephenson.atlassian.net`
- `JIRA_EMAIL` = the Jira account email the API token belongs to
- `JIRA_PROJECT_KEY` = `STUDIO`

**Repository secret**:

- `JIRA_API_TOKEN` — an Atlassian API token
  (https://id.atlassian.com/manage-profile/security/api-tokens)

`GITHUB_TOKEN` is provided automatically by Actions; no secret needed for it.

## First run / backfill

The first run will create a GitHub issue/milestone for every open Jira
epic/issue that doesn't already have a linked GitHub counterpart. If
equivalent issues already exist on GitHub from before this sync existed,
either close/delete the duplicates it creates, or manually add the marker
comment (`<!-- jira-sync key=STUDIO-XXX jsrc=00000000 ghsrc=00000000 -->`,
using placeholder hashes to force a resync) to the existing GitHub issue body
before the first scheduled run so it gets linked instead of duplicated.

## Local dry run

```bash
JIRA_GITHUB_SYNC_DRY_RUN=1 \
JIRA_BASE_URL=https://rbrentstephenson.atlassian.net \
JIRA_EMAIL=you@example.com \
JIRA_API_TOKEN=... \
JIRA_PROJECT_KEY=STUDIO \
GITHUB_TOKEN=... \
GITHUB_REPOSITORY=RBStephenson/STL-Studio \
python -m scripts.jira_github_sync.sync
```

Dry run logs every decision (`create_github` / `push_jira_to_github` /
`push_github_to_jira`) without writing to either side.
