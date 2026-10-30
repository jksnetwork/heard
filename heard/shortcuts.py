# SPDX-License-Identifier: GPL-3.0-or-later
"""Global shortcuts, as GNOME custom keybindings.

GNOME runs the command for a custom keybinding itself, so Heard only has to
register `heard <action>` under the right accelerator. Other desktops bind
keys in their own configuration (see instructions()).

Also usable from the installer:  python3 -m heard.shortcuts install|remove|list
"""

import os
import shutil
import sys

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Gio  # noqa: E402

from . import platform  # noqa: E402

MEDIA_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM = MEDIA_KEYS + ".custom-keybinding"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"

# (id, description, default accelerator or None); id is also the `heard` action
DEFAULTS = [
    ("toggle", "Start or stop dictation", "<Shift><Super>h"),
    ("send", "Stop dictation and press Enter", "<Shift><Super>Return"),
    ("cancel", "Cancel dictation", None),
    ("again", "Type the last transcript again", None),
]
DESCRIPTIONS = {d[0]: d[1] for d in DEFAULTS}

# GNOME's own shortcut lists, checked for clashes
SYSTEM_SCHEMAS = [
    ("org.gnome.desktop.wm.keybindings", "Windows"),
    ("org.gnome.shell.keybindings", "GNOME Shell"),
    ("org.gnome.mutter.keybindings", "Windows"),
    ("org.gnome.mutter.wayland.keybindings", "Windows"),
    (MEDIA_KEYS, "System"),
]


def available():
    """True when we can manage shortcuts here (GNOME with its media-keys schema)."""
    source = Gio.SettingsSchemaSource.get_default()
    return platform.desktop() == "gnome" and source is not None and source.lookup(MEDIA_KEYS, True) is not None


def _launcher():
    # set by bin/heard; GNOME runs keybinding commands without ~/.local/bin on PATH
    return os.environ.get("HEARD_LAUNCHER") or shutil.which("heard") or "heard"


def _path(action):
    return f"{BASE}heard-{action}/"


def _entry(path):
    return Gio.Settings.new_with_path(CUSTOM, path)


def _paths():
    return list(Gio.Settings.new(MEDIA_KEYS).get_strv("custom-keybindings"))


def _set_paths(paths):
    Gio.Settings.new(MEDIA_KEYS).set_strv("custom-keybindings", paths)


def current():
    """{action: accelerator or None} for Heard's shortcuts."""
    paths = set(_paths())
    out = {}
    for action, _desc, _default in DEFAULTS:
        path = _path(action)
        binding = _entry(path).get_string("binding") if path in paths else ""
        out[action] = binding or None
    return out


def set_binding(action, accel):
    """Bind `action` to `accel`; None removes the shortcut."""
    path = _path(action)
    paths = _paths()
    if accel:
        entry = _entry(path)
        entry.set_string("name", f"Heard: {DESCRIPTIONS[action].lower()}")
        entry.set_string("command", f"{_launcher()} {action}")
        entry.set_string("binding", accel)
        if path not in paths:
            _set_paths(paths + [path])
    else:
        if path in paths:
            _set_paths([p for p in paths if p != path])
        _entry(path).reset("name")
        _entry(path).reset("command")
        _entry(path).reset("binding")
    Gio.Settings.sync()


def install_defaults():
    """Add every default shortcut that doesn't clash with something else. Returns the skipped ones."""
    skipped = []
    have = current()
    for action, _desc, accel in DEFAULTS:
        if have[action] or not accel:
            continue
        clash = conflicts(accel, action)
        if clash:
            skipped.append((action, accel, clash))
        else:
            set_binding(action, accel)
    return skipped


def remove_all():
    for action, _desc, _default in DEFAULTS:
        set_binding(action, None)


# -- clashes --------------------------------------------------------------------

def _normalize(accel):
    """Comparable form of an accelerator, or None if it doesn't parse."""
    from gi.repository import Gdk, Gtk
    ok, key, mods = Gtk.accelerator_parse(accel)
    if not ok or not key:
        return None
    return Gdk.keyval_to_lower(key), int(mods)


def conflicts(accel, ignore_action=None):
    """Who else uses `accel`: a short description, or None."""
    target = _normalize(accel)
    if target is None:
        return None
    source = Gio.SettingsSchemaSource.get_default()
    for schema_id, area in SYSTEM_SCHEMAS:
        schema = source.lookup(schema_id, True)
        if schema is None:
            continue
        settings = Gio.Settings.new(schema_id)
        for key in schema.list_keys():
            value = settings.get_value(key)
            if value.get_type_string() == "as":
                accels = value.unpack()
            elif value.get_type_string() == "s" and key not in ("custom-keybindings",):
                accels = [value.unpack()]
            else:
                continue
            if any(_normalize(a) == target for a in accels if a):
                return f"{area}: {schema.get_key(key).get_summary() or key}"
    ours = {_path(a) for a, _d, _k in DEFAULTS}
    for path in _paths():
        entry = _entry(path)
        if path == (_path(ignore_action) if ignore_action else None):
            continue
        if entry.get_string("binding") and _normalize(entry.get_string("binding")) == target:
            name = entry.get_string("name") or "a custom shortcut"
            return name if path in ours else f"Custom shortcut: {name}"
    return None


# -- other desktops -------------------------------------------------------------

def instructions():
    """How to bind keys where Heard can't do it itself."""
    launcher = _launcher()
    kind = platform.desktop()
    if kind == "kde":
        return ("KDE Plasma picks up Heard's shortcuts (Meta+Shift+H, and Meta+Shift+Return to also "
                "press Enter) from its menu entry. Change them in System Settings → Keyboard → Shortcuts → Heard.")
    if kind == "hyprland":
        return ("Add these to ~/.config/hypr/hyprland.conf:\n\n"
                f"bind = SUPER SHIFT, H, exec, {launcher} toggle\n"
                f"bind = SUPER SHIFT, Return, exec, {launcher} send")
    if kind == "sway":
        return ("Add these to your Sway config:\n\n"
                f"bindsym $mod+Shift+h exec {launcher} toggle\n"
                f"bindsym $mod+Shift+Return exec {launcher} send")
    return f"Bind a key to the command `{launcher} toggle` in your desktop's keyboard settings."


def main(argv):
    command = argv[1] if len(argv) > 1 else "list"
    if not available():
        print(instructions())
        return 0
    if command == "install":
        for action, accel, clash in install_defaults():
            print(f"  skipped {accel} for '{action}': already used by {clash}")
        for action, accel in current().items():
            if accel:
                print(f"  {accel:<20} heard {action}")
    elif command == "remove":
        remove_all()
        print("Heard shortcuts removed.")
    else:
        for action, accel in current().items():
            print(f"  {accel or '(none)':<20} {DESCRIPTIONS[action]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
