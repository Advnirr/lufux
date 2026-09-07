"""The BCD store lufux writes by hand, read back with the repo's own hive parser.

Every one of these assertions stands for a boot that failed while the store was
being worked out: a missing Description\\System made sysprep's specialize pass
refuse the store as "not a system store", and a device element of the wrong
type made bootmgr look for Windows on the drive the firmware booted from.
"""
import os
import struct
import sys
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "wtg-bcd"))

import bcd_logic as B
from regf import Hive

PART_GUID = uuid.UUID("11111111-2222-3333-4444-555555555555").bytes_le
DISK_GUID = uuid.UUID("66666666-7777-8888-9999-aaaaaaaaaaaa").bytes_le


def read_store(blob):
    """{guid: {"type": int, "elems": {id: (value type, raw)}}} plus the root."""
    hive = Hive(blob)

    def walk(off, parts):
        nk = hive.nk(off)
        yield parts, nk
        for sub in hive.subkeys(nk):
            yield from walk(sub, parts + [hive.nk(sub)["name"]])

    objects, root_values = {}, {}
    for parts, nk in walk(hive.root_off, []):
        if parts[:1] == ["Description"]:
            root_values = {name: (vtype, raw) for name, vtype, raw in hive.values(nk)}
        if len(parts) >= 2 and parts[0] == "Objects":
            obj = objects.setdefault(parts[1], {"type": None, "elems": {}})
            if len(parts) == 3 and parts[2] == "Description":
                for name, _, raw in hive.values(nk):
                    if name == "Type":
                        obj["type"] = struct.unpack("<I", raw)[0]
            if len(parts) == 4 and parts[2] == "Elements":
                for name, vtype, raw in hive.values(nk):
                    if name == "Element":
                        obj["elems"][parts[3]] = (vtype, raw)
    return objects, root_values


def text(raw):
    return raw.decode("utf-16-le").rstrip("\x00")


class BuildBcd(unittest.TestCase):
    def setUp(self):
        self.store = B.build_bcd(PART_GUID, DISK_GUID)
        self.objects, self.root = read_store(self.store)

    def test_it_is_a_regf_hive(self):
        self.assertEqual(self.store[:4], b"regf")

    def test_marked_as_the_system_store(self):
        # spbcd.dll reads Description\System, writes TreatAsSystem next to it
        # and then requires both; without System the specialize pass dies with
        # 0xc0000098 on the drive's first boot
        self.assertEqual(text(self.root["KeyName"][1]), "BCD00000000")
        self.assertEqual(struct.unpack("<I", self.root["System"][1])[0], 1)

    def test_holds_exactly_bootmgr_and_one_loader(self):
        self.assertEqual(set(self.objects), {B.BOOTMGR_GUID, B.WTG_ENTRY_GUID})
        self.assertEqual(self.objects[B.BOOTMGR_GUID]["type"], B.TYPE_BOOTMGR)
        self.assertEqual(self.objects[B.WTG_ENTRY_GUID]["type"], B.TYPE_OSLOADER)

    def test_loader_points_at_the_partition_by_guid(self):
        vtype, raw = self.objects[B.WTG_ENTRY_GUID]["elems"][B.EL_DEVICE]
        self.assertEqual(vtype, B.REG_BINARY)
        self.assertEqual(len(raw), 16 + 72)
        # the descriptor starts 16 bytes in, past the zero options GUID
        self.assertEqual(struct.unpack_from("<I", raw, 16)[0], 6, "device type 6 = partition")
        self.assertEqual(struct.unpack_from("<I", raw, 24)[0], 0x48, "descriptor length")
        self.assertEqual(raw[32:48], PART_GUID)
        self.assertEqual(raw[56:72], DISK_GUID)
        self.assertEqual(struct.unpack_from("<I", raw, 52)[0], 0, "0 = GPT partitioning")

    def test_osdevice_matches_device(self):
        elems = self.objects[B.WTG_ENTRY_GUID]["elems"]
        self.assertEqual(elems[B.EL_OSDEVICE], elems[B.EL_DEVICE])

    def test_bootmgr_loads_from_the_volume_it_booted_from(self):
        # `device boot`, not the Windows partition: the ESP the firmware picked
        _, raw = self.objects[B.BOOTMGR_GUID]["elems"][B.EL_DEVICE]
        self.assertEqual(struct.unpack_from("<I", raw, 16)[0], 5, "device type 5 = boot")
        self.assertEqual(raw, B.device_boot())

    def test_bootmgr_defaults_to_the_loader(self):
        elems = self.objects[B.BOOTMGR_GUID]["elems"]
        self.assertEqual(text(elems[B.EL_DEFAULT][1]), B.WTG_ENTRY_GUID)
        order = [x for x in elems[B.EL_DISPLAYORDER][1].decode("utf-16-le").split("\x00") if x]
        self.assertEqual(order, [B.WTG_ENTRY_GUID])

    def test_paths_are_the_ones_bootmgr_and_winload_expect(self):
        loader = self.objects[B.WTG_ENTRY_GUID]["elems"]
        self.assertEqual(text(loader[B.EL_PATH][1]), r"\Windows\system32\winload.efi")
        self.assertEqual(text(loader[B.EL_SYSTEMROOT][1]), r"\Windows")
        boot = self.objects[B.BOOTMGR_GUID]["elems"]
        self.assertEqual(text(boot[B.EL_PATH][1]), r"\EFI\Microsoft\Boot\bootmgfw.efi")

    def test_description_and_timeout_are_carried_through(self):
        store = B.build_bcd(PART_GUID, DISK_GUID, description="Test Build", timeout=7)
        objects, _ = read_store(store)
        loader = objects[B.WTG_ENTRY_GUID]["elems"]
        self.assertEqual(text(loader[B.EL_DESCRIPTION][1]), "Test Build")
        timeout = objects[B.BOOTMGR_GUID]["elems"][B.EL_TIMEOUT][1]
        self.assertEqual(struct.unpack("<I", timeout)[0], 7)


class DeviceElements(unittest.TestCase):
    def test_guids_must_be_raw_sixteen_bytes(self):
        # the printed form is 36 characters and mixed endian; letting it through
        # would produce a store that points at nothing
        with self.assertRaises(ValueError):
            B.device_partition(str(uuid.uuid4()).encode(), DISK_GUID)
        with self.assertRaises(ValueError):
            B.device_partition(PART_GUID, DISK_GUID[:15])

    def test_strings_are_utf16_and_terminated(self):
        self.assertEqual(B._sz("ab"), b"a\x00b\x00\x00\x00")
        self.assertEqual(B._multi_sz(["a", "b"]), b"a\x00\x00\x00b\x00\x00\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
