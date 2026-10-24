# Releasing Perfora

Releases are built by [Check and release](https://github.com/4FusionLab/Perfora/actions/workflows/ci.yml).

## Prepare a version

1. Update `Perfora/Perfora.manifest`, the version source of truth. Versions are MAJOR.MINOR.PATCH.
2. Update `CHANGELOG.md`, both READMEs, and `docs/releases/vVERSION.md`. Include install instructions, actual validation, benchmark methodology, and material limitations.
3. Run unit tests, compile checks, and `python3 install.py --zip`. Verify archive contents and two installations into a disposable `--api-root`, including backups.
4. Run the relevant CAD checks in separate unsaved Fusion documents. Complete the acceptance matrix in `CONTRIBUTING.md`, including real OK/Cancel, Undo/Redo, native Extrude editing, Feature recompute/edit, and local F3D reopen. Record Fusion/OS versions and distinguish native CAD from Python CI. Never imply unperformed Windows CAD or cloud-save acceptance.
5. Capture product images in real Fusion with the same neutral background, framing, and palette as the existing gallery. Validate the actual geometry; do not illustrate unavailable features.
6. Review the final diff for private files, credentials, local paths, reports, caches, backups, and Autodesk assets, then push the reviewed commit to `main`.

## Release channels

The 0.x series remains experimental and is published as prereleases. Version 1.0.0 is the first stable release. Versions with MAJOR >= 1 are normal GitHub releases (`prerelease=false`) and are explicitly marked Latest. The add-in's release channel does not change the lifecycle of Autodesk APIs it uses: the Custom Feature API remains Autodesk Preview API.

The maintainer chooses the release channel. Validation records describe the platforms actually exercised; CI on Windows does not certify native Fusion CAD behavior. Outstanding platform-specific coverage remains documented, including for stable versions.

## Automated publication

Pushes to `main` run compile, geometry, installation, and packaging checks on Linux, macOS, and Windows. Pull requests run the same checks without release permissions.

After all three OS jobs pass, the release job builds the tested commit and creates a draft at that exact SHA. `scripts/release.py` derives the channel from the manifest, uploads the ZIP and SHA-256 file, downloads both to verify their bytes, then publishes with the correct prerelease/Latest flags. Only that job has `contents: write`; it uses the built-in GitHub Actions token. No personal token is stored in the project.

An existing published version is immutable. Retrying a failed upload is allowed only for a draft belonging to the same exact commit. A draft targeting another commit stops publication for inspection. Never move a published tag or replace its assets to repair a code defect; publish a new patch version.

## Verify publication

Check all three OS jobs and the release job. Verify the release's tag, target commit, draft state, channel, and Latest link. Download `Perfora-VERSION.zip` and `.sha256`, verify their bytes against the checked distribution, inspect the manifest and contents, and install into a temporary API root twice to verify backups. Check that both READMEs, release notes, and all linked screenshots render on GitHub.
