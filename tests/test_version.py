"""The version is written in six places; this fails when they drift apart.

main.py, the PKGBUILD, the RPM spec, the Debian control file and both READMEs.
Shipping with one of them stale has happened before.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def find(pattern, name):
    match = re.search(pattern, read(name), re.MULTILINE)
    assert match, f"no version found in {name}"
    return match.group(1)


class Version(unittest.TestCase):
    def setUp(self):
        self.version = find(r'^APP_VERSION = "([^"]+)"', "main.py")

    def test_it_looks_like_a_version(self):
        self.assertRegex(self.version, r"^\d+\.\d+\.\d+$")

    def test_the_package_is_built_at_the_same_version(self):
        self.assertEqual(find(r"^pkgver=(\S+)", "PKGBUILD"), self.version)

    def test_the_deb_and_rpm_agree(self):
        self.assertEqual(find(r"^Version:\s+(\S+)", "packaging/lufux.spec"), self.version)
        self.assertEqual(find(r"^Version: (\S+)", "packaging/deb/control"), self.version)

    def test_both_readme_badges_agree(self):
        for name in ("README.md", "README_ru.md"):
            with self.subTest(readme=name):
                badge = find(r"badge/release-v([\d.]+)--stable", name)
                self.assertEqual(badge, self.version)


if __name__ == "__main__":
    unittest.main()
