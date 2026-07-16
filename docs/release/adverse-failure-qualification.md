# Adverse failure qualification

Use this checklist before promoting a release. It records the expected safe
behavior for the failure cases tracked by STUDIO-204. Code-signing certificate
availability is intentionally outside this qualification.

## Automated evidence

| Scenario | Expected behavior | Evidence |
|---|---|---|
| Interrupted migration | Startup stops, the exact pre-upgrade database is restored, and the recovery snapshot remains available. | `test_failed_upgrade_restores_exact_pre_upgrade_database` |
| Disk full during upgrade snapshot | Migration does not begin, the catalog is unchanged, and no partial snapshot is retained. | `test_disk_full_during_upgrade_snapshot_keeps_catalog_and_removes_partial_snapshot` |
| Disk full during downloaded backup | The request fails, the live catalog is unchanged, and the partial export is removed. | `test_disk_full_during_download_backup_keeps_catalog_and_removes_partial_export` |
| Locked database during settings write | SQLite rejects the transaction and neither the existing nor new setting is partially committed. | `test_locked_database_rejects_setting_write_without_partial_commit` |
| Read-only/undeletable database | Reset fails loudly before replacement rather than reporting success. | `test_reset_file_removal_fails_loudly` |
| Reset initialization failure | The populated pre-reset snapshot is restored. | `test_reset_restores_snapshot_when_empty_database_creation_fails` |
| Missing library drive | Catalog metadata remains available; drive status reports unavailable without exposing paths in support diagnostics. | `TestDriveStatus`, `test_storage_recovery_is_server_gated_and_path_free` |
| Corrupt environment settings | Reload fails with generic recovery feedback and does not expose invalid values or secrets. | `test_reload_failure_does_not_leak_exception_details` |
| Update preparation failure | The updater does not install when the sidecar cannot shut down and displays an error. | `updater.test.ts` |

## Manual Windows qualification

Run these on a disposable Windows VM with a copied catalog. Keep the VM snapshot
until results and relevant sanitized logs have been captured.

### Interrupted installed update

1. Install the supported prior version and populate one identifiable catalog record.
2. Begin an update to the release candidate, then terminate the installer VM while
   files are being replaced.
3. Restart Windows. If the application launches, verify the sentinel record and run
   **Settings → Data Management → Check Health**. If it does not launch, rerun the
   same installer to repair the installation.
4. Pass when repair/retry produces a launchable app with an intact catalog. Fail the
   release if the catalog is silently reset or the installer cannot be repaired.

### Read-only data directory

1. Copy a healthy catalog and remove write permission from its data directory.
2. Launch STL Studio and attempt a settings change and database backup.
3. Pass when writes fail visibly, the original database remains byte-for-byte
   unchanged, and restoring write permission allows a normal relaunch.

### Disk exhaustion

1. Use a disposable volume with less free space than the catalog database.
2. Attempt **Download Backup**, then launch an upgrade that requires migration.
3. Pass when both operations fail visibly, no partial backup is offered as valid,
   and the original catalog passes **Check Health** after space is restored.

### Missing library drive

1. Index a model on a removable drive, close the app, and disconnect the drive.
2. Relaunch and browse the catalog, then reconnect the drive.
3. Pass when metadata remains browsable, missing previews fail without repeated
   disruption, and previously failed previews recover after reconnection.

Record the application versions, VM image, outcome, and sanitized log bundle in
the release ticket. Any data-integrity failure blocks promotion.
