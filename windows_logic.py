import os
import re
import shutil
import subprocess  # nosec B404 - argv lists only, run as the user
import tempfile

from gi.repository import GLib

from udisks_logic import (FILESYSTEM, NO_OPTIONS, bus, call, make_volume, mount,
                          mounted_iso, open_device, resolve, unmount, unmount_all)

# Locals s s s
def get_locale_dict():
    lang = os.environ.get('LANG', '')
    if lang.startswith('ru'):
        return {
# russian locals
            "prep": "Подготовка накопителя...",
            "copy_base": "Копирование базовых файлов...",
            "copy_wim": "Прямое копирование WIM...",
            "split_wim": "Разделение WIM-образа...",
            "conv_lzx": "Конвертация в LZX (Solid архив)...",
            "grub": "Установка загрузчика для Legacy BIOS (GRUB)...",
            "sync": "Синхронизация ввода-вывода (sync)...",
            "no_space": "Не хватает места в {dir} для перепаковки образа",
        }
    return {
# english locals
        "prep": "Preparing drive...",
        "copy_base": "Copying base files...",
        "copy_wim": "Directly copying WIM...",
        "split_wim": "Splitting WIM image...",
        "conv_lzx": "Converting to LZX (Solid archive)...",
        "grub": "Installing the Legacy BIOS bootloader (GRUB)...",
        "sync": "Syncing I/O (sync)...",
        "no_space": "Not enough space in {dir} to repack the image",
    }

CHUNK = 4 << 20
# FAT32 holds files up to 4 GiB - 1; the script splits from 4 GB, as it did
SPLIT_FROM = 4_000_000_000
SPLIT_MB = "3800"
WIM_NAMES = ("sources/install.wim", "sources/install.esd")
# wimlib's split and export: "Splitting WIM: 60 MiB of 4107 MiB (1%) written"
WIM_PROGRESS = re.compile(r"(\d+) MiB of (\d+) MiB")
# wimlib cannot split a solid ESD and says so with this code
WIMLIB_ERR_SOLID = 68


class Stopped(Exception):
    pass


def _copy_file(src, dst, advance, stopped):
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while chunk := fi.read(CHUNK):
            if stopped():
                raise Stopped
            fo.write(chunk)
            advance(len(chunk))
        # otherwise the copy lands in the page cache and unmount takes minutes
        fo.flush()
        os.fsync(fo.fileno())


def _copy_tree(src, dst, skip, progress, stopped):
    files = []
    for root, _, names in os.walk(src):
        rel = os.path.relpath(root, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for name in names:
            path = os.path.normpath(os.path.join(rel, name))
            if path.lower() not in skip:
                files.append(path)
    total = sum(os.path.getsize(os.path.join(src, f)) for f in files) or 1
    done = 0

    def advance(n):
        nonlocal done
        done += n
        progress(done, total)

    for f in files:
        _copy_file(os.path.join(src, f), os.path.join(dst, f), advance, stopped)


def _wimlib(args, progress, stopped):
    """Run wimlib-imagex as the user. Its return code, or Stopped."""
    wimlib = shutil.which("wimlib-imagex")
    if not wimlib:
        raise FileNotFoundError("wimlib-imagex")
    # text mode turns the \r of its progress line into line breaks
    proc = subprocess.Popen([wimlib, *args], stdout=subprocess.PIPE,  # nosec B603
                            stderr=subprocess.STDOUT, text=True)
    tail = []
    try:
        for line in proc.stdout:
            if stopped():
                raise Stopped
            match = WIM_PROGRESS.search(line)
            if match:
                progress(int(match.group(1)) << 20, max(int(match.group(2)), 1) << 20)
            elif line.strip():
                tail = (tail + [line.strip()])[-5:]
        code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait()
    if code not in (0, WIMLIB_ERR_SOLID):
        raise OSError("\n".join(tail) or f"wimlib-imagex: {code}")
    return code


def _fill(src, dst, fat32, T, status, progress, stopped):
    status(T["copy_base"])
    _copy_tree(src, dst, WIM_NAMES, progress, stopped)

    image = next((os.path.join(src, n) for n in WIM_NAMES
                  if os.path.exists(os.path.join(src, n))), None)
    if not image:
        return
    size = os.path.getsize(image)
    if size < SPLIT_FROM or not fat32:
        status(T["copy_wim"])
        done = [0]

        def advance(n):
            done[0] += n
            progress(done[0], size)

        _copy_file(image, os.path.join(dst, "sources", os.path.basename(image)), advance, stopped)
        return

    swm = os.path.join(dst, "sources", "install.swm")
    status(T["split_wim"])
    if _wimlib(["split", image, swm, SPLIT_MB], progress, stopped) == 0:
        return

    # a solid ESD: repack it as LZX first, which wimlib can split
    for f in os.listdir(os.path.dirname(swm)):
        if f.lower().endswith(".swm"):
            os.remove(os.path.join(os.path.dirname(swm), f))
    work = os.path.join(GLib.get_user_cache_dir(), "lufux")
    os.makedirs(work, exist_ok=True)
    if shutil.disk_usage(work).free < size:
        raise OSError(T["no_space"].format(dir=work))
    repacked = os.path.join(work, "install.wim")
    try:
        status(T["conv_lzx"])
        _wimlib(["export", image, "all", repacked, "--compress=maximum"], progress, stopped)
        status(T["split_wim"])
        if _wimlib(["split", repacked, swm, SPLIT_MB], progress, stopped):
            raise OSError("wimlib-imagex split failed")
    finally:
        if os.path.exists(repacked):
            os.remove(repacked)


# GRUB 2.14 include/grub/i386/pc/boot.h and offsets.h, what grub-bios-setup
# patches when it embeds core.img right after the MBR
SECTOR = 512
BPB = slice(0x3, 0x5a)
KERNEL_SECTOR = slice(0x5c, 0x64)
BOOT_DRIVE = 0x64
DRIVE_CHECK = slice(0x66, 0x68)
TABLE = slice(0x1b8, 0x1fe)
BLOCKLIST = 12
CORE_SEGMENT = 0x800 + (SECTOR >> 4)
NO_RS_LENGTH = SECTOR + 0x14
# the gap before the partition at 1 MiB
MAX_CORE_SECTORS = 2047
GRUB_DIRS = ("/app/lib/grub/i386-pc", "/usr/lib/grub/i386-pc")
GRUB_MODULES = ("biosdisk", "part_msdos", "ntfs", "ntldr")
# everything is built into core.img, nothing of GRUB's lives on the NTFS
GRUB_CFG = "ntldr /bootmgr\nboot\n"


def bios_boot_code(boot_img, core_img, sector0):
    """(MBR, core sectors) to write at LBA 0 and from LBA 1 on.

    What grub-bios-setup does for this one layout, which it will not do on an
    fd: it wants the device path and probes the whole disk.
    """
    boot = bytearray(boot_img)
    boot[BPB] = sector0[BPB]
    boot[TABLE] = sector0[TABLE]
    # a BIOS that passes a wrong drive number is answered with 0x80
    boot[DRIVE_CHECK] = b"\x90\x90"
    boot[BOOT_DRIVE] = 0xFF
    boot[KERNEL_SECTOR] = (1).to_bytes(8, "little")

    nsec = -(-len(core_img) // SECTOR)
    if nsec > MAX_CORE_SECTORS:
        raise OSError("core.img does not fit before the partition")
    core = bytearray(core_img) + bytes(nsec * SECTOR - len(core_img))
    if core[NO_RS_LENGTH:NO_RS_LENGTH + 2] == b"\xff\xff":
        raise OSError("core.img version mismatch")
    first = SECTOR - BLOCKLIST
    at = first
    while int.from_bytes(core[at + 8:at + 10], "little"):
        core[at:at + BLOCKLIST] = bytes(BLOCKLIST)
        at -= BLOCKLIST
    end = first
    if nsec > 1:
        # the first sector is loaded by boot.img, the rest by this list
        core[first:first + BLOCKLIST] = ((2).to_bytes(8, "little") + (nsec - 1).to_bytes(2, "little")
                                         + CORE_SEGMENT.to_bytes(2, "little"))
        end -= BLOCKLIST
    core[end:end + BLOCKLIST] = bytes(BLOCKLIST)
    return bytes(boot), bytes(core)


def _grub_images():
    """(boot.img, core.img) built from the GRUB on this system or in the Flatpak."""
    mkimage = shutil.which("grub-mkimage") or shutil.which("grub2-mkimage")
    modules = next((d for d in GRUB_DIRS if os.path.isfile(os.path.join(d, "boot.img"))), None)
    if not mkimage or not modules:
        raise FileNotFoundError("grub-mkimage")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = os.path.join(tmp, "early.cfg")
        with open(cfg, "w", encoding="ascii") as f:
            f.write(GRUB_CFG)
        core = os.path.join(tmp, "core.img")
        # (,msdos1): the first partition of whichever drive the BIOS booted
        subprocess.run([mkimage, "-O", "i386-pc", "-d", modules, "-o", core, "-c", cfg,  # nosec B603
                        "-p", "(,msdos1)/", *GRUB_MODULES], check=True, capture_output=True)
        with open(os.path.join(modules, "boot.img"), "rb") as f:
            boot = f.read()
        with open(core, "rb") as f:
            return boot, f.read()


def _install_bios_boot(conn, path):
    boot_img, core_img = _grub_images()
    fd = open_device(conn, path, "rw")
    try:
        boot, core = bios_boot_code(boot_img, core_img, os.pread(fd, SECTOR, 0))
        os.pwrite(fd, core, SECTOR)
        os.pwrite(fd, boot, 0)
        os.fsync(fd)
    finally:
        os.close(fd)


def write_windows(iso, dev, status, progress, stopped, scheme="gpt"):
    """Windows installer media through udisks. False if stopped.

    gpt: FAT32 for UEFI. mbr: NTFS with GRUB for Legacy BIOS.
    Raises GLib.Error for anything udisks refuses, OSError for the rest.
    """
    T = get_locale_dict()
    conn = bus()
    path = resolve(conn, dev)

    status(T["prep"])
    unmount_all(conn, path)
    part = make_volume(conn, path, scheme, "WINUSB")
    mounted = False
    try:
        usb = mount(conn, part)
        mounted = True
        with mounted_iso(iso) as src:
            _fill(src, usb, scheme == "gpt", T, status, progress, stopped)
        status(T["sync"])
        # an unmount that fails here must fail the flash: data may be unwritten
        call(conn, part, FILESYSTEM, "Unmount", NO_OPTIONS, "()")
        mounted = False
        if scheme == "mbr":
            # last: closing the disk makes udev reread the partition table,
            # and the partition object goes away for a moment
            status(T["grub"])
            _install_bios_boot(conn, path)
        return True
    except Stopped:
        return False
    finally:
        if mounted:
            unmount(conn, part)
