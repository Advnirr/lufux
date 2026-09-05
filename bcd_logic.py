"""Build a BCD boot store for a Windows To Go drive.

The BCD is a Windows registry hive. Windows creates it with bcdboot.exe, which
does not exist on Linux, and the BCD-Template shipped inside a Windows image is
not usable as-is: it carries the settings objects and {bootmgr} but none of the
elements that bind a boot entry to a volume (11000001 ApplicationDevice,
21000001 OSDevice, 24000001 DisplayOrder). A drive holding only the template
fails at boot with 0xc000000f.

So this writes a minimal store from scratch. Every hive-format constant here
was read out of a real Windows 11 BCD rather than guessed, and test_bcd.py
checks the writer against that file.
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
        """One descriptor shared by every key: self-relative, NULL DACL."""
        sd = struct.pack("<BBHIIII", 1, 0, 0x8004, 0, 0, 0, 0)
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
