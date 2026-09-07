"""The pre-flight capacity check, and the wimlib parsing it depends on.

A Windows To Go deployment runs for hours, so "no space left on device" has to
be caught before the drive is wiped rather than at the end of the apply.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    spec = importlib.util.spec_from_file_location("lufux_main", os.path.join(ROOT, "main.py"))
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
except (ImportError, ValueError):  # GTK is not installed
    main = None

GIB = 1024 ** 3
# the listing wimlib prints for a two-edition install.wim, trimmed to the keys
# the parser looks at
WIM_INFO = """\
WIM Information:
Path:           install.wim
Image Count:    2

Available Images:
------------------
Index:                  1
Name:                   Windows 11 Pro
Description:            Windows 11 Pro
Directory Count:        20000
File Count:             90000
Total Bytes:            16106127360

Index:                  2
Name:                   Windows 11 Home
Display Name:           Windows 11 Home
Total Bytes:            15032385536
"""


class Dropdown:
    def __init__(self, selected=0, active=True):
        self.selected, self.active = selected, active

    def get_selected(self):
        return self.selected

    def get_active(self):
        return self.active


@unittest.skipIf(main is None, "needs the GTK bindings main.py imports")
class ParseWimInfo(unittest.TestCase):
    def test_reads_index_name_and_size(self):
        self.assertEqual(main.parse_wim_info(WIM_INFO), [
            (1, "Windows 11 Pro", 16106127360),
            (2, "Windows 11 Home", 15032385536),
        ])

    def test_display_name_is_not_mistaken_for_the_name(self):
        names = [name for _, name, _ in main.parse_wim_info(WIM_INFO)]
        self.assertEqual(names.count("Windows 11 Home"), 1)

    def test_a_listing_without_sizes_still_yields_the_editions(self):
        info = "Index:  1\nName:   Windows 11 Pro\n"
        self.assertEqual(main.parse_wim_info(info), [(1, "Windows 11 Pro", 0)])

    def test_nothing_readable_yields_nothing(self):
        self.assertEqual(main.parse_wim_info(""), [])
        self.assertEqual(main.parse_wim_info("Total Bytes: 123\n"), [])


@unittest.skipIf(main is None, "needs the GTK bindings main.py imports")
class FormatSize(unittest.TestCase):
    def test_gibibytes_above_a_gibibyte(self):
        self.assertEqual(main.fmt_size(16 * GIB), "16.0 GiB")

    def test_mebibytes_below_it(self):
        # a netinst ISO must not be reported as 0.0 GiB
        self.assertEqual(main.fmt_size(620 * 1024 ** 2), "620 MiB")


@unittest.skipIf(main is None, "needs the GTK bindings main.py imports")
class CapacityProblem(unittest.TestCase):
    def window(self, image_bytes=12 * GIB, wtg=True, iso_path="/nonexistent.iso"):
        """A stand-in carrying only the attributes capacity_problem reads."""
        win = main.LufuxWindow.__new__(main.LufuxWindow)
        win.selected_dev = "/dev/stub"
        win.os_dropdown = Dropdown(0)
        win.wtg_check = Dropdown(active=wtg)
        win.edition_dropdown = Dropdown(0)
        win.editions = [(1, "Pro", image_bytes)]
        win.iso_path = iso_path
        return win

    def check(self, drive_bytes, **kwargs):
        win = self.window(**kwargs)
        with mock.patch.object(main, "device_size_bytes", return_value=drive_bytes):
            return win.capacity_problem()

    def test_a_drive_with_room_to_spare_passes(self):
        self.assertIsNone(self.check(32 * GIB))

    def test_an_image_larger_than_the_drive_is_blocked(self):
        kind, needed, size = self.check(8 * GIB)
        self.assertEqual(kind, "block")
        self.assertGreater(needed, size)

    def test_the_esp_counts_towards_what_is_needed(self):
        # 12 GiB image on a 12 GiB drive cannot fit: the ESP goes first
        self.assertEqual(self.check(12 * GIB)[0], "block")

    def test_a_fit_that_leaves_windows_no_room_warns(self):
        self.assertEqual(self.check(14 * GIB)[0], "tight")

    def test_an_unknown_drive_size_does_not_stop_a_flash(self):
        self.assertIsNone(self.check(0))

    def test_an_unknown_image_size_does_not_stop_a_flash(self):
        self.assertIsNone(self.check(8 * GIB, image_bytes=0))

    def test_other_modes_measure_the_iso_itself(self):
        with tempfile.NamedTemporaryFile() as iso:
            iso.truncate(700 * 1024 ** 2)
            self.assertIsNone(self.check(8 * GIB, wtg=False, iso_path=iso.name))
            kind, _, _ = self.check(512 * 1024 ** 2, wtg=False, iso_path=iso.name)
            self.assertEqual(kind, "block")

    def test_other_modes_are_not_held_to_the_windows_margin(self):
        # only Windows To Go needs room left over; a Linux ISO filling the
        # drive is fine
        with tempfile.NamedTemporaryFile() as iso:
            iso.truncate(7 * GIB)
            self.assertIsNone(self.check(8 * GIB, wtg=False, iso_path=iso.name))

    def test_a_missing_iso_does_not_stop_a_flash(self):
        self.assertIsNone(self.check(8 * GIB, wtg=False))


if __name__ == "__main__":
    unittest.main()
