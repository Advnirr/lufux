"""gpt_guids reads a GPT itself; check it against a disk parted made and sfdisk reads.

The GUIDs go into the BCD as raw bytes and are never printed, so a mixed-endian
slip here produces a store that boots nothing and says nothing about why.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import bcd_logic as B

HAVE_TOOLS = all(shutil.which(t) for t in ("parted", "sfdisk"))


@unittest.skipUnless(HAVE_TOOLS, "needs parted and sfdisk")
class GptGuids(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lufux-test-")
        cls.img = os.path.join(cls.tmp, "gpt.img")
        with open(cls.img, "wb") as f:
            f.truncate(64 << 20)
        # the same two-partition layout the Windows To Go script lays down
        subprocess.run(["parted", "-s", cls.img, "mklabel", "gpt",
                        "mkpart", "ESP", "fat32", "1MiB", "33MiB",
                        "mkpart", "Windows", "ntfs", "33MiB", "100%"],
                       check=True, capture_output=True)
        out = subprocess.run(["sfdisk", "--json", cls.img],
                             check=True, capture_output=True, text=True).stdout
        cls.table = json.loads(out)["partitiontable"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_disk_guid_matches_sfdisk(self):
        _, disk = B.gpt_guids(self.img, 2)
        self.assertEqual(str(uuid.UUID(bytes_le=disk)).upper(), self.table["id"])

    def test_partition_guid_matches_sfdisk(self):
        for number in (1, 2):
            with self.subTest(partition=number):
                part, _ = B.gpt_guids(self.img, number)
                expected = self.table["partitions"][number - 1]["uuid"]
                self.assertEqual(str(uuid.UUID(bytes_le=part)).upper(), expected)

    def test_guids_are_raw_and_of_the_right_length(self):
        part, disk = B.gpt_guids(self.img, 2)
        self.assertEqual((len(part), len(disk)), (16, 16))
        # bytes_le, not the printed order: the same UUID read the other way
        # round must not match
        self.assertNotEqual(str(uuid.UUID(bytes=part)).upper(),
                            self.table["partitions"][1]["uuid"])

    def test_an_unused_partition_is_refused(self):
        with self.assertRaises(ValueError):
            B.gpt_guids(self.img, 3)

    def test_a_disk_without_a_gpt_is_refused(self):
        empty = os.path.join(self.tmp, "empty.img")
        with open(empty, "wb") as f:
            f.truncate(8 << 20)
        with self.assertRaises(ValueError):
            B.gpt_guids(empty, 1)

    def test_the_guids_reach_the_store_unchanged(self):
        part, disk = B.gpt_guids(self.img, 2)
        store = B.build_bcd(part, disk)
        # raw, so they appear in the hive exactly as the GPT holds them
        self.assertIn(part, store)
        self.assertIn(disk, store)


if __name__ == "__main__":
    unittest.main()
