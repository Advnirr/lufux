import fcntl
import os
import shlex
import shutil
import struct
import subprocess  # nosec B404 - argv lists only, run as the user
import tempfile

from gi.repository import GLib

from bcd_logic import build_bcd, gpt_guids
from speed_logic import measure_fd
from udisks_logic import (BASIC_DATA, BLOCK, FILESYSTEM, NO_OPTIONS, PARTITION, bus, call, mount,
                          mounted_iso, objects, open_device, resolve, unmount, unmount_all)
from windows_logic import WIM_NAMES, Stopped, _wimlib

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
            "no_bootmgr": "В развёрнутой системе не найден bootmgfw.efi",
            "busy": "Накопитель занят: закройте окна файлового менеджера, открытые на нём",
            "speed": "Замер скорости накопителя...",
            "speed_abort": "Отменено: накопитель слишком медленный",
            "apply": "Развёртывание Windows на накопитель (это надолго)...",
            "boot": "Установка загрузчика UEFI...",
            "bcd": "Создание загрузочного хранилища BCD...",
            "no_bcd": "Не удалось создать хранилище BCD",
            "sync": "Синхронизация ввода-вывода (sync)..."
        }
    return {
# english locals
        "prep": "Preparing drive...",
        "part": "Creating partitions (ESP + Windows)...",
        "no_image": "install.wim/install.esd not found in the image",
        "no_index": "The selected edition is not present in the image",
        "no_bootmgr": "bootmgfw.efi not found in the deployed system",
        "busy": "The drive is busy: close any file manager window showing it",
        "speed": "Measuring drive speed...",
        "speed_abort": "Cancelled: the drive is too slow",
        "apply": "Deploying Windows to the drive (this takes a while)...",
        "boot": "Installing the UEFI bootloader...",
        "bcd": "Writing the BCD boot store...",
        "no_bcd": "Failed to write the BCD boot store",
        "sync": "Syncing I/O (sync)..."
    }

def get_windows_togo_script(img_index=1):
    # iso/dev come in as $1/$2; img_index is the WIM image to deploy.
    # A real, bootable Windows is applied to the drive (not an installer):
    # GPT with a FAT32 ESP + NTFS Windows partition, the WIM is expanded with
    # wimlib and the UEFI bootloader is taken from the deployed image.
    T = get_locale_dict()

    # img_index is an int chosen in Python, never user free-text
    idx = int(img_index)
    # bcd_logic.py ships beside this module, both in the repo and under
    # /usr/share/lufux; the script runs as root through pkexec and only reads it
    here = os.path.dirname(os.path.abspath(__file__))
    bcd_logic = shlex.quote(os.path.join(here, "bcd_logic.py"))
    speed_logic = shlex.quote(os.path.join(here, "speed_logic.py"))

    script = f"""#!/bin/bash
set -eo pipefail

ISO_PATH="$1"
DEV_PATH="$2"
IMG_INDEX="{idx}"

ISO_MNT=$(mktemp -d /tmp/lufux_iso.XXXXXX)
WIN_MNT=$(mktemp -d /tmp/lufux_win.XXXXXX)
EFI_MNT=$(mktemp -d /tmp/lufux_efi.XXXXXX)

cleanup() {{
    trap - EXIT
    set +e
    # the GUI cancels a flash by killing this shell, and bash's children
    # outlive it; unmounting while wimlib still holds write fds would either
    # fail with EBUSY or lose NTFS metadata, so stop them and wait first
    pkill -P $$ 2>/dev/null
    i=0
    while [ $i -lt 50 ] && pgrep -P $$ >/dev/null 2>&1; do
        sleep 0.1
        i=$((i+1))
    done
    pkill -9 -P $$ 2>/dev/null
    sync
    # a child killed a moment ago can still hold the mount, and a single
    # attempt then leaves it behind - that is how /tmp/lufux_* directories and
    # their loop devices survive a cancelled flash
    i=0
    while [ $i -lt 10 ]; do
        umount "$ISO_MNT" "$WIN_MNT" "$EFI_MNT" 2>/dev/null
        mountpoint -q "$ISO_MNT" || mountpoint -q "$WIN_MNT" || mountpoint -q "$EFI_MNT" || break
        sleep 0.5
        i=$((i+1))
    done
    rmdir "$ISO_MNT" "$WIN_MNT" "$EFI_MNT" 2>/dev/null
}}
trap cleanup EXIT

# udisks mounts a removable drive again the moment a filesystem appears on it,
# so a single umount loses the race: wipefs then cannot open the disk, and worse,
# wimlib would later write to an NTFS volume that is mounted behind our back.
detach() {{
    for _ in 1 2 3 4 5; do
        umount "$DEV_PATH"* 2>/dev/null
        findmnt -rno SOURCE | grep -q "^$DEV_PATH" || return 0
        sleep 1
    done
    echo "STATUS: {T['busy']}"
    return 1
}}

echo "STATUS: {T['prep']}"
detach || exit 1
wipefs -a "$DEV_PATH"

echo "STATUS: {T['speed']}"
# Windows To Go runs *from* the drive, so a slow stick costs twice: hours to
# deploy onto, and a system that is then unusable. Measure before spending
# those hours, and let the GUI put the numbers to the user. The test
# writes to the raw device - hence after wipefs, so refusing here leaves the
# drive empty instead of half-overwritten.
SPEED=$(python3 {speed_logic} "$DEV_PATH" 2>/dev/null) || SPEED=""
if [ -n "$SPEED" ]; then
    echo "$SPEED"
    # The GUI always answers, whether or not it asked the user; the timeout is
    # only there so a GUI that died cannot leave this root shell waiting for a
    # line that will never come.
    if ! read -r -t 600 ANSWER; then
        ANSWER="abort"
    fi
    if [ "$ANSWER" != "continue" ]; then
        echo "STATUS: {T['speed_abort']}"
        exit 1
    fi
fi

# sd* names partitions by appending a number, but a device whose own name ends
# in a digit - nvme0n1, mmcblk0, loop0 - separates them with a "p"
case "$DEV_PATH" in
    *[0-9]) PS="p" ;;
    *)      PS="" ;;
esac

echo "STATUS: {T['part']}"
# GPT: partition 1 = FAT32 ESP, partition 2 = NTFS Windows
parted -s "$DEV_PATH" mklabel gpt
parted -s "$DEV_PATH" mkpart ESP fat32 1MiB 513MiB
parted -s "$DEV_PATH" set 1 esp on
parted -s "$DEV_PATH" mkpart Windows ntfs 513MiB 100%
sleep 2

mkfs.vfat -F 32 -n "ESP" "${{DEV_PATH}}${{PS}}1"

# mkntfs normally asks the kernel where the partition starts and writes that
# into the NTFS boot sector, which is the field Windows reads to find the
# volume. Where the geometry ioctls answer nothing - a loop device, and some
# card readers and bridges - it writes zero instead and says so: "Windows will
# not be able to boot from this device". Lufux laid this partition down itself,
# so give mkntfs the number rather than leaving it to ask. It still cannot fill
# in heads and sectors-per-track there and keeps warning about them, but those
# are CHS fields a UEFI boot never reads: with the start set and those left at
# zero, a drive deployed onto a loop device boots to the Windows desktop.
PART_NAME=$(basename "${{DEV_PATH}}${{PS}}2")
PART_START=$(cat "/sys/class/block/$PART_NAME/start" 2>/dev/null || echo 0)
SECTOR_SIZE=$(blockdev --getss "$DEV_PATH" 2>/dev/null || echo 512)
NTFS_START=""
# sysfs counts in 512-byte sectors whatever the device's own sector size is,
# and mkntfs wants the number in the device's sectors
if [ "$PART_START" -gt 0 ] 2>/dev/null && [ "$SECTOR_SIZE" -gt 0 ] 2>/dev/null; then
    NTFS_START="-p $((PART_START * 512 / SECTOR_SIZE))"
fi
mkfs.ntfs -f $NTFS_START -L "Windows" "${{DEV_PATH}}${{PS}}2"

# locate the Windows image inside the ISO
mount -o loop,ro "$ISO_PATH" "$ISO_MNT"
TF=""
[ -f "$ISO_MNT/sources/install.wim" ] && TF="$ISO_MNT/sources/install.wim"
[ -f "$ISO_MNT/sources/install.esd" ] && TF="$ISO_MNT/sources/install.esd"
if [ -z "$TF" ]; then
    echo "STATUS: {T['no_image']}"
    exit 1
fi
if ! wimlib-imagex info "$TF" "$IMG_INDEX" >/dev/null 2>&1; then
    echo "STATUS: {T['no_index']}"
    exit 1
fi

echo "STATUS: {T['apply']}"
# Apply to the raw, UNMOUNTED NTFS volume. wimlib only preserves Windows
# security descriptors, file attributes, reparse points, named data streams
# and short names in this mode; applying to a mounted ntfs-3g directory drops
# all of them ("Ignoring Windows NT security descriptors"), which is enough on
# its own to leave the deployed Windows unbootable. See wimapply(1),
# NTFS VOLUME EXTRACTION.
detach || exit 1
wimlib-imagex apply "$TF" "$IMG_INDEX" "${{DEV_PATH}}${{PS}}2" 2>&1

echo "STATUS: {T['boot']}"
mount "${{DEV_PATH}}${{PS}}2" "$WIN_MNT"
mount "${{DEV_PATH}}${{PS}}1" "$EFI_MNT"
mkdir -p "$EFI_MNT/EFI/Microsoft/Boot" "$EFI_MNT/EFI/Boot"

if [ ! -f "$WIN_MNT/Windows/Boot/EFI/bootmgfw.efi" ]; then
    echo "STATUS: {T['no_bootmgr']}"
    exit 1
fi

# UEFI bootloader from the deployed Windows
cp "$WIN_MNT/Windows/Boot/EFI/bootmgfw.efi" "$EFI_MNT/EFI/Boot/bootx64.efi"
cp "$WIN_MNT/Windows/Boot/EFI/bootmgfw.efi" "$EFI_MNT/EFI/Microsoft/Boot/bootmgfw.efi"
# boot resources (fonts, locale, etc.)
cp -r "$WIN_MNT/Windows/Boot/EFI/." "$EFI_MNT/EFI/Microsoft/Boot/" 2>/dev/null || true
echo "STATUS: {T['bcd']}"
# The BCD store. bcdboot.exe does not exist on Linux and the BCD-Template inside
# the image is not usable on its own - it carries the settings objects and
# {{bootmgr}} but none of the elements that bind a boot entry to a volume, so a
# drive holding only the template stops at 0xc000000f. bcd_logic.py writes a
# complete store instead, reading the drive's own GPT for the identifiers that
# name partition 2 to the boot manager.
if ! python3 {bcd_logic} "$DEV_PATH" 2 "$EFI_MNT/EFI/Microsoft/Boot/BCD"; then
    echo "STATUS: {T['no_bcd']}"
    exit 1
fi

echo "STATUS: {T['sync']}"
# only these two filesystems: a bare sync waits on every device the machine has,
# and one slow USB stick elsewhere can hold it for many minutes
sync -f "$WIN_MNT" "$EFI_MNT"

# unmount before reporting success: the GUI reveals the Done button the moment
# it sees DONE, and a user pulling the stick then must not lose metadata
for MP in "$EFI_MNT" "$WIN_MNT"; do
    UMOUNTED=0
    i=0
    while [ $i -lt 5 ]; do
        if umount "$MP" 2>/dev/null; then
            UMOUNTED=1
            break
        fi
        sleep 1
        i=$((i+1))
    done
    if [ "$UMOUNTED" -ne 1 ]; then
        echo "Failed to unmount $MP" >&2
        exit 1
    fi
done
umount "$ISO_MNT" 2>/dev/null || true

echo "STATUS: DONE"
"""
    return script


ESP_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
ESP_SIZE = 512 << 20
BLKSSZGET = 0x1268


def _partition(conn, table, offset, size, ptype, name, fstype="", label=""):
    table_iface = "org.freedesktop.UDisks2.PartitionTable"
    if fstype:
        reply, _ = call(conn, table, table_iface, "CreatePartitionAndFormat",
                        GLib.Variant("(ttssa{sv}sa{sv})", (offset, size, ptype, name, {}, fstype,
                                                           {"label": GLib.Variant("s", label)})), "(o)")
    else:
        reply, _ = call(conn, table, table_iface, "CreatePartition",
                        GLib.Variant("(ttssa{sv})", (offset, size, ptype, name, {})), "(o)")
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


def _mkntfs(fd, start):
    mkntfs = shutil.which("mkntfs")
    if not mkntfs:
        raise FileNotFoundError("mkntfs")
    # -p: the start sector goes into the boot sector, Windows needs it to boot
    proc = subprocess.run([mkntfs, "-f", "-F", "-p", str(start), "-L", "Windows",  # nosec B603
                           f"/proc/self/fd/{fd}"], pass_fds=[fd], capture_output=True, text=True)
    if proc.returncode:
        raise OSError(proc.stderr.strip() or f"mkntfs: {proc.returncode}")


def _install_boot(boot, esp, store):
    """Copy the boot files extracted from the image and the BCD onto the ESP."""
    ms = os.path.join(esp, "EFI", "Microsoft", "Boot")
    shutil.copytree(boot, ms, dirs_exist_ok=True)
    os.makedirs(os.path.join(esp, "EFI", "Boot"), exist_ok=True)
    shutil.copyfile(os.path.join(boot, "bootmgfw.efi"), os.path.join(esp, "EFI", "Boot", "bootx64.efi"))
    with open(os.path.join(ms, "BCD"), "wb") as f:
        f.write(store)


def write_windows_togo(iso, dev, status, progress, stopped, img_index, ask_speed):
    """Windows To Go through udisks, for the Flatpak. False if stopped.

    mkntfs and wimlib work on the partition's fd as /proc/self/fd/N, which
    needs the patched ntfs-3g the Flatpak builds.
    ask_speed(MB/s, ops/s) returns whether to go on.
    """
    T = get_locale_dict()
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
    win = _partition(conn, path, (1 << 20) + ESP_SIZE, 0, BASIC_DATA, "Windows")
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
            # copied to the ESP after the apply; the image paths match the deployed system
            env = dict(os.environ, WIMLIB_IMAGEX_IGNORE_CASE="1")
            if subprocess.run([shutil.which("wimlib-imagex") or "wimlib-imagex", "extract",  # nosec B603
                               image, str(int(img_index)), "/Windows/Boot/EFI", f"--dest-dir={tmp}"],
                              env=env, capture_output=True, check=False).returncode:
                raise OSError(T["no_index"])
            boot = os.path.join(tmp, "EFI")
            if not os.path.isfile(os.path.join(boot, "bootmgfw.efi")):
                raise OSError(T["no_bootmgr"])

            fd = open_device(conn, win, "rw")
            try:
                sector = struct.unpack("i", fcntl.ioctl(fd, BLKSSZGET, b"\0" * 4))[0]
                _mkntfs(fd, info["Offset"] // sector)
                if stopped():
                    raise Stopped
                status(T["apply"])
                # wimlib keeps Windows metadata only when it writes the NTFS itself
                _wimlib(["apply", image, str(int(img_index)), f"/proc/self/fd/{fd}"],
                        progress, stopped, pass_fds=[fd])
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
