import os
import shlex

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
    bcd_logic = shlex.quote(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "bcd_logic.py"))

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

# sd* names partitions by appending a number, but a device whose own name ends
# in a digit - nvme0n1, mmcblk0, loop0 - separates them with a "p"
case "$DEV_PATH" in
    *[0-9]) PS="p" ;;
    *)      PS="" ;;
esac

echo "STATUS: {T['part']}"
# GPT: partition 1 = FAT32 ESP, partition 2 = NTFS Windows
parted -s "$DEV_PATH" mklabel gpt
parted -s "$DEV_PATH" mkpart ESP fat32 1MiB 1025MiB
parted -s "$DEV_PATH" set 1 esp on
parted -s "$DEV_PATH" mkpart Windows ntfs 1025MiB 100%
sleep 2

mkfs.vfat -F 32 -n "ESP" "${{DEV_PATH}}${{PS}}1"
mkfs.ntfs -f -L "Windows" "${{DEV_PATH}}${{PS}}2"

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
