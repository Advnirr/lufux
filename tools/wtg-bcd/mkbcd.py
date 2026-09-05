"""Assemble a BCD from bcd_logic primitives, for the QEMU oracle."""
import sys
sys.path.insert(0, "/home/mikhail/MyProjectsFolder/GitHub/lufux-linux")
import bcd_logic as B


def build(entries, default_guid, timeout=30, bootmgr_device=None):
    """entries: [(guid, description, device_blob, osdevice_blob)]"""
    w = B.HiveWriter("BCD")
    sk = w.security()

    def obj(guid, otype, elements):
        desc = w.key("Description", sk,
                     values=[w.value("Type", B.REG_DWORD, B.struct.pack("<I", otype))])
        els = []
        for eid, vtype, data in elements:
            els.append(w.key(eid, sk, values=[w.value("Element", vtype, data)]))
        return w.key(guid, sk, subkeys=[desc, w.key("Elements", sk, subkeys=els)])

    objects = []
    for guid, description, dev, osdev in entries:
        objects.append(obj(guid, B.TYPE_OSLOADER, [
            (B.EL_DEVICE, B.REG_BINARY, dev),
            (B.EL_PATH, B.REG_SZ, B._sz(r"\Windows\system32\winload.efi")),
            (B.EL_DESCRIPTION, B.REG_SZ, B._sz(description)),
            (B.EL_LOCALE, B.REG_SZ, B._sz("en-US")),
            (B.EL_OSDEVICE, B.REG_BINARY, osdev),
            (B.EL_SYSTEMROOT, B.REG_SZ, B._sz(r"\Windows")),
        ]))

    objects.append(obj(B.BOOTMGR_GUID, B.TYPE_BOOTMGR, [
        (B.EL_DEVICE, B.REG_BINARY, bootmgr_device or B.device_boot()),
        (B.EL_DESCRIPTION, B.REG_SZ, B._sz("Windows Boot Manager")),
        (B.EL_LOCALE, B.REG_SZ, B._sz("en-US")),
        (B.EL_DEFAULT, B.REG_SZ, B._sz(default_guid)),
        (B.EL_DISPLAYORDER, B.REG_MULTI_SZ, B._multi_sz([e[0] for e in entries])),
        (B.EL_TIMEOUT, B.REG_BINARY, B.struct.pack("<I", timeout)),
    ]))

    desc = w.key("Description", sk,
                 values=[w.value("KeyName", B.REG_SZ, B._sz("BCD"))])
    objs = w.key("Objects", sk, subkeys=objects)
    root = w.key("System", sk, subkeys=[desc, objs], root=True)
    return w.serialise(root[0])
