"""Decide whether a main-branch push changes shipped runtime or distribution inputs."""
import argparse
import fnmatch
import subprocess
from pathlib import Path


def read_rules(path):
    rules = [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()]
    return [line for line in rules if line and not line.startswith("#")]


def impacted(files, rules):
    includes = [rule for rule in rules if not rule.startswith("!")]
    excludes = [rule[1:] for rule in rules if rule.startswith("!")]
    return [path for path in files if any(fnmatch.fnmatchcase(path, rule) for rule in includes)
            and not any(fnmatch.fnmatchcase(path, rule) for rule in excludes)]


def git_paths(before, after):
    if not after:
        raise ValueError("The new commit SHA is required.")
    if not before or before == "0" * 40:
        cmd = ["git", "ls-tree", "-rz", "--name-only", after]
    else:
        cmd = ["git", "diff", "--name-only", "-z", "--no-renames", before, after]
    output = subprocess.check_output(cmd)
    return [entry.decode("utf-8", errors="surrogateescape")
            for entry in output.split(b"\0") if entry]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=".github/release-paths.txt")
    parser.add_argument("--before")
    parser.add_argument("--after")
    parser.add_argument("--changed", nargs="*")
    parser.add_argument("--github-output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    rules = read_rules(args.config)
    if not any(not rule.startswith("!") for rule in rules):
        parser.error("No runtime allowlist configured.")
    if args.self_test:
        excluded = ["README.md", "README.ru.md", "docs/guide.md",
                    ".github/workflows/ci.yml", "tests/test_example.py",
                    "GitVersion.yml", ".github/RELEASE_POLICY.md"]
        assert not impacted(excluded, rules), "Documentation or CI would trigger a release."
        first = next(rule for rule in rules if not rule.startswith("!"))
        sample = first.replace("**", "example.py").replace("*", "example.py")
        assert impacted([sample], rules), "The runtime allowlist must match runtime paths."
        print("release path policy OK")
        return
    files = args.changed if args.changed is not None else git_paths(args.before, args.after)
    matching = impacted(files, rules)
    value = "true" if matching else "false"
    print("release=" + value)
    for path in matching:
        print("  runtime change: " + path)
    if args.github_output:
        with Path(args.github_output).open("a", encoding="utf-8") as output:
            output.write("release=" + value + "\n")


if __name__ == "__main__":
    main()
