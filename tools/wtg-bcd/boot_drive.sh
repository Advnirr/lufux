#!/bin/bash
# boot_drive.sh <disk-image|block-device> <label> [screenshot seconds...]
#   Boot a finished Windows To Go drive under OVMF/KVM as a USB mass-storage
#   device - the way it will be booted in real use - and screenshot the console
#   at each of the given seconds. OOBE is the success condition, not the
#   desktop, so allow eight to ten minutes.
#
#   A regular file is booted through a qcow2 overlay, so the deployment itself
#   stays pristine and the test can be repeated. A block device is booted
#   directly and therefore needs read/write access to it (run as root), and
#   Windows will write to the drive exactly as it would on real hardware.
set -eo pipefail
TARGET="$1"; LABEL="$2"; shift 2
TIMES="${*:-30 60 90 150 210 300 400 500 600}"
D="$(dirname "$0")"; OUT="$D/boot_$LABEL"
mkdir -p "$OUT"; rm -f "$OUT"/shot_*.ppm "$OUT"/shot_*.png

if [ -b "$TARGET" ]; then
    DISK="$TARGET"
else
    DISK="$OUT/overlay.qcow2"
    rm -f "$DISK"
    qemu-img create -f qcow2 -b "$(realpath "$TARGET")" -F raw "$DISK" >/dev/null
fi

cp -f /usr/share/edk2/x64/OVMF_VARS.4m.fd "$OUT/vars.fd"
SOCK="/tmp/lufux-boot-$LABEL.sock"      # scratchpad paths exceed AF_UNIX's 108 bytes
rm -f "$SOCK"
# cache=none keeps the host page cache from ballooning on a 12 GiB image
qemu-system-x86_64 -machine q35 -m 2048 -smp 2 -accel kvm -cpu host \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd \
  -drive if=pflash,format=raw,file="$OUT/vars.fd" \
  -drive file="$DISK",if=none,id=d0,cache=none,aio=native \
  -device qemu-xhci,id=xhci -device usb-storage,bus=xhci.0,drive=d0 \
  -display none -monitor "unix:$SOCK,server,nowait" \
  -serial "file:$OUT/serial.log" &
QPID=$!

python3 - "$SOCK" "$OUT" $TIMES <<'PY'
import socket, sys, time
sock, out, times = sys.argv[1], sys.argv[2], [float(x) for x in sys.argv[3:]]
time.sleep(3)
s = socket.socket(socket.AF_UNIX); s.connect(sock); time.sleep(0.5); s.recv(65536)
prev = 3.0
for t in times:
    time.sleep(max(0, t - prev)); prev = t
    try:
        s.sendall(f"screendump {out}/shot_{int(t):04d}.ppm\n".encode())
    except OSError:
        break                      # the guest reset and took qemu with it
    time.sleep(1.5)
s.close()
PY

kill $QPID 2>/dev/null; wait $QPID 2>/dev/null
for p in "$OUT"/shot_*.ppm; do
    [ -e "$p" ] || continue
    magick "$p" "${p%.ppm}.png" && rm -f "$p"
done
# a mean of ~0 is a black screen, which is a boot that never drew anything
for f in "$OUT"/shot_*.png; do
    printf '%s mean=%s\n' "$(basename "$f")" "$(magick "$f" -format '%[mean]' info:)"
done
