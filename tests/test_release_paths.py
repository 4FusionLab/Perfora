"""Regression checks for the repository's automatic runtime-release path policy.

Match the pinned shared platform's positive/negative fnmatch allowlist semantics.
This test must never publish or create Git tags.
"""

import fnmatch
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = ROOT / ".github" / "release-paths.txt"


def read_patterns():
    rules = [
        line.strip()
        for line in RULES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not any(not rule.startswith("!") for rule in rules):
        raise ValueError("No release-eligible paths configured")
    return rules


def eligible_paths(changed):
    rules = read_patterns()
    include = [pattern for pattern in rules if not pattern.startswith("!")]
    exclude = [pattern[1:] for pattern in rules if pattern.startswith("!")]
    return [
        path for path in changed
        if any(fnmatch.fnmatchcase(path, pattern) for pattern in include)
        and not any(fnmatch.fnmatchcase(path, pattern) for pattern in exclude)
    ]


# Review these vectors when adding/removing shipped runtime inputs or changing
# the package builder. Source-only docs/tests and CI configuration are excluded.
RUNTIME_INPUTS = (
        "Perfora/Perfora.py",
        "Perfora/geometry.py",
        "Perfora/resources/toolbar/16x16.png",
        "Perfora/Perfora.manifest",
        "install.py",
)

NON_RUNTIME_INPUTS = (
        "README.md",
        "README.ru.md",
        "PerforaSmokeTest/PerforaSmokeTest.py",
        "tests/test_geometry.py",
        "docs/PUBLISHING.md",
        "scripts/release.py",
        "scripts/release_contract.py",
        ".github/workflows/ci.yml",
        ".github/release-paths.txt",
        "GitVersion.yml",
        "AGENTS.md",
)


class ReleaseEligibilityTests(unittest.TestCase):
    def test_expected_runtime_paths_always_trigger(self):
        for path in RUNTIME_INPUTS:
            with self.subTest(path=path):
                self.assertEqual(eligible_paths([path]), [path])

    def test_non_runtime_paths_never_trigger(self):
        for path in NON_RUNTIME_INPUTS:
            with self.subTest(path=path):
                self.assertEqual(eligible_paths([path]), [])

    def test_documentation_only_push_is_skipped(self):
        self.assertEqual(eligible_paths(NON_RUNTIME_INPUTS), [])

    def test_mixed_push_triggers_for_shipped_changes_only(self):
        changed = [NON_RUNTIME_INPUTS[0], RUNTIME_INPUTS[0], NON_RUNTIME_INPUTS[1]]
        self.assertEqual(eligible_paths(changed), [RUNTIME_INPUTS[0]])

    def test_deleted_runtime_path_still_triggers(self):
        # The Git diff classifier includes deleted paths; matching ignores status.
        self.assertEqual(eligible_paths([RUNTIME_INPUTS[0]]), [RUNTIME_INPUTS[0]])

    def test_rename_from_runtime_to_docs_triggers(self):
        # With git --no-renames the old (deleted) and new (added) paths both
        # appear; renaming a runtime source must not silently suppress release.
        self.assertEqual(
            eligible_paths([RUNTIME_INPUTS[0], NON_RUNTIME_INPUTS[0]]),
            [RUNTIME_INPUTS[0]],
        )


if __name__ == "__main__":
    unittest.main()
