# Update manifest

`latest.json` is generated during a release and committed only after it has been
signed with the private key held in `KACC_UPDATE_PRIVATE_KEY_B64`.

Use `python scripts/build_update_manifest.py --help` to create it. Do not commit
the private key or an unsigned placeholder manifest.
