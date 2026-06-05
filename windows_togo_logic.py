import os

# Locals
def get_locale_dict():
    lang = os.environ.get('LANG', '')
    if lang.startswith('ru'):
        return {
# russian locals
            "prep": "Подготовка накопителя...",
            "part": "Создание разделов (ESP + Windows)...",
            "no_image": "В образе не найден install.wim/install.esd",
            "apply": "Развёртывание Windows на накопитель (это надолго)...",
            "boot": "Установка загрузчика UEFI...",
            "sync": "Синхронизация ввода-вывода (sync)..."
        }
    return {
# english locals
        "prep": "Preparing drive...",
        "part": "Creating partitions (ESP + Windows)...",
        "no_image": "install.wim/install.esd not found in the image",
        "apply": "Deploying Windows to the drive (this takes a while)...",
        "boot": "Installing the UEFI bootloader...",
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

    script = f"""#!/bin/bash
set -e

ISO_PATH="$1"
DEV_PATH="$2"
IMG_INDEX="{idx}"

ISO_MNT=$(mktemp -d /tmp/lufux_iso.XXXXXX)
WIN_MNT=$(mktemp -d /tmp/lufux_win.XXXXXX)
EFI_MNT=$(mktemp -d /tmp/lufux_efi.XXXXXX)

cleanup() {{
    umount "$ISO_MNT" "$WIN_MNT" "$EFI_MNT" 2>/dev/null || true
    rmdir "$ISO_MNT" "$WIN_MNT" "$EFI_MNT" 2>/dev/null || true
}}
trap cleanup EXIT

echo "STATUS: {T['prep']}"
umount "$DEV_PATH"* 2>/dev/null || true
wipefs -a "$DEV_PATH"

echo "STATUS: {T['part']}"
# GPT: partition 1 = FAT32 ESP, partition 2 = NTFS Windows
parted -s "$DEV_PATH" mklabel gpt
parted -s "$DEV_PATH" mkpart ESP fat32 1MiB 1025MiB
parted -s "$DEV_PATH" set 1 esp on
parted -s "$DEV_PATH" mkpart Windows ntfs 1025MiB 100%
sleep 2

mkfs.vfat -F 32 -n "ESP" "${{DEV_PATH}}1"
mkfs.ntfs -f -L "Windows" "${{DEV_PATH}}2"

mount -o loop,ro "$ISO_PATH" "$ISO_MNT"
mount "${{DEV_PATH}}2" "$WIN_MNT"

# locate the Windows image inside the ISO
TF=""
[ -f "$ISO_MNT/sources/install.wim" ] && TF="$ISO_MNT/sources/install.wim"
[ -f "$ISO_MNT/sources/install.esd" ] && TF="$ISO_MNT/sources/install.esd"
if [ -z "$TF" ]; then
    echo "STATUS: {T['no_image']}"
    exit 1
fi

echo "STATUS: {T['apply']}"
# expand the chosen edition straight onto the NTFS partition
wimlib-imagex apply "$TF" "$IMG_INDEX" "$WIN_MNT" 2>&1

echo "STATUS: {T['boot']}"
mount "${{DEV_PATH}}1" "$EFI_MNT"
mkdir -p "$EFI_MNT/EFI/Microsoft/Boot" "$EFI_MNT/EFI/Boot"

# UEFI bootloader from the deployed Windows
if [ -f "$WIN_MNT/Windows/Boot/EFI/bootmgfw.efi" ]; then
    cp "$WIN_MNT/Windows/Boot/EFI/bootmgfw.efi" "$EFI_MNT/EFI/Boot/bootx64.efi"
    cp "$WIN_MNT/Windows/Boot/EFI/bootmgfw.efi" "$EFI_MNT/EFI/Microsoft/Boot/bootmgfw.efi"
fi
# boot resources (fonts, locale, etc.)
if [ -d "$WIN_MNT/Windows/Boot/EFI" ]; then
    cp -r "$WIN_MNT/Windows/Boot/EFI/." "$EFI_MNT/EFI/Microsoft/Boot/" 2>/dev/null || true
fi
# BCD store seeded from the OS image template
if [ -f "$WIN_MNT/Windows/System32/config/BCD-Template" ]; then
    cp "$WIN_MNT/Windows/System32/config/BCD-Template" "$EFI_MNT/EFI/Microsoft/Boot/BCD"
fi

echo "STATUS: {T['sync']}"
sync

echo "STATUS: DONE"
"""
    return script
