# Changelog

## 0.1.5 - 2026-08-27

- With no local unique CurseForge key, file list, download URL, and fingerprint still use Core `/v1/` paths via `https://truthimu.duckdns.org`. Those calls do not send `x-api-key`.
- A local `CURSEFORGE_API_KEY` / `CF_API_KEY` still talks to `api.curseforge.com`.
- README Start here for zip install. CurseForge is no longer described as uncheckable without a local unique key.

## 0.1.4 - 2026-08-14

- `downloaded` is one color (magenta) on the count, the `[downloaded]` tag, and the status tokens. Not cyan. Not the default white.

## 0.1.3 - 2026-08-13

- Self-update installs only a signed GitHub Release zip. The Ed25519 public key is baked into the running updater. Floating `main` zips and unsigned git fast-forwards are gone.
- `scripts\fetch-runtime.ps1` checks the official python.org embed zip (SHA256 + MD5) before extract
- Stage and apply reject jar names that leave the mods/jars folders
- Dropped `scripts\copy-mc-logs.ps1` from the public tree

## 0.1.2 - 2026-08-13

- Check summary leads with NeoForge floor vs the installed loader
- Update lines show the product version, not a Minecraft-only Modrinth tag
- Drop the extra DONE counts and the second report/manifest path block

## 0.1.1 - 2026-08-13

Console is meant to be read by a person, not only a report file.

- Every jar transfer prints a result line, including files under 256 KB (those used to be silent)
- After check, list every update and every error. Errors are red and include a plain-language why
- `errors` is not a failed-download count. A required companion is only an error if it is not a separate jar and not bundled inside the parent
- Loader/platform ids (`neoforge`, `minecraft`, …) are not treated as missing jars
- Extra `[[mods]]` ids, inline `mods = [{ ... }]`, and NeoForge JarJar (`META-INF/jarjar`) count as present. `${file.jarVersion}` is read from the jar manifest
- The checker does not add mods that are not already in the instance

## 0.1.0 - 2026-08-13

First public snapshot. Unfinished. Not a release.

- Update mods on an existing FTB App instance (does not migrate to Prism or rebuild a pack)
- Display name is the job, not an FTB product title (not official Feed the Beast)
- Identifiers dropped the FTB product name (repo, work root, package, env var)
- Modrinth via jar SHA1; exact project GET by modid or product stem when the hash misses
- CurseForge via the official Core API when `CURSEFORGE_API_KEY` / `CF_API_KEY` / `--cf-api-key` is set (file list, download URL, optional fingerprint). Pack JSON may supply project ids. No CurseForge search.
- NeoForge client install into FTB App `bin` when mod floors require it
- Inter-mod `versionRange` follow-up after per-jar picks
- `run.cmd` / `deploy.cmd` refresh app code from this GitHub repo; work files and `runtime\` stay put
