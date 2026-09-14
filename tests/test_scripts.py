"""The deployment scripts are built by string formatting, which has its own traps.

A stray brace or an unescaped one silently produces a script that does something
other than intended, and the image index reaches a root shell.
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from windows_togo_logic import get_windows_togo_script
from windows_logic import get_windows_script
from universal_logic import get_linux_script


class Formatting(unittest.TestCase):
    def scripts(self):
        return {
            "windows to go": get_windows_togo_script(1),
            "windows gpt": get_windows_script("gpt"),
            "windows mbr": get_windows_script("mbr"),
            "linux": get_linux_script(),
        }

    def test_no_doubled_braces_survive_formatting(self):
        # "${{DEV_PATH}}" in the template must come out as "${DEV_PATH}"
        for name, script in self.scripts().items():
            with self.subTest(script=name):
                self.assertNotIn("{{", script)
                self.assertNotIn("}}", script)

    def test_every_script_is_bash_with_pipefail(self):
        for name, script in self.scripts().items():
            with self.subTest(script=name):
                self.assertTrue(script.lstrip().startswith("#!/bin/bash"))
                self.assertIn("set -eo pipefail", script)


class ImageIndex(unittest.TestCase):
    def test_the_index_is_interpolated_as_a_number(self):
        self.assertIn('IMG_INDEX="3"', get_windows_togo_script(3))

    def test_a_non_numeric_index_is_refused(self):
        # the value reaches a root shell, so it never travels as free text
        with self.assertRaises(ValueError):
            get_windows_togo_script("1; rm -rf /")


class NtfsGeometry(unittest.TestCase):
    def setUp(self):
        self.script = get_windows_togo_script(1)

    def test_the_partition_start_is_handed_to_mkntfs(self):
        # left to itself mkntfs writes zero wherever the kernel cannot answer
        # its geometry ioctls, and Windows then cannot find the volume
        self.assertIn("/sys/class/block/$PART_NAME/start", self.script)
        self.assertIn("-p $((PART_START * 512 / SECTOR_SIZE))", self.script)
        self.assertIn("mkfs.ntfs -f $NTFS_START", self.script)

    def test_the_esp_is_512_mib_and_windows_follows_it(self):
        self.assertIn('mkpart ESP fat32 1MiB 513MiB', self.script)
        self.assertIn('mkpart Windows ntfs 513MiB 100%', self.script)


class LegacyBiosBoot(unittest.TestCase):
    def setUp(self):
        self.mbr = get_windows_script("mbr")
        self.gpt = get_windows_script("gpt")

    def test_mbr_media_gets_bios_boot_code(self):
        # without it the drive hangs at "Booting from Hard Disk..."
        self.assertIn('--target=i386-pc --boot-directory="$USB_MNT" --force "$DEV_PATH"', self.mbr)
        self.assertIn("ntldr /bootmgr", self.mbr)

    def test_grub_modules_are_loaded_by_name(self):
        # autoloading found nothing when GRUB booted from the NTFS volume
        for module in ("part_msdos", "ntfs", "ntldr"):
            with self.subTest(module=module):
                self.assertIn(f"insmod {module}", self.mbr)

    def test_grub_is_installed_before_the_drive_is_unmounted(self):
        self.assertLess(self.mbr.index("grub-install"), self.mbr.index('umount "$USB_MNT"'))

    def test_uefi_media_is_left_without_grub(self):
        self.assertNotIn("grub-install", self.gpt)

    def test_mbr_passes_the_partition_start_to_mkntfs(self):
        self.assertIn("mkfs.ntfs -f $NTFS_START", self.mbr)

    def test_partitions_are_named_for_devices_ending_in_a_digit(self):
        for name, script in (("mbr", self.mbr), ("gpt", self.gpt)):
            with self.subTest(scheme=name):
                self.assertIn('*[0-9]) PS="p"', script)
                self.assertNotIn('"${DEV_PATH}1"', script)


class LinuxDd(unittest.TestCase):
    def test_a_failed_dd_says_why_in_the_log(self):
        # run the real script with dd, wipefs, umount and sync replaced, against
        # a temporary file: only the progress loop is under test
        fakes = {
            "umount": "exit 0",
            "wipefs": "exit 0",
            "sync": "exit 0",
            "dd": ("echo \"dd: error writing 'target': No space left on device\" >&2\n"
                   "echo '0+1 records in' >&2\necho '0+0 records out' >&2\nexit 1"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            bindir = os.path.join(tmp, "bin")
            os.mkdir(bindir)
            for name, body in fakes.items():
                path = os.path.join(bindir, name)
                with open(path, "w") as f:
                    f.write("#!/bin/sh\n" + body + "\n")
                os.chmod(path, 0o755)
            iso = os.path.join(tmp, "image.iso")
            with open(iso, "wb") as f:
                f.write(bytes(4096))
            target = os.path.join(tmp, "target.img")
            open(target, "wb").close()
            env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""), LANG="C")
            result = subprocess.run(["bash", "-c", get_linux_script(), "lufux-test", iso, target],
                                    capture_output=True, text=True, env=env, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No space left on device", result.stdout)
        self.assertNotIn("records", result.stdout)


if __name__ == "__main__":
    unittest.main()
