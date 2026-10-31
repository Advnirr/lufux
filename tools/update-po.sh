#!/bin/sh
# Refreshes po/lufux.pot from the code and merges it into every po/*.po.
# Needs xgettext and msgmerge (gettext).
set -eu
cd "$(dirname "$(dirname "$(readlink -f "$0")")")"
xgettext --language=Python --keyword=_ --from-code=UTF-8 --add-location=file \
    --package-name=lufux --msgid-bugs-address=https://github.com/Advnirr/lufux/issues \
    -o po/lufux.pot ./*.py
for po in po/*.po; do
    msgmerge --quiet --update --backup=none --add-location=file "$po" po/lufux.pot
done
