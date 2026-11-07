"""Release contract checks are offline and cannot publish anything."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile

from scripts.release_contract import validate_release


class VersionContractTests(unittest.TestCase):
    def fixture(self, root, version="1.4.0", product="Example"):
        root = Path(root)
        archive = root / f"{product}-{version}.zip"
        with ZipFile(archive, "w") as zipped:
            zipped.writestr(f"{product}/{product}.manifest",
                            json.dumps({"version": version, "type": "addin"}))
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_suffix(".zip.sha256").write_text(
            digest + "  " + archive.name + "\n", encoding="ascii")
        notes = root / "notes.md"
        notes.write_text("Reviewed release notes", encoding="utf-8")
        return archive, notes

    def test_stable_and_prerelease_validate(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, notes = self.fixture(temp)
            manifest = "Example/Example.manifest"
            self.assertTrue(validate_release("1.4.0", "v1.4.0", "stable",
                                              manifest, [archive], notes))
            self.assertTrue(validate_release("1.4.0", "v1.4.0-beta.1", "prerelease",
                                              manifest, [archive], notes))

    def test_refuses_wrong_tag_and_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, notes = self.fixture(temp)
            for version, tag, channel in (("1.4.1", "v1.4.1", "stable"),
                                          ("1.4.0", "v1.4.1", "stable"),
                                          ("1.4.0", "v1.4.0", "prerelease")):
                with self.assertRaises(ValueError):
                    validate_release(version, tag, channel, "Example/Example.manifest",
                                     [archive], notes)

    def test_refuses_missing_notes_and_corrupt_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            archive, notes = self.fixture(temp)
            notes.write_text(" ")
            with self.assertRaises(ValueError):
                validate_release("1.4.0", "v1.4.0", "stable",
                                 "Example/Example.manifest", [archive], notes)
            notes.write_text("Reviewed")
            archive.with_suffix(".zip.sha256").write_text("invalid")
            with self.assertRaises(ValueError):
                validate_release("1.4.0", "v1.4.0", "stable",
                                 "Example/Example.manifest", [archive], notes)


if __name__ == "__main__":
    unittest.main()
