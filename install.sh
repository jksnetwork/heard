#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Install Heard for the current user (no root needed).
#
#   curl -fsSL https://raw.githubusercontent.com/jksnetwork/heard/main/install.sh | bash
#   ./install.sh                      from a checkout
#
# Options:
#   --update            same as installing again; your settings, history and engine are kept
#   --main              install the latest code from main instead of the latest release
#   --keybindings       also add the default GNOME shortcut now (the welcome screen offers this)
#   --no-engine         skip the speech engine for now (the welcome screen can install it)
#   --reinstall-engine  set the speech engine up again from scratch
#   --cpu               speech engine without the CUDA libraries, even with an NVIDIA GPU
#   --uninstall         remove everything this script added (history and settings stay)
set -euo pipefail

REPO=jksnetwork/heard
APP_ID=io.github.jksnetwork.Heard

# Started from inside a snap (e.g. VS Code's terminal)? Its GTK environment would crash
# the Python checks below, so shed it (the launcher does the same).
if [[ "${GSETTINGS_SCHEMA_DIR:-}${GTK_PATH:-}" == */snap/* ]]; then
  unset GSETTINGS_SCHEMA_DIR GTK_EXE_PREFIX GTK_PATH GTK_IM_MODULE_FILE GTK_MODULES GIO_MODULE_DIR LOCPATH
  unset GDK_PIXBUF_MODULE_FILE GDK_PIXBUF_MODULEDIR GST_PLUGIN_PATH GST_PLUGIN_SYSTEM_PATH
  export XDG_DATA_DIRS="${XDG_DATA_DIRS_VSCODE_SNAP_ORIG:-/usr/local/share:/usr/share}"
  export XDG_CONFIG_DIRS="${XDG_CONFIG_DIRS_VSCODE_SNAP_ORIG:-/etc/xdg}"
fi

say() { printf '\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError:\033[0m %s\n' "$*" >&2; exit 1; }

# -- run from a download when piped from curl ---------------------------------------

src="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"
if [ ! -f "$src/heard/app.py" ]; then
  [[ " $* " == *" --uninstall "* ]] && [ -x "${XDG_DATA_HOME:-$HOME/.local/share}/heard/install.sh" ] \
    && exec "${XDG_DATA_HOME:-$HOME/.local/share}/heard/install.sh" "$@"
  command -v curl >/dev/null || die "curl is needed to download Heard."
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  url="https://github.com/$REPO/archive/refs/heads/main.tar.gz"
  if [[ " $* " != *" --main "* ]]; then
    tag=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null \
          | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1 || true)
    [ -n "$tag" ] && url="https://github.com/$REPO/archive/refs/tags/$tag.tar.gz"
  fi
  say "Downloading Heard ${tag:-(main)}…"
  curl -fsSL "$url" | tar -xz -C "$tmp" || die "download failed: $url"
  bash "$tmp"/*/install.sh "$@"
  exit $?
fi

data="${XDG_DATA_HOME:-$HOME/.local/share}"
app_dir="$data/heard"          # also holds engine/ and history.jsonl, which updates keep
bin_dir="$HOME/.local/bin"
desktop="$data/applications/$APP_ID.desktop"
icon="$data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
unit="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/heard.service"
ext_uuid=$(sed -n 's/.*"uuid": *"\([^"]*\)".*/\1/p' "$src/gnome-extension/metadata.json")
ext_dir="$data/gnome-shell/extensions/$ext_uuid"

has() { [[ " $ARGS " == *" $1 "* ]]; }
ARGS="$*"

# -- helpers ----------------------------------------------------------------------------

package_manager() {
  local family=""
  [ -r /etc/os-release ] && family=$(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}")
  case "$family" in
    *debian*|*ubuntu*) echo apt ;;
    *fedora*|*rhel*) echo dnf ;;
    *arch*) echo pacman ;;
    *suse*) echo zypper ;;
  esac
}

check_dependencies() {
  local missing
  missing=$(python3 - <<'PY' 2>/dev/null || echo "python3"
import shutil
missing = []
try:
    import gi
    try:
        gi.require_version("Gtk", "4.0"); from gi.repository import Gtk  # noqa: F401
    except (ValueError, ImportError):
        missing.append("gtk4")
    try:
        gi.require_version("Adw", "1"); from gi.repository import Adw
        if (Adw.MAJOR_VERSION, Adw.MINOR_VERSION) < (1, 5):
            missing.append("libadwaita>=1.5")
    except (ValueError, ImportError):
        missing.append("libadwaita")
    try:
        gi.require_version("Gst", "1.0"); from gi.repository import Gst
        Gst.init(None)
        if not any(Gst.ElementFactory.find(e) for e in ("pulsesrc", "pipewiresrc")):
            missing.append("gstreamer-audio-source")
        if not Gst.ElementFactory.find("level"):
            missing.append("gstreamer-plugins-good")
    except (ValueError, ImportError):
        missing.append("gstreamer")
except ImportError:
    missing.append("pygobject")
if not shutil.which("uv"):
    try:
        import ensurepip  # noqa: F401
        import venv  # noqa: F401
    except ImportError:
        missing.append("python3-venv")
print(" ".join(missing))
PY
)
  [ -z "$missing" ] && return 0
  if [ "$missing" = "python3" ]; then
    command -v python3 >/dev/null && missing="a working PyGObject/GTK (python3 crashed importing it)"
  fi
  echo "Heard needs a few things that aren't installed: $missing"
  case "$(package_manager)" in
    apt) echo "  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gstreamer-1.0 gstreamer1.0-plugins-good gstreamer1.0-pipewire python3-venv" ;;
    dnf) echo "  sudo dnf install python3-gobject gtk4 libadwaita gstreamer1-plugins-good pipewire-gstreamer" ;;
    pacman) echo "  sudo pacman -S python-gobject gtk4 libadwaita gst-plugins-good gst-plugin-pipewire" ;;
    zypper) echo "  sudo zypper install python3-gobject typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 typelib-1_0-Gst-1_0 gstreamer-plugins-good gstreamer-plugin-pipewire" ;;
    *) echo "  Install PyGObject, GTK 4, libadwaita (1.5 or newer), GStreamer with good plugins, and Python venv support." ;;
  esac
  [[ "$missing" == *"libadwaita>=1.5"* ]] && echo "  (libadwaita 1.5 ships with Ubuntu 24.04, Fedora 40 and newer.)"
  echo "Then run this installer again."
  exit 1
}

# enabled-extensions is edited directly: GNOME only discovers a newly installed
# extension at the next login, and gnome-extensions refuses to enable it before then
ext_set_enabled() {
  command -v gsettings >/dev/null || return 0
  local list
  list=$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null | sed "s/@as //") || return 0
  list=$(python3 -c "import ast,sys; l=[u for u in ast.literal_eval(sys.argv[1]) if u!=sys.argv[2]]; l+= [sys.argv[2]] if sys.argv[3]=='1' else []; print(l)" "$list" "$ext_uuid" "$1")
  gsettings set org.gnome.shell enabled-extensions "$list"
}

shortcuts() {  # install | remove | list, using the installed copy
  HEARD_LAUNCHER="$bin_dir/heard" PYTHONPATH="$app_dir" python3 -m heard.shortcuts "$1"
}

stop_running() {
  systemctl --user stop heard.service 2>/dev/null || true
  if pgrep -f "python3 -m heard" >/dev/null; then
    "$bin_dir/heard" quit 2>/dev/null || true
  fi
}

# -- uninstall --------------------------------------------------------------------------

if has --uninstall; then
  systemctl --user disable heard.service 2>/dev/null || true
  stop_running
  [ -d "$app_dir/heard" ] && shortcuts remove >/dev/null 2>&1 || true
  ext_set_enabled 0
  rm -rf "$app_dir/heard" "$app_dir/engine" "$app_dir/install.sh" "$bin_dir/heard" "$desktop" "$unit" "$ext_dir" "$icon"
  systemctl --user daemon-reload 2>/dev/null || true
  say "Heard removed. Your settings and transcript history were left in place."
  models="${XDG_CACHE_HOME:-$HOME/.cache}/heard"
  [ -d "$models" ] && echo "Downloaded speech models ($(du -sh "$models" | cut -f1)) are in $models; delete it to free the space."
  exit 0
fi

# -- install ----------------------------------------------------------------------------

check_dependencies
if [ -d /usr/lib/heard/heard ]; then
  echo "Note: the heard system package is also installed; this per-user copy takes precedence."
fi

say "Installing Heard to $app_dir"
stop_running
rm -rf "$app_dir/heard"
mkdir -p "$app_dir" "$bin_dir" "$(dirname "$desktop")" "$(dirname "$unit")"
cp -r "$src/heard" "$app_dir/"
cp "$src/install.sh" "$app_dir/install.sh"   # kept for --uninstall
find "$app_dir/heard" -name __pycache__ -prune -exec rm -rf {} +
install -m 755 "$src/bin/heard" "$bin_dir/heard"

sed "s|Exec=heard|Exec=$bin_dir/heard|" "$src/data/$APP_ID.desktop" > "$desktop"
update-desktop-database "$(dirname "$desktop")" 2>/dev/null || true
install -Dm644 "$src/data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" "$icon"
gtk-update-icon-cache -q -t "$data/icons/hicolor" 2>/dev/null || true

if [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]]; then
  say "Installing the GNOME Shell extension"
  rm -rf "$ext_dir"
  mkdir -p "$ext_dir"
  cp "$src/gnome-extension/"{metadata.json,extension.js,stylesheet.css} "$ext_dir/"
  ext_set_enabled 1
fi

if has --no-engine; then
  :
elif has --reinstall-engine || [ ! -f "$app_dir/engine/heard-engine.json" ]; then
  say "Setting up the speech engine (this downloads faster-whisper; a few minutes)"
  engine_args=()
  has --cpu && engine_args+=(--cpu)
  if ! PYTHONPATH="$app_dir" python3 -m heard.enginesetup "${engine_args[@]}" | sed 's/^/  /'; then
    echo "The speech engine didn't install; the welcome screen can try again."
  fi
fi

# Start with the desktop session. A systemd user unit rather than XDG autostart,
# which some managed machines lock down.
cat > "$unit" <<UNIT
[Unit]
Description=Heard dictation service
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart=$bin_dir/heard daemon
Restart=on-failure

[Install]
WantedBy=graphical-session.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now heard.service >/dev/null 2>&1 || true

if has --keybindings; then
  say "Shortcuts:"
  shortcuts install
fi

case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *) echo "Note: $bin_dir isn't on your PATH; add it to run 'heard' from a terminal." ;;
esac

say "Done."
if [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]] && ! gdbus call --session --dest "$APP_ID.Shell" \
    --object-path /io/github/jksnetwork/Heard/Shell --method org.freedesktop.DBus.Peer.Ping >/dev/null 2>&1; then
  echo "The Heard extension loads at your next login. Until then Heard types through GNOME's"
  echo "remote-input portal: allow it when GNOME asks (once)."
fi
config="${XDG_CONFIG_HOME:-$HOME/.config}/heard/config.json"
if grep -q '"welcomed": true' "$config" 2>/dev/null; then
  echo "Heard is running. Your settings and shortcuts were kept."
else
  echo "Heard is running. The welcome screen will help you set up the shortcut."
fi
