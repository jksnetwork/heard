# SPDX-License-Identifier: GPL-3.0-or-later
"""The listening indicator. On GNOME the Shell extension draws it; elsewhere a
small GTK window on a layer-shell overlay (KDE, Sway, Hyprland), and failing
that a notification."""

from gi.repository import GLib, Gtk

from . import platform

BARS = 5


class Indicator:
    def __init__(self, app):
        self.app = app
        self.window = None
        self.state = "hidden"

    def set_state(self, state, text=""):
        """state: "recording", "transcribing", "busy" or "hidden"."""
        self.state = state
        if self.app.shell.available():
            self.app.shell.call("SetState", GLib.Variant("(ss)", (state, text)))
            return
        if platform.layer_shell():
            if self.window is None:
                self.window = _OverlayWindow(self.app)
            self.window.set_state(state, text)
        elif state == "recording":
            self.app.toast("Listening… run the shortcut again to stop", sticky=True)
        elif state in ("transcribing", "busy"):
            self.app.toast(text or "Transcribing…", sticky=True)
        else:
            self.app.withdraw_notification("status")

    def set_level(self, level):
        if self.state != "recording":
            return
        if self.app.shell.available():
            self.app.shell.call("SetLevel", GLib.Variant("(d)", (level,)))
        elif self.window is not None:
            self.window.set_level(level)


class _OverlayWindow(Gtk.Window):
    def __init__(self, app):
        super().__init__(application=app, title="Heard Indicator", decorated=False, resizable=False,
                         css_classes=["heard-overlay"])
        ls = platform.layer_shell()
        ls.init_for_window(self)
        ls.set_layer(self, ls.Layer.OVERLAY)
        ls.set_anchor(self, ls.Edge.TOP, True)
        ls.set_margin(self, ls.Edge.TOP, 12)
        ls.set_keyboard_mode(self, ls.KeyboardMode.NONE)
        ls.set_namespace(self, "heard")

        box = Gtk.Box(spacing=10, css_classes=["heard-pill"])
        self.dot = Gtk.Box(css_classes=["heard-dot"], valign=Gtk.Align.CENTER)
        self.label = Gtk.Label(css_classes=["heard-label"])
        self.meter = Gtk.Box(spacing=3, valign=Gtk.Align.CENTER)
        self.bars = []
        for _i in range(BARS):
            bar = Gtk.Box(css_classes=["heard-bar"], valign=Gtk.Align.CENTER)
            self.meter.append(bar)
            self.bars.append(bar)
        self.stop_btn = Gtk.Button(icon_name="media-playback-stop-symbolic", css_classes=["circular", "flat"])
        self.stop_btn.connect("clicked", lambda *_: app.toggle())
        self.send_btn = Gtk.Button(icon_name="mail-send-symbolic", css_classes=["circular", "flat"],
                                   tooltip_text="Stop, type and press Enter")
        self.send_btn.connect("clicked", lambda *_: app.toggle(send=True))
        self.cancel_btn = Gtk.Button(icon_name="window-close-symbolic", css_classes=["circular", "flat"])
        self.cancel_btn.connect("clicked", lambda *_: app.cancel())
        for child in (self.dot, self.label, self.meter, self.stop_btn, self.send_btn, self.cancel_btn):
            box.append(child)
        self.set_child(box)
        self.started = 0
        self.text = ""
        self._tick = 0

    def set_state(self, state, text):
        if self._tick:
            GLib.source_remove(self._tick)
            self._tick = 0
        if state == "hidden":
            self.set_visible(False)
            return
        recording = state == "recording"
        for css in ("heard-recording", "heard-transcribing", "heard-busy"):
            self.dot.remove_css_class(css)
        self.dot.add_css_class(f"heard-{state}")
        self.meter.set_visible(recording)
        self.stop_btn.set_visible(recording)
        self.send_btn.set_visible(recording)
        self.cancel_btn.set_visible(state != "busy")
        self.text = text
        if recording:
            self.started = GLib.get_monotonic_time()
            self.set_level(0)
            self._tick = GLib.timeout_add(500, self._update)
        self._update()
        self.present()

    def _update(self):
        if self.text or not self.meter.get_visible():
            self.label.set_label(self.text)
        else:
            secs = int((GLib.get_monotonic_time() - self.started) / 1e6)
            self.label.set_label(f"{secs // 60}:{secs % 60:02d}")
        return True

    def set_level(self, level):
        lit = round(max(0.0, min(1.0, level)) * BARS + 0.49)
        for i, bar in enumerate(self.bars):
            bar.set_size_request(3, (6, 10, 14, 10, 6)[i] if i < lit else 3)
            bar.set_opacity(1.0 if i < lit else 0.35)
