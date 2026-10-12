import os
import re
import shutil
import subprocess  # nosec B404 - argv lists only, run as the user

from gi.repository import GLib

from udisks_logic import (FILESYSTEM, NO_OPTIONS, bus, call, make_fat32, mount,
                          mounted_iso, resolve, unmount, unmount_all)

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

def get_windows_script(scheme="gpt"):
    # iso/dev/scheme come in as $1/$2/$3, mount points via mktemp -d (no
    # predictable /tmp paths, no shell injection from the file name)
    T = get_locale_dict()

    # schemes
    if scheme == "gpt":
        part_cmds = """
parted -s "$DEV_PATH" mklabel gpt
parted -s "$DEV_PATH" mkpart primary fat32 1MiB 100%
parted -s "$DEV_PATH" set 1 msftdata on
sleep 2
mkfs.vfat -F 32 -n "WINUSB" "${DEV_PATH}${PS}1"
"""
        boot_cmds = ""
    else:
        part_cmds = """
parted -s "$DEV_PATH" mklabel msdos
parted -s "$DEV_PATH" mkpart primary ntfs 1MiB 100%
parted -s "$DEV_PATH" set 1 boot on
sleep 2
# the partition start, handed to mkntfs for the reason windows_togo_logic.py
# gives: where the geometry ioctls answer nothing it writes zero instead
PART_START=$(cat "/sys/class/block/$(basename "${DEV_PATH}${PS}1")/start" 2>/dev/null || echo 0)
SECTOR_SIZE=$(blockdev --getss "$DEV_PATH" 2>/dev/null || echo 512)
NTFS_START=""
if [ "$PART_START" -gt 0 ] 2>/dev/null && [ "$SECTOR_SIZE" -gt 0 ] 2>/dev/null; then
    NTFS_START="-p $((PART_START * 512 / SECTOR_SIZE))"
fi
mkfs.ntfs -f $NTFS_START -L "WINUSB" "${DEV_PATH}${PS}1"
"""
        # A BIOS runs the boot code in the MBR and then the partition's, and a
        # drive laid out as above has neither: parted writes no boot code and
        # mkfs.ntfs writes a "This is not a bootable disk" stub. GRUB provides
        # both and loads bootmgr as a file, the way WoeUSB does; a Windows 11
        # 24H2 installer booted that way under SeaBIOS reaches Setup.
        boot_cmds = f"""
echo "STATUS: {T['grub']}"
GRUB_INSTALL=$(command -v grub-install || command -v grub2-install || true)
if [ -z "$GRUB_INSTALL" ]; then
    echo "grub-install not found" >&2
    exit 1
fi
"$GRUB_INSTALL" --target=i386-pc --boot-directory="$USB_MNT" --force "$DEV_PATH" 2>&1
# Fedora's grub2-install names the directory after itself
GRUB_DIR="$USB_MNT/grub"
[ -d "$USB_MNT/grub2" ] && GRUB_DIR="$USB_MNT/grub2"
# every module is loaded by name: booted from this NTFS volume, GRUB found no
# command it had not loaded yet, although grub-fstest reads its command.lst
# intact - so autoloading is not relied on
cat > "$GRUB_DIR/grub.cfg" <<'EOF'
insmod part_msdos
insmod ntfs
insmod ntldr
ntldr /bootmgr
boot
EOF
"""

    script = f"""#!/bin/bash
set -eo pipefail

ISO_PATH="$1"
DEV_PATH="$2"
SCHEME="$3"

ISO_MNT=$(mktemp -d /tmp/lufux_iso.XXXXXX)
USB_MNT=$(mktemp -d /tmp/lufux_usb.XXXXXX)
# the exported WIM is >4 GB by construction, so it cannot live on /tmp, which
# is a RAM-backed tmpfs on Arch and Fedora. mktemp -d (not -u) also closes the
# TOCTOU window that a name-only temp path leaves open for a root writer.
WORK_DIR=$(mktemp -d "${{TMPDIR:-/var/tmp}}/lufux_wim.XXXXXX")
WORK_WIM="$WORK_DIR/install.wim"

cleanup() {{
    trap - EXIT
    set +e
    # this trap also fires when the GUI cancels the flash, and bash's children
    # outlive bash. Unmounting while rsync/cp still holds a write fd either
    # fails with EBUSY (leaking the mktemp dir) or loses the FAT32/NTFS
    # metadata, so take the children down and wait for them to actually go.
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
        umount "$ISO_MNT" "$USB_MNT" 2>/dev/null
        mountpoint -q "$ISO_MNT" || mountpoint -q "$USB_MNT" || break
        sleep 0.5
        i=$((i+1))
    done
    rmdir "$ISO_MNT" "$USB_MNT" 2>/dev/null
    rm -rf "$WORK_DIR" 2>/dev/null
}}
trap cleanup EXIT

echo "STATUS: {T['prep']}"
umount "$DEV_PATH"* 2>/dev/null || true
wipefs -a "$DEV_PATH"

# sd* names partitions by appending a number, but a device whose own name ends
# in a digit - nvme0n1, mmcblk0, loop0 - separates them with a "p"
case "$DEV_PATH" in
    *[0-9]) PS="p" ;;
    *)      PS="" ;;
esac

# applying schemes
{part_cmds}

sleep 2
mount -o loop,ro "$ISO_PATH" "$ISO_MNT"
mount "${{DEV_PATH}}${{PS}}1" "$USB_MNT"

echo "STATUS: {T['copy_base']}"
# Copying
rsync -rlptD --no-owner --no-group --info=progress2 --exclude='sources/install.wim' --exclude='sources/install.esd' "$ISO_MNT/" "$USB_MNT/"

TF=""
[ -f "$ISO_MNT/sources/install.wim" ] && TF="$ISO_MNT/sources/install.wim"
[ -f "$ISO_MNT/sources/install.esd" ] && TF="$ISO_MNT/sources/install.esd"

if [ -n "$TF" ]; then
    FS=$(stat -c%s "$TF")

    # cuz of fat32 file size limit if we use MBR (NTFS) or file size < 4 GB, theeeeeen copying.
    if [ "$FS" -lt 4000000000 ] || [ "$SCHEME" == "mbr" ]; then
        echo "STATUS: {T['copy_wim']}"
        cp "$TF" "$USB_MNT/sources/"
    else
        # if file > 4 GB and filesystem is FAT32 (GPT), then using wimlib
        echo "STATUS: {T['split_wim']}"
        set +e
        wimlib-imagex split "$TF" "$USB_MNT/sources/install.swm" 3800 2>&1
        RES=$?
        set -e

        # Code 68 I'm lazy
        if [ $RES -eq 68 ]; then
            echo "STATUS: {T['conv_lzx']}"
            rm -f "$WORK_WIM" "$USB_MNT/sources/install.swm" 2>/dev/null || true

            # fail loudly here rather than filling the filesystem (or RAM) and
            # dying on an already-wiped drive
            AVAIL=$(df -P -B1 "$WORK_DIR" | awk 'NR==2 {{print $4}}')
            if [ "$AVAIL" -lt "$FS" ]; then
                echo "Not enough free space in $WORK_DIR: need $FS bytes, have $AVAIL" >&2
                exit 1
            fi

            wimlib-imagex export "$TF" all "$WORK_WIM" --compress=maximum 2>&1

            echo "STATUS: {T['split_wim']}"
            wimlib-imagex split "$WORK_WIM" "$USB_MNT/sources/install.swm" 3800 2>&1
            rm -f "$WORK_WIM"
        elif [ $RES -ne 0 ]; then
            exit $RES
        fi
    fi
fi
{boot_cmds}
echo "STATUS: {T['sync']}"
sync

# unmount before reporting success: the GUI reveals the Done button the moment
# it sees DONE, and a user pulling the stick then must not lose metadata
UMOUNTED=0
i=0
while [ $i -lt 5 ]; do
    if umount "$USB_MNT" 2>/dev/null; then
        UMOUNTED=1
        break
    fi
    sleep 1
    i=$((i+1))
done
if [ "$UMOUNTED" -ne 1 ]; then
    echo "Failed to unmount $USB_MNT" >&2
    exit 1
fi
umount "$ISO_MNT" 2>/dev/null || true

echo "STATUS: DONE"
"""
    return script


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


def _fill(src, dst, T, status, progress, stopped):
    status(T["copy_base"])
    _copy_tree(src, dst, WIM_NAMES, progress, stopped)

    image = next((os.path.join(src, n) for n in WIM_NAMES
                  if os.path.exists(os.path.join(src, n))), None)
    if not image:
        return
    size = os.path.getsize(image)
    if size < SPLIT_FROM:
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


def write_windows_gpt(iso, dev, status, progress, stopped):
    """Windows installer media on GPT/FAT32 through udisks. False if stopped.

    Raises GLib.Error for anything udisks refuses, OSError for the rest.
    """
    T = get_locale_dict()
    conn = bus()
    path = resolve(conn, dev)

    status(T["prep"])
    unmount_all(conn, path)
    part = make_fat32(conn, path, "WINUSB")
    mounted = False
    try:
        usb = mount(conn, part)
        mounted = True
        with mounted_iso(iso) as src:
            _fill(src, usb, T, status, progress, stopped)
        status(T["sync"])
        # an unmount that fails here must fail the flash: data may be unwritten
        call(conn, part, FILESYSTEM, "Unmount", NO_OPTIONS, "()")
        mounted = False
        return True
    except Stopped:
        return False
    finally:
        if mounted:
            unmount(conn, part)
