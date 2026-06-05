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
set -e

ISO_PATH="$1"
DEV_PATH="$2"
SCHEME="$3"

ISO_MNT=$(mktemp -d /tmp/lufux_iso.XXXXXX)
USB_MNT=$(mktemp -d /tmp/lufux_usb.XXXXXX)
WORK_WIM=$(mktemp -u /tmp/lufux_wim.XXXXXX)

cleanup() {{
    umount "$ISO_MNT" "$USB_MNT" 2>/dev/null || true
    rmdir "$ISO_MNT" "$USB_MNT" 2>/dev/null || true
    rm -f "$WORK_WIM" 2>/dev/null || true
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

echo "STATUS: DONE"
"""
    return script
