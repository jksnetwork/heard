# SPDX-License-Identifier: GPL-3.0-or-later
"""Install the speech engine: a private virtualenv with faster-whisper.

On machines with an NVIDIA GPU the CUDA runtime libraries it needs (cuBLAS,
cuDNN) come from pip too, so nothing system-wide is touched. Used by
install.sh and by the welcome screen:

    python3 -m heard.enginesetup [--cpu | --gpu] [--remove]

Progress is printed one step per line; the last line is "done" or "error: …".
"""

import argparse
import json
import shutil
import subprocess
import sys
import time

from .paths import ENGINE_DIR, ENGINE_INFO, ENGINE_PYTHON

PACKAGES = ["faster-whisper>=1.1"]
CUDA_PACKAGES = ["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9,<10"]


def has_nvidia_gpu():
    try:
        return subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def step(message):
    print(message, flush=True)


def run(argv):
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if result.returncode != 0:
        tail = "\n".join(result.stdout.strip().splitlines()[-15:])
        raise RuntimeError(f"{' '.join(argv[:3])}… failed:\n{tail}")


def install(gpu):
    uv = shutil.which("uv")
    ENGINE_DIR.parent.mkdir(parents=True, exist_ok=True)
    if ENGINE_DIR.exists():
        shutil.rmtree(ENGINE_DIR)
    step("Creating the engine environment…")
    if uv:
        run([uv, "venv", "--quiet", "--python", sys.executable, str(ENGINE_DIR)])
    else:
        run([sys.executable, "-m", "venv", str(ENGINE_DIR)])
    packages = PACKAGES + (CUDA_PACKAGES if gpu else [])
    step("Downloading faster-whisper" + (" and the CUDA libraries (about 1.5 GB)…" if gpu else "…"))
    if uv:
        run([uv, "pip", "install", "--quiet", "--python", str(ENGINE_PYTHON), *packages])
    else:
        run([str(ENGINE_PYTHON), "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
        run([str(ENGINE_PYTHON), "-m", "pip", "install", "--quiet", *packages])
    step("Checking the engine…")
    run([str(ENGINE_PYTHON), "-c", "import faster_whisper, ctranslate2"])
    version = subprocess.run([str(ENGINE_PYTHON), "-c", "import faster_whisper; print(faster_whisper.__version__)"],
                             capture_output=True, text=True).stdout.strip()
    ENGINE_INFO.write_text(json.dumps({"gpu": gpu, "faster_whisper": version,
                                       "installed": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2) + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="heard.enginesetup", description="Install Heard's speech engine")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--cpu", action="store_true", help="skip the CUDA libraries even with an NVIDIA GPU")
    group.add_argument("--gpu", action="store_true", help="install the CUDA libraries without checking for a GPU")
    group.add_argument("--remove", action="store_true", help="delete the engine (downloaded models stay)")
    args = p.parse_args(argv)
    if args.remove:
        shutil.rmtree(ENGINE_DIR, ignore_errors=True)
        step("done")
        return 0
    gpu = args.gpu or (not args.cpu and has_nvidia_gpu())
    step("NVIDIA GPU found: using CUDA." if gpu else "No NVIDIA GPU: using the CPU.")
    try:
        install(gpu)
    except (OSError, RuntimeError) as e:
        step(f"error: {e}")
        return 1
    step("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
