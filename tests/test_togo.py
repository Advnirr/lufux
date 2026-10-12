"""Windows To Go: the parts that need no drive."""
import os
import struct
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import windows_togo_logic as G


def ntfs_volume(path, sectors):
    """A file with an NTFS boot sector at 0 and its backup after the volume."""
    boot = bytearray(512)
    boot[3:11] = b"NTFS    "
    struct.pack_into("<H", boot, 0x0b, 512)
    struct.pack_into("<Q", boot, 0x28, sectors)
    with open(path, "wb") as f:
        f.write(boot)
        f.seek(sectors * 512)
        f.write(boot)


class NtfsStart(unittest.TestCase):
    def test_both_boot_sectors_get_the_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ntfs.img")
            ntfs_volume(path, 100)
            fd = os.open(path, os.O_RDWR)
            try:
                G.set_ntfs_start(fd, 1050624)
                for at in (0, 100 * 512):
                    self.assertEqual(struct.unpack("<I", os.pread(fd, 4, at + 0x1c))[0], 1050624)
            finally:
                os.close(fd)

    def test_something_else_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "empty.img")
            with open(path, "wb") as f:
                f.truncate(4096)
            fd = os.open(path, os.O_RDWR)
            try:
                with self.assertRaises(OSError):
                    G.set_ntfs_start(fd, 2048)
                self.assertEqual(os.pread(fd, 4096, 0), bytes(4096))
            finally:
                os.close(fd)


if __name__ == "__main__":
    unittest.main()
