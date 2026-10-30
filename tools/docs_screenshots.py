# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate the screenshots in docs/images/.

Run inside a nested GNOME Shell so nothing personal ends up in the images:

    HEARD_NESTED_HEADLESS=1 tools/nested-shell.sh python3 tools/docs_screenshots.py [welcome settings history indicator]

Settings and history go to a temporary directory and are filled with sample
transcripts; the speech engine is read from your install (for its status row).
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "images"
HEARD = str(ROOT / "bin" / "heard")

TMP = Path(tempfile.mkdtemp(prefix="heard-docs-"))
real_data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
os.environ.setdefault("HEARD_ENGINE_DIR", str(real_data / "heard" / "engine"))
os.environ["XDG_CONFIG_HOME"] = str(TMP / "config")
os.environ["XDG_DATA_HOME"] = str(TMP / "data")

from gi.repository import Gio, GLib  # noqa: E402

SAMPLES = [
    ("Refactor the settings window so the engine status sits next to the shortcuts, and add a test "
     "for the vocabulary prompt.", 7.4, 0.42),
    ("Can you explain why the PipeWire source drops the first few hundred milliseconds after resume?", 5.1, 0.38),
    ("Reply to Sam: sounds good, let's ship it Thursday after the review.", 3.6, 0.31),
    ("Write a commit message for the history search fix.", 2.9, 0.29),
    ("Summarise the open issues labelled GNOME 47 and suggest which to fix first.", 4.8, 0.36),
]


def seed():
    from heard.transcripts import Transcripts
    store = Transcripts(TMP / "data" / "heard" / "history.jsonl")
    for text, seconds, elapsed in SAMPLES:
        store.add(text, 500, seconds=seconds, elapsed=elapsed, model="large-v3-turbo", device="cuda",
                  method="typed")
    config = TMP / "config" / "heard"
    config.mkdir(parents=True, exist_ok=True)
    (config / "config.json").write_text(json.dumps({
        "welcomed": True, "show_tray": False, "preload": False, "sounds": False,
        "vocabulary": "Claude, PipeWire, GNOME"}))


def screenshot(name, crop=None):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    path = str(OUT / f"{name}.png")
    bus.call_sync("org.gnome.Shell.Screenshot", "/org/gnome/Shell/Screenshot", "org.gnome.Shell.Screenshot",
                  "Screenshot", GLib.Variant("(bbs)", (False, False, path)), None, Gio.DBusCallFlags.NONE,
                  10000, None)
    if crop:
        from gi.repository import GdkPixbuf
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        x, y, w, h = crop
        pixbuf.new_subpixbuf(x, y, w, h).savev(path, "png", [], [])
    print("saved", path)


def heard(*args):
    subprocess.run([HEARD, *args], check=True)


def shell(method, signature, *args):
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    bus.call_sync("io.github.jksnetwork.Heard.Shell", "/io/github/jksnetwork/Heard/Shell",
                  "io.github.jksnetwork.Heard.Shell", method, GLib.Variant(signature, args) if args else None,
                  None, Gio.DBusCallFlags.NONE, 5000, None)


def main():
    only = set(sys.argv[1:])  # e.g. "welcome indicator"; default: all
    OUT.mkdir(parents=True, exist_ok=True)
    seed()
    # GNOME Shell only takes screenshots for a few well-known callers
    Gio.bus_own_name(Gio.BusType.SESSION, "org.gnome.Screenshot", Gio.BusNameOwnerFlags.NONE, None, None, None)
    ctx = GLib.MainContext.default()
    end = time.monotonic() + 1
    while time.monotonic() < end:
        ctx.iteration(False)

    for action, name in (("welcome", "welcome"), ("settings", "settings"), ("history", "history")):
        if only and name not in only:
            continue
        daemon = subprocess.Popen([HEARD, "daemon"])
        time.sleep(3)
        heard(action)
        time.sleep(3)
        screenshot(name)
        heard("quit")
        daemon.wait(timeout=10)

    if only and "indicator" not in only:
        return 0
    shell("SetState", "(ss)", "recording", "")
    for level in (0.2, 0.9, 0.6, 0.75):
        shell("SetLevel", "(d)", level)
        time.sleep(0.15)
    time.sleep(1.4)
    screenshot("indicator", crop=(600, 0, 400, 90))
    shell("SetState", "(ss)", "transcribing", "Transcribing…")
    time.sleep(0.5)
    screenshot("transcribing", crop=(600, 0, 400, 90))
    shell("SetState", "(ss)", "hidden", "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
