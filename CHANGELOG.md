# Changelog

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
