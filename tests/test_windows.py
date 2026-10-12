"""Windows installer media through udisks: the parts that need no drive."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import windows_logic as W


class CopyTree(unittest.TestCase):
    def test_everything_but_the_image_is_copied(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            os.makedirs(os.path.join(src, "sources"))
            os.makedirs(os.path.join(src, "efi", "boot"))
            for name, data in (("setup.exe", b"a"), ("efi/boot/bootx64.efi", b"bb"),
                               ("sources/boot.wim", b"ccc"), ("sources/install.wim", b"big")):
                with open(os.path.join(src, name), "wb") as f:
                    f.write(data)
            seen = []
            W._copy_tree(src, dst, W.WIM_NAMES, lambda d, t: seen.append((d, t)), lambda: False)
            self.assertFalse(os.path.exists(os.path.join(dst, "sources", "install.wim")))
            with open(os.path.join(dst, "efi", "boot", "bootx64.efi"), "rb") as f:
                self.assertEqual(f.read(), b"bb")
            self.assertEqual(seen[-1], (6, 6))

    def test_stopping_raises(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            with open(os.path.join(src, "setup.exe"), "wb") as f:
                f.write(b"a")
            with self.assertRaises(W.Stopped):
                W._copy_tree(src, dst, W.WIM_NAMES, lambda d, t: None, lambda: True)


class Wimlib(unittest.TestCase):
    def run_fake(self, body, stopped=lambda: False):
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "wimlib-imagex")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\n" + body + "\n")
            os.chmod(fake, 0o755)
            seen = []
            with mock.patch.object(W.shutil, "which", return_value=fake):
                code = W._wimlib(["split"], lambda d, t: seen.append((d, t)), stopped)
            return code, seen

    def test_progress_is_read_in_bytes(self):
        code, seen = self.run_fake(
            r"printf 'Splitting WIM: 60 MiB of 4107 MiB (1%%) written\r'")
        self.assertEqual(code, 0)
        self.assertEqual(seen, [(60 << 20, 4107 << 20)])

    def test_apply_progress_in_gib(self):
        _, seen = self.run_fake(
            r"printf 'Extracting file data: 3 GiB of 11 GiB (27%%) done\r'")
        self.assertEqual(seen, [(3 << 30, 11 << 30)])

    def test_a_solid_esd_is_reported_not_raised(self):
        self.assertEqual(self.run_fake("exit 68")[0], W.WIMLIB_ERR_SOLID)

    def test_another_failure_raises_with_what_wimlib_said(self):
        with self.assertRaises(OSError) as caught:
            self.run_fake("echo 'ERROR: disk full'; exit 1")
        self.assertIn("disk full", str(caught.exception))

    def test_stopping_kills_it(self):
        with self.assertRaises(W.Stopped):
            self.run_fake("echo line; sleep 30", stopped=lambda: True)


def fake_core(sectors):
    """A core.img: no_rs_length set, an old blocklist left in the first sector."""
    core = bytearray(sectors * 512)
    core[W.NO_RS_LENGTH:W.NO_RS_LENGTH + 2] = (0x400).to_bytes(2, "little")
    core[500:512] = (7).to_bytes(8, "little") + (3).to_bytes(2, "little") + (0x900).to_bytes(2, "little")
    return bytes(core[:-100])


class BiosBoot(unittest.TestCase):
    def setUp(self):
        self.boot_img = bytes(range(256)) * 2
        self.sector0 = bytearray(512)
        self.sector0[0x1b8:0x1fe] = b"\xab" * (0x1fe - 0x1b8)
        self.boot, self.core = W.bios_boot_code(self.boot_img, fake_core(20), bytes(self.sector0))

    def test_the_partition_table_survives(self):
        self.assertEqual(self.boot[0x1b8:0x1fe], b"\xab" * (0x1fe - 0x1b8))
        self.assertEqual(self.boot[0x1fe:], self.boot_img[0x1fe:])

    def test_boot_img_points_at_sector_1(self):
        self.assertEqual(int.from_bytes(self.boot[0x5c:0x64], "little"), 1)
        self.assertEqual(self.boot[0x64], 0xFF)
        self.assertEqual(self.boot[0x66:0x68], b"\x90\x90")

    def test_the_blocklist_loads_the_rest_after_the_first_sector(self):
        self.assertEqual(len(self.core), 20 * 512)
        start = int.from_bytes(self.core[500:508], "little")
        length = int.from_bytes(self.core[508:510], "little")
        segment = int.from_bytes(self.core[510:512], "little")
        self.assertEqual((start, length, segment), (2, 19, 0x820))
        # and a terminator below it
        self.assertEqual(self.core[488:500], bytes(12))

    def test_a_core_too_big_for_the_gap_is_refused(self):
        with self.assertRaises(OSError):
            W.bios_boot_code(self.boot_img, fake_core(2048), bytes(512))


if __name__ == "__main__":
    unittest.main()
