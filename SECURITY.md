# Security

This repository is an unfinished personal snapshot. It is not a release and is
not offered for general use.

## Report a vulnerability

Use **GitHub private vulnerability reporting** on this repository (Security
tab, then "Report a vulnerability"). Do not open a public issue.

I may take a while to reply. There is no paid bounty.

## What this tool touches

On a Windows machine it can:

- Read FTB App instance files under `%LOCALAPPDATA%\.ftba`
- Download jars from Modrinth, the official CurseForge Core API download URL
  (when an approved key is set), and FTB pack file URLs
- Write into the instance `mods` folder after a backup
- Install a NeoForge client into the FTB App `bin` folder
- Replace its own app files from `TruthDecodes/instance-mod-updater` on GitHub

It does not send your world saves or Microsoft account tokens. It does talk to
public mod APIs and to GitHub for self-update.

## Self-update

`run.cmd` and `deploy.cmd` pull the default branch of this GitHub repository
(git fast-forward, or a zip of that branch). Anyone with write access to this
repo can change the code that lands on your PC. Do not add collaborators you
do not trust. Skip a launch with `--no-self-update` or
`INSTANCE_UPDATER_NO_SELF_UPDATE=1` (`FTB_NO_SELF_UPDATE` is still honored as an alias).

## Secrets

Do not put API keys in this repository.

A CurseForge Core API key may be supplied at run time
(`CURSEFORGE_API_KEY`, `CF_API_KEY`, or `--cf-api-key`). CurseForge file lists,
download URLs, and fingerprint lookup need that key. Keep it in your
environment, not in a file that gets copied or committed.

## Assumptions

- Close Minecraft before `apply` or a loader upgrade
- Run as the Windows user that owns the FTB instance
- Treat backups under the work root as yours to keep; this tool does not
  promise they last forever
