#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Build dist/heard_<version>_all.deb (Ubuntu 24.04+, Debian 13+).
#
#   packaging/build-deb.sh
#
# Installs system-wide: the app in /usr/lib/heard, the launcher in /usr/bin,
# the GNOME extension, a systemd user unit (enabled per user from the welcome
# screen) and AppStream metadata so software centres show a proper page.
#
# The speech engine (faster-whisper, and CUDA libraries on NVIDIA machines) is
# not packaged: it's a large pip environment set up per user from the welcome
# screen, in ~/.local/share/heard/engine.
set -euo pipefail

src="$(cd "$(dirname "$0")/.." && pwd)"
version=$(python3 -c "import re,sys; print(re.search(r'\"(.+)\"', open(sys.argv[1]).read()).group(1))" \
  "$src/heard/__init__.py")
app_id=io.github.jksnetwork.Heard
ext_uuid=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['uuid'])" "$src/gnome-extension/metadata.json")

out="$src/dist"
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$out"

# -- files ----------------------------------------------------------------------
install -d "$root/usr/lib/heard"
cp -r "$src/heard" "$root/usr/lib/heard/"
find "$root/usr/lib/heard" -name __pycache__ -prune -exec rm -rf {} +
install -Dm755 "$src/bin/heard" "$root/usr/bin/heard"

install -Dm644 "$src/data/$app_id.desktop" "$root/usr/share/applications/$app_id.desktop"
install -Dm644 "$src/data/$app_id.metainfo.xml" "$root/usr/share/metainfo/$app_id.metainfo.xml"
install -Dm644 "$src/data/icons/hicolor/symbolic/apps/$app_id-symbolic.svg" \
  "$root/usr/share/icons/hicolor/symbolic/apps/$app_id-symbolic.svg"

ext="$root/usr/share/gnome-shell/extensions/$ext_uuid"
install -d "$ext"
install -m644 "$src/gnome-extension/"{metadata.json,extension.js,stylesheet.css} "$ext/"

install -Dm644 /dev/stdin "$root/usr/lib/systemd/user/heard.service" <<'UNIT'
[Unit]
Description=Heard dictation service
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=/usr/bin/heard daemon
Restart=on-failure

[Install]
WantedBy=graphical-session.target
UNIT

doc="$root/usr/share/doc/heard"
install -d "$doc"
install -m644 "$src/README.md" "$doc/"
cat > "$doc/copyright" <<COPYRIGHT
Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/
Upstream-Name: Heard
Source: https://github.com/jksnetwork/heard

Files: *
Copyright: $(date +%Y) jksnetwork and Heard contributors
License: GPL-3.0-or-later
 On Debian systems, the full text of the GNU General Public License version 3
 can be found in /usr/share/common-licenses/GPL-3.
COPYRIGHT
printf 'heard (%s) unstable; urgency=medium\n\n  * Release %s.\n\n -- jksnetwork <4691887+jksnetwork@users.noreply.github.com>  %s\n' \
  "$version" "$version" "$(date -R)" | gzip -9n > "$doc/changelog.gz"

# -- control --------------------------------------------------------------------
install -d "$root/DEBIAN"
size=$(du -sk --exclude=DEBIAN "$root" | cut -f1)
cat > "$root/DEBIAN/control" <<CONTROL
Package: heard
Version: $version
Architecture: all
Maintainer: jksnetwork <4691887+jksnetwork@users.noreply.github.com>
Installed-Size: $size
Section: utils
Priority: optional
Homepage: https://github.com/jksnetwork/heard
Depends: python3 (>= 3.10), python3-gi (>= 3.42), python3-venv,
 gir1.2-gtk-4.0 (>= 4.12), gir1.2-adw-1 (>= 1.5), gir1.2-gstreamer-1.0,
 gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-pipewire | gstreamer1.0-pulseaudio
Recommends: wl-clipboard
Suggests: wtype, ydotool
Description: speech-to-text dictation into any app, on Wayland
 Press a shortcut, speak, and press it again: your words are typed wherever
 you were typing. Speech recognition is OpenAI's Whisper (via faster-whisper)
 running locally, on an NVIDIA GPU when there is one; nothing is sent anywhere.
 .
 On GNOME a bundled Shell extension types the text and shows a listening
 indicator. KDE Plasma, Hyprland and Sway are supported with ydotool or wtype.
CONTROL

# checksums, for dpkg --verify
(cd "$root" && find . -path ./DEBIAN -prune -o -type f -printf '%P\0' | sort -z | xargs -0 md5sum) \
  > "$root/DEBIAN/md5sums"

deb="$out/heard_${version}_all.deb"
dpkg-deb --root-owner-group -Zxz --build "$root" "$deb" >/dev/null
echo "$deb"
