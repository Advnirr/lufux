#!/bin/sh
# Builds the Flatpak into the signed repo served from GitHub Pages:
# publish-flatpak.sh PAGES_DIR KEY_ID [BUNDLE]
# Writes PAGES_DIR/repo, the .flatpakref and .flatpakrepo, and BUNDLE if given.
# FLATPAK_BUILDER overrides the builder command, GNUPGHOME the key's home.
set -eu

root=$(dirname "$(dirname "$(readlink -f "$0")")")
pages=$(readlink -f "$1")
key=$2
bundle=${3:-}
app=io.github.Advnirr.Lufux
url=https://advnirr.github.io/lufux
mkdir -p "${TMPDIR:-$HOME/.cache}"
work=$(mktemp -d -p "${TMPDIR:-$HOME/.cache}")
trap 'rm -rf "$work"' EXIT

gpg_home=${GNUPGHOME:+--gpg-homedir=$GNUPGHOME}
# shellcheck disable=SC2086
${FLATPAK_BUILDER:-flatpak-builder} --force-clean --disable-rofiles-fuse \
    --state-dir="$work/state" --repo="$pages/repo" --default-branch=stable \
    --gpg-sign="$key" $gpg_home "$work/build" "$root/packaging/flatpak/$app.yml"
# shellcheck disable=SC2086
flatpak build-update-repo --gpg-sign="$key" $gpg_home --title=Lufux \
    --default-branch=stable --generate-static-deltas --prune --prune-depth=3 "$pages/repo"

if [ -n "$bundle" ]; then
    flatpak build-bundle --runtime-repo=https://flathub.org/repo/flathub.flatpakrepo \
        "$pages/repo" "$bundle" "$app" stable
fi

key64=$(gpg --export "$key" | base64 -w0)
cat > "$pages/$app.flatpakref" <<EOF
[Flatpak Ref]
Name=$app
Branch=stable
Title=Lufux
Url=$url/repo/
SuggestRemoteName=lufux
RuntimeRepo=https://flathub.org/repo/flathub.flatpakrepo
IsRuntime=false
GPGKey=$key64
EOF
cat > "$pages/lufux.flatpakrepo" <<EOF
[Flatpak Repo]
Title=Lufux
Url=$url/repo/
Homepage=https://github.com/Advnirr/lufux
GPGKey=$key64
EOF
# Jekyll skips names starting with "_", and static delta names can
touch "$pages/.nojekyll"
