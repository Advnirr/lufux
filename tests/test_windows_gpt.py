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

    def test_a_solid_esd_is_reported_not_raised(self):
        self.assertEqual(self.run_fake("exit 68")[0], W.WIMLIB_ERR_SOLID)

    def test_another_failure_raises_with_what_wimlib_said(self):
        with self.assertRaises(OSError) as caught:
            self.run_fake("echo 'ERROR: disk full'; exit 1")
        self.assertIn("disk full", str(caught.exception))

    def test_stopping_kills_it(self):
        with self.assertRaises(W.Stopped):
            self.run_fake("echo line; sleep 30", stopped=lambda: True)


if __name__ == "__main__":
    unittest.main()
