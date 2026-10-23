# SPDX-License-Identifier: GPL-3.0-only
"""Exercise the real distribution and installer outside the user's Fusion setup."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('perfora_installer', ROOT / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DistributionTests(unittest.TestCase):
    def test_zip_is_complete_reproducible_and_installs_with_backups(self):
        with tempfile.TemporaryDirectory() as temporary:
            sandbox = Path(temporary)
            source = sandbox / 'source'
            source.mkdir()
            for directory in ('Perfora', 'PerforaSmokeTest', 'tests', 'docs', 'scripts'):
                shutil.copytree(ROOT / directory, source / directory,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for name in ('README.md', 'README.ru.md', 'CONTRIBUTING.md', 'CHANGELOG.md',
                         'LICENSE', 'perfora.png', 'install.py'):
                shutil.copyfile(ROOT / name, source / name)
            # Local caches and reports must never leak into the release.
            (source / 'Perfora/__pycache__').mkdir()
            (source / 'Perfora/__pycache__/private.pyc').write_bytes(b'private')
            (source / 'Perfora/.DS_Store').write_bytes(b'private')
            archive = installer.build_archive(source)
            original = archive.read_bytes()
            os.utime(source / 'Perfora/geometry.py', (1700000000, 1700000000))
            self.assertEqual(original, installer.build_archive(source).read_bytes())
            self.assertEqual(archive.with_suffix('.zip.sha256').read_text().split(),
                             [hashlib.sha256(original).hexdigest(), archive.name])
            unpacked = sandbox / 'unpacked'
            with zipfile.ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                names = set(bundle.namelist())
                self.assertTrue({'Perfora/Perfora.py', 'Perfora/Perfora.manifest',
                                 'Perfora/resources/toolbar-f692fbb3/32x32.png',
                                 'PerforaSmokeTest/PerforaSmokeTest.py', 'LICENSE',
                                 'README.md', 'README.ru.md', 'perfora.png'} <= names)
                self.assertFalse(any('__pycache__' in name or '.DS_Store' in name
                                     or '\\' in name or name.startswith(('.git', 'test-results'))
                                     for name in names))
                bundle.extractall(unpacked)
            api = sandbox / 'Fusion API'
            for _ in range(2):
                subprocess.run([sys.executable, str(unpacked / 'install.py'), '--api-root', str(api)],
                               check=True, capture_output=True, text=True)
            self.assertEqual((api / 'AddIns/Perfora/geometry.py').read_bytes(),
                             (source / 'Perfora/geometry.py').read_bytes())
            self.assertTrue((api / 'Scripts/PerforaSmokeTest/PerforaSmokeTest.py').is_file())
            self.assertEqual(len(list((api / 'PerforaBackups').iterdir())), 2)
            manifest = json.loads((api / 'AddIns/Perfora/Perfora.manifest').read_text())
            self.assertFalse(manifest['runOnStartup'])
            self.assertEqual(manifest['id'], '6f1cbfba-a828-4b37-a356-d86cdd0dfc21')

    @unittest.skipIf(sys.platform == 'win32', 'Creating symlinks needs extra Windows privileges')
    def test_installer_refuses_symlink_without_touching_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / 'source', root / 'target'
            source.mkdir()
            target.mkdir()
            marker = target / 'keep.txt'
            marker.write_text('keep')
            destination = root / 'link'
            destination.symlink_to(target, target_is_directory=True)
            with self.assertRaises(SystemExit):
                installer.copy_directory(source, destination)
            self.assertEqual(marker.read_text(), 'keep')
            self.assertTrue(destination.is_symlink())


    def test_installer_survives_legacy_console_encoding(self):
        with tempfile.TemporaryDirectory() as temporary:
            api = Path(temporary) / 'API-тест'
            result = subprocess.run(
                [sys.executable, str(ROOT / 'install.py'), '--api-root', str(api)],
                env=dict(os.environ, PYTHONIOENCODING='cp1252'), capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode('ascii', 'replace'))
            self.assertTrue((api / 'AddIns/Perfora/Perfora.py').is_file())
            self.assertTrue((api / 'Scripts/PerforaSmokeTest/PerforaSmokeTest.py').is_file())
