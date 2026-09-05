#!/bin/bash
# run2.sh <disk.img> <label> [shot seconds...]  - boot in OVMF, screenshot repeatedly
D="$(dirname "$0")"; IMG="$1"; LABEL="$2"; shift 2; TIMES="${*:-20 40 70 110}"
cp -f /usr/share/edk2/x64/OVMF_VARS.4m.fd "$D/vars_$LABEL.fd"
rm -f "/tmp/lufux-mon-$LABEL.sock" "$D/shot_$LABEL"_*.ppm
qemu-system-x86_64 -machine q35 -m 2048 -accel tcg \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd \
  -drive if=pflash,format=raw,file="$D/vars_$LABEL.fd" \
  -drive file="$IMG",format=raw,if=none,id=d0 -device ide-hd,drive=d0 \
  -display none -monitor "unix:/tmp/lufux-mon-$LABEL.sock,server,nowait" \
  -serial "file:$D/serial_$LABEL.log" -no-reboot &
QPID=$!
python3 - "/tmp/lufux-mon-$LABEL.sock" "$D/shot_$LABEL" $TIMES <<'PY'
import socket, sys, time
sock, base, times = sys.argv[1], sys.argv[2], [float(x) for x in sys.argv[3:]]
time.sleep(3); s = socket.socket(socket.AF_UNIX); s.connect(sock); time.sleep(0.5); s.recv(65536)
prev = 3.0
for t in times:
    time.sleep(max(0, t - prev)); prev = t
    try:
        s.sendall(f"screendump {base}_{int(t)}.ppm\n".encode())
    except OSError:
        break
    time.sleep(1.5)
s.close()
PY
kill $QPID 2>/dev/null; wait $QPID 2>/dev/null
for p in "$D/shot_$LABEL"_*.ppm; do magick "$p" "${p%.ppm}.png" 2>/dev/null; rm -f "$p"; done
magick montage "$D/shot_$LABEL"_*.png -tile 2x -geometry +4+4 -label '%f' "$D/mont_$LABEL.png" 2>/dev/null
echo "montage: $D/mont_$LABEL.png"
