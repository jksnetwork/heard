# SPDX-License-Identifier: GPL-3.0-or-later
"""Client for the Heard GNOME Shell extension (gnome-extension/), when it is running."""

import os

from gi.repository import Gio, GLib


class ShellHelper:
    BUS_NAME = "io.github.jksnetwork.Heard.Shell"
    PATH = "/io/github/jksnetwork/Heard/Shell"
    IFACE = "io.github.jksnetwork.Heard.Shell"
    TIMEOUT = 30_000  # typing a long dictation takes a moment

    def __init__(self):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)

    def available(self):
        if os.environ.get("HEARD_NO_SHELL"):  # testing the other desktops' paths on GNOME
            return False
        try:
            self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                               "GetNameOwner", GLib.Variant("(s)", (self.BUS_NAME,)),
                               None, Gio.DBusCallFlags.NONE, 500, None)
            return True
        except GLib.Error:
            return False

    def subscribe(self, signal, callback):
        """callback(*args) whenever the extension emits `signal`."""
        self.bus.signal_subscribe(self.BUS_NAME, self.IFACE, signal, self.PATH, None,
                                  Gio.DBusSignalFlags.NONE,
                                  lambda *a: callback(*a[5].unpack()))

    def call(self, method, params=None, callback=None):
        """Async call; callback(result_tuple, None) or callback(None, error)."""
        def done(bus, res):
            try:
                result = bus.call_finish(res).unpack()
            except GLib.Error as e:
                if callback:
                    callback(None, e)
                return
            if callback:
                callback(result, None)
        self.bus.call(self.BUS_NAME, self.PATH, self.IFACE, method, params, None,
                      Gio.DBusCallFlags.NO_AUTO_START, self.TIMEOUT, None, done)
