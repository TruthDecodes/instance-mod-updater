# Mod updater for FTB App instances

**Unfinished.** Version 0.1.6. Personal snapshot, not a release. No support.
Do not treat it as ready for anyone else. Not an official Feed the Beast product.

Update **mods on an existing FTB App instance** (your real modlist stays where it is).
Does **not** migrate you to Prism or rebuild a pack.

License: [MIT](LICENSE). Copyright 2026 Truth. Security: [SECURITY.md](SECURITY.md).

## Start here

You can run the updater without reading further. The defaults are already set.

### Install

1. Download `instance-mod-updater-x.y.z.zip` from [Releases](https://github.com/TruthDecodes/instance-mod-updater/releases/latest). Not the green **Code** zip (`main` is unsigned).
2. Put the files so `run.cmd` is at `C:\Users\Public\instance-mod-updater\run.cmd` (the zip has a version folder; move those files up if needed).
3. One time, in that folder:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch-runtime.ps1
```

Git clone or copy a tree: [Install](#install).

### Update mods

Close Minecraft.

```powershell
cd C:\Users\Public\instance-mod-updater
.\run.cmd list
.\run.cmd all -i "name from list"
```

Use `run.cmd`. It refreshes this tool from a signed GitHub Release, then checks mods, applies updates, and upgrades NeoForge if the mods need it. Pack ids come from the instance when FTB already stored them.

If FTB App offers to reinstall the pack loader, decline.

Dry run, report-then-apply, or explicit pack ids: [Step by step](#step-by-step) · [Pack metadata](#pack-metadata-ftb).
CurseForge file lists, download URLs, and fingerprints work for the published Release without a local unique key.

### Safety

Close the game before apply or a loader upgrade. Replaced jars and `instance.json` are backed up. Apply stops if jars are still locked.

[Safety](#safety) · [After loader upgrade](#after-loader-upgrade) · [Policy](#policy) · [Commands](#commands)

## Sources

| Source | Auth |
| --- | --- |
| **Modrinth** | Public API (jar SHA1 identity; exact `GET /project/{modid\|stem}` when hash misses) |
| **CurseForge** | Official [Core API](https://docs.curseforge.com/rest-api/). File list, download URL, and fingerprint match. Core `/v1/` calls go to `https://truthimu.duckdns.org` and do not send `x-api-key`. Project ids may come from the FTB pack manifest or from a fingerprint hit. No CurseForge search. |
| **NeoForge** | Official Maven installer into FTB App `bin\` |

## Requirements

- Windows desktop user that owns the FTB instance
- FTB App installed (`%LOCALAPPDATA%\.ftba`)
- Python 3.11+ **or** bundled embeddable CPython under `runtime\python\`
- Close Minecraft before `apply` / loader upgrade

No `pip` packages. Stdlib only.

## Install

Zip install is in [Start here](#start-here). The archive unpacks as `instance-mod-updater-x.y.z\`; `run.cmd` must sit in `C:\Users\Public\instance-mod-updater\`.

Git clone (same folder, then the same one-time runtime):

```powershell
git clone https://github.com/TruthDecodes/instance-mod-updater.git C:\Users\Public\instance-mod-updater
cd C:\Users\Public\instance-mod-updater
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\fetch-runtime.ps1
```

Or copy the tree and run `scripts\fetch-runtime.ps1` the same way.

## Update the tool (from Public)
**tldr; The tool self-updates upon running it.**

`run.cmd` already does this before each command. Use this section only if you want the details.

The live install is `%PUBLIC%\instance-mod-updater`. That folder is also the work root (jars, reports, manifests). Updating must not wipe those.

`run.cmd` / `run.ps1` **self-update from a signed GitHub Release before each command**. Only app code is replaced:

- `instance_mod_updater\`, `scripts\`, `tests\`
- `run.cmd`, `run.ps1`, `run-bypass.ps1`, `deploy.cmd`
- `README.md`, `CHANGELOG.md`, `LICENSE`, `pyproject.toml`

Left alone: `runtime\`, `jars\`, `manifest.json`, `report-*`, `pack-*.json`, backups, installer jars, logs, and any extra files you added.

```powershell
cd C:\Users\Public\instance-mod-updater

# Refresh code only (no check/apply)
.\deploy.cmd

# Normal use: updates itself, then runs the command
.\run.cmd list

# Skip this launch
.\run.cmd --no-self-update list
```

`deploy.cmd` is the one-shot you can drop into Public if the tree is stale. After that, `run.cmd` keeps itself current.

Updates come only from a GitHub Release zip that verifies with the Ed25519 public key baked into the running updater. Floating `main` zips are not used.

Skip always: `set INSTANCE_UPDATER_NO_SELF_UPDATE=1`
(`FTB_NO_SELF_UPDATE` is still honored as an alias.)

## Step by step

Daily use is [Start here](#start-here). This is the longer command list.

Change to the directory you placed the files in.
Run `.\run.cmd` to see on-screen help.
Run `.\run.cmd list` to see your FTB instances/modpacks installed.
Run `.\run.cmd check -i "<modpack_name>"` to check (and download) the latest mods for the pack.
Run `.\run.cmd apply` to apply all downloaded mods to the pack(s).

**Use `run.cmd.` `run.ps1` is also currently available for those that want it.**. PowerShell is by default blocked by `Restricted` execution policy; .cmd is not.

```powershell
cd C:\Users\Public\instance-mod-updater

.\run.cmd list

# One shot: check + download + apply + NeoForge if needed
.\run.cmd all -i "ftb unstable 6" --pack-id 132 --version-id 100392
```

If execution policy blocks `.ps1` only:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1 list
```

Check, then apply:

```powershell
.\run.cmd check -i "ftb unstable 6" --pack-id 132 --version-id 100392
notepad $env:PUBLIC\instance-mod-updater\report-latest.md
.\run.cmd apply
.\run.cmd upgrade-loader -i "ftb unstable 6" --floor-from-mods
```

Dry run (no apply / no loader write):

```powershell
.\run.cmd all -i "ftb unstable 6" --pack-id 132 --version-id 100392 --dry-run
```

## Pack metadata (FTB)

`--pack-id` / `--version-id` load the FTB public pack JSON. That file is how the tool learns Minecraft/loader targets and, when present, CurseForge project ids for mods that are not on Modrinth by SHA1.

Matching order for a jar: exact pack SHA1 → exact pack filename → same **modid** as a pack mod → same **jar product stem** (name with loader/version stripped). That last path is how an instance that already moved past the pack pin still finds the pack row.

Those mods list on CurseForge through the same Core path as other CF jars (publisher origin; no local unique key).

| Pack | pack-id | version-id (example) |
| --- | --- | --- |
| FTB Unstable 6 | `132` | `100392` (pack 1.8.0) |

If `instance.json` already stores pack/version ids, you can omit `--pack-id` / `--version-id`.
Or pass a local pack JSON: `--pack-json path\to\pack.json`.

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

## Commands

| Command | What it does |
| --- | --- |
| `list` | List FTB instances |
| `self-update` | Refresh app code from a signed GitHub Release (same as `deploy.cmd`); does not touch work files |
| `check` | Hash jars → Modrinth + official CurseForge file lists and fingerprint cascade; then mandatory inter-mod `versionRange` on staged/remaining jars; stage jars + `manifest.json` + reports. Status: `upd` planned, `dl` transferred, `cached` already in work/jars; `uncheckable` with why |
| `apply` | Backup old jars, copy staged jars into instance `mods\` (refuses if jars locked) |
| `upgrade-loader` | NeoForge client install into `.ftba\bin`, retarget `instance.json` |
| `all` | check → apply → upgrade-loader if needed |

Default work root: `%PUBLIC%\instance-mod-updater\` (jars, manifests, backups, installer, logs).

Console uses light ANSI colors when the terminal supports them (Windows Terminal, recent PowerShell/cmd, etc.). Disable with `NO_COLOR=1`; force with `FORCE_COLOR=1`.

## Helpers

| Script | Purpose |
| --- | --- |
| `deploy.cmd` | Refresh app code from a signed GitHub Release; leave runtime and work files alone |
| `scripts\self-update.ps1` | Thin launcher that calls the Python verifier |
| `scripts\fetch-runtime.ps1` | Download embeddable CPython into `runtime\python\` (SHA256 pinned) |
| `scripts\sign-release.py` | Maintainer: pack and sign a release zip (needs the offline key) |

## After loader upgrade

1. Launch from **FTB App**.
2. If FTB offers to reinstall the pack’s pinned loader, **decline** / keep the custom NeoForge version.
3. On failure: inspect the instance `logs\latest.log` under `%LOCALAPPDATA%\.ftba\instances\<name>\`.

## Safety

- Backs up replaced jars and `instance.json` before loader changes.
- Unlocks instance / sets modified so FTB is less likely to overwrite a custom loader (still decline reinstall prompts).
- Apply preflights for locked mod jars (close the game first).

## Layout

```text
instance-mod-updater/
  run.cmd / run.ps1
  deploy.cmd
  README.md
  scripts/
    self-update.ps1
    fetch-runtime.ps1
    sign-release.py
  instance_mod_updater/
    cli.py
    pipeline.py
    modrinth.py
    curseforge.py
    pack_manifest.py
    app_local.py
    inventory.py
    neoforge.py
    progress.py
    term.py
    versions.py
    httputil.py
```
