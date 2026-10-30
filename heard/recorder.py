# SPDX-License-Identifier: GPL-3.0-or-later
"""Microphone capture with GStreamer, straight into the format Whisper wants
(16 kHz mono S16LE), plus a level meter, silence auto-stop and start/stop tones."""

import os
import time

import gi

gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst  # noqa: E402

from .paths import runtime_dir  # noqa: E402

Gst.init(None)

RATE = 16000
CAPS = f"audio/x-raw,format=S16LE,rate={RATE},channels=1"
SPEECH_DB = -42  # RMS above this counts as speaking (silence auto-stop, empty takes)
TAIL_MS = 200  # keep recording briefly after stop, so the last word isn't clipped


def microphones():
    """Input devices as [(display name, is default)], monitors of outputs left out."""
    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter("Audio/Source", None)
    if not monitor.start():
        return []
    out = []
    for device in monitor.get_devices() or []:
        props = device.get_properties()
        if props and props.get_value("device.class") == "monitor":
            continue
        default = bool(props and props.has_field("is-default") and props.get_value("is-default"))
        out.append((device.get_display_name(), default))
    monitor.stop()
    return sorted(set(out), key=lambda d: (not d[1], d[0]))


def _source(name):
    """A source element for the named microphone, or the system default."""
    if name:
        monitor = Gst.DeviceMonitor.new()
        monitor.add_filter("Audio/Source", None)
        if monitor.start():
            try:
                for device in monitor.get_devices() or []:
                    if device.get_display_name() == name:
                        return device.create_element("source")
            finally:
                monitor.stop()
    for factory in ("pulsesrc", "pipewiresrc", "autoaudiosrc"):
        element = Gst.ElementFactory.make(factory, "source")
        if element is not None:
            return element
    raise RuntimeError("no GStreamer audio source available (install gstreamer1.0-pulseaudio or -pipewire)")


class Recorder:
    """One dictation at a time. on_level(0..1) ~20x a second; on_auto_stop() when
    silence_stop or max_seconds says it's time."""

    def __init__(self, config, on_level=None, on_auto_stop=None):
        self.config = config
        self.on_level = on_level
        self.on_auto_stop = on_auto_stop
        self.pipeline = None
        self.path = None
        self.file = None
        self.started = 0.0
        self._spoke = False
        self._quiet_since = None
        self._limit_id = 0
        self.heard_speech = False  # anything above SPEECH_DB in this take
        self.peak_db = -100.0

    @property
    def active(self):
        return self.pipeline is not None

    @property
    def elapsed(self):
        return time.monotonic() - self.started if self.active else 0.0

    def start(self):
        """Raises RuntimeError if the microphone can't be opened."""
        if self.active:
            return
        self.path = runtime_dir() / f"take-{os.getpid()}-{int(time.time() * 1000)}.pcm"
        pipeline = Gst.Pipeline.new("heard-recorder")
        source = _source(self.config.microphone)
        convert = Gst.ElementFactory.make("audioconvert")
        resample = Gst.ElementFactory.make("audioresample")
        caps = Gst.ElementFactory.make("capsfilter")
        caps.set_property("caps", Gst.Caps.from_string(CAPS))
        level = Gst.ElementFactory.make("level")
        level.set_property("interval", 50 * Gst.MSECOND)
        level.set_property("post-messages", True)
        sink = Gst.ElementFactory.make("appsink")
        sink.set_property("emit-signals", True)
        sink.set_property("sync", False)
        sink.connect("new-sample", self._on_sample)
        for element in (source, convert, resample, caps, level, sink):
            pipeline.add(element)
        source.link(convert)
        convert.link(resample)
        resample.link(caps)
        caps.link(level)
        level.link(sink)

        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)
        self.file = open(self.path, "wb")
        self.pipeline = pipeline
        self.started = time.monotonic()
        self._spoke = False
        self._quiet_since = None
        self.heard_speech = False
        self.peak_db = -100.0
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self._teardown()
            self._discard()
            raise RuntimeError("could not open the microphone")
        if self.config.max_seconds > 0:
            self._limit_id = GLib.timeout_add_seconds(self.config.max_seconds, self._on_limit)

    def stop(self, callback):
        """Finish recording; callback(path, seconds) once the file is complete."""
        if not self.active:
            callback(None, 0.0)
            return

        def finish():
            path, seconds = self.path, self.elapsed
            self._teardown()
            self.path = None
            callback(path, seconds)
            return False
        GLib.timeout_add(TAIL_MS, finish)

    def cancel(self):
        if self.active:
            self._teardown()
            self._discard()

    # -- internals -----------------------------------------------------------------

    def _on_sample(self, sink):
        # streaming thread
        sample = sink.emit("pull-sample")
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        if ok:
            try:
                if self.file is not None:
                    self.file.write(info.data)
            finally:
                buffer.unmap(info)
        return Gst.FlowReturn.OK

    def _on_message(self, _bus, message):
        if message.type == Gst.MessageType.ERROR:
            err, _debug = message.parse_error()
            print(f"heard: recording error: {err.message}")
            if self.on_auto_stop:
                self.on_auto_stop()
        elif message.type == Gst.MessageType.ELEMENT:
            s = message.get_structure()
            if s and s.get_name() == "level":
                rms = s.get_value("rms")
                db = max(rms) if rms else -100.0
                self._on_db(db)

    def _on_db(self, db):
        if self.on_level:
            # -60 dB .. -10 dB mapped onto 0..1 for the meter
            self.on_level(min(1.0, max(0.0, (db + 60) / 50)))
        self.peak_db = max(self.peak_db, db)
        if db > SPEECH_DB:
            self.heard_speech = True
        limit = self.config.silence_stop
        if limit <= 0:
            return
        now = time.monotonic()
        if db > SPEECH_DB:
            self._spoke = True
            self._quiet_since = None
        elif self._spoke:
            if self._quiet_since is None:
                self._quiet_since = now
            elif now - self._quiet_since >= limit and self.on_auto_stop:
                self._spoke = False  # fire once
                self.on_auto_stop()

    def _on_limit(self):
        self._limit_id = 0
        if self.active and self.on_auto_stop:
            self.on_auto_stop()
        return False

    def _teardown(self):
        if self._limit_id:
            GLib.source_remove(self._limit_id)
            self._limit_id = 0
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline.get_bus().remove_signal_watch()
            self.pipeline = None
        if self.file is not None:
            self.file.close()
            self.file = None

    def _discard(self):
        if self.path:
            try:
                os.unlink(self.path)
            except OSError:
                pass
            self.path = None


def seconds_of(path):
    try:
        return os.path.getsize(path) / (2 * RATE)
    except OSError:
        return 0.0


# -- feedback tones --------------------------------------------------------------

_tones = []  # keep playing pipelines alive


def chime(rising=True):
    """Two short soft tones: rising when recording starts, falling when it stops."""
    freqs = (660, 990) if rising else (990, 660)
    for i, freq in enumerate(freqs):
        GLib.timeout_add(i * 90, _tone, freq)


def _tone(freq):
    desc = (f"audiotestsrc wave=sine freq={freq} volume=0.15 samplesperbuffer=441 num-buffers=7 ! "
            "audio/x-raw,rate=44100,channels=1 ! audioconvert ! autoaudiosink")
    try:
        pipeline = Gst.parse_launch(desc)
    except GLib.Error:
        return False
    bus = pipeline.get_bus()
    bus.add_signal_watch()

    def done(_bus, message):
        if message.type in (Gst.MessageType.EOS, Gst.MessageType.ERROR):
            pipeline.set_state(Gst.State.NULL)
            bus.remove_signal_watch()
            if pipeline in _tones:
                _tones.remove(pipeline)
    bus.connect("message", done)
    _tones.append(pipeline)
    pipeline.set_state(Gst.State.PLAYING)
    return False

