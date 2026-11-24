"""Release helper: one version across the Python package and the Mac app, and the changelog.

    python scripts/release.py 0.2.0             # set every version to 0.2.0; move "Unreleased" to "0.2.0"
    python scripts/release.py --check           # every version agrees (CI)
    python scripts/release.py --check v0.2.0    # ...and matches this tag, with a changelog section (release CI)
    python scripts/release.py --notes 0.2.0     # print that version's changelog section (release notes)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?")

# (file, pattern with one group around the version): the first match is the version.
FILES = [
    ("src/dsd/__init__.py", r'^__version__ = "([^"]+)"'),
    ("app/src-tauri/tauri.conf.json", r'^  "version": "([^"]+)"'),
    ("app/src-tauri/Cargo.toml", r'^\[package\]\nname = "dsd-app"\nversion = "([^"]+)"'),
    ("app/src-tauri/Cargo.lock", r'^name = "dsd-app"\nversion = "([^"]+)"'),
]


def versions() -> dict[str, str]:
    out = {}
    for rel, pattern in FILES:
        m = re.search(pattern, (ROOT / rel).read_text(), re.M)
        if not m:
            raise SystemExit(f"{rel}: no version found")
        out[rel] = m.group(1)
    return out


def set_version(version: str) -> None:
    for rel, pattern in FILES:
        path = ROOT / rel
        text = path.read_text()
        m = re.search(pattern, text, re.M)
        if not m:
            raise SystemExit(f"{rel}: no version found")
        path.write_text(text[: m.start(1)] + version + text[m.end(1):])


def notes(version: str) -> str | None:
    m = re.search(rf"^## \[?{re.escape(version)}\]?.*?\n(.*?)(?=^## |\Z)", CHANGELOG.read_text(), re.M | re.S)
    return m.group(1).strip() if m else None


def cut_changelog(version: str) -> None:
    text = CHANGELOG.read_text()
    if notes(version) is not None:
        return
    m = re.search(r"^## Unreleased\n", text, re.M)
    if not m:
        raise SystemExit("CHANGELOG.md has no '## Unreleased' section")
    heading = f"## Unreleased\n\n## {version} - {date.today().isoformat()}\n"
    CHANGELOG.write_text(text[: m.start()] + heading + text[m.end():])


def check(tag: str | None) -> list[str]:
    found = versions()
    problems = []
    if len(set(found.values())) > 1:
        problems.append("versions differ: " + ", ".join(f"{k}={v}" for k, v in found.items()))
    if tag:
        want = tag.removeprefix("v")
        problems += [f"{k} is {v}, tag is {tag}" for k, v in found.items() if v != want]
        if not notes(want):
            problems.append(f"CHANGELOG.md has no notes under '## {want}'")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", help="new version, e.g. 0.2.0")
    ap.add_argument("--check", nargs="?", const="", metavar="TAG", help="check versions agree (and match TAG)")
    ap.add_argument("--notes", metavar="VERSION", help="print a version's changelog section")
    args = ap.parse_args(argv)

    if args.notes:
        body = notes(args.notes.removeprefix("v"))
        if not body:
            print(f"no notes for {args.notes}", file=sys.stderr)
            return 1
        print(body)
        return 0
    if args.check is not None:
        problems = check(args.check or None)
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        if not problems:
            print(f"ok: {next(iter(versions().values()))}")
        return 1 if problems else 0
    if not args.version or not SEMVER.fullmatch(args.version):
        ap.error("give a version like 0.2.0")
    set_version(args.version)
    cut_changelog(args.version)
    print(f"set version {args.version}; now fill in CHANGELOG.md under '## {args.version}', then open a release PR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
