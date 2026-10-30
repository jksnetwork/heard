# SPDX-License-Identifier: GPL-3.0-or-later
"""Where Heard keeps things. No GTK imports: the speech worker and the engine
installer use this too, from Python environments without PyGObject."""

import os
from pathlib import Path


def _xdg(var, fallback):
    return Path(os.environ.get(var) or Path.home() / fallback)


DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "heard"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "heard"
CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / "heard"

# the speech engine: a private virtualenv with faster-whisper (and CUDA libraries
# on NVIDIA machines), set up by `python3 -m heard.enginesetup`
ENGINE_DIR = Path(os.environ.get("HEARD_ENGINE_DIR") or DATA_DIR / "engine")
ENGINE_PYTHON = ENGINE_DIR / "bin" / "python"
ENGINE_INFO = ENGINE_DIR / "heard-engine.json"
MODELS_DIR = CACHE_DIR / "models"

HISTORY_FILE = DATA_DIR / "history.jsonl"


def runtime_dir():
    """Private per-session scratch space for recordings in flight."""
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = Path(base) / "heard"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def engine_installed():
    return ENGINE_PYTHON.exists() and ENGINE_INFO.exists()
