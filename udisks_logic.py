"""UDisks2 over D-Bus: the drive list and everything that needs root.

polkit asks the password, no root process of our own, so this also works
inside a Flatpak.
"""
import contextlib
import os
import re
import time

from gi.repository import Gio, GLib

UDISKS = "org.freedesktop.UDisks2"
MANAGER = "/org/freedesktop/UDisks2/Manager"
BLOCK = "org.freedesktop.UDisks2.Block"
FILESYSTEM = "org.freedesktop.UDisks2.Filesystem"
PARTITION = "org.freedesktop.UDisks2.Partition"
# major 8 only, as lsblk -I 8 did: no NVMe, no SD cards, see issue #2
DEVICE_RE = re.compile(r"^/dev/sd[a-z]+$")
# Microsoft basic data, what parted's msftdata flag set
BASIC_DATA = "ebd0a0a2-b9e5-4433-87c0-68b6b72699c7"
NO_OPTIONS = GLib.Variant("(a{sv})", ({},))


def bus():
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def call(conn, path, iface, method, args, reply, fds=None):
    # interactive, or udisks refuses at once instead of letting polkit ask;
    # no timeout, the password dialog waits for the user
    return conn.call_with_unix_fd_list_sync(
        UDISKS, path, iface, method, args, GLib.VariantType(reply),
        Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, GLib.MAXINT, fds, None)


def objects(conn):
    reply, _ = call(conn, "/org/freedesktop/UDisks2", "org.freedesktop.DBus.ObjectManager",
                    "GetManagedObjects", None, "(a{oa{sa{sv}}})")
    return reply.unpack()[0]


def _bytes(value):
    return bytes(value).rstrip(b"\0").decode(errors="replace")


def list_drives():
    """[(device, size, model)] of the USB and removable disks, sorted by device."""
    objs = objects(bus())
    drives = []
    for ifaces in objs.values():
        block = ifaces.get(BLOCK)
        if not block or PARTITION in ifaces:
            continue
        drive = objs.get(block["Drive"], {}).get("org.freedesktop.UDisks2.Drive")
        dev = _bytes(block["Device"])
        if not drive or not DEVICE_RE.match(dev) or not block["Size"]:
            continue
        # the same rule as lsblk's RM and TRAN columns
        if not drive["Removable"] and drive["ConnectionBus"] != "usb":
            continue
        model = " ".join(x for x in (drive["Vendor"], drive["Model"]) if x)
        drives.append((dev, block["Size"], model))
    return sorted(drives)


def resolve(conn, dev):
    reply, _ = call(conn, MANAGER, "org.freedesktop.UDisks2.Manager", "ResolveDevice",
                    GLib.Variant("(a{sv}a{sv})", ({"path": GLib.Variant("s", dev)}, {})), "(ao)")
    paths = reply.unpack()[0]
    if not paths:
        raise LookupError(f"udisks does not know {dev}")
    return paths[0]


def device_size(dev):
    """The device's size in bytes, 0 when udisks does not know it."""
    try:
        conn = bus()
        reply, _ = call(conn, resolve(conn, dev), "org.freedesktop.DBus.Properties", "Get",
                        GLib.Variant("(ss)", (BLOCK, "Size")), "(v)")
        return reply.unpack()[0]
    except (GLib.Error, LookupError):
        return 0


def unmount_all(conn, path):
    # the disk itself can hold a filesystem too, an old isohybrid stick does
    for obj, ifaces in objects(conn).items():
        part = ifaces.get(PARTITION)
        if obj != path and (not part or part["Table"] != path):
            continue
        fs = ifaces.get(FILESYSTEM)
        if fs and fs["MountPoints"]:
            call(conn, obj, FILESYSTEM, "Unmount", NO_OPTIONS, "()")


def _wait_for_fs(conn, path, timeout=10):
    # udisks probes a new device after the call that made it returns
    end = time.monotonic() + timeout
    while True:
        fs = objects(conn).get(path, {}).get(FILESYSTEM)
        if fs is not None:
            return fs
        if time.monotonic() > end:
            raise LookupError(f"no filesystem on {path}")
        time.sleep(0.2)


def mount(conn, path):
    """Mount the filesystem on path and return where it went."""
    fs = _wait_for_fs(conn, path)
    # the desktop may have automounted it a moment ago
    if fs["MountPoints"]:
        return _bytes(fs["MountPoints"][0])
    reply, _ = call(conn, path, FILESYSTEM, "Mount", NO_OPTIONS, "(s)")
    return reply.unpack()[0]


def unmount(conn, path):
    with contextlib.suppress(GLib.Error):
        call(conn, path, FILESYSTEM, "Unmount", NO_OPTIONS, "()")


@contextlib.contextmanager
def mounted_iso(iso):
    """Mount the ISO read-only through a loop device and yield its mount point.

    The file goes to udisks as an fd, which also works for a portal path.
    """
    conn = bus()
    # the fd list takes the fd over and closes it
    fds = Gio.UnixFDList.new_from_array([os.open(iso, os.O_RDONLY | os.O_CLOEXEC)])
    reply, _ = call(conn, MANAGER, "org.freedesktop.UDisks2.Manager", "LoopSetup",
                    GLib.Variant("(ha{sv})", (0, {"read-only": GLib.Variant("b", True)})),
                    "(o)", fds)
    loop = reply.unpack()[0]
    try:
        yield mount(conn, loop)
    finally:
        unmount(conn, loop)
        with contextlib.suppress(GLib.Error):
            call(conn, loop, "org.freedesktop.UDisks2.Loop", "Delete", NO_OPTIONS, "()")


def make_volume(conn, path, scheme, label):
    """Wipe the disk and put one partition across it, starting at 1 MiB.

    gpt gets FAT32, mbr gets NTFS on an active partition. Returns the partition.
    """
    gpt = scheme == "gpt"
    call(conn, path, BLOCK, "Format",
         GLib.Variant("(sa{sv})", ("gpt" if gpt else "dos", {})), "()")
    options = {} if gpt else {"partition-type": GLib.Variant("s", "primary")}
    reply, _ = call(conn, path, "org.freedesktop.UDisks2.PartitionTable", "CreatePartitionAndFormat",
                    GLib.Variant("(ttssa{sv}sa{sv})", (
                        1 << 20, 0, BASIC_DATA if gpt else "0x07", "", options,
                        "vfat" if gpt else "ntfs", {"label": GLib.Variant("s", label)})),
                    "(o)")
    part = reply.unpack()[0]
    if not gpt:
        # some BIOSes boot a USB disk only with an active partition
        call(conn, part, PARTITION, "SetFlags", GLib.Variant("(ta{sv})", (0x80, {})), "()")
    return part


def open_device(conn, path, mode, flags=0):
    """An fd on the whole device. O_EXCL: refused while anything holds it."""
    reply, fds = call(conn, path, BLOCK, "OpenDevice",
                      GLib.Variant("(sa{sv})", (mode, {"flags": GLib.Variant(
                          "i", os.O_EXCL | os.O_CLOEXEC | flags)})), "(h)")
    return fds.get(reply.unpack()[0])


def can_format(fstype):
    """Whether udisks has the mkfs for fstype."""
    try:
        reply, _ = call(bus(), MANAGER, "org.freedesktop.UDisks2.Manager", "CanFormat",
                        GLib.Variant("(s)", (fstype,)), "((bs))")
        return reply.unpack()[0][0]
    except GLib.Error:
        return False


def is_canceled(error):
    """True when the user dismissed the password dialog."""
    return "NotAuthorizedDismissed" in getattr(error, "message", "")
