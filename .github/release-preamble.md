## Installing on Windows

Download `STL-Studio-Setup-<version>.exe` below and run it.

**Windows will warn you on first run.** STL Studio is not code-signed yet, so
SmartScreen shows *"Windows protected your PC"* with an unknown publisher.
Choose **More info → Run anyway**. This is expected for every current release
and is not a malware detection.

If there is no **More info** link, or your browser refused the download, see
[Windows blocked the installer](https://github.com/RBStephenson/STL-Studio/blob/main/docs/troubleshooting.md#windows-blocked-the-installer-smartscreen).

### Verifying this download

Because the installer is unsigned, you can confirm it is exactly what CI
published:

```powershell
# Checksum — compare against the SHA256SUMS asset below
Get-FileHash .\STL-Studio-Setup-<version>.exe -Algorithm SHA256

# Build provenance — proves it came from this repo's workflow (requires gh CLI)
gh attestation verify .\STL-Studio-Setup-<version>.exe --repo RBStephenson/STL-Studio
```

Full install guide: [Getting started](https://github.com/RBStephenson/STL-Studio/blob/main/docs/getting-started.md)

---
