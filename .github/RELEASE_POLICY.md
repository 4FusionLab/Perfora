# 4FusionLab — automatic runtime release policy

## Trigger

- A direct push to `main` or a PR merge into `main` is the only normal release event. PR checks, manual CI dispatch and version-tag pushes **do not** initiate publication.
- Before publishing, compare the entire `github.event.before..GITHUB_SHA` range, including renamed/deleted runtime files. A release is eligible **only** if the pushed commits change a shippable add-in/runtime file, runtime resource, native component, or explicitly designated distribution input.
- The repository's `.github/release-paths.txt` is the audited allowlist; the pinned shared 4FusionLab runtime-changes Action enforces it. Changes limited to README, guides, design documents, screenshots, tests, CI workflows, repository policy or GitVersion config must not publish a release.
- All required existing CI checks must succeed before publishing. A failed gate means no release, no mutable tag and no replaced assets.

## Version and distribution

- GitVersion.Tool **6.8.2** derives numeric `MAJOR.MINOR.PATCH` using `GitVersion.yml` and the full Git history. The package ZIP, embedded Fusion manifest (where applicable), auto-created immutable `vMAJOR.MINOR.PATCH` tag and GitHub Release refer to the same commit/version.
- The pipeline creates the tag **automatically** when it publishes the GitHub Release. Contributors never create or push release tags manually. A pre-existing version tag pointing to another commit is an error; a published release is never overwritten.
- Existing reviewed, version-specific release notes are used when present; otherwise notes are automatically generated from Git history. No manually prepared release-note file is required just to ship a code change.
- Stable releases become Latest. Prereleases never become Latest. Project-specific native-CAD acceptance, tests, signed/hashed archives, OS compatibility and publication limitations remain in force.

## This repository

Runtime allowlist: `Perfora/**`, `install.py`. Linux/macOS/Windows tests, Fusion manifest and ZIP SHA-256 remain mandatory. Historical 0.x releases remain experimental.

If a push changes no eligible runtime file, CI may run but the GitHub Release job is skipped, even when GitVersion computes a different candidate version.

## Shared release actions

The repository consumes read-only GitVersion, runtime-impact, release-note and ZIP/manifest/SHA-256 Actions from `4FusionLab/.github`, pinned to `ad9d60ba4aabc494b4f2c85d6c566a50ca423751`. Perfora retains its own extensive CAD/geometry tests, installer, release contract, draft upload verification and immutable GitHub Release publisher. Obsolete local copies of runtime-change and release-notes helpers were removed.
