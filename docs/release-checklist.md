# Release qualification checklist

Before approving a release candidate:

- Complete the [clean-machine release acceptance](release/clean-machine-acceptance.md)
  on a disposable Windows VM. Record its operator, candidate version, VM image,
  PASS result, and evidence location in the release ticket; release promotion
  must reference that completed ticket.
- Confirm the normal Tests, Build Check, CodeQL, and packaging jobs are green.
- Require the Windows packaging smoke to pass its custom/default-directory,
  shortcut creation/removal, repair/reinstall, relaunch, user-data retention,
  and uninstall checks. Production certificate acquisition and signed-installer
  verification remain separate release decisions and are not covered by this gate.
- Run **Actions → Installed Update Smoke → Run workflow** with the latest
  supported published release as `bootstrap_tag`, the candidate ref, and a
  candidate semantic version newer than the bootstrap.
- Require a green `update-smoke` job. It installs the published bootstrap NSIS
  package in isolated runner directories, seeds representative database state,
  serves the candidate updater feed on loopback, accepts the update, and asserts
  candidate version plus data persistence after installer replacement/relaunch.
- If it fails, download `installed-update-smoke-diagnostics` and inspect the
  Electron log, sidecar locks, and relevant process report before retrying.

The workflow never uses the developer workstation or production user data. Its
test-only updater override accepts only an explicit smoke-mode switch and an
HTTP loopback feed URL.

## Publication gate and recovery

The Release workflow keeps every candidate as a draft until all platform
artifacts have uploaded. It then downloads that exact draft asset set, creates
`SHA256SUMS`, verifies `latest.yml` points to the real NSIS filename, and runs
the installed-update rehearsal from the latest published version. Only the
publish job can clear the draft flag, and it depends on the complete
qualification job.

If qualification fails, leave the release as a draft and download
`release-qualification-diagnostics`. Repair the workflow or replace the bad
draft assets, then rerun the release workflow with the same explicit version.
The upload steps overwrite draft assets safely. If a clean restart is required,
delete the draft release first, then delete its tag, fix the cause, and rerun;
never publish a partial draft manually. Verify the public release contains the
installer, matching blockmap, `latest.yml`, Linux binary, three CycloneDX SBOMs,
and `SHA256SUMS`. Follow [Release supply-chain verification](release/supply-chain-verification.md)
to validate the downloaded assets and GitHub attestations independently.

Production certificate acquisition and signed-installer verification remain
separate release decisions and are excluded from this qualification gate.

For bootstrap releases through v0.20.3, which predate the smoke-mode
auto-accept hook, the harness replaces the installed copy's generated updater
feed configuration with the loopback feed and clicks the existing Download and
Restart confirmation dialogs. Starting with v0.20.4, smoke mode accepts those
two updater actions directly, so the harness does not wait for obsolete dialog
titles. Both paths still drive only the candidate assisted NSIS installer's
allowlisted navigation buttons and record every matched window and button set
in failure diagnostics. The published executable and updater implementation
remain unchanged.

Update rehearsals use the disposable GitHub-hosted runner account's normal
per-user data directories because the assisted installer relaunch does not
preserve process-level AppData overrides. A clean-profile preflight prevents
the rehearsal from using pre-existing STL Studio data; the runner is destroyed
after the job.
