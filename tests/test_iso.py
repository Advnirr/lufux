"""Naming the system in an ISO."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import iso_logic as I


class Label(unittest.TestCase):
    def test_the_label_is_read_from_the_volume_descriptor(self):
        pvd = bytearray(2048)
        pvd[1:6] = b"CD001"
        pvd[40:72] = b"CACHYOS_202509".ljust(32)
        with tempfile.NamedTemporaryFile() as f:
            f.write(bytes(I.PVD_OFFSET) + pvd)
            f.flush()
            self.assertEqual(I.volume_label(f.name), "CACHYOS_202509")

    def test_a_file_that_is_no_iso_has_no_label(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(bytes(I.PVD_OFFSET + 2048))
            f.flush()
            self.assertEqual(I.volume_label(f.name), "")


class Identify(unittest.TestCase):
    def test_known_systems(self):
        self.assertEqual(I.identify("alpine-std 3.24.2 x86_64", "a.iso"), "Alpine Linux 3.24.2")
        self.assertEqual(I.identify("CACHYOS", "cachyos-desktop-linux-250928.iso"), "CachyOS")
        self.assertEqual(I.identify("ARCH_202510", "archlinux-2025.10.01-x86_64.iso"), "Arch Linux 2025.10.01")

    def test_a_flavour_wins_over_its_base(self):
        self.assertEqual(I.identify("Kubuntu 24.04 LTS amd64", ""), "Kubuntu 24.04")

    def test_arch_inside_another_word_is_not_arch(self):
        self.assertEqual(I.identify("RESEARCH_TOOLS", ""), "RESEARCH_TOOLS")

    def test_an_unknown_image_is_named_by_its_label(self):
        self.assertEqual(I.identify("ANALYSIS_TOOLS", "analysis-tools.iso"), "ANALYSIS_TOOLS")
        self.assertEqual(I.identify("", "my-image.iso"), "my-image")

    def test_windows_takes_its_version_from_the_editions(self):
        self.assertEqual(I.windows_name([(1, "Windows 11 Enterprise LTSC", 0)]), "Windows 11")
        self.assertEqual(I.windows_name([]), "Windows")


class Kind(unittest.TestCase):
    def kind(self, data):
        with tempfile.NamedTemporaryFile() as f:
            f.write(data)
            f.flush()
            return I.iso_kind(f.name)

    def test_windows_in_utf16_as_udf_stores_it(self):
        self.assertEqual(self.kind(bytes(1001) + "install.wim".encode("utf-16-be")), 0)

    def test_windows_wins_over_linux(self):
        self.assertEqual(self.kind(b"grub.cfg" + bytes(100) + b"BOOT.WIM"), 0)

    def test_linux(self):
        self.assertEqual(self.kind(b"..casper.."), 1)

    def test_a_name_across_two_chunks(self):
        self.assertEqual(self.kind(bytes(I.ISO_CHUNK - 4) + b"install.esd"), 0)

    def test_nothing_known_and_a_missing_file(self):
        self.assertEqual(self.kind(b"hello"), 2)
        self.assertEqual(I.iso_kind("/nonexistent.iso"), 2)


if __name__ == "__main__":
    unittest.main()
