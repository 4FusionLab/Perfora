"""The release archive embeds GitVersion without editing the source manifest."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from install import build_archive

ROOT = Path(__file__).resolve().parents[1]


class GitVersionPackageTests(unittest.TestCase):
    def test_release_version_is_embedded_in_archive_only(self):
        manifest = ROOT / 'Perfora/Perfora.manifest'
        checked_in_version = json.loads(manifest.read_text(encoding='utf-8'))['version']
        with tempfile.TemporaryDirectory() as temp:
            # Build into the real root, which has the full allowlisted tree.
            archive = build_archive(ROOT, version_override='9.8.7')
            try:
                self.assertEqual(archive.name, 'Perfora-9.8.7.zip')
                with zipfile.ZipFile(archive) as zipped:
                    self.assertEqual(json.loads(zipped.read('Perfora/Perfora.manifest'))['version'], '9.8.7')
                self.assertEqual(json.loads(manifest.read_text(encoding='utf-8'))['version'],
                                 checked_in_version)
            finally:
                archive.unlink(missing_ok=True)
                archive.with_suffix('.zip.sha256').unlink(missing_ok=True)
