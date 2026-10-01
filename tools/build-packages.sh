#!/bin/sh
# Builds the .deb and the .rpm into dist/: build-packages.sh [deb] [rpm]
# Needs dpkg-deb and rpmbuild. Uses the working tree, not a tag.
set -eu

root=$(dirname "$(dirname "$(readlink -f "$0")")")
version=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "$root/main.py")
dist="$root/dist"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$dist"

build_deb() {
    stage="$work/deb"
    sh "$root/packaging/install.sh" "$stage"
    install -Dm644 "$root/packaging/deb/copyright" "$stage/usr/share/doc/lufux/copyright"
    install -Dm644 "$root/packaging/deb/control" "$stage/DEBIAN/control"
    echo "Installed-Size: $(du -sk --exclude=DEBIAN "$stage" | cut -f1)" >> "$stage/DEBIAN/control"
    dpkg-deb --root-owner-group --build "$stage" "$dist/lufux_${version}_all.deb"
}

build_rpm() {
    top="$work/rpm"
    mkdir -p "$top/SOURCES"
    # named like GitHub's tarball of the tag, which Source0 points to
    (cd "$root" && tar -czf "$top/SOURCES/v$version-stable.tar.gz" \
        --transform "s|^|lufux-$version-stable/|" \
        main.py *_logic.py io.github.mikhail.lufux.desktop lufux.svg \
        LICENSE README.md packaging/install.sh)
    rpmbuild -bb --define "_topdir $top" "$root/packaging/lufux.spec"
    cp "$top"/RPMS/noarch/*.rpm "$dist/"
}

[ $# -gt 0 ] || set -- deb rpm
for kind in "$@"; do
    case $kind in
        deb) build_deb ;;
        rpm) build_rpm ;;
        *) echo "usage: build-packages.sh [deb] [rpm]" >&2; exit 2 ;;
    esac
done
ls -l "$dist"
