# SPDX-License-Identifier: GPL-3.0-or-later
"""Which desktop we're on.

GNOME is served by the Shell extension (shell.ShellHelper). Elsewhere text is
typed with whatever tool the compositor allows:

  Hyprland / Sway   wtype (virtual-keyboard protocol)
  KDE and others    ydotool (uinput; needs its daemon running)
  nothing usable    the clipboard, and you paste
"""

import os
import shutil
import subprocess


def desktop():
    current = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
    if "gnome" in current:
        return "gnome"
    if "kde" in current:
        return "kde"
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return "hyprland"
    if os.environ.get("SWAYSOCK"):
        return "sway"
    return "other"


def have(tool):
    return shutil.which(tool) is not None


def ydotool_ready():
    """ydotool only works while ydotoold is running and its socket is reachable."""
    if not have("ydotool"):
        return False
    socket = os.environ.get("YDOTOOL_SOCKET") or f"/run/user/{os.getuid()}/.ydotool_socket"
    if os.path.exists(socket) or os.path.exists("/tmp/.ydotool_socket"):
        return True
    try:
        return subprocess.run(["pgrep", "-x", "ydotoold"], capture_output=True, timeout=2).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def typing_tool():
    """'wtype', 'ydotool' or None, for desktops without the GNOME extension."""
    if desktop() in ("sway", "hyprland", "other") and have("wtype") and os.environ.get("WAYLAND_DISPLAY"):
        return "wtype"
    if ydotool_ready():
        return "ydotool"
    return None


# -- layer shell (KDE, wlroots): an indicator above everything, without focus ---

_layer_shell = None


def layer_shell():
    """The Gtk4LayerShell module when usable on this desktop, else None."""
    global _layer_shell
    if _layer_shell is None:
        _layer_shell = False
        if desktop() != "gnome":  # mutter does not implement wlr-layer-shell
            try:
                import gi
                gi.require_version("Gtk4LayerShell", "1.0")
                from gi.repository import Gtk4LayerShell
                if Gtk4LayerShell.is_supported():
                    _layer_shell = Gtk4LayerShell
            except (ImportError, ValueError):
                pass
    return _layer_shell or None
