#!/bin/sh
# Copies lufux into DESTDIR. Every package but the Flatpak is built with it.
# Needs msgfmt (gettext) for the translations.
set -eu

src=$(dirname "$(dirname "$(readlink -f "$0")")")
share="${1:?usage: install.sh DESTDIR}/usr/share"

install -Dm755 "$src/main.py" "$share/lufux/main.py"
for module in "$src"/*_logic.py "$src/i18n.py"; do
    install -Dm644 "$module" "$share/lufux/${module##*/}"
done
for po in "$src"/po/*.po; do
    lang=$(basename "$po" .po)
    install -d "$share/locale/$lang/LC_MESSAGES"
    msgfmt --check -o "$share/locale/$lang/LC_MESSAGES/lufux.mo" "$po"
done
install -Dm644 "$src/io.github.Advnirr.Lufux.desktop" \
    "$share/applications/io.github.Advnirr.Lufux.desktop"
install -Dm644 "$src/io.github.Advnirr.Lufux.metainfo.xml" "$share/metainfo/io.github.Advnirr.Lufux.metainfo.xml"
install -Dm644 "$src/lufux.svg" "$share/icons/hicolor/scalable/apps/io.github.Advnirr.Lufux.svg"
