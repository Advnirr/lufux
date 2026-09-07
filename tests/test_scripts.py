"""The deployment scripts are built by string formatting, which has its own traps.

A stray brace or an unescaped one silently produces a script that does something
other than intended, and the image index reaches a root shell.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from windows_togo_logic import get_windows_togo_script
from windows_logic import get_windows_script
from universal_logic import get_linux_script


class Formatting(unittest.TestCase):
    def scripts(self):
        return {
            "windows to go": get_windows_togo_script(1),
            "windows": get_windows_script("gpt"),
            "linux": get_linux_script(),
        }

    def test_no_doubled_braces_survive_formatting(self):
        # "${{DEV_PATH}}" in the template must come out as "${DEV_PATH}"
        for name, script in self.scripts().items():
            with self.subTest(script=name):
                self.assertNotIn("{{", script)
                self.assertNotIn("}}", script)

    def test_every_script_is_bash_with_pipefail(self):
        for name, script in self.scripts().items():
            with self.subTest(script=name):
                self.assertTrue(script.lstrip().startswith("#!/bin/bash"))
                self.assertIn("set -eo pipefail", script)


class ImageIndex(unittest.TestCase):
    def test_the_index_is_interpolated_as_a_number(self):
        self.assertIn('IMG_INDEX="3"', get_windows_togo_script(3))

    def test_a_non_numeric_index_is_refused(self):
        # the value reaches a root shell, so it never travels as free text
        with self.assertRaises(ValueError):
            get_windows_togo_script("1; rm -rf /")


class NtfsGeometry(unittest.TestCase):
    def setUp(self):
        self.script = get_windows_togo_script(1)

    def test_the_partition_start_is_handed_to_mkntfs(self):
        # left to itself mkntfs writes zero wherever the kernel cannot answer
        # its geometry ioctls, and Windows then cannot find the volume
        self.assertIn("/sys/class/block/$PART_NAME/start", self.script)
        self.assertIn("-p $((PART_START * 512 / SECTOR_SIZE))", self.script)
        self.assertIn("mkfs.ntfs -f $NTFS_START", self.script)

    def test_the_esp_is_512_mib_and_windows_follows_it(self):
        self.assertIn('mkpart ESP fat32 1MiB 513MiB', self.script)
        self.assertIn('mkpart Windows ntfs 513MiB 100%', self.script)


if __name__ == "__main__":
    unittest.main()
