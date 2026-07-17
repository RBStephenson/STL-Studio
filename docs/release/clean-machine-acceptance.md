# Clean-machine release acceptance

Run this checklist on a disposable, fully patched Windows 11 VM before promoting
a release candidate. A second operator is useful when available, but is not
required; the release author may run the checklist. Start from a clean VM
snapshot with no prior STL Studio installation or user data, and retain the
evidence so another maintainer can review the result asynchronously.

## Record

- Candidate version and release URL:
- Bootstrap version used for the update check:
- VM image and Windows build:
- Operator and date:
- Result: PASS / FAIL
- Evidence bundle location:

Keep screenshots, exported diagnostics, and this completed checklist together.
Sanitize logs before attaching them to a public ticket. A failed or incomplete
step blocks release promotion.

## Preconditions

- [ ] Download the candidate installer and `SHA256SUMS` from the draft release.
- [ ] Verify the installer checksum and record the command output.
- [ ] Prepare a small test library containing at least two STL files and one
  preview image. Record file names, counts, and the source path without exposing
  private paths publicly.
- [ ] Take a clean VM snapshot and confirm no STL Studio process, installation,
  Start Menu entry, or user-data directory exists.

Evidence: checksum output, clean-state screenshot, and test-library manifest.

## 1. Install and first launch

- [ ] Run the installer with default options and launch from the Start Menu.
- [ ] Confirm the app opens without an error, reports the candidate version, and
  creates only the expected application and user-data directories.
- [ ] Close and relaunch the app from the desktop or Start Menu shortcut.

Expected: installation and both launches succeed; the displayed version matches
the candidate. Evidence: installer completion, About/version, and first-library
screenshots plus sanitized startup diagnostics.

## 2. Scan and persistence

- [ ] Add the prepared test library and run a scan.
- [ ] Confirm the expected models and preview are visible and the scan reports no
  unexplained errors.
- [ ] Favorite one model, add a tag to the other, then close and relaunch.
- [ ] Confirm the models, preview, favorite, tag, and library location persist.

Expected: scanned content and user changes survive a full application restart.
Evidence: scan summary and before/after-relaunch screenshots.

## 3. Backup and restore

- [ ] Download a database backup and record its filename and size.
- [ ] Change the sentinel favorite or tag, then restore the backup.
- [ ] Relaunch and confirm the pre-backup state is restored and the catalog passes
  **Settings -> Data Management -> Check Health**.

Expected: backup completes, restore replaces the later change, and health check
passes. Evidence: backup file metadata, restore result, and health screenshot.

## 4. Update from the supported bootstrap

- [ ] Revert to the clean snapshot, install the latest supported published
  bootstrap, and repeat the scan plus sentinel favorite/tag.
- [ ] Use the normal updater flow to install the candidate.
- [ ] Confirm the candidate launches, reports its new version, and preserves the
  scanned catalog, preview, favorite, and tag.

Expected: the published upgrade path completes without manual file replacement
or data loss. Evidence: bootstrap and candidate version screenshots, updater
screenshots, and post-update catalog screenshot.

## 5. Diagnostics

- [ ] Open **Help -> About & support -> Copy diagnostics** and save the copied
  text with the other acceptance evidence.
- [ ] Confirm the output contains useful version and health context.
- [ ] Inspect it for credentials, tokens, private library paths, or unrelated
  personal data before attaching it anywhere.

Expected: diagnostics are copied successfully and do not expose secrets or
unnecessary private data. Evidence: the sanitized copied output; retain it
privately if it contains machine-specific data.

## 6. Uninstall

- [ ] Uninstall STL Studio through Windows Settings.
- [ ] Confirm shortcuts and installed application files are removed.
- [ ] Confirm whether user data remains, matching the documented retention
  behavior, then record and remove it before discarding the VM.

Expected: the uninstaller completes without an error, removes application files
and shortcuts, and handles user data as documented. Evidence: uninstall result
and post-uninstall filesystem/shortcut screenshots.

## Promotion sign-off

- [ ] Every step above passed and required evidence is attached to or linked from
  the release ticket.
- [ ] Automated release qualification and the adverse-failure checklist are also
  complete.
- [ ] The release ticket records this checklist's operator, date, candidate
  version, VM image, evidence location, and final PASS result.

Release promotion must reference the completed release ticket. Do not promote a
candidate with a failure, missing evidence, or an unexplained deviation.
