"""Select reviewed notes when available; otherwise generate notes from commit history."""
import argparse
import subprocess
from pathlib import Path


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--product", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--candidate", action="append", default=[])
    args = parser.parse_args()
    output = Path(args.output)
    for name in args.candidate:
        path = Path(name)
        if path.is_file() and path.read_text(encoding="utf-8").strip():
            output.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            print("Using reviewed release notes: " + name)
            return
    previous = git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD")
    base = previous.stdout.strip() if previous.returncode == 0 else None
    rev = base + "..HEAD" if base else "HEAD"
    command = ["git", "log", "--max-count=100", "--format=- %s (%h)", rev]
    logs = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()
    if not logs:
        raise SystemExit("Cannot generate release notes without changes since last tag.")
    heading = f"# {args.product} v{args.version}\n\n"
    context = f"Changes since {base}:\n\n" if base else "Initial release changes:\n\n"
    output.write_text(heading + context + logs + "\n", encoding="utf-8")
    print("Generated release notes from " + (base or "initial Git history"))


if __name__ == "__main__":
    main()
