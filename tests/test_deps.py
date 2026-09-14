"""Dependency detection and the install command built from it.

The command is handed to pkexec, so it is built as argv lists and never as a
shell string; these tests are what keeps a package name from becoming one.
"""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import deps_logic as D


class InstallCommand(unittest.TestCase):
    def cmd(self, missing, base="arch"):
        with mock.patch.object(D, "get_distro_info", return_value=(base, "Test Linux")):
            return D.get_install_cmd(missing)

    def test_arch_installs_in_one_step(self):
        self.assertEqual(self.cmd(["wimlib-imagex"]),
                         [["pkexec", "pacman", "-S", "--noconfirm", "wimlib"]])

    def test_debian_updates_before_installing(self):
        self.assertEqual(self.cmd(["mkfs.ntfs"], base="debian"), [
            ["pkexec", "apt-get", "update"],
            ["pkexec", "apt-get", "install", "-y", "ntfs-3g"],
        ])

    def test_fedora_uses_its_own_package_names(self):
        self.assertEqual(self.cmd(["wimlib-imagex", "mkfs.ntfs"], base="fedora"),
                         [["pkexec", "dnf", "install", "-y", "ntfsprogs", "wimlib-utils"]])

    def test_packages_are_deduplicated_and_ordered(self):
        # mkfs.vfat and mkfs.ntfs on Debian are two packages, parted is one,
        # and asking twice must not install twice
        cmd = self.cmd(["parted", "parted", "mkfs.vfat"])
        self.assertEqual(cmd[0][-2:], ["dosfstools", "parted"])

    def test_one_command_can_need_two_packages(self):
        # Debian and Fedora ship grub-install and the BIOS modules separately
        self.assertEqual(self.cmd(["grub-install"], base="debian")[1][-2:],
                         ["grub-pc-bin", "grub2-common"])
        self.assertEqual(self.cmd(["grub-install"], base="fedora")[0][-2:],
                         ["grub2-pc-modules", "grub2-tools"])
        self.assertEqual(self.cmd(["grub-install"])[0][-1], "grub")

    def test_nothing_to_install_returns_nothing(self):
        self.assertIsNone(self.cmd([]))
        self.assertIsNone(self.cmd(["something-not-in-the-map"]))

    def test_an_unrecognised_distro_is_not_guessed_at(self):
        self.assertIsNone(self.cmd(["parted"], base="unknown"))

    def test_without_pkexec_there_is_nothing_to_elevate_with(self):
        # installing the elevation tool would itself need elevation
        self.assertIsNone(self.cmd(["pkexec", "parted"]))

    def test_the_command_is_argv_lists_never_a_shell_string(self):
        for base in ("arch", "debian", "fedora"):
            with self.subTest(base=base):
                for step in self.cmd(["parted", "grub-install"], base=base):
                    self.assertIsInstance(step, list)
                    self.assertTrue(all(isinstance(arg, str) for arg in step))
                    self.assertEqual(step[0], "pkexec")


class RequiredCommands(unittest.TestCase):
    def test_every_required_command_is_packaged_on_every_distro(self):
        with mock.patch.object(D, "_have_cmd", return_value=False):
            missing = D.check_dependencies(bios_boot=True)
        for base, packages in D.PKG_MAP.items():
            with self.subTest(base=base):
                self.assertEqual([cmd for cmd in missing if cmd not in packages], [])

    def test_windows_media_reports_every_tool_it_calls(self):
        # each of these runs after the wipe; dropping one from the list must fail
        with mock.patch.object(D, "_have_cmd", return_value=False):
            self.assertEqual(D.check_dependencies(), [
                "wimlib-imagex", "rsync", "parted", "pkexec", "mkfs.vfat", "mkfs.ntfs"])

    def test_the_dd_path_needs_only_pkexec(self):
        with mock.patch.object(D, "_have_cmd", return_value=False):
            self.assertEqual(D.check_dependencies(windows=False), ["pkexec"])
        with mock.patch.object(D, "_have_cmd", lambda name: name == "pkexec"):
            self.assertEqual(D.check_dependencies(windows=False), [])

    def test_a_command_only_in_sbin_counts_as_present(self):
        # sbin is off a normal user's PATH on Debian, where shutil.which alone
        # reports parted missing while it is installed
        with mock.patch.object(D.shutil, "which", return_value=None), \
             mock.patch.object(D.os, "access", lambda path, mode: path == "/sbin/parted"):
            self.assertTrue(D._have_cmd("parted"))
            self.assertFalse(D._have_cmd("rsync"))


class BiosGrub(unittest.TestCase):
    def check(self, bios_boot, have_cmds=(), have_module=False):
        # every other tool is present, so only the GRUB checks decide
        with mock.patch.object(D, "_have_cmd", lambda name: name in have_cmds or not name.startswith("grub")), \
             mock.patch.object(D.os.path, "isfile", lambda path: have_module and path == D.GRUB_BIOS_MODULE):
            return D.check_dependencies(bios_boot=bios_boot)

    def test_only_mbr_media_asks_for_grub(self):
        self.assertEqual(self.check(bios_boot=False), [])
        self.assertEqual(self.check(bios_boot=True), ["grub-install"])

    def test_fedoras_grub2_install_counts(self):
        self.assertEqual(self.check(True, have_cmds=("grub2-install",), have_module=True), [])

    def test_the_command_without_bios_modules_is_not_enough(self):
        # a UEFI-only GRUB has grub-install and would fail after the wipe
        self.assertEqual(self.check(True, have_cmds=("grub-install",)), ["grub-install"])


if __name__ == "__main__":
    unittest.main()
