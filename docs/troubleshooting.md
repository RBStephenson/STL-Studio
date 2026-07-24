# Troubleshooting & FAQ

- [Windows blocked the installer (SmartScreen)](#windows-blocked-the-installer-smartscreen)
- [The app does nothing for a while after an update](#the-app-does-nothing-for-a-while-after-an-update)
- [I added models to a creator but they don't show up](#i-added-models-to-a-creator-but-they-dont-show-up)
- [A model has the wrong thumbnail](#a-model-has-the-wrong-thumbnail)
- [A model has no thumbnail at all](#a-model-has-no-thumbnail-at-all)
- [Images in a hidden folder aren't picked up](#images-in-a-hidden-folder-arent-picked-up)
- [When should I rescan vs. run a full scan?](#when-should-i-rescan-vs-run-a-full-scan)
- [A whole creator is missing or shows only one model](#a-whole-creator-is-missing-or-shows-only-one-model)
- [Models are flagged "needs review"](#models-are-flagged-needs-review)
- [The scan seems stuck or slow](#the-scan-seems-stuck-or-slow)
- [Scale or type tags are wrong/missing](#scale-or-type-tags-are-wrongmissing)
- [NSFW images are showing / blurred](#nsfw-images-are-showing--blurred)
- [Where is my data stored? Is it safe?](#where-is-my-data-stored-is-it-safe)
- [How do I back up or move my library?](#how-do-i-back-up-or-move-my-library)
- [A collection shows 0 models after I added some](#a-collection-shows-0-models-after-i-added-some)
- [Application crashes and recovery](#application-crashes-and-recovery)
- ["The STL Studio backend stopped unexpectedly"](#the-stl-studio-backend-stopped-unexpectedly)
- [Accessing support logs](#accessing-support-logs)

---

## Windows blocked the installer (SmartScreen)

**This is expected.** STL Studio is not code-signed yet, so Windows has no
publisher identity to check the installer against. It is not a malware
detection, and it happens on every current release.

**"Windows protected your PC" (blue dialog):** click **More info**, then
**Run anyway**.

**No "More info" link, or the button only says "Don't run":** Windows is
treating the file as blocked rather than merely unrecognized. Clear the
mark-of-the-web that your browser attached when it downloaded the file:

1. Right-click `STL-Studio-Setup-<version>.exe` → **Properties**.
2. On the **General** tab, tick **Unblock** at the bottom.
3. **Apply**, then run the installer again.

**Your browser refused to finish the download**, or removed the file after it
completed: this is browser-level reputation filtering, separate from
SmartScreen. In Chrome or Edge, open the downloads list and choose **Keep** on
the blocked entry. Corporate-managed machines may block unsigned installers by
policy — in that case the download cannot be recovered locally and needs your IT
administrator.

**Microsoft Defender quarantined the file:** that is a different message
("Threat found" / "Virus detected"), not SmartScreen. STL Studio's installer
should not trigger it. Before overriding anything, verify the download is
genuine using the checksum and build attestation steps in
[Verifying your download](getting-started.md#verifying-your-download). If
verification passes and Defender still objects, please
[open an issue](https://github.com/RBStephenson/STL-Studio/issues) — a false
positive on a released binary is worth knowing about.

Signed installers are planned but are not part of the current release scope
(see [Release scope](support-policy.md#release-scope)). Until then, the
verification steps above are the reliable way to confirm you have the real file.

## The app does nothing for a while after an update

**This is expected, and it's only a first-launch cost.** After the installer
runs (auto-update or manual), antivirus software scans the newly-installed
files the first time you launch that version — STL Studio itself does not
control when this happens or how long it takes. On some machines this can look
like the window never appears, or appears but stays blank for up to a minute.

This is a one-time cost per version, not per launch: your antivirus caches its
verdict on the installed files, so subsequent launches of the same version
start normally. If it happens on every launch, that points to something else —
see [Application crashes and recovery](#application-crashes-and-recovery).

If this is disruptive, add an exclusion for STL Studio's install directory
(default `%LOCALAPPDATA%\Programs\STL Studio`) in your antivirus settings so
the scan happens once, in the background, rather than blocking the first
launch.

## I added models to a creator but they don't show up

Run a **Rescan** on that creator from the
[Creators page](features.md#creators--per-creator-rescan). A new scan is needed
for the app to see folders added since the last one. The per-creator rescan is
the quickest way — it re-reads just that creator's folder.

If the creator is **brand new** and isn't listed on the Creators page yet, run a
**full Scan Library** — that's what first discovers the folder and creates the
creator entry. Once a creator appears in your list (even showing **0 models**), a
per-creator **Rescan** can index it: the rescan now resolves the folder by the
creator's name when it has no models yet, so it bootstraps cleanly.

## A model has the wrong thumbnail

Open the model, click **Change image** on the preview, and pick the correct
image in the **From Folder** tab — or paste a **From URL** link. This commonly
happens when a thumbnail came from a web-enrichment scrape that matched the wrong
listing.

## A model has no thumbnail at all

The scanner looks for images inside (and just above) the model's folder. If
there genuinely aren't any images there, it can't show one. Options:

- Use **Change image → From URL** to point at an online image.
- Add an image file to the model's folder and rescan that creator.

## Images in a hidden folder aren't picked up

This is intentional. The scanner skips any dot-prefixed directory — hidden
folders like `.git`, or similar caches other tools leave behind, are never
treated as gallery images, STLs, or models of their own. If a model's folder
already has stale entries from before this behavior existed, rescan that
creator to drop them.

## When should I rescan vs. run a full scan?

| Situation | Do this |
|-----------|---------|
| Added/updated models for **one creator** | **Rescan** that creator |
| A creator is **listed but shows 0 models** | **Rescan** that creator (now bootstraps by name) |
| Added a creator **not yet listed** anywhere | **Full** Scan Library |
| Added models across **many creators** | **Full** Scan Library |
| Want to refresh tags after an app update | Either — both refresh metadata |

## A whole creator is missing or shows only one model

First, make sure the creator's folder is **directly under one of your scan
roots** (see [folder structure](scanning-and-folders.md#the-folder-layout-it-expects)).
Check your scan roots in **Settings**, then run a full scan.

If a creator that previously worked suddenly shows only a single model, run a
full Scan Library — older versions of the app could mis-handle creators whose
**name** contained a type word (like "Figures" or "Miniatures"); current versions
fix this, and a rescan corrects the data.

## Models are flagged "needs review"

That's the scanner saying "I wasn't sure this folder is a real model." Work
through them in the [Triage queue](features.md#triage-queue) — dismiss the ones
that are fine, skip the ones you're unsure about. The flag clears automatically
for models that have STL files once they're confirmed.

## The scan seems stuck or slow

- The **first** full scan of a large library takes a while — models appear as
  they're found, so progress is visible.
- Scanning across a slow **external/USB drive or NAS** is limited by that drive's
  speed, not the app.
- You can **Cancel** a scan at any time; already-indexed models are kept.
- For routine updates, prefer a **per-creator rescan** over a full scan.

## Scale or type tags are wrong/missing

Auto-tags come from folder and file names. If a model's scale isn't tagged,
check that the scale appears in the folder name in a recognizable form
(`1:6`, `1_6`, `1-6`, `1_6scale`, `75mm`, etc.). After confirming, run a rescan
of that creator — tag detection re-runs on every scan. You can also add or remove
tags yourself on the model (your tags are kept separate from auto-tags).

## NSFW images are showing / blurred

Use the **NSFW On/Off** toggle in the top-right of the nav. When **off**, models
flagged NSFW are blurred. To change a specific model's flag, use the **NSFW**
button on its card or detail header. You can also filter the Library by NSFW
status.

## Where is my data stored? Is it safe?

The catalog database and model files stay on your machine. Optional AI and
storefront integrations make network requests only when you configure and use
them. The catalog database lives in your user data folder (see
[Getting Started](getting-started.md#standalone-recommended)) and survives app
updates. The app reads your STL folders; in Docker mode they're mounted
**read-only**, so your original files are never modified.

A scan or rescan only removes a model's gallery images, thumbnail, or the
model itself when it can positively confirm the corresponding files are
gone — a transient failure to read a folder (an external/network drive
blipping mid-scan, a permission hiccup) is never treated as "these files no
longer exist." Affected entries are simply left untouched until a later
rescan can confirm one way or the other.

For an extra safety net, use **Settings → Data Management → Download Backup** to
save a snapshot of the catalog (see below).

## How do I back up or move my library?

Open **Settings → Data Management**:

- **Download Backup** saves your whole catalog — tags, favorites, and print
  queue — as a single timestamped `.db` file. Do this before any risky
  change, or just periodically.
- **Restore from Backup…** loads one of those files back in (after validating
  it), replacing your current catalog. This is also how you move your library to
  another machine: back up on the old one, install the app on the new one, then
  restore.

Both actions only affect the index — they never touch your STL files on disk.
Restore can't run while a scan is in progress, and it asks you to type a
confirmation phrase since it overwrites your current catalog.

Your **collections** (names, memberships, and renames) are part of the index and
are included in every backup automatically.

## A collection shows 0 models after I added some

The model count on the Collections page is refreshed when the page loads. If you
added models from a detail page and then navigated back, click away and return to
the Collections page to see the updated counts. The counts are always accurate
when you open a collection's detail view.

# Application crashes and recovery

If a page fails while STL Studio is running, the application shows a recovery screen. Use
**Try again** first; if the same error returns, choose **Reload STL Studio**. Saved catalog data is
stored by the backend and is not removed by either action, but edits that had not yet been saved may
need to be entered again.

The installed desktop app also detects an unexpected renderer-process exit and offers to reload the
window or quit. An internal Electron main-process error is shown in an error dialog instead of being
silently ignored. After reopening the app, use **Help → About & support → Copy diagnostics** when
reporting a repeatable failure.

## "The STL Studio backend stopped unexpectedly"

The desktop app runs its backend as a separate process. If that process stops on its own after the
app has started — an out-of-memory condition during a very large scan, an antivirus quarantine, or a
crash — the app now notices and offers **Restart backend** or **Quit**.

**Your saved catalog data is unchanged.** The database is written as work completes, so models
already scanned stay scanned. Anything you had typed but not yet saved may need re-entering, and a
scan or import that was mid-run stops where it was; start it again after the restart.

Choosing **Restart backend** shows the loading screen while a fresh backend starts, then returns you
to the app. If the backend stops several times in quick succession the app stops offering to restart
it and shows the recovery page instead, rather than looping the same prompt — at that point close and
reopen STL Studio.

If this happens repeatedly, enable **Persistent support logs** under **Settings → Preferences**,
reproduce it, then attach the logs to an issue (see
[Accessing support logs](#accessing-support-logs)). The backend's own output is captured there and is
usually what identifies the cause.

## Accessing support logs

Enable **Persistent support logs** under **Settings → Preferences**, then open
**Help → About & support**. **Download logs** works in both Electron and Docker and
produces a sanitized ZIP. Electron also provides **Open logs folder**.

Docker stores the same backend files under `/data/logs`; with the standard Compose
file that is the host's `./data/logs` directory. For a live terminal stream, use
`docker compose logs backend`. Each process keeps a 2 MiB active log and three
rotated backups. Disabling the feature stops new persistent writes but does not
delete existing diagnostic files.

### When the app won't start at all

The Settings toggle above needs a working window to reach — no help if STL
Studio never gets that far (see
[the app does nothing for a while after an update](#the-app-does-nothing-for-a-while-after-an-update)
for the common cause). Two ways around that, both effective before any window
exists:

**Environment variable.** Set `STL_STUDIO_DIAGNOSTICS=1` before launching STL
Studio and it logs from the very first startup checkpoint, with no Settings
step required:

```powershell
$env:STL_STUDIO_DIAGNOSTICS = "1"
& "$env:LOCALAPPDATA\Programs\STL Studio\STL Studio.exe"
```

**Marker file.** The Settings toggle just writes an empty file named
`persistent-diagnostics.enabled` in the app's userData folder — creating it by
hand has the same effect on the next launch. The folder name has changed
across versions, so check both:

- `%APPDATA%\STL Studio\`
- `%APPDATA%\stl-studio-desktop\`

Whichever one exists on your machine is the right one; `desktop.log` and its
rotated backups (`desktop.log.1`–`.3`) land in a `logs` subfolder there once
diagnostics are on.
