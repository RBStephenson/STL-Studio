# Support and compatibility policy

This policy describes the configurations STL Studio supports for the v1.0 release
line, the upgrade paths that have been qualified, and what to include when asking
for help.

## Supported platforms

| Configuration | Support level | Notes |
|---|---|---|
| Windows 11, x64 | Supported | Primary desktop configuration. Use the published `STL-Studio-Setup-<version>.exe` installer. |
| Windows 10 22H2, x64 | Supported while the underlying Electron runtime supports it | Windows 10 may require Microsoft's Extended Security Updates after its normal support lifecycle. |
| Linux, x64 headless binary | Best effort | Runs as a local web service. The packaged Electron desktop window and automatic updater are Windows-only. |
| Docker Compose | Best effort | Intended for experienced self-hosters. Host operating systems and NAS platforms are not individually qualified. |
| Windows on ARM, 32-bit Windows, Windows Server, and macOS desktop | Unsupported | No matching desktop installer is built or qualified. macOS users may try Docker on a best-effort basis. |

“Supported” means releases are built and checked in CI and the installer,
application lifecycle, backup/restore, migration-failure, and updater paths have
repeatable qualification coverage. It does not mean every hardware, filesystem,
NAS, security-product, or corporate-policy combination has been tested.

## Upgrades, backups, and rollback

- Direct upgrades are supported from **v0.18.0 or newer** to the current release.
- Before a major upgrade, create a backup under **Settings → Data Management →
  Download Backup** and keep it until the new version has been exercised with
  your library.
- STL files remain in their library folders; the application database stores the
  catalog and settings.
- A schema upgrade first creates a `pre_upgrade_<timestamp>.db` snapshot. If the
  migration fails, startup stops and restores the original database automatically.
- Downgrades are not supported. Schema migrations are not reversed, and a backup
  created by a newer version is not guaranteed to load in an older version.
- To roll back, reinstall the older application and restore a backup or automatic
  pre-upgrade snapshot created by that older version.

## Getting help

Search the [Troubleshooting guide](troubleshooting.md) first. For a reproducible
problem, open a [GitHub bug report](https://github.com/RBStephenson/STL-Studio/issues/new?template=bug_report.md)
and include:

- the STL Studio version and installation method;
- the Windows version and architecture, or Docker/Linux environment;
- concise reproduction steps and the expected versus actual result;
- the sanitized summary from **Help → About & support → Copy diagnostics**; and
- a sanitized log bundle when it is relevant to the failure.

## Privacy and diagnostic sharing

STL Studio does not submit diagnostics or log bundles automatically. The catalog,
settings, and persistent logs remain on the local machine unless you choose to
share them. Optional AI and storefront integrations make network requests only
when configured and used.

**Copy diagnostics** includes an allowlisted health summary. Persistent support
logs are off by default, rotate within a fixed size, and redact credentials and
local paths. Sanitization is a safety layer, not a guarantee: review copied text,
screenshots, and downloaded logs before attaching them to a public report. Never
share API keys, passwords, private model metadata, or library paths that you do
not want disclosed.

## Release scope

Code signing is not part of the current qualification scope. Until signed
installers are published, Windows SmartScreen may require **More info → Run
anyway** for a downloaded installer.
