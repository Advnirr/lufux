#!/usr/bin/env python3
"""Set the version everywhere it is written: bump-version.py 1.3.7

main.py shows it in the About dialog, the PKGBUILD names the package, and both
READMEs carry a release badge. tests/test_version.py fails when they disagree.

What this does not touch, because it lives outside the repo: the AUR package,
whose pkgver() derives from the git tag. Tag and release first, then update it.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# file, pattern with the version as its one group, replacement template
EDITS = [
    ("main.py", r'^APP_VERSION = "([\d.]+)"', 'APP_VERSION = "{v}"'),
    ("PKGBUILD", r"^pkgver=([\d.]+)", "pkgver={v}"),
    ("README.md", r"badge/release-v([\d.]+)--stable", "badge/release-v{v}--stable"),
    ("README_ru.md", r"badge/release-v([\d.]+)--stable", "badge/release-v{v}--stable"),
]


def main(argv):
    if len(argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", argv[1]):
        raise SystemExit("usage: bump-version.py X.Y.Z")
    version = argv[1]

    for name, pattern, template in EDITS:
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
            f.write(text[:match.start()] + template.format(v=version) + text[match.end():])
        print(f"{name}: {match.group(1)} -> {version}")

    print("\nStill to do by hand: the changelog, the tag v{v}-stable, the GitHub "
          "release, and the AUR clone.".format(v=version))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
