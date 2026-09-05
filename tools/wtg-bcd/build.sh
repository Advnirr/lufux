#!/bin/bash
# build.sh <bcd-file> <out-disk.img>   - assemble a WTG-shaped test drive, no root
set -eo pipefail
BCD="$1"; OUT="$2"; D="$(dirname "$0")"

ESP_MB=64; WIN_MB=192
rm -f "$OUT" "$D/esp.img" "$D/win.img"

# --- ESP: FAT32 with the real bootmgfw.efi and the BCD under test ---
truncate -s ${ESP_MB}M "$D/esp.img"
mformat -i "$D/esp.img" -F -v ESP ::
mmd -i "$D/esp.img" ::/EFI ::/EFI/Boot ::/EFI/Microsoft ::/EFI/Microsoft/Boot
mcopy -i "$D/esp.img" "$D/bootmgfw.efi" ::/EFI/Boot/bootx64.efi
mcopy -i "$D/esp.img" "$D/bootmgfw.efi" ::/EFI/Microsoft/Boot/bootmgfw.efi
mcopy -i "$D/esp.img" "$BCD"            ::/EFI/Microsoft/Boot/BCD

# --- Windows partition: NTFS holding \Windows\System32\winload.efi ---
rm -rf "$D/tree"; mkdir -p "$D/tree/Windows/System32"
cp "$D/winload.efi" "$D/tree/Windows/System32/winload.efi"
rm -f "$D/tree.wim"; wimlib-imagex capture "$D/tree" "$D/tree.wim" W --compress=none >/dev/null
truncate -s ${WIN_MB}M "$D/win.img"
mkfs.ntfs -F -f -L Windows "$D/win.img" >/dev/null 2>&1
wimlib-imagex apply "$D/tree.wim" 1 "$D/win.img" >/dev/null

# --- assemble a GPT disk ---
truncate -s $((ESP_MB + WIN_MB + 4))M "$OUT"
parted -s "$OUT" mklabel gpt
parted -s "$OUT" mkpart ESP fat32 1MiB $((1 + ESP_MB))MiB
parted -s "$OUT" set 1 esp on
parted -s "$OUT" mkpart Windows ntfs $((1 + ESP_MB))MiB 100%
dd if="$D/esp.img" of="$OUT" bs=1M seek=1              conv=notrunc status=none
dd if="$D/win.img" of="$OUT" bs=1M seek=$((1+ESP_MB))  conv=notrunc status=none
parted -s "$OUT" print
