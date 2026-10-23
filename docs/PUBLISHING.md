# Releasing Perfora

Releases are built by [Check and release](https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml).

## Prepare a version

1. Update `Perfora/Perfora.manifest`. This is the version source of truth.
2. Update `CHANGELOG.md`, both READMEs, and add `docs/releases/vVERSION.md` with install instructions, actual validation, and known limits.
3. Run `python3 -m unittest discover -s tests -v` and `python3 install.py --zip`.
4. Run the relevant CAD checks in a separate document in Fusion. Record Fusion version and OS. Python CI does not certify native CAD behavior.
5. Review the diff for private files and local paths, then push the reviewed change to `main`.

## Automated publication

Every push to `main` runs geometry and packaging checks on Linux, macOS, and Windows. Pull requests run the same checks without release permissions.

After all checks pass, the release job builds the tested commit, creates a draft prerelease at its exact SHA, uploads the ZIP and SHA-256 file, downloads both back to verify their bytes, and publishes the prerelease. Only that job has `contents: write`. It uses the built-in GitHub Actions token; no personal token is stored in the project.

An already published version is kept unchanged. To publish another version, bump the manifest and add matching notes. A failed upload can be retried for the same draft and commit. A draft targeting a different commit stops the job for inspection.

## Verify publication

Check all three OS jobs and the release job. Download the named `Perfora-VERSION.zip` and its `.sha256` asset, verify the checksum, extract it, and test installation with a disposable `--api-root`. Confirm manifest version and installer backups. Never replace assets or move tags of an existing published release to repair a code defect; publish a new patch version.

The 0.1.x series is experimental. Promote a future version to stable only after the acceptance checks in `CONTRIBUTING.md`, including native Windows CAD checks, save/reopen, Undo/Redo, and native Extrude editing.
