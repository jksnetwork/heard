# SPDX-License-Identifier: GPL-3.0-or-later
"""User settings, stored as JSON in ~/.config/heard/config.json."""

import json
from dataclasses import asdict, dataclass, fields

from .paths import CONFIG_DIR

CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Config:
    # -- speech recognition --
    # a faster-whisper model name; see settings.MODELS
    model: str = "large-v3-turbo"
    # "auto" uses the NVIDIA GPU when the engine can, else the CPU
    device: str = "auto"
    # spoken language as an ISO code ("en", "de", …); "" detects it each time
    language: str = "en"
    # names and jargon Whisper should spell your way, e.g. "Claude, Kubernetes, PipeWire"
    vocabulary: str = ""
    # load the model when Heard starts, so the first dictation isn't slow
    preload: bool = True
    # free the model's (GPU) memory after this many idle minutes; 0 keeps it loaded
    unload_after: int = 30

    # -- recording --
    # GStreamer device name of the microphone; "" is the system default
    microphone: str = ""
    # stop by itself after this many seconds of silence once you've spoken; 0 = only on the shortcut
    silence_stop: float = 0
    # hard limit on one dictation, in seconds
    max_seconds: int = 300
    # short tones when recording starts and stops
    sounds: bool = True

    # -- output --
    # "auto": type it, falling back to paste for characters the keyboard can't type
    # "type": always type; "paste": clipboard + paste keystroke; "clipboard": just copy
    output: str = "auto"
    # turn curly quotes, dashes and ellipses into plain ASCII (helps typing and terminals)
    plain_punctuation: bool = True
    # add a space after the text, so consecutive dictations don't run together
    trailing_space: bool = True
    # press Enter after typing (sends the prompt right away)
    press_enter: bool = False
    # keep the transcript on the clipboard as well
    copy_to_clipboard: bool = True
    # lets the RemoteDesktop portal (typing without the GNOME extension) skip its permission dialog
    portal_restore_token: str = ""

    # -- app --
    # transcripts kept for the History window; 0 = none
    history_limit: int = 500
    show_tray: bool = True
    # the welcome window has been seen (it sets up shortcuts, the engine, the extension)
    welcomed: bool = False

    @classmethod
    def load(cls) -> "Config":
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (OSError, ValueError):
            data = {}
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        if not CONFIG_FILE.exists():
            cfg.save()
        return cfg

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2) + "\n")

    def engine_options(self):
        """Model options for the speech worker."""
        from .paths import MODELS_DIR
        return {"model": self.model, "device": self.device, "models_dir": str(MODELS_DIR)}
