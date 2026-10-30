# SPDX-License-Identifier: GPL-3.0-or-later
"""Check the extension types and pastes into a focused window. Run inside a nested shell:

    HEARD_NESTED_HEADLESS=1 tools/nested-shell.sh python3 tools/type_test.py

Opens a text window, has the extension type (and paste) into it, then compares
what arrived with what was sent. Exits non-zero on a mismatch.
"""

import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

TYPED = "Fix the bug in app.py, then run `make test` -- it's 5 > 3 & ok? "
PASTED = "Café naïve — über. "
DEST = ["--dest", "io.github.jksnetwork.Heard.Shell", "--object-path", "/io/github/jksnetwork/Heard/Shell"]


def shell(method, *args):
    out = subprocess.run(["gdbus", "call", "--session", *DEST, "--method",
                          f"io.github.jksnetwork.Heard.Shell.{method}", *args],
                         capture_output=True, text=True, timeout=30)
    return out.stdout.strip() or out.stderr.strip()


def main():
    app = Gtk.Application(application_id="io.github.jksnetwork.HeardTypeTest")
    result = {}

    def activate(app):
        win = Gtk.ApplicationWindow(application=app, title="Type test", default_width=700, default_height=300)
        view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD)
        win.set_child(view)
        win.present()
        view.grab_focus()

        def calls():
            # off the main loop, so this window keeps handling the keys it's sent
            print("indicator:", shell("SetState", "recording", ""))
            print("level:", shell("SetLevel", "0.7"))
            print("focused:", shell("FocusedApp"))
            print("type:", shell("TypeText", TYPED, "type", "false"))
            print("paste:", shell("TypeText", PASTED, "paste", "false"))
            print("hide:", shell("SetState", "hidden", ""))
            GLib.timeout_add(800, collect)

        def run():
            threading.Thread(target=calls, daemon=True).start()
            return False

        def collect():
            buf = view.get_buffer()
            result["text"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
            app.quit()
            return False
        GLib.timeout_add(1500, run)

    app.connect("activate", activate)
    app.run([])
    got = result.get("text", "")
    want = TYPED + PASTED
    print("sent:", repr(want))
    print("got: ", repr(got))
    print("PASS" if got == want else "FAIL")
    return 0 if got == want else 1


if __name__ == "__main__":
    sys.exit(main())
