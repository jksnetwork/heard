# SPDX-License-Identifier: GPL-3.0-or-later
"""Typing through the RemoteDesktop portal (org.freedesktop.portal.RemoteDesktop).

Used when the GNOME extension isn't running (e.g. right after installing,
before logging out and in) and on KDE without ydotool. The desktop asks once
to allow remote interaction; the permission is remembered with a restore
token, and the session stays open while Heard runs.

Characters the keyboard layout can't produce are skipped by the compositor,
so the caller only sends typeable text this way.
"""

import uuid

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib  # noqa: E402

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.RemoteDesktop"
KEYBOARD = 1
PERSIST_UNTIL_REVOKED = 2
CHUNK = 32  # keys per main-loop turn
RETURN = 0xFF0D


def available():
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        reply = bus.call_sync(BUS, PATH, "org.freedesktop.DBus.Properties", "Get",
                              GLib.Variant("(ss)", (IFACE, "AvailableDeviceTypes")),
                              None, Gio.DBusCallFlags.NONE, 1000, None)
        return bool(reply.unpack()[0] & KEYBOARD)
    except GLib.Error:
        return False


def keysym(ch):
    return RETURN if ch == "\n" else Gdk.unicode_to_keyval(ord(ch))


class PortalKeyboard:
    def __init__(self, config):
        self.config = config
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.session = None
        self._starting = []  # callbacks waiting for the session

    # -- session ------------------------------------------------------------------

    def _request(self, method, signature, values, options, on_response):
        """Call a portal method that answers through a Request object's Response signal.
        signature/values are the arguments before the trailing options dict."""
        token = "heard" + uuid.uuid4().hex[:12]
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        sub = [0]

        def response(_bus, _sender, _path, _iface, _signal, params):
            self.bus.signal_unsubscribe(sub[0])
            code, results = params.unpack()
            on_response(code, results)
        sub[0] = self.bus.signal_subscribe(BUS, "org.freedesktop.portal.Request", "Response", request_path,
                                           None, Gio.DBusSignalFlags.NO_MATCH_RULE, response)
        options = dict(options, handle_token=GLib.Variant("s", token))

        def called(bus, res):
            try:
                bus.call_finish(res)
            except GLib.Error as e:
                self.bus.signal_unsubscribe(sub[0])
                on_response(2, {"error": e.message})
        self.bus.call(BUS, PATH, IFACE, method, GLib.Variant(f"({signature}a{{sv}})", (*values, options)), None,
                      Gio.DBusCallFlags.NONE, -1, None, called)

    def _ensure_session(self, callback):
        """callback(error or None) once a session with keyboard access is running."""
        if self.session:
            callback(None)
            return
        self._starting.append(callback)
        if len(self._starting) > 1:
            return

        def finish(error):
            if error:
                self.session = None
            waiting, self._starting = self._starting, []
            for cb in waiting:
                cb(error)

        def created(code, results):
            if code != 0:
                finish(results.get("error", "could not open a remote input session"))
                return
            self.session = results["session_handle"]
            self.bus.signal_subscribe(BUS, "org.freedesktop.portal.Session", "Closed", self.session, None,
                                      Gio.DBusSignalFlags.NONE, lambda *_: setattr(self, "session", None))
            options = {"types": GLib.Variant("u", KEYBOARD),
                       "persist_mode": GLib.Variant("u", PERSIST_UNTIL_REVOKED)}
            if self.config.portal_restore_token:
                options["restore_token"] = GLib.Variant("s", self.config.portal_restore_token)
            self._request("SelectDevices", "o", (self.session,), options, selected)

        def selected(code, results):
            if code != 0:
                finish(results.get("error", "keyboard access was not granted"))
                return
            self._request("Start", "os", (self.session, ""), {}, started)

        def started(code, results):
            if code != 0:
                finish("typing into other apps wasn't allowed" if code == 1
                       else results.get("error", "the remote input session didn't start"))
                return
            token = results.get("restore_token")
            if token and token != self.config.portal_restore_token:
                self.config.portal_restore_token = token
                self.config.save()
            finish(None)

        self._request("CreateSession", "", (), {"session_handle_token": GLib.Variant("s", "heard")}, created)

    def close(self):
        if self.session:
            self.bus.call(BUS, self.session, "org.freedesktop.portal.Session", "Close", None, None,
                          Gio.DBusCallFlags.NONE, -1, None, None)
            self.session = None

    # -- typing -----------------------------------------------------------------------

    def type(self, text, enter, callback):
        """Type `text` (then Enter); callback(error or None)."""
        def go(error):
            if error:
                callback(error)
                return
            keys = [keysym(ch) for ch in text] + ([RETURN] if enter else [])
            # give the user a moment to let go of the shortcut's modifier keys
            GLib.timeout_add(250, send, keys, 0)

        def send(keys, start):
            if not self.session:
                callback("the remote input session closed")
                return False
            for sym in keys[start:start + CHUNK]:
                for state in (1, 0):
                    self.bus.call(BUS, PATH, IFACE, "NotifyKeyboardKeysym",
                                  GLib.Variant("(oa{sv}iu)", (self.session, {}, sym, state)),
                                  None, Gio.DBusCallFlags.NONE, -1, None, None)
            if start + CHUNK < len(keys):
                GLib.timeout_add(5, send, keys, start + CHUNK)
            else:
                callback(None)
            return False
        self._ensure_session(go)
