# SPDX-License-Identifier: GPL-3.0-or-later
"""Getting a transcript into the app you were using.

GNOME: the Shell extension types it (or pastes it) into the focused window.
Sway/Hyprland: wtype. KDE and others: ydotool. Failing those (GNOME before
the extension has loaded, KDE without ydotool), the RemoteDesktop portal.
Otherwise it lands on the clipboard and a notification asks you to paste.
"""

import subprocess
import threading

from gi.repository import GLib

from . import platform, portal, text

# what `method` in the delivery callback can be, for messages
DESCRIPTIONS = {"typed": "Typed", "pasted": "Pasted", "copied": "Copied"}


def resolve_mode(mode, content):
    """The extension's mode for a config.output value: "type" or "paste" (None = clipboard only)."""
    if mode == "clipboard":
        return None
    if mode == "auto":
        return "type" if text.typeable(content) else "paste"
    return mode


class Output:
    def __init__(self, app):
        self.app = app
        self._portal = None
        self._portal_ok = None  # cached portal.available()

    @property
    def config(self):
        return self.app.config

    def deliver(self, content, callback, enter=False):
        """Type/paste/copy `content`, then press Enter if `enter`; callback(method, error)
        with method in DESCRIPTIONS. (Only copying to the clipboard never presses Enter.)"""
        mode = resolve_mode(self.config.output, content)
        if mode is None:
            self.copy(content)
            callback("copied", None)
        elif self.app.shell.available():
            self._with_shell(content, mode, enter, callback)
        elif platform.typing_tool():
            self._with_tool(platform.typing_tool(), content, enter, callback)
        elif self._portal_available():
            self._with_portal(content, enter, callback)
        else:
            self.copy(content)
            callback("copied", None)

    def copy(self, content):
        """Put text on the clipboard, without needing keyboard focus where possible."""
        if self.app.shell.available():
            self.app.shell.call("SetClipboardText", GLib.Variant("(s)", (content,)))
        elif platform.have("wl-copy"):
            try:
                subprocess.Popen(["wl-copy", "--", content], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
        else:
            # needs focus on most Wayland compositors, but it's the last resort
            from gi.repository import Gdk
            Gdk.Display.get_default().get_clipboard().set(content)

    def _with_shell(self, content, mode, enter, callback):
        def done(result, error):
            if error:
                # still give the user their words
                self.copy(content)
                callback("copied", error.message if hasattr(error, "message") else str(error))
                return
            method = result[0]
            if method == "typed" and self.config.copy_to_clipboard:
                self.copy(content.rstrip())
            callback(method, None)
        self.app.shell.call("TypeText", GLib.Variant("(ssb)", (content, mode, enter)), done)

    def _portal_available(self):
        if self._portal_ok is None:
            self._portal_ok = portal.available()
        return self._portal_ok

    def _with_portal(self, content, enter, callback):
        if self._portal is None:
            self._portal = portal.PortalKeyboard(self.config)

        def done(error):
            if error:
                self.copy(content)
                callback("copied", error)
            else:
                # no clipboard copy here: without focus or the extension GNOME would ignore it
                callback("typed", None)
        self._portal.type(content, enter, done)

    def prepare(self):
        """Open the portal session now if it will be needed, so its permission
        dialog comes up at start-up rather than in the middle of a dictation."""
        if self.config.output == "clipboard" or self.app.shell.available() or platform.typing_tool():
            return
        if self._portal_available():
            if self._portal is None:
                self._portal = portal.PortalKeyboard(self.config)
            self._portal._ensure_session(lambda error: error and print(f"heard: portal: {error}"))

    def close(self):
        if self._portal is not None:
            self._portal.close()

    def _with_tool(self, tool, content, enter, callback):
        def work():
            import time
            time.sleep(0.3)  # let go of the shortcut's keys first
            try:
                if tool == "wtype":
                    argv = ["wtype", "--", content]
                    tail = ["wtype", "-k", "Return"]
                else:
                    argv = ["ydotool", "type", "--key-delay", "2", "--", content]
                    tail = ["ydotool", "key", "28:1", "28:0"]
                subprocess.run(argv, check=True, capture_output=True, timeout=60)
                if enter:
                    subprocess.run(tail, check=True, capture_output=True, timeout=5)
                error = None
            except (OSError, subprocess.SubprocessError) as e:
                error = str(e)
            GLib.idle_add(finish, error)

        def finish(error):
            if error:
                self.copy(content)
                callback("copied", f"{tool} failed: {error}")
            else:
                if self.config.copy_to_clipboard:
                    self.copy(content.rstrip())
                callback("typed", None)
            return False
        threading.Thread(target=work, daemon=True).start()
