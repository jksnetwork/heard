# SPDX-License-Identifier: GPL-3.0-or-later
"""Preferences window, editing the same Config the rest of the app uses."""

import json
import subprocess

from gi.repository import Adw, Gtk

from . import engine, recorder
from .paths import ENGINE_INFO
from .shortcuts_ui import ShortcutsGroup

UNIT = "heard.service"

# (faster-whisper name, label); the first is the default
MODELS = [
    ("large-v3-turbo", "Large v3 Turbo: best balance (1.6 GB)"),
    ("distil-large-v3", "Distil Large v3: English only, fastest large (1.5 GB)"),
    ("large-v3", "Large v3: most accurate, slower (3 GB)"),
    ("medium", "Medium (1.5 GB)"),
    ("small", "Small: good on a CPU (480 MB)"),
    ("small.en", "Small, English only (480 MB)"),
    ("base.en", "Base, English only: fastest on a CPU (150 MB)"),
    ("tiny.en", "Tiny, English only (75 MB)"),
]
DEVICES = [("auto", "Automatic (GPU when available)"), ("cuda", "NVIDIA GPU (CUDA)"), ("cpu", "CPU")]
LANGUAGES = [
    ("", "Detect automatically"), ("en", "English"), ("es", "Spanish"), ("fr", "French"), ("de", "German"),
    ("it", "Italian"), ("pt", "Portuguese"), ("nl", "Dutch"), ("pl", "Polish"), ("sv", "Swedish"),
    ("ru", "Russian"), ("uk", "Ukrainian"), ("tr", "Turkish"), ("ar", "Arabic"), ("hi", "Hindi"),
    ("zh", "Chinese"), ("ja", "Japanese"), ("ko", "Korean"),
]
OUTPUTS = [
    ("auto", "Type it (paste when it can't be typed)"),
    ("type", "Always type"),
    ("paste", "Always paste"),
    ("clipboard", "Only copy to the clipboard"),
]


def _systemctl(*args):
    """Output of `systemctl --user ARGS` (stripped), or None if it failed to run or the unit is unknown."""
    try:
        result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    out = result.stdout.strip()
    if args[0] == "is-enabled":
        return out if out in ("enabled", "disabled") else None
    return out if result.returncode == 0 else None


# Start at login is the systemd user unit set up by install.sh or the package.
# Toggling it never stops the running instance.

def autostart_state():
    """"enabled", "disabled", or None when the login service isn't installed."""
    return _systemctl("is-enabled", UNIT)


def set_autostart(on):
    return _systemctl("enable" if on else "disable", UNIT) is not None


def engine_info():
    try:
        return json.loads(ENGINE_INFO.read_text())
    except (OSError, ValueError):
        return {}


def model_label(name):
    return dict(MODELS).get(name, name)


class EngineGroup(Adw.PreferencesGroup):
    """Speech engine status, with Install and Load buttons (used by Welcome and Settings)."""

    def __init__(self, app, title="Speech engine"):
        super().__init__(title=title)
        self.app = app
        self.installing = False
        self.engine_row = Adw.ActionRow()
        self.engine_icon = Gtk.Image()
        self.engine_row.add_prefix(self.engine_icon)
        self.spinner = Gtk.Spinner(valign=Gtk.Align.CENTER, visible=False)
        self.engine_row.add_suffix(self.spinner)
        self.install_btn = Gtk.Button(valign=Gtk.Align.CENTER)
        self.install_btn.connect("clicked", lambda *_: self.install())
        self.engine_row.add_suffix(self.install_btn)
        self.add(self.engine_row)

        self.model_row = Adw.ActionRow()
        self.model_spinner = Gtk.Spinner(valign=Gtk.Align.CENTER, visible=False)
        self.model_row.add_suffix(self.model_spinner)
        self.load_btn = Gtk.Button(label="Load Now", valign=Gtk.Align.CENTER)
        self.load_btn.connect("clicked", lambda *_: self.load())
        self.model_row.add_suffix(self.load_btn)
        self.add(self.model_row)
        self.refresh()

    def refresh(self):
        installed = engine.Engine.installed()
        info = engine_info()
        if self.installing:
            return
        if installed:
            self.engine_icon.set_from_icon_name("emblem-ok-symbolic")
            self.engine_row.set_title("Speech engine installed")
            self.engine_row.set_subtitle(f"faster-whisper {info.get('faster_whisper', '')}  ·  "
                                         + ("with NVIDIA GPU support" if info.get("gpu") else "CPU only"))
            self.install_btn.set_label("Reinstall")
            self.install_btn.remove_css_class("suggested-action")
        else:
            self.engine_icon.set_from_icon_name("dialog-warning-symbolic")
            self.engine_row.set_title("Speech engine not installed")
            self.engine_row.set_subtitle("Whisper runs on this computer; nothing is sent anywhere. "
                                         "The download is about 2.5 GB with GPU support, 300 MB without.")
            self.install_btn.set_label("Install")
            self.install_btn.add_css_class("suggested-action")
        self.model_row.set_visible(installed)
        self.model_row.set_title(model_label(self.app.config.model))
        eng = self.app.engine
        if eng.loaded:
            self.model_row.set_subtitle(f"Loaded, running on {'the GPU' if eng.device == 'cuda' else 'the CPU'}")
            self.load_btn.set_visible(False)
        else:
            self.model_row.set_subtitle("Downloaded and loaded on first use, or now")
            self.load_btn.set_visible(True)

    def install(self):
        self.installing = True
        self.install_btn.set_visible(False)
        self.spinner.set_visible(True)
        self.spinner.start()
        self.engine_row.set_title("Installing the speech engine…")
        self.app.engine.stop()

        def done(ok, message):
            self.installing = False
            self.spinner.stop()
            self.spinner.set_visible(False)
            self.install_btn.set_visible(True)
            self.refresh()
            if ok:
                self.load()
            else:
                self.engine_row.set_subtitle(f"Failed: {message}")
        engine.install(self.engine_row.set_subtitle, done)

    def load(self):
        self.load_btn.set_visible(False)
        self.model_spinner.set_visible(True)
        self.model_spinner.start()
        self.model_row.set_subtitle("Loading (the first time downloads the model)…")

        def done(_reply, error):
            self.model_spinner.stop()
            self.model_spinner.set_visible(False)
            self.refresh()
            if error:
                self.model_row.set_subtitle(f"Failed: {error}")
                self.load_btn.set_visible(True)
        self.app.engine.preload(done)


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Heard Settings", default_width=660, default_height=760,
                         search_enabled=False)
        self.app = app
        self.config = app.config
        self.connect("close-request", lambda *_: self.config.save() or False)

        page = Adw.PreferencesPage(title="General", icon_name="emblem-system-symbolic")
        self.add(page)

        speech = Adw.PreferencesGroup(title="Speech recognition")
        page.add(speech)
        speech.add(self.combo("Model", "model", MODELS, reload=True))
        speech.add(self.combo("Run on", "device", DEVICES, reload=True))
        speech.add(self.combo("Language", "language", LANGUAGES))
        vocab = self.entry("Vocabulary", "vocabulary")
        speech.add(vocab)
        speech.set_description("Vocabulary: names and jargon to spell your way, separated by commas "
                               "(e.g. Claude, Kubernetes, PipeWire).")
        speech.add(self.switch("Load the model when Heard starts", "preload",
                               "The first dictation is instant instead of taking a few seconds"))
        speech.add(self.spin("Free the model after idle minutes", "unload_after", 0, 1440,
                             "Gives the GPU memory back; 0 keeps it loaded"))

        recording = Adw.PreferencesGroup(title="Recording")
        page.add(recording)
        mics = [("", "System default")] + [(name, name) for name, _default in recorder.microphones()]
        recording.add(self.combo("Microphone", "microphone", mics))
        recording.add(self.spin("Stop after seconds of silence", "silence_stop", 0, 10,
                                "Once you've started speaking; 0 waits for the shortcut", step=0.5, digits=1))
        recording.add(self.spin("Longest dictation (seconds)", "max_seconds", 10, 1800))
        recording.add(self.switch("Play sounds", "sounds", "A short tone when listening starts and stops"))

        output = Adw.PreferencesGroup(title="Output")
        page.add(output)
        output.add(self.combo("Put the text", "output", OUTPUTS))
        output.add(self.switch("Plain punctuation", "plain_punctuation",
                               "Straight quotes, hyphens and three dots instead of typographic ones"))
        output.add(self.switch("Add a space after", "trailing_space",
                               "So consecutive dictations don't run together"))
        output.add(self.switch("Always press Enter after typing", "press_enter",
                               "Or just once: finish with Shift+Super+Enter instead of Shift+Super+H"))
        output.add(self.switch("Also copy to the clipboard", "copy_to_clipboard"))

        general = Adw.PreferencesGroup(title="General")
        page.add(general)
        general.add(self.autostart_row())
        general.add(self.switch("Show tray icon", "show_tray", "Takes effect after restarting Heard"))
        general.add(self.spin("Transcripts to keep in history", "history_limit", 0, 10000,
                              "Only text is kept, never audio. 0 keeps none"))

        keys_page = Adw.PreferencesPage(title="Shortcuts & Engine",
                                        icon_name="preferences-desktop-keyboard-shortcuts-symbolic")
        self.add(keys_page)
        keys_page.add(ShortcutsGroup(title="Global shortcuts"))
        self.engine_group = EngineGroup(app)
        keys_page.add(self.engine_group)
        status = Adw.PreferencesGroup(title="GNOME extension")
        keys_page.add(status)
        active = app.shell.available()
        status.add(Adw.ActionRow(
            title="Active" if active else "Not running",
            subtitle="Typing into apps and the listening indicator are available"
            if active else "Log out and back in after installing so Heard can type into apps"))
        welcome = Adw.ButtonRow(title="Show Welcome Screen") if hasattr(Adw, "ButtonRow") else None
        if welcome is None:
            welcome = Adw.ActionRow(title="Show welcome screen", activatable=True)
            welcome.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        welcome.connect("activated", lambda *_: app.open_welcome())
        status.add(welcome)

    # -- start at login -------------------------------------------------------

    def autostart_row(self):
        row = Adw.SwitchRow(title="Start at login",
                            subtitle="Keeps the model loaded and the shortcut instant. "
                                     "When off, the first shortcut starts Heard.")
        state = autostart_state()
        if state is None:
            row.set_sensitive(False)
            row.set_subtitle("Unavailable: Heard's login service isn't installed")
            return row
        row.set_active(state == "enabled")
        row.connect("notify::active", self.on_autostart_toggled)
        return row

    def on_autostart_toggled(self, row, _pspec):
        if not set_autostart(row.get_active()):
            self.app.notify_error("Could not change start at login")

    # -- row builders -------------------------------------------------------

    def switch(self, title, key, subtitle=None):
        row = Adw.SwitchRow(title=title, active=getattr(self.config, key))
        if subtitle:
            row.set_subtitle(subtitle)
        row.connect("notify::active", lambda r, _p: self.set(key, r.get_active()))
        return row

    def spin(self, title, key, lo, hi, subtitle=None, step=1, digits=0):
        row = Adw.SpinRow.new_with_range(lo, hi, step)
        row.set_title(title)
        row.set_digits(digits)
        row.set_value(getattr(self.config, key))
        if subtitle:
            row.set_subtitle(subtitle)
        cast = float if digits else int
        row.connect("notify::value", lambda r, _p: self.set(key, cast(r.get_value())))
        return row

    def entry(self, title, key):
        row = Adw.EntryRow(title=title, text=getattr(self.config, key), show_apply_button=True)
        row.connect("apply", lambda r: self.set(key, r.get_text().strip()))
        return row

    def combo(self, title, key, choices, reload=False):
        """A drop-down over (value, label) choices; an unknown current value is kept as an extra entry."""
        choices = list(choices)
        current = getattr(self.config, key)
        if current not in [v for v, _l in choices]:
            choices.append((current, current))
        row = Adw.ComboRow(title=title, model=Gtk.StringList.new([label for _v, label in choices]))
        row.set_selected([v for v, _l in choices].index(current))

        def changed(r, _p):
            value = choices[r.get_selected()][0]
            if value == getattr(self.config, key):
                return
            self.set(key, value)
            if reload:
                self.reload_model()
        row.connect("notify::selected", changed)
        return row

    def reload_model(self):
        """Model or device changed: load the new one now if the old one was in use."""
        eng = self.app.engine
        if eng.loaded or self.config.preload:
            eng.loaded = False
            self.engine_group.load()
        else:
            self.engine_group.refresh()

    def set(self, key, value):
        setattr(self.config, key, value)
        self.config.save()
