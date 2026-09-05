"""Build a BCD boot store for a Windows To Go drive.

The BCD is a Windows registry hive. Windows creates it with bcdboot.exe, which
does not exist on Linux, and the BCD-Template shipped inside a Windows image is
not usable as-is: it carries the settings objects and {bootmgr} but none of the
elements that bind a boot entry to a volume (11000001 ApplicationDevice,
21000001 OSDevice, 24000001 DisplayOrder). A drive holding only the template
fails at boot with 0xc000000f.

So this writes a minimal store from scratch. Every hive-format constant and
every field of the device elements was read out of a real BCD rather than
guessed, and the whole store is checked by booting it: tools/wtg-bcd holds the
harness that runs a real bootmgfw.efi against it under QEMU/OVMF.
"""

import struct

HBIN_HEADER_SIZE = 32
ROOT_FLAGS = 0x2C          # hive entry + compressed (ASCII) name
KEY_FLAGS = 0x20           # compressed (ASCII) name
VK_ASCII_NAME = 0x0001

REG_SZ = 1
REG_BINARY = 3
REG_DWORD = 4
REG_MULTI_SZ = 7


class HiveWriter:
    """Lays cells out sequentially in one hbin; offsets are hbin-relative."""

    def __init__(self, hive_name="BCD"):
        self.hive_name = hive_name
        # reserve the hbin header so that alloc() hands out real offsets
        self.buf = bytearray(HBIN_HEADER_SIZE)

    def alloc(self, payload):
        size = (4 + len(payload) + 7) & ~7      # cells are 8-byte aligned
        off = len(self.buf)
        self.buf += struct.pack("<i", -size) + payload
        self.buf += b"\x00" * (size - 4 - len(payload))
        return off

    def _patch(self, cell_off, field_off, fmt, *values):
        struct.pack_into(fmt, self.buf, cell_off + 4 + field_off, *values)

    def security(self):
        """One descriptor shared by every key.

        bootmgr ignores the descriptor entirely, but Windows does not: sysprep's
        specialize pass opens this store through the registry, and a descriptor
        without an owner is rejected there with STATUS_INVALID_OWNER
        (0xc000005a), which fails the whole pass. So write a real self-relative
        descriptor: Administrators owns it, and both Administrators and SYSTEM
        get full access, inherited by every key below.
        """
        admins = struct.pack("<BB6sII", 1, 2, b"\x00\x00\x00\x00\x00\x05", 32, 544)
        system = struct.pack("<BB6sI", 1, 1, b"\x00\x00\x00\x00\x00\x05", 18)
        KEY_ALL_ACCESS, CONTAINER_INHERIT = 0xF003F, 0x02

        def ace(sid):
            return struct.pack("<BBHI", 0, CONTAINER_INHERIT, 8 + len(sid),
                               KEY_ALL_ACCESS) + sid

        aces = ace(admins) + ace(system)
        dacl = struct.pack("<BBHHH", 2, 0, 8 + len(aces), 2, 0) + aces
        owner_at = 20 + len(dacl)
        group_at = owner_at + len(admins)
        sd = (struct.pack("<BBHIIII", 1, 0, 0x8004, owner_at, group_at, 0, 20)
              + dacl + admins + system)

        off = self.alloc(b"sk" + struct.pack("<HIIII", 0, 0, 0, 1, len(sd)) + sd)
        self._patch(off, 0x04, "<II", off, off)      # flink/blink -> itself
        return off

    def value(self, name, vtype, data):
        nb = name.encode("latin1")
        off = self.alloc(b"vk" + struct.pack(
            "<HIIIHH", len(nb), len(data), 0, vtype, VK_ASCII_NAME, 0) + nb)
        self._patch(off, 0x08, "<I", self.alloc(data))
        return off, name, len(data)

    def key(self, name, sk_off, subkeys=(), values=(), root=False):
        """subkeys: [(offset, name)]; values: [(offset, name, data_len)]"""
        nb = name.encode("latin1")
        sk_list = self._subkey_list(subkeys) if subkeys else 0xFFFFFFFF
        v_list = self.alloc(b"".join(struct.pack("<I", o) for o, _, _ in values)) \
            if values else 0xFFFFFFFF
        off = self.alloc(b"nk" + struct.pack(
            "<HQIIIIIIIIIIIIIIIHH",
            ROOT_FLAGS if root else KEY_FLAGS,
            0,                                   # last written
            0,                                   # access bits
            0xFFFFFFFF,                          # parent, patched below
            len(subkeys), 0, sk_list, 0xFFFFFFFF,
            len(values), v_list,
            sk_off, 0xFFFFFFFF,                  # security, class name
            max((len(n) for _, n in subkeys), default=0), 0,
            max((len(n) for _, n, _ in values), default=0),
            max((d for _, _, d in values), default=0),
            0,                                   # work var
            len(nb), 0,
        ) + nb)
        for child, _ in subkeys:
            self._patch(child, 0x10, "<I", off)   # child's parent pointer
        return off, name

    def _subkey_list(self, entries):
        # "lf" leaf: (key offset, first four name characters), sorted by name
        entries = sorted(entries, key=lambda e: e[1].lower())
        body = struct.pack("<H", len(entries))
        for off, name in entries:
            body += struct.pack("<I", off) + name.encode("latin1")[:4].ljust(4, b"\x00")
        return self.alloc(b"lf" + body)

    def serialise(self, root_off):
        hbins = bytearray(self.buf)
        pad = (-len(hbins)) % 4096
        if pad:
            # the unused tail of the hbin is one free (positive size) cell
            hbins += struct.pack("<i", pad) + b"\x00" * (pad - 4)
        struct.pack_into("<4sIIIIQI", hbins, 0,
                         b"hbin", 0, len(hbins), 0, 0, 0, 0)

        head = bytearray(4096)
        struct.pack_into("<4sIIQIIIIIII", head, 0,
                         b"regf", 1, 1, 0,
                         1, 3,            # major, minor
                         0, 1,            # file type (primary), format (direct)
                         root_off, len(hbins), 1)
        head[0x30:0x30 + 64] = self.hive_name.encode("utf-16-le").ljust(64, b"\x00")[:64]
        checksum = 0
        for i in range(0, 0x1FC, 4):
            checksum ^= struct.unpack_from("<I", head, i)[0]
        struct.pack_into("<I", head, 0x1FC, checksum)
        return bytes(head) + bytes(hbins)


# --- BCD objects ------------------------------------------------------------

BOOTMGR_GUID = "{9dea862c-5cdd-4e70-acc1-f32b344d4795}"

TYPE_BOOTMGR = 0x10100002
TYPE_OSLOADER = 0x10200003

# element ids
EL_DEVICE = "11000001"        # ApplicationDevice
EL_PATH = "12000002"          # ApplicationPath
EL_DESCRIPTION = "12000004"
EL_LOCALE = "12000005"
EL_INHERIT = "14000006"
EL_DEFAULT = "23000003"
EL_DISPLAYORDER = "24000001"
EL_TIMEOUT = "25000004"
EL_OSDEVICE = "21000001"
EL_SYSTEMROOT = "22000002"


def _sz(text):
    return text.encode("utf-16-le") + b"\x00\x00"


def _multi_sz(items):
    return b"".join(_sz(i) for i in items) + b"\x00\x00"


def device_boot():
    """`device boot` - the volume this application was loaded from.

    Reproduced byte for byte from the {memdiag} entry of a real Windows 11
    BCD: a zero options GUID, then a 72-byte descriptor whose only non-zero
    fields are the device type (5) and its own length.
    """
    return (b"\x00" * 16
            + struct.pack("<IIII", 5, 0, 0x48, 0)
            + b"\x00" * 56)


def device_partition(partition_guid, disk_guid):
    """`device partition=...` for a partition on a GPT disk.

    The 72-byte descriptor is laid out as measured from a real BCD (the byte
    offsets below are into the descriptor, i.e. 16 past the start of the
    element, which begins with the zero options GUID):

        +0   device type 6 - a partition
        +4   flags
        +8   descriptor length, 0x48
        +16  partition identifier: the GPT partition GUID
        +32  the containing device: 0 = a local hard disk
        +36  its partitioning: 0 = GPT
        +40  disk identifier: the GPT disk GUID

    Both GUIDs are the raw 16 bytes as they appear in the GPT, i.e. mixed
    endian (uuid.UUID.bytes_le), not the printed form.

    On an MBR disk the same descriptor carries the partition's byte offset at
    +16 and the 4-byte MBR disk signature at +40, with 1 (MBR) at +36; lufux
    only ever writes GPT drives, so that variant is not built here.
    """
    if len(partition_guid) != 16 or len(disk_guid) != 16:
        raise ValueError("GPT GUIDs must be 16 raw bytes")
    d = bytearray(72)
    struct.pack_into("<IIII", d, 0, 6, 0, 0x48, 0)
    d[16:32] = partition_guid
    struct.pack_into("<II", d, 32, 0, 0)
    d[40:56] = disk_guid
    return b"\x00" * 16 + bytes(d)


def gpt_guids(disk_path, partition_number):
    """Read (partition_guid, disk_guid) out of a disk's GPT, as raw bytes.

    Reads the block device directly rather than shelling out to parted or
    sgdisk: the GUIDs are needed exactly as stored, and every printed form
    would have to be converted back.
    """
    with open(disk_path, "rb") as f:
        for sector in (512, 4096):
            f.seek(sector)
            header = f.read(92)
            if header[:8] == b"EFI PART":
                break
        else:
            raise ValueError(f"no GPT header on {disk_path}")
        disk_guid = header[0x38:0x48]
        entry_lba, count, entry_size = struct.unpack("<QII", header[0x48:0x58])
        if not 1 <= partition_number <= count:
            raise ValueError(f"no partition {partition_number} on {disk_path}")
        f.seek(entry_lba * sector + (partition_number - 1) * entry_size)
        entry = f.read(entry_size)
    if entry[:16] == b"\x00" * 16:
        raise ValueError(f"partition {partition_number} on {disk_path} is unused")
    return entry[16:32], disk_guid


# The store holds a single boot entry, so its GUID only has to be stable and
# distinct from the well-known ones.
WTG_ENTRY_GUID = "{a1b2c3d4-1111-4a2b-9c3d-4e5f60718293}"


def build_bcd(partition_guid, disk_guid, description="Windows To Go", timeout=30):
    """Return a complete BCD store pointing at one Windows partition."""
    w = HiveWriter("BCD")
    sk = w.security()

    def obj(guid, otype, elements):
        desc = w.key("Description", sk,
                     values=[w.value("Type", REG_DWORD, struct.pack("<I", otype))])
        els = [w.key(eid, sk, values=[w.value("Element", vtype, data)])
               for eid, vtype, data in elements]
        return w.key(guid, sk, subkeys=[desc, w.key("Elements", sk, subkeys=els)])

    device = device_partition(partition_guid, disk_guid)
    objects = [
        obj(WTG_ENTRY_GUID, TYPE_OSLOADER, [
            (EL_DEVICE, REG_BINARY, device),
            (EL_PATH, REG_SZ, _sz(r"\Windows\system32\winload.efi")),
            (EL_DESCRIPTION, REG_SZ, _sz(description)),
            (EL_LOCALE, REG_SZ, _sz("en-US")),
            (EL_OSDEVICE, REG_BINARY, device),
            (EL_SYSTEMROOT, REG_SZ, _sz(r"\Windows")),
        ]),
        # {bootmgr}'s own device is `boot`: the volume it was loaded from,
        # which is the ESP of whichever drive the firmware picked.
        obj(BOOTMGR_GUID, TYPE_BOOTMGR, [
            (EL_DEVICE, REG_BINARY, device_boot()),
            (EL_PATH, REG_SZ, _sz(r"\EFI\Microsoft\Boot\bootmgfw.efi")),
            (EL_DESCRIPTION, REG_SZ, _sz("Windows Boot Manager")),
            (EL_LOCALE, REG_SZ, _sz("en-US")),
            (EL_DEFAULT, REG_SZ, _sz(WTG_ENTRY_GUID)),
            (EL_DISPLAYORDER, REG_MULTI_SZ, _multi_sz([WTG_ENTRY_GUID])),
            (EL_TIMEOUT, REG_BINARY, struct.pack("<I", timeout)),
        ]),
    ]

    # KeyName is the registry key the store gets mounted under; BCD00000000 is
    # the system store's. System marks the store as the system store, and is
    # what sysprep's specialize pass looks for: spbcd.dll reads
    # Description\System, writes Description\TreatAsSystem=1 next to it when it
    # is set, and then requires both to be non-zero. Without System the pass
    # fails with "File is not system store" (0xc0000098), which surfaces on the
    # drive's first boot as "Windows Setup could not configure Windows to run on
    # this computer's hardware" - long after the boot chain itself has worked.
    desc = w.key("Description", sk, values=[
        w.value("KeyName", REG_SZ, _sz("BCD00000000")),
        w.value("System", REG_DWORD, struct.pack("<I", 1)),
    ])
    root = w.key("System", sk,
                 subkeys=[desc, w.key("Objects", sk, subkeys=objects)], root=True)
    return w.serialise(root[0])


def main(argv):
    """bcd_logic.py <disk> <partition-number> <output-BCD> [description]"""
    if not 4 <= len(argv) <= 5:
        raise SystemExit(main.__doc__)
    disk, number, out = argv[1], int(argv[2]), argv[3]
    part_guid, disk_guid = gpt_guids(disk, number)
    store = build_bcd(part_guid, disk_guid, *argv[4:5])
    with open(out, "wb") as f:
        f.write(store)


if __name__ == "__main__":
    import sys
    main(sys.argv)
