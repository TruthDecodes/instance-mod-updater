# Mod updater for FTB App instances

**Unfinished.** Version 0.1.7. No support.
Not an official Feed the Beast product.

Updates **mods on an existing FTB App instance**.

License: [MIT](LICENSE). Copyright 2026 Truth. Security: [SECURITY.md](SECURITY.md).

## Install

1. Download `instance-mod-updater-x.y.z.zip` from [Releases](https://github.com/TruthDecodes/instance-mod-updater/releases/latest).
   Not the green **Code** zip (`main` is unsigned).
2. Create an empty folder anywhere you want and unpack the zip **into that folder**
   (`run.cmd` should sit directly in it).
3. Run:

```text
.\run.cmd list
```

The Release zip includes a pinned Windows embeddable Python® under `runtime\python\`
(with that build’s `LICENSE.txt`). You do not need a separate python.org install.
See [No Python?](#no-python) only if that runtime is missing or broken.

## Update mods

Close Minecraft. Open a command prompt in the folder where you put `run.cmd`.

```text
.\run.cmd list
.\run.cmd all -i "name from list"
```

That is the normal path. `run.cmd` refreshes this tool from a signed GitHub Release,
then checks mods, applies updates, and upgrades NeoForge if the mods need it.
Pack ids come from the instance when FTB already stored them.

If FTB App offers to reinstall the pack loader afterward, decline.

## Safety

- Close the game before apply or a loader upgrade.
- Replaced jars and `instance.json` are backed up.
- Apply stops if jars are still locked.
- After a loader upgrade, launch from **FTB App**. If it offers to reinstall the
  pack’s pinned loader, **decline**. On failure, check
  `%LOCALAPPDATA%\.ftba\instances\<name>\logs\latest.log`.

## Commands

| Command | What it does |
| --- | --- |
| `list` | List FTB instances |
| `all -i "name"` | Check, download, apply, and upgrade NeoForge if needed |
| `check -i "name"` | Stage updates and write reports (no apply) |
| `apply` | Copy staged jars into the instance `mods\` folder |
| `upgrade-loader` | NeoForge client install into `.ftba\bin`, retarget `instance.json` |
| `self-update` | Refresh app code only (same as `deploy.cmd`) |

Default work root: the same folder as `run.cmd` (jars, manifests, backups, reports, logs).
Override with `--work-root` if you want those files elsewhere.

Useful extras:

```text
.\run.cmd all -i "name" --dry-run
.\run.cmd check -i "name"
notepad .\report-latest.md
.\run.cmd apply
```

If `instance.json` does not already store pack/version ids:

```text
.\run.cmd all -i "ftb unstable 6" --pack-id 132 --version-id 100392
```

Skip self-update for one launch: `.\run.cmd --no-self-update list`
(or set `INSTANCE_UPDATER_NO_SELF_UPDATE=1`).

## Pack metadata (FTB)

`--pack-id` / `--version-id` load the FTB public pack JSON. That file is how the
tool learns Minecraft/loader targets and, when present, CurseForge project ids
for mods that are not on Modrinth by SHA1.

Matching order for a jar: exact pack SHA1 → exact pack filename → same **modid**
as a pack mod → same **jar product stem** (name with loader/version stripped).
That last path is how an instance that already moved past the pack pin still
finds the pack row.

| Pack | pack-id | version-id (example) |
| --- | --- | --- |
| FTB Unstable 6 | `132` | `100392` (pack 1.8.0) |

You can also pass a local pack JSON: `--pack-json path\to\pack.json`.

```text
https://api.feed-the-beast.com/v1/modpacks/public/modpack/{packId}/{versionId}
```

## Policy

- Prefer **release** builds for this Minecraft version + loader.
- If only **beta** (or only alpha) exists for that game/loader, treat that as the author’s normal channel.
- Never replace with a version that is not strictly newer when comparable.
- After per-jar picks, read **mandatory** inter-mod `versionRange` on staged jars (and installed jars that are not being replaced). If an already-installed companion is out of range, pull a newer eligible build for that companion. **Does not add mods that are not already in the instance.** A required companion with no jar of its own is an **error** (red, with a why), not a download.
- On NeoForge instances, reject CF jars whose filenames are pure `-forge-` (not NeoForge).
- Skip CurseForge files marked early-access. Skip download when the official mod record disallows third-party distribution.
- NeoForge upgrade uses the latest **matching MC line** (e.g. `26.1.2.x` for MC `26.1.2`, not `26.2.x`) when mod dependency floors require it.
- NeoForge floor is taken from **neoforge** dependency ranges in mods.toml, not FML `loaderVersion` (e.g. `[63,)`).
- **Status meanings (layman):**
  - **`current`**: we looked up Modrinth and/or CurseForge and you already have the newest eligible build for this MC+loader. Safe to read as “up to date on a public listing.”
  - **`uncheckable` / `pack_only`**: latest was **not** checked. Structured reason codes + short why (CLI + report). Matching the pack pin is **never** “up to date.”
  - **`no_source`**: no Modrinth hash, no pack row, and cascade still failed (same style of reasons).
  - **`errors`**: problems found after the scan. Not a count of failed downloads. Typical: a required companion is not a separate jar and is not bundled in the parent (JarJar / extra `[[mods]]`); or a companion is present but no matching update was found. The console lists every error in red. Libraries the game already loads from inside a parent jar are not errors.
- **Resolve cascade** (when jar SHA1 is not on Modrinth **and** the pack row has no CurseForge project id):
  1. Exact Modrinth `GET /project/{id-or-slug}` using installed **modid** and jar **product stem** only. **No** free-text Modrinth search.
  2. CurseForge **fingerprint** (`hashes.cfMurmur` or local jar murmur). Official `POST /v1/fingerprints/{gameId}` only. **No** CurseForge search.
  3. If still unresolved → **uncheckable** with codes such as `mr_project_not_found`, `mr_no_eligible_version`, `fingerprint_miss`, `ftb_private_blob`.
- **True FTB-only blobs** (e.g. `ftb-auxilium-neoforge-*.jar`): cascade finds no public project → `ftb_private_blob` / pack pin match; optional re-sync from the pack file URL when local SHA differs (`pack_ftb_only_pin_refresh`). Never counted under `current`.

## Sources

| Source | Auth |
| --- | --- |
| **Modrinth** | Public API (jar SHA1 identity; exact `GET /project/{modid\|stem}` when hash misses) |
| **CurseForge** | Official [Core API](https://docs.curseforge.com/rest-api/). File list, download URL, and fingerprint match. Core `/v1/` calls go to `https://truthimu.duckdns.org` and do not send `x-api-key`. Project ids may come from the FTB pack manifest or from a fingerprint hit. No CurseForge search. |
| **NeoForge** | Official Maven installer into FTB App `bin\` |

CurseForge file lists, download URLs, and fingerprints work for the published Release without a local unique key.

## How the tool updates itself

`run.cmd` already refreshes from a signed GitHub Release before each command.
App code and the bundled `runtime\` are replaced (`instance_mod_updater\`,
`scripts\`, `tests\`, `run.cmd`, `run.ps1`, `deploy.cmd`, docs, and so on).

Left alone: `jars\`, `manifest.json`, `report-*`, `pack-*.json`,
backups, installer jars, logs, and any extra files you added.

Updates come only from a GitHub Release zip that verifies with the Ed25519
public key baked into the running updater. Floating `main` zips are not used.

One-shot refresh without a mod command: `.\deploy.cmd`

## No Python?

Signed Releases already ship `runtime\python\`. `run.cmd` uses that first, then a
real Python 3.11+ on PATH (`py` or `python`, not the Microsoft Store stub).

If you installed from a git checkout (no Release zip) or the runtime folder is
missing, fetch the same pinned embed:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch-runtime.ps1
```

Then run `.\run.cmd list` again. A system python.org install is only a fallback.

## From source (optional)

Git clone into any folder if you prefer that over the Release zip. Git does not
include the embed; run `fetch-runtime.ps1` once (or use system Python). Prefer
the Release zip for normal use; `main` is unsigned.

```text
git clone https://github.com/TruthDecodes/instance-mod-updater.git
cd instance-mod-updater
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch-runtime.ps1
.\run.cmd list
```

## Layout

```text
(your folder)/
  run.cmd
  deploy.cmd
  README.md
  runtime\python\   (embeddable CPython from the Release zip; includes LICENSE.txt)
  scripts/
    fetch-runtime.ps1
    self-update.ps1
    sign-release.py
  instance_mod_updater/
    …
```

`run.ps1` exists for the same commands if you want PowerShell. Prefer `run.cmd`
so you do not fight ExecutionPolicy. Maintainer-only: `scripts\sign-release.py`.

## Third-party

This application redistributes the official Windows [embeddable package](https://docs.python.org/3/using/windows.html#the-embeddable-package)
from python.org under the Python Software Foundation License. The full license
text ships as `runtime\python\LICENSE.txt`. “Python” is a registered trademark
of the Python Software Foundation.
