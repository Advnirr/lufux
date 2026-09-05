import os

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
            "sync": "Синхронизация ввода-вывода (sync)..."
        }
    return {
# english locals
        "prep": "Preparing drive...",
        "copy_base": "Copying base files...",
        "copy_wim": "Directly copying WIM...",
        "split_wim": "Splitting WIM image...",
        "conv_lzx": "Converting to LZX (Solid archive)...",
        "sync": "Syncing I/O (sync)..."
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
mkfs.vfat -F 32 -n "WINUSB" "${DEV_PATH}1"
"""
    else:
        part_cmds = """
parted -s "$DEV_PATH" mklabel msdos
parted -s "$DEV_PATH" mkpart primary ntfs 1MiB 100%
parted -s "$DEV_PATH" set 1 boot on
sleep 2
mkfs.ntfs -f -L "WINUSB" "${DEV_PATH}1"
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
    umount "$ISO_MNT" "$USB_MNT" 2>/dev/null
    rmdir "$ISO_MNT" "$USB_MNT" 2>/dev/null
    rm -rf "$WORK_DIR" 2>/dev/null
}}
trap cleanup EXIT

echo "STATUS: {T['prep']}"
umount "$DEV_PATH"* 2>/dev/null || true
wipefs -a "$DEV_PATH"

# applying schemes
{part_cmds}

sleep 2
mount -o loop,ro "$ISO_PATH" "$ISO_MNT"
mount "${{DEV_PATH}}1" "$USB_MNT"

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
