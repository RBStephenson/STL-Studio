# Jira <-> GitHub Sync (STUDIO-264)

Jira (project `STUDIO`) is the system of record. Both sync directions are
**independently opt-in** and **off by default**; with neither enabled the run
is a no-op.

- **Reverse — GitHub → Jira** (`JIRA_GITHUB_SYNC_CREATE_JIRA`): issues opened
  directly on the public GitHub repo are mirrored into Jira. This is the
  primary intended use: end users file bugs/requests on GitHub, you triage in
  Jira.
- **Forward — Jira → GitHub** (`JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB`): open Jira
  issues/epics are published to GitHub as issues/milestones.

> ⚠️ **Forward mirroring on a public repo publishes every open Jira issue
> publicly** — including internal or security-sensitive tickets. Only enable
> `JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB` if every open Jira issue is safe to
> disclose. For the "end users file issues, I work in Jira" workflow, leave
> forward **off** and enable reverse only.

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

Forward mirroring (Jira → GitHub) is gated by `JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB`
(default off). When on, new items created in Jira are mirrored to GitHub;
GitHub open/closed state is never touched (see above). Keep this off for a
public repo unless every open Jira issue is safe to publish.

Reverse creation (GitHub → Jira) is gated by the
`JIRA_GITHUB_SYNC_CREATE_JIRA` repo variable (default off). When enabled, each
**open, non-PR** GitHub issue that has **no** `jira-sync` marker (i.e. one
opened directly on GitHub, not by this sync) creates a matching Jira issue,
after which the GitHub issue is stamped with the marker so later runs link the
pair instead of duplicating it.

- **Issue type**: defaults to `Task`; GitHub labels map `bug` → Bug and
  `enhancement`/`feature`/`story` → Story (`bug` wins when several apply).
- **Scope**: only open, unlinked, non-PR issues. Closed issues, pull requests,
  milestones, and already-linked issues are skipped.
- **Duplicate safety**: the marker is written back immediately after the Jira
  issue is created. If that write-back ever fails, the run logs an error with
  the exact marker to paste onto the GitHub issue by hand — otherwise the next
  run would create a second Jira issue for it.

With the flag off (the default), issues opened directly on GitHub are simply
left untouched (no marker, no match).

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
- `JIRA_GITHUB_SYNC_CREATE_JIRA` = `true` to enable reverse (GitHub → Jira)
  creation; omit or set `false`/`off` to keep it off (default)
- `JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB` = `true` to enable forward (Jira →
  GitHub) mirroring; omit or set `false`/`off` to keep it off (default).
  **Leave off on a public repo** unless all open Jira issues are safe to
  disclose.

Accepted truthy values for the flags: `true`/`1`/`yes`/`on` (case-insensitive);
anything else (including `false`/`off`/unset) is treated as disabled.

For the typical "end users file issues on GitHub, I work in Jira" setup:
`JIRA_GITHUB_SYNC_ENABLED=true`, `JIRA_GITHUB_SYNC_CREATE_JIRA=true`, and
`JIRA_GITHUB_SYNC_MIRROR_TO_GITHUB` left off.

**Repository secret**:

- `JIRA_API_TOKEN` — an Atlassian API token
  (https://id.atlassian.com/manage-profile/security/api-tokens). Use a
  **classic unscoped** token ("Create API token"), not a scoped one — scoped
  tokens are rejected by the site-URL Basic-auth flow this client uses and
  fail silently (the request is treated as anonymous: `/myself` returns 401
  while search returns an empty result set).

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
