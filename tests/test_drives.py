"""Keeping the chosen drive chosen, and what pkexec is asked to run as root.

Both guard against the same outcome from different directions: the wrong disk
being wiped, and the wrong program being run with the rights to wipe it.
"""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    spec = importlib.util.spec_from_file_location("lufux_main", os.path.join(ROOT, "main.py"))
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
except (ImportError, ValueError):  # GTK is not installed
    main = None


def display_available():
    try:
        return main is not None and main.Gtk.init_check()
    except Exception:  # noqa: BLE001
        return False


@unittest.skipIf(main is None, "GTK is not installed")
class Reselect(unittest.TestCase):
    DRIVES = ["sdb 8G Kingston", "sdc 16G SanDisk"]

    def test_the_choice_follows_its_device_when_another_stick_appears(self):
        self.assertEqual(main.reselect(["sda 32G Other", *self.DRIVES], "sdc", first=False), 2)

    def test_a_vanished_choice_selects_nothing_rather_than_another_drive(self):
        self.assertIsNone(main.reselect(["sdb 8G Kingston"], "sdc", first=False))

    def test_the_first_list_preselects_its_first_drive(self):
        self.assertEqual(main.reselect(self.DRIVES, None, first=True), 0)

    def test_no_choice_is_not_turned_into_one_later(self):
        self.assertIsNone(main.reselect(self.DRIVES, None, first=False))


@unittest.skipUnless(display_available(), "no display for GTK")
class RefreshKeepsTheSelection(unittest.TestCase):
    # a real Gtk.DropDown: set_model() resetting the selection is GTK behaviour,
    # so a stub would prove nothing
    def window(self, drives):
        win = main.LufuxWindow.__new__(main.LufuxWindow)
        win.current_step = 0
        win.last_drives = []
        win.drive_dropdown = main.Gtk.DropDown()
        win.update_ui_state = lambda: None
        win.get_usb_drives = lambda: drives[0]
        return win

    def test_a_stick_plugged_in_does_not_move_the_selection(self):
        drives = [["sdb 8G Kingston", "sdc 16G SanDisk"]]
        win = self.window(drives)
        win.auto_refresh_drives()
        win.drive_dropdown.set_selected(1)
        drives[0] = ["sda 32G Other", "sdb 8G Kingston", "sdc 16G SanDisk"]
        win.auto_refresh_drives()
        self.assertEqual(win.drive_dropdown.get_selected_item().get_string(), "sdc 16G SanDisk")

    def test_pulling_the_chosen_stick_does_not_select_the_other_one(self):
        # a DropDown cannot hold "nothing": INVALID_LIST_POSITION snaps back to
        # row 0, which would be exactly the silent switch this guards against
        drives = [["sdb 8G Kingston", "sdc 16G SanDisk"]]
        win = self.window(drives)
        win.auto_refresh_drives()
        win.drive_dropdown.set_selected(1)
        drives[0] = ["sdb 8G Kingston"]
        win.auto_refresh_drives()
        selected = win.drive_dropdown.get_selected_item().get_string()
        self.assertEqual(selected, main.T["pick_drive"])
        self.assertFalse(main.is_drive_row(selected))

    def test_the_placeholder_stays_until_a_drive_is_picked(self):
        drives = [["sdb 8G Kingston", "sdc 16G SanDisk"]]
        win = self.window(drives)
        win.auto_refresh_drives()
        win.drive_dropdown.set_selected(1)
        drives[0] = ["sdb 8G Kingston"]
        win.auto_refresh_drives()
        drives[0] = ["sdb 8G Kingston", "sdd 64G Other"]
        win.auto_refresh_drives()
        self.assertEqual(win.drive_dropdown.get_selected_item().get_string(), main.T["pick_drive"])

    def test_the_first_stick_is_preselected_as_before(self):
        drives = [[main.T["no_drives"]]]
        win = self.window(drives)
        win.auto_refresh_drives()
        drives[0] = ["sdb 8G Kingston"]
        win.auto_refresh_drives()
        self.assertEqual(win.drive_dropdown.get_selected_item().get_string(), "sdb 8G Kingston")


@unittest.skipIf(main is None, "GTK is not installed")
class DriveRows(unittest.TestCase):
    def test_only_real_drives_count(self):
        self.assertTrue(main.is_drive_row("sdb 8G Kingston"))
        self.assertFalse(main.is_drive_row(main.T["no_drives"]))
        self.assertFalse(main.is_drive_row(main.T["pick_drive"]))


@unittest.skipIf(main is None, "GTK is not installed")
class PkexecArgv(unittest.TestCase):
    def test_the_program_is_an_absolute_path_in_a_trusted_dir(self):
        argv = main.pkexec_argv("bash", "-c", "true")
        self.assertTrue(os.path.isabs(argv[1]))
        self.assertIn(os.path.dirname(argv[1]), main.TRUSTED_BIN_DIRS)
        self.assertEqual(argv[2:], ["-c", "true"])

    def test_a_program_outside_the_trusted_dirs_is_refused(self):
        with self.assertRaises(FileNotFoundError):
            main.pkexec_argv("lufux-no-such-program")

    def test_nothing_hands_pkexec_a_bare_program_name(self):
        with open(os.path.join(ROOT, "main.py"), encoding="utf-8") as f:
            source = f.read()
        self.assertNotRegex(source, r"resolve_bin\('pkexec'\),\s*'")


if __name__ == "__main__":
    unittest.main()
