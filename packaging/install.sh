#!/bin/sh
# Copies lufux into DESTDIR. Both the .deb and the .rpm are built with it.
set -eu

src=$(dirname "$(dirname "$(readlink -f "$0")")")
share="${1:?usage: install.sh DESTDIR}/usr/share"

install -Dm755 "$src/main.py" "$share/lufux/main.py"
for module in "$src"/*_logic.py; do
    install -Dm644 "$module" "$share/lufux/${module##*/}"
done
install -Dm644 "$src/io.github.mikhail.lufux.desktop" \
    "$share/applications/io.github.mikhail.lufux.desktop"
install -Dm644 "$src/lufux.svg" "$share/icons/hicolor/scalable/apps/lufux.svg"
