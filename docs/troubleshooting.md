# Troubleshooting & FAQ

- [I added models to a creator but they don't show up](#i-added-models-to-a-creator-but-they-dont-show-up)
- [A model has the wrong thumbnail](#a-model-has-the-wrong-thumbnail)
- [A model has no thumbnail at all](#a-model-has-no-thumbnail-at-all)
- [When should I rescan vs. run a full scan?](#when-should-i-rescan-vs-run-a-full-scan)
- [A whole creator is missing or shows only one model](#a-whole-creator-is-missing-or-shows-only-one-model)
- [Models are flagged "needs review"](#models-are-flagged-needs-review)
- [The scan seems stuck or slow](#the-scan-seems-stuck-or-slow)
- [Scale or type tags are wrong/missing](#scale-or-type-tags-are-wrongmissing)
- [NSFW images are showing / blurred](#nsfw-images-are-showing--blurred)
- [macOS won't open the app](#macos-wont-open-the-app)
- [Where is my data stored? Is it safe?](#where-is-my-data-stored-is-it-safe)
- [How do I back up or move my library?](#how-do-i-back-up-or-move-my-library)
- [A collection shows 0 models after I added some](#a-collection-shows-0-models-after-i-added-some)

---

## I added models to a creator but they don't show up

Run a **Rescan** on that creator from the
[Creators page](features.md#creators--per-creator-rescan). A new scan is needed
for the app to see folders added since the last one. The per-creator rescan is
the quickest way — it re-reads just that creator's folder.

If the creator is brand new (didn't exist before), use a **full Scan Library**
instead — per-creator rescan only works for creators already in the library.

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

## When should I rescan vs. run a full scan?

| Situation | Do this |
|-----------|---------|
| Added/updated models for **one creator** | **Rescan** that creator |
| Added a **brand-new creator** | **Full** Scan Library |
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

## macOS won't open the app

The standalone macOS binary isn't notarized yet, so Gatekeeper blocks it on first
launch. **Right-click the file → Open → Open.** You only need to do this once.

## Where is my data stored? Is it safe?

Everything runs locally and your library never leaves your machine. The catalog
database lives in your user data folder (see
[Getting Started](getting-started.md#standalone-recommended)) and survives app
updates. The app reads your STL folders; in Docker mode they're mounted
**read-only**, so your original files are never modified.

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
