# Release supply-chain verification

Every published release includes a checksum manifest and CycloneDX SBOMs for
the dependencies packaged into its Windows and Linux artifacts:

- `stl-studio-backend-windows.cdx.json` records the Python environment resolved
  on the Windows build runner before build-only tools are installed.
- `stl-studio-backend-linux.cdx.json` records the equivalent Linux environment.
- `stl-studio-desktop-windows.cdx.json` records the complete Electron packaging
  dependency graph. It intentionally includes development dependencies because
  Electron is declared as a development dependency but its runtime is embedded
  in the installer.

The release workflow downloads the complete draft, rejects missing or extra
assets, validates each SBOM, writes `SHA256SUMS`, and verifies every checksum
before publication. It then creates GitHub-hosted SLSA build-provenance
attestations for the installer and Linux binary. The same binaries receive SBOM
attestations: both backend and desktop SBOMs for Windows, and the backend SBOM
for Linux.

## Verify a downloaded release

Download every asset into an otherwise empty directory. On Linux or macOS:

```bash
sha256sum --check SHA256SUMS
gh attestation verify STL-Studio-Setup-<version>.exe --repo RBStephenson/STL-Studio
gh attestation verify stl-studio-linux --repo RBStephenson/STL-Studio
```

On PowerShell, verify the checksum manifest with the repository harness:

```powershell
python scripts/validate_release_assets.py . --version <version>
gh attestation verify STL-Studio-Setup-<version>.exe --repo RBStephenson/STL-Studio
gh attestation verify stl-studio-linux --repo RBStephenson/STL-Studio
```

`gh attestation verify` validates that GitHub Actions built the downloaded
subject for this repository. Add `--format json` to inspect all matching
attestations, including the CycloneDX SBOM predicates. A missing attestation,
checksum mismatch, malformed SBOM, or unexpected asset is a failed release
verification; do not install that candidate.
