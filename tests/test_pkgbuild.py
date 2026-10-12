"""The PKGBUILD's sha256sums must match the files. Run updpkgsums when this fails."""
import glob
import hashlib
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def array(name, text):
    match = re.search(rf"^{name}=\((.*?)\)", text, re.MULTILINE | re.DOTALL)
    assert match, f"no {name} in PKGBUILD"
    return re.findall(r"""["']([^"']+)["']""", match.group(1))


class Pkgbuild(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, "PKGBUILD"), encoding="utf-8") as f:
            text = f.read()
        self.sources = array("source", text)
        self.sums = array("sha256sums", text)

    def test_every_source_has_its_sum(self):
        self.assertEqual(len(self.sources), len(self.sums))
        for source, expected in zip(self.sources, self.sums):
            with self.subTest(source=source):
                with open(os.path.join(ROOT, source), "rb") as f:
                    self.assertEqual(hashlib.sha256(f.read()).hexdigest(), expected)

    def test_every_module_is_packaged(self):
        modules = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "*_logic.py"))}
        self.assertEqual(modules - set(self.sources), set())


if __name__ == "__main__":
    unittest.main()
