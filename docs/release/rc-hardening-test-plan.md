# Release-candidate hardening test plan

A manual hardening pass for a release candidate, run alongside the
[clean-machine acceptance](clean-machine-acceptance.md) and the
[release qualification checklist](../release-checklist.md). Those cover install
mechanics and supply chain; this one covers **application behaviour**, weighted
toward whatever changed since the previous build.

**Scope: the Windows Electron desktop build.** Linux deployments (Docker
Compose and the standalone binary) have their own plan —
[rc-hardening-test-plan-linux.md](rc-hardening-test-plan-linux.md) — because the
surface differs enough that sharing one document would mislead: there is no
Electron shell, so the CSP and external-navigation work does not apply, while
case-sensitivity matters far more.

Sections 0, 1, and 3–7 are reusable for any candidate. **Section 2 is rewritten
for each build** — it exists to exercise the specific changes that have not yet
run in a packaged app, and is worthless if copied forward unchanged.

---

## Current cycle

**Build under test:** `v1.0.0-beta.8` (commit `bf3297b`)
**Predecessor:** `v1.0.0-beta.7` (`611e66c`)
**Delta:** exactly six blocker fixes — STUDIO-258, 259, 298, 366, 320, and 226
(closed by decision). Nothing else.

This is the intended **release candidate** for STUDIO-215's soak, and the
"exit criteria written down before the run" artifact STUDIO-214 requires.

> Every change in this cycle's Section 2 was verified at unit and module level
> only. No packaged app was launched during development, because no local
> sidecar build exists — so this plan is the first genuine end-to-end exercise
> of all of it.

---

## How to use this

Sections are ordered by risk, not by user journey. **Section 2 is the priority** — it covers behaviour that has never run in a packaged app. Sections 3–4 are regression cover; Section 5 is what is knowingly still broken, so you do not waste time filing it.

Record every finding with the build tag (`beta.8`). Findings from earlier betas age out fast — the cadence has been roughly one build per day.

### Before you start: two safety rules

1. **Do not run destructive tests against your real library.** Reorganize moves files on disk. Use a constructed corpus (Section 1.3) or a copy. Undo exists and is covered by tests, but "covered by tests" is not "guaranteed against an irreplaceable collection."
2. **Never cold-copy the database while the app is running.** It is SQLite in WAL mode; copying only the `.db` without `-wal`/`-shm` produces a silently stale snapshot. Quit the app first, or copy all three files together.

```powershell
# Safe DB snapshot — app must be CLOSED
$src = "$env:LOCALAPPDATA\STL-Inventory"
$dst = "$env:USERPROFILE\Desktop\stl-db-backup-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory $dst | Out-Null
Copy-Item "$src\stl_inventory.db*" $dst
```

---

## 0. Artifact integrity (5 min, before installing)

The app is unsigned, so provenance is the only "is this genuine" answer available.

```bash
gh release view v1.0.0-beta.8 --json tagName,isPrerelease,isDraft \
  -q '"tag=\(.tagName) prerelease=\(.isPrerelease) draft=\(.isDraft)"'

# Must still be the stable bridge, NOT beta.8:
gh api repos/RBStephenson/STL-Studio/releases/latest -q '.tag_name'

# Build provenance (expect a non-zero attestation count)
gh attestation verify STL-Studio-Setup-1.0.0-beta.8.exe --repo RBStephenson/STL-Studio
```

```powershell
# Checksum matches the published manifest
(Get-FileHash .\STL-Studio-Setup-1.0.0-beta.8.exe -Algorithm SHA256).Hash.ToLower()
# compare against the Setup line in SHA256SUMS
```

| # | Check | Pass |
|---|---|---|
| 0.1 | beta.8 marked **Pre-release**, not draft | ☐ |
| 0.2 | `releases/latest` still returns **v0.20.7** | ☐ |
| 0.3 | `gh attestation verify` succeeds | ☐ |
| 0.4 | Installer SHA256 matches `SHA256SUMS` | ☐ |

**Why 0.2 matters:** the softprops action re-asserts release metadata and has previously flipped a beta to "Latest" (STUDIO-285). It is a silent failure — nothing errors, users just get offered a beta as the stable download.

---

## 1. Install and first boot

### 1.1 Clean install

| # | Step | Expected | Pass |
|---|---|---|---|
| 1.1.1 | Run installer on a machine with no prior install | SmartScreen warning appears; "More info → Run anyway" proceeds | ☐ |
| 1.1.2 | Launch from Start menu | Splash appears immediately, no white flash, no hang | ☐ |
| 1.1.3 | Wait for backend | App UI replaces splash within ~60s cold | ☐ |
| 1.1.4 | Check Task Manager | Exactly one `stl-studio.exe` sidecar | ☐ |
| 1.1.5 | Quit via File → Exit | Both Electron and sidecar processes gone within ~10s | ☐ |
| 1.1.6 | Relaunch, then launch a second instance | Second launch focuses the existing window, no second sidecar | ☐ |

### 1.2 Upgrade-in-place (the path real users take)

| # | Step | Expected | Pass |
|---|---|---|---|
| 1.2.1 | Install beta.7 first, add a few models, then install beta.8 over it | Library intact, no re-scan required, settings preserved | ☐ |
| 1.2.2 | Check Alembic ran | No migration errors in diagnostics log | ☐ |

### 1.3 Constructed test corpora

STUDIO-214 asks for at least three library shapes. Build these once and keep them:

| Shape | Contents | What it stresses |
|---|---|---|
| **A — small flat** | ~20 models, no creator folders, STLs directly under root | flat-layout scan path |
| **B — medium `{creator}/{model}`** | ~200 models across ~15 creators | the normal path |
| **C — messy** | nested packs, mixed separators in names, **case-variant creator folders** (`Abe3D/` and `abe3d/`), non-ASCII names (`Ångström`, `日本語`), a very deep path (>200 chars), a folder with a trailing space | this session's fixes + edge cases |

Corpus C is where beta.8's changes actually get exercised. Build it deliberately.

---

## 2. New in this build — priority testing

> Everything in this section was verified at unit/module level only. **No packaged app was ever launched during development** (no local sidecar build exists), so this is the first genuine end-to-end exercise of all of it.

### 2.1 Content-Security-Policy — STUDIO-258

The app window now gets a CSP enforced at the Electron session layer. Previously it had **none at all**. The failure mode is a silently broken UI: CSP violations only appear in the console.

**Enable DevTools:** View menu → Toggle DevTools (or Ctrl+Shift+I).

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.1.1 | Open DevTools console, then click through **every** major page: Library, Creators, Collections, Queue, Triage, Import, Paint Shelf, Tags, Settings, Help | Zero `Refused to load…` / `Content Security Policy` messages | ☐ |
| 2.1.2 | Open a model detail page with a **3D preview** | Model renders; no CSP error from three.js | ☐ |
| 2.1.3 | Open a model with **gallery images** | Thumbnails render | ☐ |
| 2.1.4 | Import → Fetch from a storefront URL | **Remote CDN thumbnails render** in the preview (this is why `img-src` allows `https:`) | ☐ |
| 2.1.5 | Open a **painting guide** (Paint Shelf → a guide) | Formatted HTML renders, including styled blocks | ☐ |
| 2.1.6 | Trigger the offline/retry page (quit sidecar via Task Manager, then reload) | Fallback page renders and the retry link works | ☐ |
| 2.1.7 | In DevTools console, run the injection check below | `false` — inline script blocked | ☐ |

```js
// Paste in DevTools console. Expect false + a CSP violation logged.
(() => { const s=document.createElement('script');
  s.textContent='window.__X__=true'; document.head.appendChild(s);
  return window.__X__===true; })()
```

**Highest-risk item here is 2.1.5** — the guide reader uses inline `<style>` elements and sanitized HTML. If `style-src 'unsafe-inline'` were wrong, guides would render unstyled.

**If you find a violation:** capture the full console message. The directive name in it tells us exactly which line of `desktop/src/csp.ts` is too tight.

### 2.2 External navigation — STUDIO-259

`target="_blank"` links used to open a remote site **inside a chromeless Electron window** with no address bar. They now go to the system browser.

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.2.1 | Help → click **Patreon** link | Opens in **default browser**, not in-app | ☐ |
| 2.2.2 | Help → **Buy Me a Coffee** | Same | ☐ |
| 2.2.3 | Help → **PaintRack** (courageousoctopus.com) | Same | ☐ |
| 2.2.4 | Help → **Support and compatibility policy** (GitHub wiki) | Same | ☐ |
| 2.2.5 | Help → **brenttheprogrammer.com** | Same | ☐ |
| 2.2.6 | After each: check no new Electron window appeared | App still has exactly one window | ☐ |
| 2.2.7 | A model's **Source URL** → open it | Opens in system browser | ☐ |
| 2.2.8 | In-app navigation (sidebar links, model cards, back/forward, mouse side-buttons) | All still work **in-app** — not diverted to the browser | ☐ |

**2.2.8 is the regression risk.** The guard could be over-tight and start throwing internal navigation at the browser. If the app suddenly opens your browser when you click "Creators," that is this.

### 2.3 Creator case-insensitivity — STUDIO-298

Folder-derived creator names now dedup case-insensitively on every platform.

Use **corpus C** with both `Abe3D/` and `abe3d/` present.

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.3.1 | Scan corpus C | **One** creator named Abe3d, not two | ☐ |
| 2.3.2 | Open that creator | Models from **both** folders listed | ☐ |
| 2.3.3 | Scan again | Still one creator; model count unchanged | ☐ |
| 2.3.4 | Targeted rescan of that creator (creator page → Rescan) | **No models disappear** | ☐ |
| 2.3.5 | Check diagnostics log | A warning naming the case-variant adoption | ☐ |

```sql
-- Any creators differing only by case? Expect zero rows.
SELECT LOWER(name) AS k, COUNT(*), GROUP_CONCAT(name, ' | ')
FROM creators GROUP BY k HAVING COUNT(*) > 1;
```

**2.3.4 is the one that matters most.** A targeted rescan clears the creator's STL rows and prunes anything the re-walk misses. It is safe only because directories are resolved from indexed model paths rather than creator names. If models vanish here, stop and report immediately — that is data loss.

### 2.4 Path separators — STUDIO-366

Reorganize now writes host-native (backslash) paths, matching the scanner. **Windows-only behaviour** — invisible on Linux.

Run against a **copy**, never your real library.

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.4.1 | Enable reorganize in Settings, preview a reorganize on corpus B | Preview paths display normally | ☐ |
| 2.4.2 | Apply it | Files move; models still open, thumbnails still show | ☐ |
| 2.4.3 | Run the SQL below | **Zero** rows with forward slashes among newly-reorganized models | ☐ |
| 2.4.4 | Rescan after the reorganize | **No duplicate models**, no duplicate STL rows | ☐ |
| 2.4.5 | Undo the reorganize | Files return; models still resolve; thumbnails intact | ☐ |
| 2.4.6 | Re-run 2.4.3 after undo | Paths native again | ☐ |
| 2.4.7 | Reorganize a **package-mode** pack (nested models under one pack folder) | Nested models repath correctly | ☐ |
| 2.4.8 | Reorganize a model **with gallery images** | Images follow, still display | ☐ |

```sql
-- Rows still holding the old forward-slash form. See Section 5 — pre-existing
-- rows are EXPECTED here; what matters is that this count does not GROW
-- after a reorganize.
SELECT COUNT(*) AS fwd_slash_models FROM models
WHERE folder_path LIKE '%/%' AND folder_path NOT LIKE '%\%';

SELECT COUNT(*) AS fwd_slash_stls FROM stl_files
WHERE path LIKE '%/%' AND path NOT LIKE '%\%';
```

**Method note:** record the count *before* the reorganize and compare after. A non-zero baseline is expected and is STUDIO-368, not a beta.8 regression.

**2.4.5 is the highest-risk step in this whole plan.** Undo was broken mid-development by this change and repaired — the DB would have described the pre-undo layout while files had already moved back. Verify both the files *and* the DB agree.

### 2.5 Image download hardening — STUDIO-320

Downloaded images are now validated by their actual bytes, fetched through an SSRF guard, and size-capped.

| # | Step | Expected | Pass |
|---|---|---|---|
| 2.5.1 | Import → paste a Gumroad/Cults3D/MyMiniFactory product URL → Fetch | Metadata + gallery images fetched as before | ☐ |
| 2.5.2 | Import that pack | Gallery images land in the pack folder | ☐ |
| 2.5.3 | Model detail → Change image → **From URL** with a valid image link | Downloads and applies | ☐ |
| 2.5.4 | Same, but paste a link to an **HTML page** | Clean error, no crash, nothing saved | ☐ |
| 2.5.5 | Same, but a URL returning a non-image (e.g. a PDF link) | Rejected with "not a supported image" | ☐ |
| 2.5.6 | Same, but `http://127.0.0.1:8080/whatever` | Rejected — "That URL isn't allowed" | ☐ |
| 2.5.7 | Collection cover from URL | Still works | ☐ |
| 2.5.8 | Check pack folders after imports | No `gallery_*.jpg` files that are not actually images | ☐ |

**Watch for a false-positive regression at 2.5.1–2.5.3:** validation got stricter, so a CDN image that is genuinely fine but unusual could now be rejected. If a gallery image silently goes missing that used to appear, that is worth reporting — the accepted formats are PNG, JPEG, WebP, GIF.

---

## 3. Core regression pass

Run against **corpus B**, then repeat the destructive ones against **corpus C**.

### 3.1 Scan

| # | Check | Pass |
|---|---|---|
| 3.1.1 | Full scan completes; progress bar advances; no stall | ☐ |
| 3.1.2 | Model count matches expectation for the corpus | ☐ |
| 3.1.3 | Scan a second time — count unchanged (idempotent) | ☐ |
| 3.1.4 | Cancel a scan mid-run — no partial corruption, next scan clean | ☐ |
| 3.1.5 | Scan with a drive/mount unavailable — **models are NOT pruned** | ☐ |
| 3.1.6 | Non-ASCII and deep-path models indexed correctly | ☐ |

**3.1.5 has caused real data loss before** (mount-detach incident, STUDIO-79). Worth doing deliberately: disconnect the drive, scan, reconnect, confirm nothing was wiped.

### 3.2 Browse / edit

| # | Check | Pass |
|---|---|---|
| 3.2.1 | Search, filters (creator, site, support status, needs-review), sort | ☐ |
| 3.2.2 | Model detail: rename, edit creator, tags, notes — persist across restart | ☐ |
| 3.2.3 | Bulk edit / bulk apply does not clobber unrelated fields | ☐ |
| 3.2.4 | Variant grouping: manual merge and split | ☐ |
| 3.2.5 | Thumbnails and gallery images display; clear image works | ☐ |
| 3.2.6 | 3D viewer loads an STL | ☐ |

### 3.3 Backup / restore

| # | Check | Pass |
|---|---|---|
| 3.3.1 | Create a backup | ☐ |
| 3.3.2 | Restore it into a clean profile — library matches | ☐ |
| 3.3.3 | Restore a **large** backup (no 413 / timeout) | ☐ |

### 3.4 Restart / recovery

| # | Check | Pass |
|---|---|---|
| 3.4.1 | Kill the sidecar in Task Manager while the app is open | Recovery dialog offers restart; restarting works | ☐ |
| 3.4.2 | Kill it repeatedly (4+ times quickly) | Crash-loop guard stops offering; falls back to recovery page | ☐ |
| 3.4.3 | Close during an active scan | Clean shutdown, no orphan sidecar | ☐ |
| 3.4.4 | Window position/size restored after restart | ☐ |
| 3.4.5 | Enable diagnostics (Settings), reproduce something, open the log folder | Log contains the session | ☐ |

### 3.5 Auto-update

| # | Check | Pass |
|---|---|---|
| 3.5.1 | Help/menu → Check for Updates on beta.8 | Reports up to date (beta.8 is newest prerelease) | ☐ |
| 3.5.2 | `latest.yml` present in the release assets | ☐ |

---

## 4. Data-integrity sweep

Run **after** the destructive sections. App closed, then:

```powershell
$db = "$env:LOCALAPPDATA\STL-Inventory\stl_inventory.db"
sqlite3 $db  # or use a GUI
```

```sql
-- 1. Duplicate creators differing only by case (expect 0 — STUDIO-298)
SELECT LOWER(name), COUNT(*) FROM creators GROUP BY 1 HAVING COUNT(*) > 1;

-- 2. Duplicate model rows for the same folder ignoring separator+case
--    (expect 0 new ones — STUDIO-365/366)
SELECT LOWER(REPLACE(folder_path,'\','/')) AS k, COUNT(*)
FROM models GROUP BY k HAVING COUNT(*) > 1;

-- 3. Models with no STL rows (phantoms)
SELECT COUNT(*) FROM models m
WHERE NOT EXISTS (SELECT 1 FROM stl_files s WHERE s.model_id = m.id);

-- 4. Orphaned STL rows
SELECT COUNT(*) FROM stl_files s
WHERE NOT EXISTS (SELECT 1 FROM models m WHERE m.id = s.model_id);

-- 5. Creators with zero models (should be pruned)
SELECT COUNT(*) FROM creators c
WHERE NOT EXISTS (SELECT 1 FROM models m WHERE m.creator_id = c.id);

-- 6. Separator mix (see Section 5 — baseline, not necessarily a bug)
SELECT
  SUM(CASE WHEN folder_path LIKE '%\%' THEN 1 ELSE 0 END) AS native,
  SUM(CASE WHEN folder_path LIKE '%/%' AND folder_path NOT LIKE '%\%' THEN 1 ELSE 0 END) AS forward
FROM models;
```

### Name-diff method for rescans

Counts hide silent no-ops and one-off regressions. When testing anything that renames or re-derives model names, **snapshot names before and diff after** rather than comparing counts:

```sql
-- before
.mode csv
.output before.csv
SELECT id, name, folder_path FROM models ORDER BY id;
.output stdout
-- …run the scan…
-- after: same to after.csv, then diff the two files
```

---

## 5. Known issues — do not re-file

| Issue | Status |
|---|---|
| Models reorganized **before** beta.8 still hold forward-slash paths; exact-match lookups miss them | Expected. **STUDIO-368**, deliberately out of scope for 366. A non-zero baseline in the Section 2.4 query is this, not a regression. |
| App is unsigned; SmartScreen warns on install | Expected. STUDIO-99 deferred; documented in README/getting-started/troubleshooting. |
| macOS/Linux desktop builds | Not shipped for v1.0. |
| `_creator_dirs_by_name` case policy is undocumented in code | **STUDIO-369**, cosmetic/tech-debt, no user impact. |

---

## 6. Exit criteria for the soak (STUDIO-215)

Promote beta.8 to v1.0.0 only when **all** of these hold:

1. Sections 0, 1, and 2 pass in full. Section 2 has **no** open findings — these are the unproven changes.
2. Section 3 has no P1/P2 findings. Cosmetic issues may be deferred with a linked ticket.
3. Section 4 queries 1–4 return zero.
4. **No schema or installer change has landed since the tag.** Any such change resets the clock and requires a new RC.
5. The soak has run its defined duration with normal daily use (scan, browse, edit, reorganize, backup, restart) — duration written down before starting, per 215's own criteria.
6. STUDIO-216 release notes are drafted and match the promoted artifact.

**The cadence is the real obstacle.** Five commits landed between beta.7 and beta.8, voiding all prior soak time. If betas keep being cut daily, the soak never accrues and v1.0 never ships. Freeze `main` for the soak window, or accept that the clock restarts each time.

---

## 7. Recording findings

For each issue, capture:

- **Build tag** — `beta.8` (non-negotiable; findings age out within a day or two)
- Exact steps, and which corpus (A/B/C)
- Expected vs actual
- DevTools console output for anything UI-related — **the CSP directive name is the diagnostic**
- Diagnostics log excerpt for anything backend-related
- Whether it reproduces on a clean profile

File release-blocking findings as linked Jira tickets against STUDIO-214. Anything that touches models disappearing, paths, or undo should be treated as P1 until proven otherwise.
