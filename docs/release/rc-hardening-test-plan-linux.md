# Release-candidate hardening test plan — Linux

Companion to the [Windows/desktop hardening plan](rc-hardening-test-plan.md).
Run alongside the [release qualification checklist](../release-checklist.md).

**Linux is a different product surface, not a port of the desktop app.** There is
no Electron shell — that is Windows-only for v1.0. Linux ships two things:

| Path | Artifact | Notes |
|---|---|---|
| **Docker Compose** | `ghcr.io/…-backend`, `…-frontend` images | nginx serves the SPA and proxies `/api`; the primary multi-device deployment |
| **Standalone binary** | `stl-studio-linux` (PyInstaller one-file) | serves UI + API itself; no container required |

The browser is the client in both cases, so anything the Electron shell owns —
CSP enforcement, window-open handling, the sidecar lifecycle, auto-update — is
either absent or handled by the browser instead.

---

## Current cycle

**Build under test:** `v1.0.0-beta.8` (commit `bf3297b`)
**Predecessor:** `v1.0.0-beta.7` (`611e66c`)

### Which of this build's fixes actually apply here

| Fix | Applies on Linux? |
|---|---|
| STUDIO-258 — Electron CSP | **No.** Electron-only. See "Known gap" below — the browser path has no CSP at all. |
| STUDIO-259 — external navigation | **No.** A real browser opens links in a real tab with a visible address bar; the Electron phishing surface does not exist. |
| STUDIO-298 — creator case-insensitivity | **Yes, and this is the priority.** Linux is the case-sensitive host, so this is where the behaviour change bites. |
| STUDIO-366 — native path separators | **Yes, as a no-op regression check.** `_canon`'s output already matches native form on POSIX, so nothing should change — verify that it didn't. |
| STUDIO-320 — image download hardening | **Yes, fully.** |
| STUDIO-226 — closed by decision | **Yes.** Its whole subject was Linux case handling; the decision reversed what it asked for. |

> **Read this before Section 2.** STUDIO-298 deliberately made creator identity
> case-insensitive on *every* platform, including case-sensitive filesystems.
> On Linux, `Abe3D/` and `abe3d/` now resolve to **one** creator where they
> previously produced two. STUDIO-226 asked for the opposite and was closed in
> favour of cross-host parity. Section 2.1 exists to confirm that decision is
> safe in practice on the host where it actually changes behaviour.

---

## Known gap — no CSP on the browser-served path

STUDIO-258 added a Content-Security-Policy at the **Electron session layer**.
Nothing adds one for browser clients: `frontend/nginx.conf.template` sets no
`add_header` directives, and the FastAPI app sets no security headers. So a
Docker or standalone-binary deployment serves the app with **no CSP, no
`X-Frame-Options`, and no `X-Content-Type-Options`**.

This is the same class of gap 258 closed for the desktop, still open for
everyone else. It matters more, not less, when the app is reachable over a
network rather than bound to loopback.

Section 3.5 verifies the current (absent) state so it is measured rather than
assumed. **Do not file this as a beta.8 regression** — it predates this build.
Tracked as **STUDIO-370**.

---

## 0. Artifact integrity

```bash
gh release view v1.0.0-beta.8 --json tagName,isPrerelease,isDraft \
  -q '"tag=\(.tagName) prerelease=\(.isPrerelease) draft=\(.isDraft)"'

# Standalone binary checksum against the published manifest
sha256sum stl-studio-linux
grep -i 'stl-studio-linux' SHA256SUMS

# Provenance
gh attestation verify stl-studio-linux --repo RBStephenson/STL-Studio

# Container images — confirm the tag you are about to run
docker pull ghcr.io/rbstephenson/stl-studio-backend:v1.0.0-beta.8
docker pull ghcr.io/rbstephenson/stl-studio-frontend:v1.0.0-beta.8
docker image inspect ghcr.io/rbstephenson/stl-studio-backend:v1.0.0-beta.8 \
  -f '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

| # | Check | Pass |
|---|---|---|
| 0.1 | `stl-studio-linux` checksum matches `SHA256SUMS` | ☐ |
| 0.2 | Attestation verifies | ☐ |
| 0.3 | Image revision label matches `bf3297b` | ☐ |
| 0.4 | SBOM `stl-studio-backend-linux.cdx.json` present in the release | ☐ |

---

## 1. Deployment

### 1.1 Docker Compose — cold start

| # | Step | Expected | Pass |
|---|---|---|---|
| 1.1.1 | `docker compose up -d` with no `.env` present | Comes up on the `/dev/null` mount defaults without erroring | ☐ |
| 1.1.2 | Set `LIBRARY_DIR` / `STL_DRIVE_1` in `.env`, recreate | Roots visible in the app | ☐ |
| 1.1.3 | Browse to `http://localhost` | SPA loads; `/api` proxied correctly | ☐ |
| 1.1.4 | `docker compose ps` | Both services healthy, `restart: unless-stopped` | ☐ |
| 1.1.5 | Check published ports | Bound to **127.0.0.1 only** — `ss -tlnp` shows no `0.0.0.0:80` | ☐ |
| 1.1.6 | `docker compose down && up -d` | Library and settings survive (SQLite under `./data`) | ☐ |
| 1.1.7 | Stop mid-scan, restart | No corruption; next scan completes | ☐ |

**1.1.5 matters:** the API is unauthenticated. If it is listening on `0.0.0.0`,
anyone on the LAN can drive it. That binding is deliberate in
`docker-compose.yml`; confirm a real deploy has not overridden it.

### 1.2 Standalone binary

`stl-studio-linux` is a first-class delivery path, not a debugging aid: it is
the whole application in one file, serving both the API and the bundled SPA
(`packaging/standalone.py` mounts `frontend/dist` at `/`). It is also the same
PyInstaller artifact the Windows Electron build wraps as its sidecar, so its
frozen-import graph is shared — a missing hidden import breaks both.

Unlike the container, it stores data under the XDG location rather than `/data`:
`$XDG_DATA_HOME`, falling back to `~/.local/share` (`standalone.py:48`). It
prints the resolved path on startup.

| # | Step | Expected | Pass |
|---|---|---|---|
| 1.2.1 | `chmod +x stl-studio-linux && ./stl-studio-linux --port 8484` | Starts; prints the serving URL and the data directory | ☐ |
| 1.2.2 | `curl -fsS localhost:8484/api/health` | 2xx | ☐ |
| 1.2.3 | Browse to `http://localhost:8484` | **The SPA loads from the binary itself** — no separate frontend needed | ☐ |
| 1.2.4 | Exercise the painting/colour-match feature | No frozen-import crash — this is the import graph STUDIO-100 broke and STUDIO-102's CI smoke covers | ☐ |
| 1.2.5 | Confirm the data directory it reported | Under `~/.local/share`, **not** `/data`; created if absent | ☐ |
| 1.2.6 | `XDG_DATA_HOME=/tmp/stl-test ./stl-studio-linux --port 8484` | Honours the override; DB lands there | ☐ |
| 1.2.7 | `ss -tlnp \| grep 8484` | Bound to **loopback**, not `0.0.0.0` — the API is unauthenticated | ☐ |
| 1.2.8 | SIGTERM the process | Clean exit, no orphan children | ☐ |
| 1.2.9 | Run as a non-root user against a library it owns | No permission errors; nothing requires root | ☐ |
| 1.2.10 | Run it on a machine that also has the Docker stack | Two **separate** libraries (XDG vs `./data`) — confirm this is understood, not a bug report | ☐ |
| 1.2.11 | Second instance on the same port | Fails clearly rather than half-starting | ☐ |

**1.2.4 is the one with history.** STUDIO-100 shipped an unbootable installer
because CI built the frozen exe but never launched it (`No module named
'unittest'`). STUDIO-102 added `scripts/smoke_boot.py` to both CI matrix legs,
so the Linux binary is now boot-smoked automatically — but the smoke only polls
`/api/health`. A feature whose imports are lazy (the painting/colour-match path
pulls in skimage/scipy/numpy) can still be broken in a binary that boots fine.
Exercise it in the UI.

**1.2.10 is a support trap more than a defect.** Someone running both the
container and the binary on one machine gets two independent databases and will
report "my library disappeared."

### 1.3 Reverse proxy and TRUSTED_HOSTS

The write guard rejects state-changing requests whose `Origin`/`Host` is not
localhost or listed in `TRUSTED_HOSTS`. **This is the single most likely thing
to break a real deployment**, and it fails in a confusing way: reads work, so the
app looks fine until the first edit silently 403s.

| # | Step | Expected | Pass |
|---|---|---|---|
| 1.3.1 | Serve behind a proxy on a custom hostname **without** setting `TRUSTED_HOSTS` | Reads work; **writes are blocked** | ☐ |
| 1.3.2 | Set `TRUSTED_HOSTS=<that hostname>`, recreate | Writes succeed | ☐ |
| 1.3.3 | From a second device (tablet/phone over VPN), edit a model | Save succeeds | ☐ |
| 1.3.4 | Request with a forged `Host` header not in the allowlist | Write rejected | ☐ |
| 1.3.5 | `STL_SECRET_KEY` set in `.env`, container restarted | Stored API keys survive the restart | ☐ |

```bash
# 1.3.4 — expect a rejection, not a 2xx
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  -H 'Host: evil.example.com' http://localhost/api/scan/start
```

### 1.4 Test corpora

Same three shapes as the desktop plan (small flat / medium `{creator}/{model}` /
messy), **plus these Linux-only additions to the messy corpus**, which cannot
exist on Windows:

- `Abe3D/` **and** `abe3d/` as genuinely distinct directories
- Two files in one folder differing only by case (`Head.stl` / `head.stl`)
- A filename containing a backslash, e.g. `weird\name.stl` — legal on Linux, and
  a plausible way to confuse separator handling
- A symlinked model folder, and a symlink pointing outside the scan root
- A path component with a leading dot

### 1.5 If you are testing from scratch — read this first

A clean Docker deployment is the best way to run this plan: it exercises the
cold-start path, mount configuration, and `TRUSTED_HOSTS` for real, and it is
the only honest way to test Section 2.1, because an existing database already
contains creators.

**But a fresh database is not a fresh copy of your Windows instance.** Scan
behaviour is driven by settings stored in the database, not by code alone —
notably `scan_parts_names` and `scan_tag_rules`. A new deployment starts with
defaults, so it can legitimately index a *different number of models* from the
same files.

This has already burned one investigation: a Docker instance showed an 83-model
gap against Windows and looked like a scanner defect. It was a reset database
that had lost its scan settings. Five code hypotheses were measured before the
cause turned out to be configuration drift.

So, if you compare a from-scratch Linux instance against a Windows one:

| # | Step | Pass |
|---|---|---|
| 1.5.1 | Before comparing anything, diff `app_settings` between the two instances | ☐ |
| 1.5.2 | Confirm `scan_parts_names` and `scan_tag_rules` match | ☐ |
| 1.5.3 | Only then treat a count difference as a possible defect | ☐ |

```sql
-- Run on BOTH instances and diff the output.
SELECT key, value FROM app_settings ORDER BY key;
```

A count mismatch with differing settings is not a finding. A count mismatch with
identical settings is worth reporting, and worth reporting precisely — include
both settings dumps.

---

## 2. Priority — behaviour that only changes on Linux

### 2.1 Creator case collapse — STUDIO-298 / 226

Use the messy corpus with both `Abe3D/` and `abe3d/` present and **models in
each**.

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.1.1 | Full scan | **One** creator, not two | ☐ |
| 2.1.2 | Open it | Models from **both** directories are listed | ☐ |
| 2.1.3 | Scan again | Count unchanged; no duplicate creator appears | ☐ |
| 2.1.4 | **Targeted rescan of that creator** | **No models disappear** | ☐ |
| 2.1.5 | Container/app logs | A warning naming the case-variant adoption | ☐ |
| 2.1.6 | Add a *third* spelling (`ABE3D/`) with a model, rescan | Still one creator; new model indexed | ☐ |
| 2.1.7 | Rename `abe3d/` → `abe3d-renamed/`, rescan | Models repath; nothing pruned from the surviving folder | ☐ |

```sql
-- Expect zero rows
SELECT LOWER(name) AS k, COUNT(*), GROUP_CONCAT(name,' | ')
FROM creators GROUP BY k HAVING COUNT(*) > 1;
```

**2.1.4 is the most dangerous step in this document.** A targeted rescan clears
the creator's STL rows and prunes anything the re-walk does not rediscover. It is
safe only because directories are resolved from indexed model paths rather than
from the creator name. On Linux, one creator now legitimately maps to *two*
directories — this step is the practical proof that both get walked. **If models
vanish, stop testing and report it as data loss.**

**Snapshot before you start**, and diff rather than comparing counts:

```bash
sqlite3 data/stl_inventory.db \
  "SELECT id,name,folder_path FROM models ORDER BY id;" > before.txt
# …run the rescan…
sqlite3 data/stl_inventory.db \
  "SELECT id,name,folder_path FROM models ORDER BY id;" > after.txt
diff before.txt after.txt
```

### 2.2 Path separators stayed a no-op — STUDIO-366

On Linux `_canon`'s output already equals the native form, so this change should
be invisible. The test is that it *is*.

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.2.1 | Reorganize preview + apply on a copy of the medium corpus | Paths unchanged in style — forward slashes throughout | ☐ |
| 2.2.2 | SQL below | **Zero** rows containing a backslash | ☐ |
| 2.2.3 | Rescan after reorganize | No duplicate models or STL rows | ☐ |
| 2.2.4 | Undo the reorganize | Files and DB both return to the original state | ☐ |
| 2.2.5 | Reorganize a model whose **filename contains a backslash** | Not mangled into a directory separator | ☐ |

```sql
-- On Linux a backslash in a stored path is data, never a separator.
SELECT COUNT(*) FROM models    WHERE folder_path LIKE '%\%' ESCAPE '\';
SELECT COUNT(*) FROM stl_files WHERE path        LIKE '%\%' ESCAPE '\';
```

**2.2.5 is the interesting one.** `_native_store` runs `str(PurePosixPath(p))` on
POSIX, which leaves backslashes alone — but it is worth confirming against a real
file rather than trusting the reasoning.

### 2.3 Image download hardening — STUDIO-320

Applies identically to Linux; the SSRF guard matters more here because the
container can reach other services on the Docker network.

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.3.1 | Import → fetch a storefront URL | Metadata and gallery images fetched | ☐ |
| 2.3.2 | Thumbnail from a valid image URL | Downloads and applies | ☐ |
| 2.3.3 | Thumbnail from an HTML page URL | Clean error, nothing stored | ☐ |
| 2.3.4 | Thumbnail from `http://backend:8000/api/health` (the sibling container) | **Rejected** — private address | ☐ |
| 2.3.5 | Thumbnail from `http://169.254.169.254/…` | **Rejected** | ☐ |
| 2.3.6 | Inspect the pack folder after imports | No `gallery_*.jpg` that is not a real image | ☐ |

**2.3.4 is Linux/Docker-specific and worth doing deliberately.** On the desktop
the only private target is loopback; inside Compose, service names resolve to
other containers, so an unguarded fetch could reach them. Confirm the guard
covers that.

---

## 3. Linux-specific platform behaviour

### 3.1 Case-sensitive filesystem

| # | Check | Pass |
|---|---|---|
| 3.1.1 | Two files differing only by case in one folder both index | ☐ |
| 3.1.2 | Renaming a model folder's case only → no duplicate model row | ☐ |
| 3.1.3 | Search and filters are case-insensitive in the UI regardless | ☐ |

### 3.2 Mounts and permissions

| # | Check | Pass |
|---|---|---|
| 3.2.1 | Scan with a bind mount present, then **unmount it and rescan** — models are **NOT** pruned | ☐ |
| 3.2.2 | Remount and rescan — models restored/intact | ☐ |
| 3.2.3 | Read-only mount — scan degrades gracefully, no crash | ☐ |
| 3.2.4 | Files written by the container (thumbnails, gallery images) have sane ownership on the host | ☐ |
| 3.2.5 | A symlinked model folder indexes; a symlink escaping the scan root does not | ☐ |
| 3.2.6 | Non-ASCII filenames round-trip correctly | ☐ |

**3.2.1 has caused real data loss before** (mount-detach incident; the
availability prune gate exists because of it). It is the highest-value regression
test on Linux because bind mounts detach far more casually than a Windows drive
letter does.

**3.2.4 matters for the demo path:** if the container writes as root, host-side
cleanup and backups become awkward.

### 3.3 Database on the mount

| # | Check | Pass |
|---|---|---|
| 3.3.1 | `./data` on a local filesystem — normal operation | ☐ |
| 3.3.2 | If anyone puts `./data` on NFS/SMB, note it | SQLite WAL over a network filesystem is not safe; expect corruption | ☐ |
| 3.3.3 | Backup/restore round-trip inside the container | ☐ |

### 3.4 Multi-client access

The Gen Con deployment is a tablet over VPN, so this is the real usage pattern,
not a hypothetical.

| # | Check | Pass |
|---|---|---|
| 3.4.1 | Two browsers open simultaneously; edit in one | Other reflects the change on refresh | ☐ |
| 3.4.2 | Start a scan from one client | Other sees progress; second scan attempt is rejected (write lock) | ☐ |
| 3.4.3 | Tablet/mobile viewport | Layout usable | ☐ |
| 3.4.4 | Long-running scan with a client disconnected mid-run | Scan completes server-side | ☐ |

### 3.5 Response headers — measure the known gap

```bash
curl -sI http://localhost/ | grep -iE 'content-security|x-frame|x-content-type|strict-transport'
```

| # | Check | Expected today | Pass |
|---|---|---|---|
| 3.5.1 | Headers on the SPA response | **None present** — records the gap | ☐ |
| 3.5.2 | Headers on an `/api` response | **None present** | ☐ |

Record the actual output. This is evidence for the follow-up ticket, not a
beta.8 defect.

---

## 4. Core regression

Same coverage as the desktop plan §3, minus anything Electron-owned:

| # | Check | Pass |
|---|---|---|
| 4.1 | Full scan: completes, idempotent on re-run, cancellable | ☐ |
| 4.2 | Browse: search, filters, sort | ☐ |
| 4.3 | Edit: rename, creator, tags, notes — persist across restart | ☐ |
| 4.4 | Variant grouping: manual merge and split | ☐ |
| 4.5 | Thumbnails, gallery images, 3D viewer | ☐ |
| 4.6 | Backup and restore, including a large backup | ☐ |
| 4.7 | Import: preview → apply → inbox clears | ☐ |
| 4.8 | Painting guides render | ☐ |
| 4.9 | Settings persist across container recreate | ☐ |

**Not applicable on Linux:** auto-update (`latest.yml` is for the Windows
Electron updater), SmartScreen, installer/uninstaller, window state, sidecar
crash recovery, single-instance lock.

---

## 5. Known issues — do not re-file

| Issue | Status |
|---|---|
| No CSP or security headers on the browser-served path | Pre-existing, **not** a beta.8 regression. STUDIO-258 covered Electron only. Tracked as **STUDIO-370**; §3.5 records the before state. |
| Pre-beta.8 reorganized rows may hold non-native paths | STUDIO-368. On Linux the canonical form already *is* native, so this is largely a Windows concern. |
| No Electron desktop build for Linux | Deferred past v1.0. |
| Unsigned artifacts | STUDIO-99 deferred. |

---

## 6. Exit criteria

Linux is a supported deployment target, so it gates promotion alongside Windows:

1. Sections 0–2 pass in full. §2.1.4 in particular must be clean — it is the data-loss path.
2. §3.2.1 (mount detach) passes. No exceptions; this has destroyed a library before.
3. §1.3 passes on a deployment resembling the real one, including from a second device.
4. No schema or installer change has landed since the tag.
5. Findings recorded with the build tag `beta.8` and the deployment path (Compose vs standalone).

## 7. Recording findings

Capture the same detail as the desktop plan, plus:

- **Which path** — Docker Compose or standalone binary
- **Host distro and kernel**, and Docker version
- **Whether the library is on a bind mount, and its filesystem type** (`df -T`)
- `docker compose logs backend --tail=200` for backend issues
- Whether it reproduces with the library on a plain local ext4 path — this
  separates real defects from mount-specific behaviour
- For any count comparison against another instance: **both** `app_settings`
  dumps (see §1.5). Without them the comparison is not interpretable.
