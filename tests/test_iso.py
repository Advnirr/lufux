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
        self.assertEqual(I.identify("alpine-std 3.24.2 x86_64", "a.iso")[:2], ("Alpine Linux 3.24.2", "alpine"))
        self.assertEqual(I.identify("CACHYOS", "cachyos-desktop-linux-250928.iso")[1], "cachyos")
        self.assertEqual(I.identify("ARCH_202510", "archlinux-2025.10.01-x86_64.iso")[1], "archlinux")

    def test_a_flavour_wins_over_its_base(self):
        self.assertEqual(I.identify("Kubuntu 24.04 LTS amd64", "")[1], "kubuntu")

    def test_arch_inside_another_word_is_not_arch(self):
        self.assertIsNone(I.identify("RESEARCH_TOOLS", "")[1])

    def test_an_unknown_image_is_named_by_its_label(self):
        self.assertEqual(I.identify("ANALYSIS_TOOLS", "analysis-tools.iso"), ("ANALYSIS_TOOLS", None, I.UNKNOWN_COLOR))
        self.assertEqual(I.identify("", "my-image.iso")[0], "my-image")

    def test_windows_takes_its_version_from_the_editions(self):
        self.assertEqual(I.identify("CES_X64FREV_EN-US_DV9", "x.iso", windows=True)[1], "windows")
        self.assertEqual(I.windows_name([(1, "Windows 11 Enterprise LTSC", 0)]), "Windows 11")
        self.assertEqual(I.windows_name([]), "Windows")


class Badge(unittest.TestCase):
    def test_only_a_letter_or_digit_reaches_the_svg(self):
        self.assertIn(b">X</text>", I.badge_svg("<x", "#000"))
        self.assertIn(b">C</text>", I.badge_svg("cachyos", "#000"))


if __name__ == "__main__":
    unittest.main()
