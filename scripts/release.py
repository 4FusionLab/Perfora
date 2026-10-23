# SPDX-License-Identifier: GPL-3.0-only
"""Publish a verified experimental release from the tested GitHub Actions commit."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def gh(*args, check=True):
    return subprocess.run(['gh', *args], cwd=ROOT, check=check, text=True, capture_output=True)


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    commit = os.environ['GITHUB_SHA']
    version = json.loads((ROOT / 'Perfora/Perfora.manifest').read_text(encoding='utf-8'))['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise SystemExit('Manifest version must be MAJOR.MINOR.PATCH.')
    tag = 'v' + version
    archive = ROOT / ('dist/Perfora-' + version + '.zip')
    checksum = archive.with_suffix('.zip.sha256')
    notes = ROOT / ('docs/releases/' + tag + '.md')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if checksum.read_text(encoding='utf-8').split() != [digest, archive.name]:
        raise SystemExit('Archive checksum mismatch.')
    if not notes.is_file():
        raise SystemExit('Add reviewed release notes at ' + str(notes))
    existing = gh('release', 'view', tag, '--repo', repository,
                  '--json', 'isDraft,targetCommitish,url', check=False)
    if existing.returncode == 0:
        release = json.loads(existing.stdout)
        if not release['isDraft']:
            print('Already published; keep existing release unchanged: ' + release['url'])
            print('Bump the manifest version to publish another release.')
            return
        if release['targetCommitish'] != commit:
            raise SystemExit('Existing draft belongs to a different commit; refusing to overwrite it.')
    else:
        gh('release', 'create', tag, '--repo', repository, '--target', commit,
           '--draft', '--prerelease', '--title', 'Perfora ' + version + ' · Experimental',
           '--notes-file', str(notes))
    gh('release', 'upload', tag, str(archive), str(checksum), '--repo', repository, '--clobber')
    # Read back the uploaded files before making the release visible.
    with tempfile.TemporaryDirectory(prefix='perfora-release-') as temporary:
        gh('release', 'download', tag, '--repo', repository, '--dir', temporary,
           '--pattern', archive.name, '--pattern', checksum.name)
        for path in (archive, checksum):
            if (Path(temporary) / path.name).read_bytes() != path.read_bytes():
                raise SystemExit('Uploaded asset differs from the build: ' + path.name)
    gh('release', 'edit', tag, '--repo', repository, '--draft=false', '--prerelease', '--latest=false')
    result = json.loads(gh('release', 'view', tag, '--repo', repository,
                          '--json', 'isDraft,isPrerelease,assets,url').stdout)
    if result['isDraft'] or not result['isPrerelease']:
        raise SystemExit('Release publication state is incorrect.')
    if {asset['name'] for asset in result['assets']} != {archive.name, checksum.name}:
        raise SystemExit('Unexpected release assets.')
    print('Published and verified: ' + result['url'])


if __name__ == '__main__':
    main()
