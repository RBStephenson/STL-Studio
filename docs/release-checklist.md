# Release qualification checklist

Before approving a v1.0.0 release candidate:

- Confirm the normal Tests, Build Check, CodeQL, and packaging jobs are green.
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
