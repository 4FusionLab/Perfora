"""Offline release artifact contract used by 4FusionLab add-ins.

Does not create tags, mutate releases, access Fusion, or call GitHub.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

NUMERIC_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
PRERELEASE_ID = re.compile(r"[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*\Z")


def validate_release(version, tag, channel, manifest, archives, notes):
    """Check numeric Fusion metadata, release identity, versioned notes and ZIP integrity."""
    if not NUMERIC_VERSION.fullmatch(version):
        raise ValueError("GitVersion MajorMinorPatch must be numeric MAJOR.MINOR.PATCH")
    if channel not in ("stable", "prerelease"):
        raise ValueError("Release channel must be stable or prerelease")
    base_tag = "v" + version
    if channel == "stable":
        if tag != base_tag:
            raise ValueError("Stable tag must equal " + base_tag)
    elif not (tag.startswith(base_tag + "-") and
              PRERELEASE_ID.fullmatch(tag[len(base_tag) + 1:])):
        raise ValueError("Prerelease tag must be vMAJOR.MINOR.PATCH-IDENTIFIER")
    notes = Path(notes)
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        raise ValueError("Reviewed, version-specific release notes are required")
    if not archives:
        raise ValueError("At least one ZIP artifact is required")
    product = Path(manifest).stem
    for archive in map(Path, archives):
        if not archive.is_file() or archive.suffix != ".zip":
            raise ValueError("Missing ZIP distribution: " + str(archive))
        if not (archive.name == f"{product}-{version}.zip" or
                archive.name.startswith(f"{product}-{version}-")):
            raise ValueError("ZIP filename does not match calculated version: " + archive.name)
        checksum = archive.with_suffix(".zip.sha256")
        if not checksum.is_file():
            raise ValueError("Missing SHA-256 checksum: " + str(checksum))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if checksum.read_text(encoding="ascii") != digest + "  " + archive.name + "\n":
            raise ValueError("ZIP checksum mismatch: " + archive.name)
        with zipfile.ZipFile(archive) as zipped:
            members = zipped.namelist()
            if any(name.startswith("/") or ".." in Path(name).parts or "\\" in name
                   for name in members):
                raise ValueError("Unsafe package member path")
            inner = str(manifest).replace("\\", "/")
            metadata = json.loads(zipped.read(inner))
            if metadata.get("version") != version:
                raise ValueError("Embedded Fusion manifest version differs from GitVersion")
            if metadata.get("type") != "addin":
                raise ValueError("Package has no Fusion add-in manifest")
            if zipped.testzip() is not None:
                raise ValueError("Corrupt ZIP distribution")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="GitVersion MajorMinorPatch")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--channel", choices=("stable", "prerelease"), required=True)
    parser.add_argument("--manifest", required=True, help="Manifest path in ZIP")
    parser.add_argument("--archive", action="append", required=True, help="One or more ZIP paths")
    parser.add_argument("--notes", required=True)
    args = parser.parse_args()
    validate_release(args.version, args.tag, args.channel,
                     args.manifest, args.archive, args.notes)
    print(f"Verified {len(args.archive)} packages for {args.tag} ({args.channel})")


if __name__ == "__main__":
    main()
