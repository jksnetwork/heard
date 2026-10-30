# SPDX-License-Identifier: GPL-3.0-or-later
"""The speech worker: runs inside the engine virtualenv and keeps a Whisper
model loaded between dictations. The app talks to it in JSON lines:

  -> {"id": 1, "cmd": "transcribe", "path": ".../take.pcm", "model": "large-v3-turbo",
      "device": "auto", "language": "", "prompt": "Claude, GNOME"}
  <- {"id": 1, "ok": true, "text": "…", "language": "en", "audio": 3.2, "elapsed": 0.41, "device": "cuda"}
  -> {"id": 2, "cmd": "load", ...model options...}     warm up without transcribing
  -> {"id": 3, "cmd": "unload"}                          free the GPU memory
  <- {"event": "status", "message": "Downloading the model…"}

Audio files are raw 16 kHz mono signed 16-bit little-endian PCM.

No GTK here, and this module must stay importable without the app's dependencies.
"""

import gc
import glob
import json
import os
import sys
import time

SAMPLE_RATE = 16000
PAD_SECONDS = 0.6  # trailing silence: without it Whisper sometimes drops the last phrase


def _cuda_library_dirs():
    """lib/ folders of the pip-installed NVIDIA packages (cuBLAS, cuDNN) in this environment."""
    dirs = []
    for site in sys.path:
        dirs += glob.glob(os.path.join(site, "nvidia", "*", "lib"))
    return dirs


def _ensure_library_path():
    """CTranslate2 dlopens libcublas/libcudnn by name, and the loader only reads
    LD_LIBRARY_PATH at start-up, so re-exec once with it set."""
    if os.environ.get("HEARD_WORKER_LIBS"):
        return
    dirs = _cuda_library_dirs()
    env = dict(os.environ, HEARD_WORKER_LIBS="1")
    if dirs:
        env["LD_LIBRARY_PATH"] = ":".join(dirs + [p for p in env.get("LD_LIBRARY_PATH", "").split(":") if p])
    os.execve(sys.executable, [sys.executable, "-m", "heard.worker", *sys.argv[1:]], env)


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


class Engine:
    def __init__(self):
        self.model = None
        self.key = None  # (name, device) of the loaded model
        self.device = None

    def load(self, name, device="auto", models_dir=None):
        if self.model is not None and self.key == (name, device):
            return
        self.unload()
        from faster_whisper import WhisperModel
        from faster_whisper.utils import download_model

        repo = name  # a faster-whisper model name or a Hugging Face repo id
        try:
            path = download_model(repo, local_files_only=True, cache_dir=models_dir)
        except Exception:
            send({"event": "status", "message": f"Downloading the {name} model…"})
            path = download_model(repo, cache_dir=models_dir)

        candidates = [("cuda", "float16"), ("cpu", "int8")] if device == "auto" else [
            (device, "float16" if device == "cuda" else "int8")]
        errors = []
        for dev, compute in candidates:
            if dev == "cuda" and not self._cuda_available():
                errors.append("no CUDA device")
                continue
            try:
                model = WhisperModel(path, device=dev, compute_type=compute,
                                     cpu_threads=min(8, os.cpu_count() or 4))
                # cuDNN/cuBLAS load lazily on the first real work: surface failures now
                self._warm_up(model)
            except Exception as e:  # noqa: BLE001 - anything here means "try the next device"
                errors.append(f"{dev}: {e}")
                gc.collect()
                continue
            self.model, self.key, self.device = model, (name, device), dev
            return
        raise RuntimeError("could not load the model (" + "; ".join(errors) + ")")

    @staticmethod
    def _cuda_available():
        try:
            import ctranslate2
            return ctranslate2.get_cuda_device_count() > 0
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _warm_up(model):
        import numpy as np
        segments, _info = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), beam_size=1,
                                           without_timestamps=True)
        list(segments)

    def unload(self):
        self.model = self.key = self.device = None
        gc.collect()

    def transcribe(self, path, language="", prompt="", beam_size=5, vad=False):
        import numpy as np
        audio = np.fromfile(path, dtype="<i2").astype(np.float32) / 32768.0
        seconds = len(audio) / SAMPLE_RATE
        audio = np.concatenate([audio, np.zeros(int(PAD_SECONDS * SAMPLE_RATE), dtype=np.float32)])
        start = time.monotonic()
        segments, info = self.model.transcribe(
            audio,
            language=language or None,
            initial_prompt=prompt or None,
            beam_size=beam_size,
            vad_filter=vad,
            without_timestamps=True,
            condition_on_previous_text=False,
        )
        text = "".join(s.text for s in segments).strip()
        return {"text": text, "language": info.language, "audio": round(seconds, 2),
                "elapsed": round(time.monotonic() - start, 3), "device": self.device}


def handle(engine, request):
    cmd = request.get("cmd")
    if cmd == "unload":
        engine.unload()
        return {}
    if cmd == "ping":
        return {"device": engine.device}
    if cmd in ("load", "transcribe"):
        engine.load(request.get("model", "large-v3-turbo"), request.get("device", "auto"),
                    request.get("models_dir"))
        if cmd == "load":
            return {"device": engine.device}
        try:
            return engine.transcribe(request["path"], request.get("language", ""), request.get("prompt", ""),
                                     int(request.get("beam_size", 5)), bool(request.get("vad", False)))
        finally:
            if request.get("delete"):
                try:
                    os.unlink(request["path"])
                except OSError:
                    pass
    raise ValueError(f"unknown command {cmd!r}")


def main():
    _ensure_library_path()
    engine = Engine()
    send({"event": "ready", "pid": os.getpid()})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = {}
        try:
            request = json.loads(line)
            reply = handle(engine, request)
            send({"id": request.get("id"), "ok": True, **reply})
        except Exception as e:  # noqa: BLE001 - report every failure to the app
            send({"id": request.get("id"), "ok": False, "error": f"{type(e).__name__}: {e}"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
