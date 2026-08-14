# Contributing

This public tree is an unfinished snapshot. I am not accepting pull requests,
issues, or feature requests yet.

If you found a security problem, see [SECURITY.md](SECURITY.md).

Releases that `run.cmd` will install are signed offline. The public key is
`UPDATE_PUBLIC_KEY_HEX` in `instance_mod_updater/self_update.py`. Maintainers
pack and sign with `scripts/sign-release.py` and attach
`instance-mod-updater-x.y.z.zip` plus `.zip.sig` to a GitHub Release. The
private key does not belong in this repository or in Actions.
