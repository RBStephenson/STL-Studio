# STL Studio — Documentation

<!-- wiki-only:strip -->
> ✏️ **This folder is the single source of truth for the user docs.** The
> [STL Studio Wiki](https://github.com/RBStephenson/STL-Inventory/wiki) is
> **generated** from these files by `scripts/wiki/build_wiki.py` on every merge
> to `main` — so edit Markdown here (via a PR), never on the wiki directly.
> These same files also back the in-app **Help** page.
<!-- /wiki-only -->

A locally-hosted web app for cataloguing, browsing, and managing a large STL
model library — search, filter, tag, preview in 3D, and plan your prints.

## Contents

| Guide | What's inside |
|-------|---------------|
| [Getting Started](getting-started.md) | Download, run, point it at your drives, and run your first scan |
| [Docker — Drive Mounts](docker.md) | Configuring drive mounts in Docker mode — adding/changing drives, container vs. host paths, read-only mounts |
| [Feature Guide](features.md) | Every screen and what it does — Library, Triage, favorites, print queue, collections, image picker, Kit Builder, enrichment, bulk enrich, import folder, reorganize, Paint Shelf & PaintRack CSV, AI & Integrations, backup & restore |
| [Scanning & Folder Structure](scanning-and-folders.md) | How the scanner finds your models, the folder layout it expects, and automatic tagging |
| [Troubleshooting & FAQ](troubleshooting.md) | Models not showing up, wrong thumbnails, rescan vs. full scan, and other common questions |
| [Adverse Failure Qualification](release/adverse-failure-qualification.md) | Repeatable release checks for interrupted updates, storage failures, locked databases, missing drives, and invalid settings |

## What it does, in one paragraph

Point STL Studio at the folder(s) where your STL files live (your external
drives, a NAS, wherever). It walks the folders, detects each model, pulls in
preview images and any metadata it can find, and builds a searchable library.
From there you can filter by creator, scale, type, or tag; mark favorites;
queue models to print; track what you've already printed; preview STLs in 3D;
assemble multi-part builds; and group models into named **collections**.

Everything runs **locally** — your library never leaves your machine.
