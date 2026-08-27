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
- Download jars from Modrinth, the official CurseForge Core API download URL,
  and FTB pack file URLs
- Write into the instance `mods` folder after a backup
- Install a NeoForge client into the FTB App `bin` folder
- Replace its own app files from a **signed** GitHub Release of
  `TruthDecodes/instance-mod-updater`

It does not send your world saves or Microsoft account tokens. It does talk to
public mod APIs and to GitHub for self-update.

## Self-update

`run.cmd` and `deploy.cmd` install only a newer **GitHub Release** whose zip
verifies against an Ed25519 public key baked into the already-running updater.
The private key is not in this repository and is not used by GitHub Actions.
A push to `main` is not enough to land code on installed copies.

Skip a launch with `--no-self-update` or
`INSTANCE_UPDATER_NO_SELF_UPDATE=1` (`FTB_NO_SELF_UPDATE` is still honored as an alias).

## Secrets

Do not put API keys in this repository.

A CurseForge Core API key may be supplied at run time if it is yours
(`CURSEFORGE_API_KEY` or `CF_API_KEY`). Prefer the environment: `--cf-api-key`
is visible on the process command line. Without a local unique key, the
published app still performs those Core operations via the publisher origin.
The zip does not contain a credential for that origin. On first use the app
creates a machine-local install token (outside the install root) so the
publisher can rate-limit and revoke a noisy install. That token is not a
CurseForge key and is not proof that the caller is this app.
Keep any unique CurseForge key in your environment, not in a file that gets
copied or committed.

## Service access

The MIT license is for this software. It does not grant use of any network
service the official application contacts. Those services exist only for
official signed releases of instance-mod-updater published by Truth. Access
from other software is not allowed. Access may be rate-limited, changed, or
withdrawn at any time.

## Assumptions

- Close Minecraft before `apply` or a loader upgrade
- Run as the Windows user that owns the FTB instance
- Treat backups under the work root as yours to keep; this tool does not
  promise they last forever
