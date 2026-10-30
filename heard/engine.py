# SPDX-License-Identifier: GPL-3.0-or-later
"""Client for the speech worker (worker.py), which runs in the engine virtualenv.

The worker is started on demand and kept running so the model stays loaded;
after `unload_after` idle minutes it is asked to free the model (and the GPU
memory with it). If it dies it is started again on the next request.
"""

import json
import sys
from pathlib import Path

from gi.repository import Gio, GLib

from . import text
from .paths import ENGINE_PYTHON, engine_installed

APP_ROOT = str(Path(__file__).resolve().parent.parent)
INSTALL_HINT = "The speech engine isn't installed yet. Open Heard's welcome screen to set it up."


class Engine:
    def __init__(self, config, on_status=None):
        self.config = config
        self.on_status = on_status  # callback(message) for progress like model downloads
        self.proc = None
        self.stdin = None
        self.pending = {}  # id -> callback(result, error)
        self.next_id = 1
        self.device = None  # "cuda"/"cpu" once a model is loaded
        self.loaded = False
        self._idle_id = 0

    @staticmethod
    def installed():
        return engine_installed()

    @property
    def busy(self):
        return bool(self.pending)

    # -- process ------------------------------------------------------------------

    def _ensure_running(self):
        if self.proc is not None:
            return True
        if not self.installed():
            return False
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE)
        pythonpath = GLib.getenv("PYTHONPATH")
        launcher.setenv("PYTHONPATH", APP_ROOT + (":" + pythonpath if pythonpath else ""), True)
        launcher.setenv("PYTHONUNBUFFERED", "1", True)
        # the bin/heard launcher may preload gtk4-layer-shell; the worker has no use for it
        launcher.unsetenv("LD_PRELOAD")
        try:
            self.proc = launcher.spawnv([str(ENGINE_PYTHON), "-m", "heard.worker"])
        except GLib.Error as e:
            print(f"heard: could not start the speech engine: {e.message}", file=sys.stderr)
            return False
        self.stdin = self.proc.get_stdin_pipe()
        stdout = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self._read(stdout, self.proc)
        self.proc.wait_async(None, self._on_exit)
        return True

    def _read(self, stream, proc):
        def done(s, res):
            try:
                line, _len = s.read_line_finish_utf8(res)
            except GLib.Error:
                line = None
            if line is None:
                return  # EOF: _on_exit cleans up
            self._on_line(line)
            if proc is self.proc:
                self._read(s, proc)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, done)

    def _on_line(self, line):
        try:
            msg = json.loads(line)
        except ValueError:
            print(f"heard worker: {line}", file=sys.stderr)
            return
        if msg.get("event") == "status":
            if self.on_status:
                self.on_status(msg.get("message", ""))
            return
        if "event" in msg:
            return
        callback = self.pending.pop(msg.get("id"), None)
        if msg.get("ok"):
            if msg.get("device"):
                self.device = msg["device"]
                self.loaded = True
            if callback:
                callback(msg, None)
        elif callback:
            callback(None, msg.get("error") or "unknown error")

    def _on_exit(self, proc, res):
        try:
            proc.wait_finish(res)
        except GLib.Error:
            pass
        if proc is not self.proc:
            return
        self.proc = self.stdin = None
        self.loaded = False
        self.device = None
        pending, self.pending = self.pending, {}
        for callback in pending.values():
            callback(None, "the speech engine stopped unexpectedly")

    def stop(self):
        if self.proc is not None:
            proc, self.proc = self.proc, None
            proc.force_exit()
        self.loaded = False

    # -- requests -------------------------------------------------------------------

    def request(self, cmd, callback=None, **payload):
        """Send a command; callback(reply_dict, None) or callback(None, error_message)."""
        if not self._ensure_running():
            if callback:
                GLib.idle_add(lambda: callback(None, INSTALL_HINT) and False)
            return
        rid = self.next_id
        self.next_id += 1
        self.pending[rid] = callback
        data = json.dumps({"id": rid, "cmd": cmd, **payload}) + "\n"
        try:
            self.stdin.write_all(data.encode(), None)
            self.stdin.flush(None)
        except GLib.Error as e:
            self.pending.pop(rid, None)
            if callback:
                callback(None, f"could not reach the speech engine: {e.message}")

    def preload(self, callback=None):
        self.request("load", callback, **self.config.engine_options())
        self._schedule_unload()

    def transcribe(self, path, callback):
        c = self.config
        self.request("transcribe", callback, path=str(path), delete=True, language=c.language,
                     prompt=text.build_prompt(c.vocabulary), **c.engine_options())
        self._schedule_unload()

    def unload(self):
        if self.proc is not None and self.loaded:
            self.request("unload")
            self.loaded = False

    def _schedule_unload(self):
        if self._idle_id:
            GLib.source_remove(self._idle_id)
            self._idle_id = 0
        minutes = self.config.unload_after
        if minutes > 0:
            def fire():
                self._idle_id = 0
                if self.busy:
                    self._schedule_unload()
                else:
                    self.unload()
                return False
            self._idle_id = GLib.timeout_add_seconds(int(minutes * 60), fire)


def install(on_line, on_done, cpu=False):
    """Run `python3 -m heard.enginesetup` in the background.
    on_line(text) for each progress line; on_done(ok, last_line)."""
    argv = [sys.executable, "-m", "heard.enginesetup"] + (["--cpu"] if cpu else [])
    launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
    pythonpath = GLib.getenv("PYTHONPATH")
    launcher.setenv("PYTHONPATH", APP_ROOT + (":" + pythonpath if pythonpath else ""), True)
    try:
        proc = launcher.spawnv(argv)
    except GLib.Error as e:
        on_done(False, e.message)
        return
    stream = Gio.DataInputStream.new(proc.get_stdout_pipe())
    last = [""]

    def read(s, res):
        try:
            line, _len = s.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            proc.wait_async(None, finished)
            return
        if line.strip():
            last[0] = line.strip()
            on_line(last[0])
        s.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

    def finished(p, res):
        try:
            p.wait_finish(res)
        except GLib.Error:
            pass
        ok = p.get_successful() and last[0] == "done"
        on_done(ok, last[0].removeprefix("error: "))
    stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)
