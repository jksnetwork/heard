# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end check: record, transcribe and type into a focused window, with a
speech recording played into a temporary PipeWire microphone. Run inside a
headless nested shell, with the speech engine installed:

    HEARD_NESTED_HEADLESS=1 tools/nested-shell.sh python3 tools/dictation_test.py SPEECH.wav "expected words"

With --auto-stop, `heard stop` is never sent: the silence after the recording
has to end the dictation (silence_stop is set to 2 seconds). With --send, it
finishes with `heard send` and checks that Enter was pressed after the text.

Uses throwaway settings and history; your own are left alone.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HEARD = str(ROOT / "bin" / "heard")
MIC = "HeardTestMic"


def main():
    auto_stop = "--auto-stop" in sys.argv
    send = "--send" in sys.argv
    wav, expected = [a for a in sys.argv[1:] if not a.startswith("--")][:2]
    expected = expected.lower()
    data_home = tempfile.mkdtemp(prefix="heard-test-")
    real_data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    os.environ.setdefault("HEARD_ENGINE_DIR", str(real_data / "heard" / "engine"))
    os.environ["XDG_DATA_HOME"] = data_home
    config_dir = Path(os.environ["XDG_CONFIG_HOME"]) / "heard"  # private in the nested session
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(json.dumps({
        "microphone": MIC, "welcomed": True, "show_tray": False, "sounds": False, "preload": True,
        "silence_stop": 2.0 if auto_stop else 0}))

    loopback = subprocess.Popen([
        "pw-loopback", "-n", "heardtest",
        "--capture-props=media.class=Audio/Sink node.name=heardtest_in node.description=HeardTestIn",
        f"--playback-props=media.class=Audio/Source node.name=heardtest_mic node.description={MIC} "
        "audio.channels=1"])
    daemon = subprocess.Popen([HEARD, "daemon"])
    result = {}
    app = Gtk.Application(application_id="io.github.jksnetwork.HeardDictationTest")

    def activate(app):
        win = Gtk.ApplicationWindow(application=app, title="Dictation test", default_width=800, default_height=300)
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD)
        win.set_child(view)
        win.present()
        view.grab_focus()
        buf = view.get_buffer()

        def contents():
            return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

        def drive():
            time.sleep(6)  # the daemon loads the model
            t0 = time.monotonic()
            subprocess.run([HEARD, "start"], check=True)
            time.sleep(0.5)
            subprocess.run(["pw-play", "--target", "heardtest_in", wav], check=True)
            stop = time.monotonic()
            if not auto_stop:
                time.sleep(0.5)
                stop = time.monotonic()
                subprocess.run([HEARD, "send" if send else "stop"], check=True)
            # done once text has arrived and stopped changing for half a second
            seen, steady_since = "", None
            for _ in range(200):
                time.sleep(0.1)
                GLib.idle_add(lambda: result.update(text=contents()) and False)
                now = result.get("text", "")
                if now and now == seen:
                    steady_since = steady_since or time.monotonic()
                    if time.monotonic() - steady_since >= 0.5:
                        break
                else:
                    seen, steady_since = now, None
                    if now and "first" not in result:
                        result["first"] = time.monotonic() - stop
            result["latency"] = result.get("first", 0)
            result["total"] = time.monotonic() - t0
            GLib.idle_add(app.quit)

        threading.Thread(target=drive, daemon=True).start()

    app.connect("activate", activate)
    try:
        app.run([])
    finally:
        subprocess.run([HEARD, "quit"])
        daemon.wait(timeout=10)
        loopback.terminate()
    history = Path(data_home) / "heard" / "history.jsonl"
    got = result.get("text", "")
    print("typed:   ", repr(got))
    print(f"{'end of speech' if auto_stop else 'stop'} -> first text: {result.get('latency', 0):.2f} s")
    if history.exists():
        print("history: ", history.read_text().strip())
    ok = expected in got.lower()
    if send:
        enter = got.endswith("\n") and not got.endswith(" \n")
        print("Enter pressed, no space before it:", enter)
        ok = ok and enter
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
