# SPDX-License-Identifier: GPL-3.0-or-later
"""Application entry point: a single resident instance driven by command-line actions.

The first `heard <action>` starts the service; later invocations forward their
arguments to it over D-Bus and exit. Staying resident keeps the speech model
loaded, so a dictation is transcribed in well under a second.

A dictation: `heard toggle` starts recording, the next `heard toggle` stops it;
the audio goes to the speech worker, and the text is typed into whatever
window has focus.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import __version__, platform, recorder, text  # noqa: E402
from .config import Config  # noqa: E402
from .engine import INSTALL_HINT, Engine  # noqa: E402
from .history import HistoryWindow  # noqa: E402
from .indicator import Indicator  # noqa: E402
from .output import DESCRIPTIONS, Output  # noqa: E402
from .settings import SettingsWindow, model_label  # noqa: E402
from .shell import ShellHelper  # noqa: E402
from .transcripts import Transcripts  # noqa: E402
from .tray import Tray  # noqa: E402
from .welcome import WelcomeWindow  # noqa: E402

APP_ID = "io.github.jksnetwork.Heard"
MIN_SECONDS = 0.4  # shorter takes are accidental double-presses
DEBUG = bool(os.environ.get("HEARD_DEBUG"))


def debug(message, since=None):
    if DEBUG:
        took = f" (+{time.monotonic() - since:.3f} s)" if since else ""
        print(f"heard: {message}{took}", file=sys.stderr, flush=True)

CSS = """
window.heard-overlay { background: transparent; }
.heard-pill {
  margin: 8px;
  padding: 4px 6px 4px 14px;
  border-radius: 99px;
  background: rgba(26,26,30,0.92);
  color: white;
  box-shadow: 0 4px 16px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.12);
}
.heard-pill button { color: white; min-width: 26px; min-height: 26px; padding: 0; }
.heard-dot { min-width: 10px; min-height: 10px; border-radius: 5px; background: #ff3b30; }
.heard-dot.heard-transcribing, .heard-dot.heard-busy { background: #ffb340; }
.heard-label { font-weight: bold; font-feature-settings: "tnum"; }
.heard-bar { min-width: 3px; border-radius: 2px; background: white; }
"""

ACTIONS = ["toggle", "start", "stop", "cancel", "again", "history", "settings", "welcome", "launch",
           "daemon", "quit"]


def build_parser():
    p = argparse.ArgumentParser(prog="heard", description="Speech-to-text dictation for Linux on Wayland")
    p.add_argument("action", nargs="?", default="toggle", choices=ACTIONS,
                   help="toggle (default): start dictating, or stop and type the text | "
                        "start | stop | cancel: discard the current dictation | "
                        "again: type the last transcript again | history: past transcripts | "
                        "settings | welcome: setup screen | launch: welcome on first run, else history | "
                        "daemon: start in background | quit")
    return p


class HeardApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.config = None
        self.shell = ShellHelper()
        self.engine = None
        self.recorder = None
        self.output = None
        self.indicator = None
        self.transcripts = Transcripts()
        self.tray = None
        self.history = None
        self.settings = None
        self.welcome = None
        self.state = "idle"  # idle | recording | transcribing
        self.stopped_at = 0.0
        self.take = 0  # bumped per dictation, so a cancelled one's result is ignored

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.hold()  # stay resident even with no windows open
        self.config = Config.load()
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.engine = Engine(self.config, on_status=self.on_engine_status)
        self.recorder = recorder.Recorder(self.config, on_level=self.on_level,
                                          on_auto_stop=lambda: GLib.idle_add(self.on_auto_stop))
        self.output = Output(self)
        # give the GNOME extension a moment to claim its bus name at login before falling back
        GLib.timeout_add_seconds(2, lambda: self.output.prepare() and False)
        self.indicator = Indicator(self)
        self.shell.subscribe("IndicatorClicked", self.on_indicator_clicked)
        if self.config.show_tray:
            self.tray = Tray(self)
            self.tray.start()
        if self.config.preload and self.engine.installed():
            self.engine.preload()

    def do_shutdown(self):
        if self.recorder:
            self.recorder.cancel()
        if self.indicator:
            self.indicator.set_state("hidden")
        if self.engine:
            self.engine.stop()
        if self.output:
            self.output.close()
        Adw.Application.do_shutdown(self)

    def do_command_line(self, cmdline):
        argv = cmdline.get_arguments()[1:]
        try:
            args = build_parser().parse_args(argv)
        except SystemExit:
            return 1
        self.run_action(args.action)
        return 0

    def run_action(self, action):
        if action == "quit":
            self.quit()
        elif action == "daemon":
            if not self.config.welcomed:
                # first login after installing: give the session a moment to settle
                GLib.timeout_add_seconds(3, lambda: self.open_welcome() and False)
        elif action == "launch":
            if self.config.welcomed:
                self.open_history()
            else:
                self.open_welcome()
        elif action == "toggle":
            self.toggle()
        elif action == "start":
            if self.state == "idle":
                self.start()
        elif action == "stop":
            if self.state == "recording":
                self.stop()
        elif action == "cancel":
            self.cancel()
        elif action == "again":
            self.type_again()
        elif action == "history":
            self.open_history()
        elif action == "settings":
            self.open_settings()
        elif action == "welcome":
            self.open_welcome()
        return True

    # -- dictation ----------------------------------------------------------------

    @property
    def recording(self):
        return self.state == "recording"

    @property
    def transcribing(self):
        return self.state == "transcribing"

    def set_state(self, state):
        self.state = state
        if self.tray:
            self.tray.refresh()

    def toggle(self):
        if self.state == "recording":
            self.stop()
        elif self.state == "idle":
            self.start()
        # while transcribing, a second press would only queue up confusion: ignore it

    def start(self):
        if not self.engine.installed():
            self.notify_error(INSTALL_HINT)
            self.open_welcome()
            return
        try:
            self.recorder.start()
        except (RuntimeError, GLib.Error) as e:
            self.notify_error(f"Could not start recording: {e}")
            return
        self.take += 1
        self.set_state("recording")
        if self.config.sounds:
            recorder.chime(rising=True)
        self.indicator.set_state("recording")
        if not self.engine.loaded and not self.engine.busy:
            # load the model while you speak
            self.engine.preload()

    def stop(self):
        if self.state != "recording":
            return
        take = self.take
        self.stopped_at = time.monotonic()
        debug("stop")
        self.set_state("transcribing")
        if self.config.sounds:
            recorder.chime(rising=False)
        self.indicator.set_state("transcribing", "Transcribing…")
        self.recorder.stop(lambda path, seconds: self.on_recorded(take, path, seconds))

    def cancel(self):
        if self.state == "recording":
            self.recorder.cancel()
        elif self.state != "transcribing":
            return
        self.take += 1
        self.set_state("idle")
        self.indicator.set_state("hidden")

    def on_auto_stop(self):
        if self.state == "recording":
            self.stop()
        return False

    def on_recorded(self, take, path, seconds):
        if take != self.take:
            return
        debug(f"recorded {recorder.seconds_of(path) if path else 0:.1f} s, peak {self.recorder.peak_db:.0f} dB, "
              f"speech {'yes' if self.recorder.heard_speech else 'no'}", self.stopped_at)
        if not path or recorder.seconds_of(path) < MIN_SECONDS or not self.recorder.heard_speech:
            if path:
                Path(path).unlink(missing_ok=True)
            self.finish()
            if path and not self.recorder.heard_speech:
                self.toast("Didn't hear anything. Check the microphone in Settings.")
            return
        debug("recording closed", self.stopped_at)
        self.engine.transcribe(path, lambda reply, error: self.on_transcribed(take, seconds, reply, error))

    def on_transcribed(self, take, seconds, reply, error):
        if take != self.take:
            return  # cancelled meanwhile
        debug(f"transcribed in {reply.get('elapsed') if reply else '?'} s", self.stopped_at)
        if error:
            self.finish()
            self.notify_error(f"Transcription failed: {error}")
            return
        heard = text.clean(reply.get("text", ""), self.config.plain_punctuation)
        if not heard:
            self.finish()
            self.toast("Didn't catch that")
            return
        details = {"seconds": round(seconds, 1), "elapsed": reply.get("elapsed"),
                   "model": self.config.model, "device": reply.get("device")}

        def delivered(method, problem):
            debug(f"{method}", self.stopped_at)
            self.finish()
            self.transcripts.add(heard, self.config.history_limit, method=DESCRIPTIONS[method].lower(),
                                 **details)
            if self._live(self.history):
                self.history.reload()
            if problem:
                self.notify_error(f"Couldn't type the text ({problem}); it's on the clipboard.")
            elif method == "copied" and self.config.output != "clipboard":
                self.toast("Copied " + text.preview(heard) + ". Paste it with Ctrl+V.")
        self.output.deliver(text.finish(heard, self.config.trailing_space), delivered)

    def finish(self):
        self.set_state("idle")
        self.indicator.set_state("hidden")

    def type_again(self):
        last = self.transcripts.last()
        if not last:
            self.toast("Nothing dictated yet")
            return
        if self.state != "idle":
            return

        def delivered(method, problem):
            if problem:
                self.notify_error(f"Couldn't type the text ({problem}); it's on the clipboard.")
            elif method == "copied" and self.config.output != "clipboard":
                self.toast("Copied. Paste it with Ctrl+V.")
        self.output.deliver(text.finish(last["text"], self.config.trailing_space), delivered)

    # -- feedback from the recorder, engine and indicator ------------------------------

    def on_level(self, level):
        self.indicator.set_level(level)

    def on_engine_status(self, message):
        if self.state == "transcribing":
            self.indicator.set_state("transcribing", message)
        elif self.state == "idle":
            self.toast(message)

    def on_indicator_clicked(self, action):
        if action == "stop":
            self.stop()
        elif action == "cancel":
            self.cancel()

    # -- windows ------------------------------------------------------------

    def present(self, window):
        """Show a regular window, raised even when triggered from a global hotkey."""
        if self.shell.available():
            self.shell.call("ManageWindow", GLib.Variant("(s)", (window.get_title(),)),
                            lambda *_: window.present())
        else:
            window.present()

    def _live(self, window):
        """True while `window` is still open (closed windows leave the application's list)."""
        return window is not None and window in self.get_windows()

    def open_history(self):
        if self._live(self.history):
            self.history.reload()
        else:
            self.history = HistoryWindow(self)
        self.present(self.history)

    def open_welcome(self):
        if not self._live(self.welcome):
            self.welcome = WelcomeWindow(self)
        self.present(self.welcome)

    def open_settings(self):
        if not self._live(self.settings):
            self.settings = SettingsWindow(self)
        self.present(self.settings)

    def open_about(self):
        shell = "active" if self.shell.available() else "not running (log out and in after installing)"
        if self.engine.loaded:
            engine = f"{model_label(self.config.model)} on {self.engine.device}"
        else:
            engine = "installed, model not loaded" if self.engine.installed() else "not installed"
        about = Adw.AboutWindow(
            application_name="Heard",
            application_icon="audio-input-microphone",
            version=__version__,
            comments="Speech-to-text dictation for Linux, running on your own computer.",
            website="https://github.com/jksnetwork/heard",
            issue_url="https://github.com/jksnetwork/heard/issues",
            license_type=Gtk.License.GPL_3_0,
            debug_info=(f"Heard {__version__}\n"
                        f"Desktop: {platform.desktop()} ({GLib.getenv('XDG_CURRENT_DESKTOP') or 'unknown'})\n"
                        f"GNOME extension: {shell}\n"
                        f"Typing tool: {platform.typing_tool() or 'none'}\n"
                        f"Speech engine: {engine}\n"
                        f"Model: {self.config.model}, device setting: {self.config.device}\n"
                        f"GTK {Gtk.get_major_version()}.{Gtk.get_minor_version()}, "
                        f"libadwaita {Adw.get_major_version()}.{Adw.get_minor_version()}"),
            debug_info_filename="heard-debug.txt",
        )
        about.set_application(self)
        self.present(about)

    # -- feedback -----------------------------------------------------------

    def toast(self, message, sticky=False):
        n = Gio.Notification.new("Heard")
        n.set_body(message)
        n.set_priority(Gio.NotificationPriority.LOW)
        self.send_notification("status", n)
        if not sticky:
            GLib.timeout_add_seconds(4, lambda: self.withdraw_notification("status") or False)

    def notify_error(self, message):
        message = re.sub(r"^GDBus\.Error:[\w.]+:\s*", "", message)
        print(f"heard: {message}", file=sys.stderr)
        n = Gio.Notification.new("Heard")
        n.set_body(message)
        self.send_notification("error", n)


def main():
    # help is printed by this process: everything else is forwarded to the
    # resident instance, whose output the caller never sees
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        build_parser().print_help()
        return 0
    return HeardApp().run(sys.argv)
