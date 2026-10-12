import ctypes
import ctypes.util
import fcntl
import os
import shutil
import struct
import subprocess  # nosec B404 - argv lists only, run as the user
import tempfile

from gi.repository import GLib

from bcd_logic import build_bcd, gpt_guids
from speed_logic import measure_fd
from udisks_logic import (BASIC_DATA, BLOCK, FILESYSTEM, NO_OPTIONS, PARTITION, bus, call, mount,
                          mounted_iso, objects, open_device, resolve, unmount, unmount_all)
from windows_logic import WIM_NAMES, Stopped

# Locals
def get_locale_dict():
    lang = os.environ.get('LANG', '')
    if lang.startswith('ru'):
        return {
# russian locals
            "prep": "Подготовка накопителя...",
            "part": "Создание разделов (ESP + Windows)...",
            "no_image": "В образе не найден install.wim/install.esd",
            "no_index": "Выбранной редакции нет в образе",
            "no_bootmgr": "В образе не найден bootmgfw.efi",
            "speed": "Замер скорости накопителя...",
            "apply": "Развёртывание Windows на накопитель (это надолго)...",
            "boot": "Установка загрузчика UEFI...",
            "sync": "Синхронизация ввода-вывода (sync)..."
        }
    return {
# english locals
        "prep": "Preparing drive...",
        "part": "Creating partitions (ESP + Windows)...",
        "no_image": "install.wim/install.esd not found in the image",
        "no_index": "The selected edition is not present in the image",
        "no_bootmgr": "bootmgfw.efi not found in the image",
        "speed": "Measuring drive speed...",
        "apply": "Deploying Windows to the drive (this takes a while)...",
        "boot": "Installing the UEFI bootloader...",
        "sync": "Syncing I/O (sync)..."
    }


ESP_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
ESP_SIZE = 512 << 20
BLKSSZGET = 0x1268
FD_PREFIX = "/proc/self/fd/"

# wimlib.h
EXTRACT_FLAG_NTFS = 1
MSG_EXTRACT_STREAMS = 4
STATUS_ABORT = 1
ERR_ABORTED_BY_PROGRESS = 76
PROGRESS_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


class _Extract(ctypes.Structure):
    # the start of wimlib_progress_info_extract
    _fields_ = [("image", ctypes.c_uint32), ("extract_flags", ctypes.c_uint32),
                ("wimfile_name", ctypes.c_void_p), ("image_name", ctypes.c_void_p),
                ("target", ctypes.c_void_p), ("reserved", ctypes.c_void_p),
                ("total_bytes", ctypes.c_uint64), ("completed_bytes", ctypes.c_uint64)]


class _NtfsDevice(ctypes.Structure):
    # the start of ntfs-3g's struct ntfs_device
    _fields_ = [("d_ops", ctypes.c_void_p), ("d_state", ctypes.c_ulong),
                ("d_name", ctypes.c_char_p), ("d_private", ctypes.c_void_p)]


NTFS_OPEN = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_NtfsDevice), ctypes.c_int)
# ntfs-3g's ND_Open, ND_ReadOnly and ND_Block bits
ND_OPEN, ND_READONLY, ND_BLOCK = 1, 2, 8

_lib = None
_keep = []


def _hook_ntfs_open(path):
    """Let libntfs-3g take a udisks fd as /proc/self/fd/N.

    It opens the device by path, and that fd cannot be reopened as a user.
    open is the first entry of its exported ntfs_device_unix_io_ops.
    """
    ops = ctypes.c_void_p.in_dll(ctypes.CDLL(path), "ntfs_device_unix_io_ops")
    orig = NTFS_OPEN(ops.value)
    libc = ctypes.CDLL(None)
    libc.malloc.restype = ctypes.c_void_p

    def open_fd(dev, flags):
        name = dev.contents.d_name.decode(errors="replace")
        if not name.startswith(FD_PREFIX):
            return orig(dev, flags)
        # ntfs-3g closes it and frees d_private itself
        priv = libc.malloc(ctypes.sizeof(ctypes.c_int))
        ctypes.c_int.from_address(priv).value = os.dup(int(name[len(FD_PREFIX):]))
        dev.contents.d_private = priv
        state = ND_OPEN | ND_BLOCK
        if flags & os.O_ACCMODE != os.O_RDWR:
            state |= ND_READONLY
        dev.contents.d_state |= state
        return 0

    hook = NTFS_OPEN(open_fd)
    _keep.extend((orig, hook))
    ops.value = ctypes.cast(hook, ctypes.c_void_p).value


def _wimlib():
    global _lib
    if _lib:
        return _lib
    lib = ctypes.CDLL(ctypes.util.find_library("wim") or "libwim.so.15")
    lib.wimlib_open_wim.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    lib.wimlib_register_progress_function.argtypes = [ctypes.c_void_p, PROGRESS_FUNC, ctypes.c_void_p]
    lib.wimlib_extract_image.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    lib.wimlib_free.argtypes = [ctypes.c_void_p]
    lib.wimlib_get_error_string.restype = ctypes.c_char_p
    # the copy wimlib itself loaded, whatever its soname
    with open("/proc/self/maps", encoding="utf-8") as maps:
        ntfs = next((line.split()[-1] for line in maps if "/libntfs-3g.so" in line), None)
    if not ntfs:
        raise OSError("wimlib is built without NTFS-3G")
    _hook_ntfs_open(ntfs)
    _lib = lib
    return lib


def _wim_error(lib, code):
    return lib.wimlib_get_error_string(code).decode(errors="replace")


def _apply(image, index, fd, progress, stopped):
    """wimlib apply onto the NTFS behind fd, in this process."""
    lib = _wimlib()
    wim = ctypes.c_void_p()
    code = lib.wimlib_open_wim(image.encode(), 0, ctypes.byref(wim))
    if code:
        raise OSError(_wim_error(lib, code))

    def report(msg, info, _ctx):
        if stopped():
            return STATUS_ABORT
        if msg == MSG_EXTRACT_STREAMS:
            e = _Extract.from_address(info)
            progress(e.completed_bytes, max(e.total_bytes, 1))
        return 0

    callback = PROGRESS_FUNC(report)
    try:
        lib.wimlib_register_progress_function(wim, callback, None)
        # NTFS mode: wimlib writes the volume itself and keeps Windows metadata
        code = lib.wimlib_extract_image(wim, index, f"{FD_PREFIX}{fd}".encode(), EXTRACT_FLAG_NTFS)
    finally:
        lib.wimlib_free(wim)
    if code == ERR_ABORTED_BY_PROGRESS:
        raise Stopped
    if code:
        raise OSError(_wim_error(lib, code))


def _partition(conn, table, offset, size, ptype, name, fstype, label):
    reply, _ = call(conn, table, "org.freedesktop.UDisks2.PartitionTable", "CreatePartitionAndFormat",
                    GLib.Variant("(ttssa{sv}sa{sv})", (offset, size, ptype, name, {}, fstype,
                                                       {"label": GLib.Variant("s", label)})), "(o)")
    return reply.unpack()[0]


def _speed_test(conn, path):
    """(MB/s, ops/s), or None when it cannot be measured."""
    try:
        fd = open_device(conn, path, "rw", os.O_DIRECT | os.O_SYNC)
    except GLib.Error:
        return None
    try:
        return measure_fd(fd, True)
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)


def set_ntfs_start(fd, start):
    """Write the partition start into the NTFS boot sector and its backup.

    Windows needs it to boot. mkntfs writes 0 where the kernel does not
    tell it, on a loop device for one.
    """
    boot = bytearray(os.pread(fd, 512, 0))
    if boot[3:11] != b"NTFS    ":
        raise OSError("no NTFS boot sector")
    sector = struct.unpack_from("<H", boot, 0x0b)[0]
    sectors = struct.unpack_from("<Q", boot, 0x28)[0]
    struct.pack_into("<I", boot, 0x1c, start)
    os.pwrite(fd, boot, 0)
    # the backup sits right after the volume
    backup = sectors * sector
    if os.pread(fd, 11, backup)[3:11] == b"NTFS    ":
        os.pwrite(fd, boot, backup)


def _install_boot(boot, esp, store):
    """Copy the boot files extracted from the image and the BCD onto the ESP."""
    ms = os.path.join(esp, "EFI", "Microsoft", "Boot")
    shutil.copytree(boot, ms, dirs_exist_ok=True)
    os.makedirs(os.path.join(esp, "EFI", "Boot"), exist_ok=True)
    shutil.copyfile(os.path.join(boot, "bootmgfw.efi"), os.path.join(esp, "EFI", "Boot", "bootx64.efi"))
    with open(os.path.join(ms, "BCD"), "wb") as f:
        f.write(store)


def _extract_boot(image, index, dest, T):
    env = dict(os.environ, WIMLIB_IMAGEX_IGNORE_CASE="1")
    wimlib = shutil.which("wimlib-imagex") or "wimlib-imagex"
    if subprocess.run([wimlib, "extract", image, str(index), "/Windows/Boot/EFI",  # nosec B603
                       f"--dest-dir={dest}"], env=env, capture_output=True, check=False).returncode:
        raise OSError(T["no_index"])
    boot = os.path.join(dest, "EFI")
    if not os.path.isfile(os.path.join(boot, "bootmgfw.efi")):
        raise OSError(T["no_bootmgr"])
    return boot


def write_windows_togo(iso, dev, status, progress, stopped, img_index, ask_speed):
    """Windows To Go through udisks. False if stopped.

    ask_speed(MB/s, ops/s) returns whether to go on.
    """
    T = get_locale_dict()
    index = int(img_index)
    conn = bus()
    path = resolve(conn, dev)

    status(T["prep"])
    unmount_all(conn, path)
    call(conn, path, BLOCK, "Format", GLib.Variant("(sa{sv})", ("empty", {})), "()")

    status(T["speed"])
    speed = _speed_test(conn, path)
    if speed and not ask_speed(*speed):
        return False

    status(T["part"])
    call(conn, path, BLOCK, "Format", GLib.Variant("(sa{sv})", ("gpt", {})), "()")
    esp = _partition(conn, path, 1 << 20, ESP_SIZE, ESP_TYPE, "ESP", "vfat", "ESP")
    win = _partition(conn, path, (1 << 20) + ESP_SIZE, 0, BASIC_DATA, "Windows", "ntfs", "Windows")
    info = objects(conn)[win][PARTITION]
    fd = open_device(conn, path, "r")
    try:
        part_guid, disk_guid = gpt_guids(fd, info["Number"])
    finally:
        os.close(fd)

    try:
        with mounted_iso(iso) as src, tempfile.TemporaryDirectory(prefix="lufux-") as tmp:
            image = next((os.path.join(src, n) for n in WIM_NAMES
                          if os.path.exists(os.path.join(src, n))), None)
            if not image:
                raise OSError(T["no_image"])
            boot = _extract_boot(image, index, tmp, T)

            status(T["apply"])
            unmount(conn, win)
            fd = open_device(conn, win, "rw")
            try:
                sector = struct.unpack("i", fcntl.ioctl(fd, BLKSSZGET, b"\0" * 4))[0]
                set_ntfs_start(fd, info["Offset"] // sector)
                _apply(image, index, fd, progress, stopped)
                os.fsync(fd)
            finally:
                os.close(fd)

            status(T["boot"])
            mnt = mount(conn, esp)
            try:
                _install_boot(boot, mnt, build_bcd(part_guid, disk_guid))
                status(T["sync"])
                call(conn, esp, FILESYSTEM, "Unmount", NO_OPTIONS, "()")
            except BaseException:
                unmount(conn, esp)
                raise
        return True
    except Stopped:
        return False
