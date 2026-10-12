"""Isohybrid images, written block for block through UDisks2.

udisks opens the device and hands back a file descriptor, polkit asks the
password. No root process of our own, so this works inside a Flatpak too.
"""
import os
import re

from gi.repository import Gio, GLib

UDISKS = "org.freedesktop.UDisks2"
MANAGER = "/org/freedesktop/UDisks2/Manager"
CHUNK = 4 << 20
# what wipefs used to clear: the backup GPT of the drive's old layout
TAIL = 1 << 20
# major 8 only, as lsblk -I 8 did: no NVMe, no SD cards, see issue #2
DEVICE_RE = re.compile(r"^/dev/sd[a-z]+$")


def get_locale_dict():
    lang = os.environ.get('LANG', '')
    if lang.startswith('ru'):
        return {
            "unmount": "Отмонтирование...",
            "copy": "Копирование образа...",
            "sync": "Синхронизация ввода-вывода (sync)...",
        }
    return {
        "unmount": "Unmounting...",
        "copy": "Copying image...",
        "sync": "Syncing I/O (sync)...",
    }


def _bus():
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def _call(bus, path, iface, method, args, reply, fds=None):
    # interactive, or udisks refuses at once instead of letting polkit ask;
    # no timeout, the password dialog waits for the user
    return bus.call_with_unix_fd_list_sync(
        UDISKS, path, iface, method, args, GLib.VariantType(reply),
        Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, GLib.MAXINT, fds, None)


def _objects(bus):
    reply, _ = _call(bus, "/org/freedesktop/UDisks2", "org.freedesktop.DBus.ObjectManager",
                     "GetManagedObjects", None, "(a{oa{sa{sv}}})")
    return reply.unpack()[0]


def _bytes(value):
    return bytes(value).rstrip(b"\0").decode(errors="replace")


def list_drives():
    """[(device, size, model)] of the USB and removable disks, sorted by device."""
    objects = _objects(_bus())
    drives = []
    for ifaces in objects.values():
        block = ifaces.get("org.freedesktop.UDisks2.Block")
        if not block or "org.freedesktop.UDisks2.Partition" in ifaces:
            continue
        drive = objects.get(block["Drive"], {}).get("org.freedesktop.UDisks2.Drive")
        dev = _bytes(block["Device"])
        if not drive or not DEVICE_RE.match(dev) or not block["Size"]:
            continue
        # the same rule as lsblk's RM and TRAN columns
        if not drive["Removable"] and drive["ConnectionBus"] != "usb":
            continue
        model = " ".join(x for x in (drive["Vendor"], drive["Model"]) if x)
        drives.append((dev, block["Size"], model))
    return sorted(drives)


def device_size(dev):
    """The device's size in bytes, 0 when udisks does not know it."""
    try:
        bus = _bus()
        path = _resolve(bus, dev)
        reply, _ = _call(bus, path, "org.freedesktop.DBus.Properties", "Get",
                         GLib.Variant("(ss)", ("org.freedesktop.UDisks2.Block", "Size")), "(v)")
        return reply.unpack()[0]
    except (GLib.Error, LookupError):
        return 0


def _resolve(bus, dev):
    reply, _ = _call(bus, MANAGER, "org.freedesktop.UDisks2.Manager", "ResolveDevice",
                     GLib.Variant("(a{sv}a{sv})", ({"path": GLib.Variant("s", dev)}, {})), "(ao)")
    paths = reply.unpack()[0]
    if not paths:
        raise LookupError(f"udisks does not know {dev}")
    return paths[0]


def _unmount_all(bus, path):
    # the disk itself can hold a filesystem too, an old isohybrid stick does
    for obj, ifaces in _objects(bus).items():
        part = ifaces.get("org.freedesktop.UDisks2.Partition")
        if obj != path and (not part or part["Table"] != path):
            continue
        fs = ifaces.get("org.freedesktop.UDisks2.Filesystem")
        if fs and fs["MountPoints"]:
            _call(bus, obj, "org.freedesktop.UDisks2.Filesystem", "Unmount",
                  GLib.Variant("(a{sv})", ({},)), "()")


def copy_image(iso, fd, progress, stopped):
    """Copy iso onto fd. False if stopped() said to stop part way."""
    size = os.fstat(fd).st_size or os.lseek(fd, 0, os.SEEK_END)
    total = os.path.getsize(iso)
    if size > total + TAIL:
        os.pwrite(fd, bytes(TAIL), size - TAIL)
    os.lseek(fd, 0, os.SEEK_SET)
    done = 0
    with open(iso, "rb") as src:
        while chunk := src.read(CHUNK):
            if stopped():
                return False
            view = memoryview(chunk)
            while view:
                view = view[os.write(fd, view):]
            done += len(chunk)
            progress(done / total)
    return True


def write_image(iso, dev, status, progress, stopped):
    """Write iso onto dev. False if stopped() said to stop part way.

    Raises GLib.Error for anything udisks refuses, OSError for a failed write.
    """
    T = get_locale_dict()
    bus = _bus()
    path = _resolve(bus, dev)

    status(T["unmount"])
    _unmount_all(bus, path)

    # O_EXCL: the kernel refuses if anything still holds the disk.
    # O_SYNC: otherwise the copy fills the page cache in a second and the
    # whole write happens during fsync, with the bar already at 100%
    flags = os.O_EXCL | os.O_SYNC | os.O_CLOEXEC
    reply, fds = _call(bus, path, "org.freedesktop.UDisks2.Block", "OpenDevice",
                       GLib.Variant("(sa{sv})", ("w", {"flags": GLib.Variant("i", flags)})), "(h)")
    fd = fds.get(reply.unpack()[0])
    try:
        status(T["copy"])
        if not copy_image(iso, fd, progress, stopped):
            return False
        status(T["sync"])
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def is_canceled(error):
    """True when the user dismissed the password dialog."""
    return "NotAuthorizedDismissed" in getattr(error, "message", "")
