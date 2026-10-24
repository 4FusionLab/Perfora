# SPDX-License-Identifier: GPL-3.0-only
"""Release-channel and publication-failure contracts, without GitHub mutations."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('perfora_release', ROOT / 'scripts/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def exercise(self, version='1.0.0', existing=None, corrupt=False, expected_error=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('Perfora', 'dist', 'docs/releases'):
                (root / name).mkdir(parents=True)
            (root / 'Perfora/Perfora.manifest').write_text(json.dumps({'version': version}))
            archive = root / ('dist/Perfora-' + version + '.zip')
            archive.write_bytes(b'checked distribution')
            checksum = archive.with_suffix('.zip.sha256')
            checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
            (root / ('docs/releases/v' + version + '.md')).write_text('Reviewed notes')
            state = dict(existing) if existing else None
            if state is not None:
                state.setdefault('url', 'https://example.invalid/release')
            calls = []
            uploaded = {}

            def gh(*args, check=True):
                nonlocal state
                calls.append(args)
                action = args[1]
                if action == 'view':
                    return SimpleNamespace(returncode=0 if state else 1,
                        stdout=json.dumps(state) if state else '')
                if action == 'create':
                    state = dict(isDraft=True, isPrerelease='--prerelease=true' in args,
                        targetCommitish='tested-commit', url='https://example.invalid/release')
                elif action == 'upload':
                    for path in (archive, checksum):
                        uploaded[path.name] = path.read_bytes()
                elif action == 'download':
                    destination = Path(args[args.index('--dir') + 1])
                    for name, contents in uploaded.items():
                        (destination / name).write_bytes(b'corrupt' if corrupt else contents)
                elif action == 'edit':
                    state.update(isDraft=False, isPrerelease='--prerelease=true' in args,
                        latest='--latest=true' in args,
                        assets=[{'name': name} for name in uploaded])
                return SimpleNamespace(returncode=0, stdout='')

            with patch.object(release, 'ROOT', root), patch.object(release, 'gh', gh), \
                 patch.dict(os.environ, GITHUB_REPOSITORY='owner/project', GITHUB_SHA='tested-commit'), \
                 contextlib.redirect_stdout(io.StringIO()):
                if expected_error:
                    with self.assertRaises(SystemExit):
                        release.main()
                else:
                    release.main()
            return state, calls

    def test_first_stable_is_published_as_latest_without_prerelease(self):
        state, _ = self.exercise()
        self.assertFalse(state['isDraft'])
        self.assertFalse(state['isPrerelease'])
        self.assertTrue(state['latest'])
        self.assertEqual(len(state['assets']), 2)

    def test_zero_major_remains_experimental(self):
        state, _ = self.exercise(version='0.2.1')
        self.assertTrue(state['isPrerelease'])
        self.assertFalse(state['latest'])

    def test_existing_published_release_is_never_modified(self):
        existing = dict(isDraft=False, targetCommitish='old-commit', url='https://example.invalid/existing')
        state, calls = self.exercise(existing=existing)
        self.assertEqual(state, existing)
        self.assertFalse(any(c[1] in ('create', 'upload', 'edit') for c in calls))

    def test_wrong_commit_draft_is_not_overwritten(self):
        _, calls = self.exercise(existing=dict(isDraft=True, targetCommitish='other-commit'), expected_error=True)
        self.assertFalse(any(c[1] in ('upload', 'edit') for c in calls))

    def test_corrupt_download_does_not_publish(self):
        state, calls = self.exercise(corrupt=True, expected_error=True)
        self.assertTrue(state['isDraft'])
        self.assertFalse(any(c[1] == 'edit' for c in calls))

    def test_matching_draft_can_be_retried_as_stable(self):
        state, _ = self.exercise(existing=dict(isDraft=True, targetCommitish='tested-commit'))
        self.assertFalse(state['isDraft'])
        self.assertFalse(state['isPrerelease'])
        self.assertTrue(state['latest'])
