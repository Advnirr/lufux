#!/bin/bash
# boot_bcd.sh <bcd-file> <label> [screenshot seconds...]
#   Drop a BCD into the ESP of a disk built by build.sh and boot it.
set -eo pipefail
D="$(dirname "$0")"; cd "$D"; BCD="$1"; L="$2"; shift 2
cp -f esp.img "esp_$L.img"
mcopy -o -i "esp_$L.img" "$BCD" ::/EFI/Microsoft/Boot/BCD
cp -f disk.img "disk_$L.img"
dd if="esp_$L.img" of="disk_$L.img" bs=1M seek=1 conv=notrunc status=none
./run.sh "disk_$L.img" "$L" "$@"
rm -f "disk_$L.img" "esp_$L.img"
# the console text sits in the middle band of the 1280x800 framebuffer
for f in shot_${L}_*.png; do
    magick "$f" -crop 1280x460+0+120 +repage "lbl_${L}_${f##*_}"
done
