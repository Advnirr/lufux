"""The dd mode: the copy itself and which disks udisks lets through."""
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import universal_logic as U


class Copy(unittest.TestCase):
    def run_copy(self, image, target, stopped=lambda: False):
        with tempfile.TemporaryDirectory() as tmp:
            iso = os.path.join(tmp, "image.iso")
            with open(iso, "wb") as f:
                f.write(image)
            dev = os.path.join(tmp, "dev")
            with open(dev, "wb") as f:
                f.write(target)
            fd = os.open(dev, os.O_RDWR)
            try:
                seen = []
                done = U.copy_image(iso, fd, lambda d, t: seen.append((d, t)), stopped)
            finally:
                os.close(fd)
            with open(dev, "rb") as f:
                return done, f.read(), seen

    def test_the_image_lands_at_the_start(self):
        image = os.urandom(U.CHUNK + 123)
        done, data, seen = self.run_copy(image, b"\xff" * (U.CHUNK * 3))
        self.assertTrue(done)
        self.assertEqual(data[:len(image)], image)
        self.assertEqual(seen[-1], (len(image), len(image)))

    def test_the_old_backup_gpt_is_wiped(self):
        done, data, _ = self.run_copy(b"\x01" * 4096, b"\xff" * (U.TAIL * 4))
        self.assertEqual(data[-U.TAIL:], bytes(U.TAIL))
        # what lies between the image and the tail is left alone
        self.assertEqual(data[4096:4097], b"\xff")

    def test_stopping_writes_nothing_more(self):
        image = os.urandom(U.CHUNK * 2)
        calls = []
        def stopped():
            calls.append(1)
            return len(calls) > 1
        done, data, _ = self.run_copy(image, bytes(U.CHUNK * 4), stopped)
        self.assertFalse(done)
        self.assertEqual(data[:U.CHUNK], image[:U.CHUNK])
        self.assertEqual(data[U.CHUNK:U.CHUNK * 2], bytes(U.CHUNK))


class Verify(unittest.TestCase):
    def check(self, image, target):
        with tempfile.TemporaryDirectory() as tmp:
            iso = os.path.join(tmp, "image.iso")
            with open(iso, "wb") as f:
                f.write(image)
            dev = os.path.join(tmp, "dev")
            with open(dev, "wb") as f:
                f.write(target)
            fd = os.open(dev, os.O_RDWR)
            try:
                return U.verify_image(iso, fd, lambda d, t: None, lambda: False)
            finally:
                os.close(fd)

    def test_a_good_copy_passes(self):
        image = os.urandom(U.CHUNK * 2 + 4096)
        self.assertTrue(self.check(image, image + bytes(U.CHUNK)))

    def test_a_changed_byte_fails(self):
        image = os.urandom(U.CHUNK * 2)
        bad = bytearray(image)
        bad[U.CHUNK + 5] ^= 1
        with self.assertRaises(U.Mismatch):
            self.check(image, bytes(bad))

    def test_a_drive_smaller_than_the_image_fails(self):
        image = os.urandom(U.CHUNK * 2)
        with self.assertRaises(U.Mismatch):
            self.check(image, image[:U.CHUNK])


def disk(dev, size=8 << 30, removable=False, bus="usb", partition=False):
    drive = "/drive/" + dev
    block = {"org.freedesktop.UDisks2.Block": {
        "Device": list(dev.encode()) + [0], "Size": size, "Drive": drive}}
    if partition:
        block["org.freedesktop.UDisks2.Partition"] = {}
    return {
        "/block/" + dev + ("p" if partition else ""): block,
        drive: {"org.freedesktop.UDisks2.Drive": {
            "Removable": removable, "ConnectionBus": bus, "Vendor": "Ven", "Model": "Stick"}},
    }


class Listing(unittest.TestCase):
    def listed(self, *disks):
        objects = {}
        for d in disks:
            objects.update(d)
        with mock.patch.object(U, "_objects", return_value=objects), \
             mock.patch.object(U, "_bus"):
            return [dev for dev, _, _ in U.list_drives()]

    def test_usb_and_removable_disks_are_listed(self):
        self.assertEqual(self.listed(disk("/dev/sdb"), disk("/dev/sdc", removable=True, bus="")),
                         ["/dev/sdb", "/dev/sdc"])

    def test_an_internal_disk_is_not(self):
        self.assertEqual(self.listed(disk("/dev/sda", bus="")), [])

    def test_nvme_and_partitions_are_not(self):
        # the nvme rule is issue #2: an enclosure looks like the system disk
        self.assertEqual(self.listed(disk("/dev/nvme1n1"), disk("/dev/sdb", partition=True)), [])

    def test_an_empty_card_reader_is_not(self):
        self.assertEqual(self.listed(disk("/dev/sdd", size=0, removable=True)), [])


if __name__ == "__main__":
    unittest.main()
