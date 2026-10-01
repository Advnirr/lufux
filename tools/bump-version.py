#!/usr/bin/env python3
"""Set the version everywhere it is written: bump-version.py 1.3.7

It lives in main.py, the PKGBUILD, the RPM spec, the Debian control file and
both READMEs. tests/test_version.py fails when they disagree.

What this does not touch, because it lives outside the repo: the AUR package,
whose pkgver() derives from the git tag. Tag and release first, then update it.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# file, pattern with the version as its one group
EDITS = [
    ("main.py", r'^APP_VERSION = "([\d.]+)"'),
    ("PKGBUILD", r"^pkgver=([\d.]+)"),
    ("packaging/lufux.spec", r"^Version:\s+([\d.]+)"),
    ("packaging/deb/control", r"^Version: ([\d.]+)"),
    ("README.md", r"badge/release-v([\d.]+)--stable"),
    ("README_ru.md", r"badge/release-v([\d.]+)--stable"),
]


def main(argv):
    if len(argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        raise SystemExit("usage: bump-version.py X.Y.Z")
    version = argv[1]

    for name, pattern in EDITS:
        path = os.path.join(ROOT, name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            raise SystemExit(f"{name}: no version to replace, pattern changed?")
        if match.group(1) == version:
            print(f"{name}: already {version}")
            continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(text[:match.start(1)] + version + text[match.end(1):])
        print(f"{name}: {match.group(1)} -> {version}")

    print("\nStill to do by hand: the changelog, the tag v{v}-stable, the GitHub "
          "release, and the AUR clone.".format(v=version))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
