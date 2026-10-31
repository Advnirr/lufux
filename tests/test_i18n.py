"""Translations: every string in the code has one, and nothing breaks its format."""
import ast
import glob
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import i18n

POS = sorted(glob.glob(os.path.join(ROOT, "po", "*.po")))


def code_strings():
    """Every literal passed to _() in the app's modules."""
    found = set()
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "_" and node.args
                    and isinstance(node.args[0], ast.Constant)):
                found.add(node.args[0].value)
    return found


class Catalogs(unittest.TestCase):
    def test_there_is_a_russian_one(self):
        self.assertIn(os.path.join(ROOT, "po", "ru.po"), POS)

    def test_every_string_is_translated_and_none_is_stale(self):
        strings = code_strings()
        for po in POS:
            with self.subTest(po=os.path.basename(po)):
                catalog = i18n.read_po(po)
                self.assertEqual(strings - catalog.keys(), set(), "run tools/update-po.sh")
                self.assertEqual(catalog.keys() - strings, set(), "run tools/update-po.sh")

    def test_placeholders_and_markup_survive(self):
        # a {name} lost in translation is a KeyError in .format() at runtime
        for po in POS:
            for msgid, msgstr in i18n.read_po(po).items():
                with self.subTest(po=os.path.basename(po), msgid=msgid[:40]):
                    self.assertEqual(sorted(re.findall(r"{\w*}", msgid)),
                                     sorted(re.findall(r"{\w*}", msgstr)))
                    self.assertEqual(sorted(re.findall(r"</?\w+>", msgid)),
                                     sorted(re.findall(r"</?\w+>", msgstr)))

    @unittest.skipUnless(shutil.which("msgfmt"), "needs msgfmt")
    def test_msgfmt_reads_the_same_as_read_po(self):
        import gettext
        for po in POS:
            with self.subTest(po=os.path.basename(po)), tempfile.NamedTemporaryFile() as mo:
                subprocess.run(["msgfmt", "--check", "-o", mo.name, po], check=True)  # nosec B603 B607
                with open(mo.name, "rb") as f:
                    compiled = gettext.GNUTranslations(f)
                for msgid, msgstr in i18n.read_po(po).items():
                    self.assertEqual(compiled.gettext(msgid), msgstr)


class Picking(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("C")

    def env(self, **values):
        return mock.patch.dict(os.environ, values, clear=True)

    def test_the_saved_choice_wins_over_the_locale(self):
        with self.env(LANG="en_US.UTF-8"):
            i18n.set_language("ru_RU.UTF-8")
        self.assertEqual(i18n.language(), "ru")
        self.assertEqual(i18n._("Next"), "Далее")

    def test_lc_messages_is_followed(self):
        with self.env(LANG="en_US.UTF-8", LC_MESSAGES="ru_RU.UTF-8"):
            i18n.set_language()
        self.assertEqual(i18n.language(), "ru")

    def test_language_comes_first(self):
        with self.env(LANGUAGE="de:ru", LANG="en_US.UTF-8"):
            i18n.set_language()
        self.assertEqual(i18n.language(), "ru")

    def test_english_and_c_are_untranslated(self):
        for lang in ("en_US.UTF-8", "C"):
            i18n.set_language(lang)
            self.assertEqual(i18n.language(), "en")
            self.assertEqual(i18n._("Next"), "Next")


if __name__ == "__main__":
    unittest.main()
