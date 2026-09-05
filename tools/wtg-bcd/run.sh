#!/bin/bash
# run.sh <disk.img> <label> [seconds]  - boot in OVMF, screenshot the console
D="$(dirname "$0")"; IMG="$1"; LABEL="$2"; WAIT="${3:-25}"
cp -f /usr/share/edk2/x64/OVMF_VARS.4m.fd "$D/vars_$LABEL.fd"
rm -f "/tmp/lufux-mon-$LABEL.sock" "$D/shot_$LABEL.ppm"
qemu-system-x86_64 -machine q35 -m 2048 -accel tcg \
  -drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd \
  -drive if=pflash,format=raw,file="$D/vars_$LABEL.fd" \
  -drive file="$IMG",format=raw,if=none,id=d0 -device ide-hd,drive=d0 \
  -display none -monitor "unix:/tmp/lufux-mon-$LABEL.sock,server,nowait" \
  -serial "file:$D/serial_$LABEL.log" -no-reboot &
QPID=$!
sleep "$WAIT"
python3 - "/tmp/lufux-mon-$LABEL.sock" "$D/shot_$LABEL.ppm" <<'PY'
import socket, sys, time
s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); time.sleep(0.5)
s.recv(65536)
s.sendall(b"screendump " + sys.argv[2].encode() + b"\n"); time.sleep(2.0)
s.close()
PY
kill $QPID 2>/dev/null; wait $QPID 2>/dev/null
magick "$D/shot_$LABEL.ppm" "$D/shot_$LABEL.png" 2>/dev/null && echo "screenshot: $D/shot_$LABEL.png"
