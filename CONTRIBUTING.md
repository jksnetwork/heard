# Contributing to Heard

Thanks for helping. Two kinds of testing are especially valuable right now:

- **Desktops other than GNOME.** KDE Plasma, Hyprland and Sway support (typing with `ydotool`/`wtype`, the layer-shell indicator, the RemoteDesktop portal on KDE) is written against those desktops' documented APIs but hasn't been tried on them yet.
- **Machines without an NVIDIA GPU.** The CPU path works but has seen little use. Reports of which model is usable on which CPU are welcome.

## Reporting bugs

Please include:
- your distribution, desktop and version, and whether the speech engine runs on a GPU or the CPU
- what you did, what you expected, and what happened
- the debug info from **About Heard → Troubleshooting** (tray menu)
- if you can, the output of `heard quit; HEARD_DEBUG=1 heard daemon` while you reproduce it. It logs timings, the microphone level and errors, never what you said.

If the GNOME extension misbehaves, the shell's log helps: `journalctl --user -b | grep -i heard`.

## Running from a checkout

```bash
./install.sh --no-engine    # once: GNOME extension, shortcut command, unit; skip if you have the engine
bin/heard quit              # stop an installed instance, if one is running
HEARD_DEBUG=1 bin/heard daemon   # run this checkout in the foreground
bin/heard toggle            # in another terminal: trigger actions
```

`bin/heard` uses the checkout when it sits next to the `heard/` package. The speech engine is shared: `python3 -m heard.enginesetup` creates it in `~/.local/share/heard/engine` (set `HEARD_ENGINE_DIR` to use another one).

Requirements: Python 3.10+, PyGObject, GTK 4 (4.12+), libadwaita (1.5+), GStreamer with the good plugins (`level`, `pulsesrc` or `pipewiresrc`). The engine needs Python venv support or `uv`, and a few GB of disk.

## How it fits together

```
 hotkey / tray / CLI ──► heard <action> ──D-Bus──► resident Heard app (GTK 4, system Python)
                                                     │
          ┌──────────────────────────────────────────┼─────────────────────────────────┐
          ▼                                          ▼                                 ▼
  recorder.py: GStreamer             engine.py ──JSON lines──► worker.py          output.py
  mic → 16 kHz mono S16LE            (stdin/stdout)            in the engine venv:  GNOME: extension (TypeText)
  + level meter, silence stop                                  faster-whisper,      wlroots: wtype · KDE: ydotool
                                                               model kept loaded    else: RemoteDesktop portal,
                                                                                    then the clipboard
```

- **The app is a single resident instance** (`Gio.Application`), started at login by a systemd user unit. Later `heard …` invocations forward their arguments to it and exit. Staying resident keeps the model loaded and the shortcut instant.
- **The speech worker runs in its own virtualenv** (`heard/worker.py`, started by `heard/engine.py`). That keeps faster-whisper, CTranslate2 and the pip-installed CUDA libraries away from the system Python that runs GTK, and a crash there doesn't take the app down: the next request restarts it. The worker re-executes itself once with `LD_LIBRARY_PATH` pointing at the pip NVIDIA packages, because CTranslate2 loads cuBLAS/cuDNN by name. It must not import GTK or anything outside the standard library and the engine's packages.
- **Whisper settings that matter:** the VAD filter is off, because it dropped whole sentences in testing. A short punctuated prompt (`text.BASE_PROMPT`) makes Whisper punctuate and capitalise; longer prompts made it skip the start of speech. Silent takes are never transcribed, because Whisper invents text for silence. Each take is padded with 0.6 s of silence, which helps it keep the last words.
- **Typing on Wayland** needs the compositor's help: the extension's virtual keyboard on GNOME, `wtype` or `ydotool` elsewhere, the RemoteDesktop portal as a fallback (it asks for permission once and keeps a restore token).

### Source layout

| Path | What's in it |
|---|---|
| `heard/app.py` | Application, command-line actions, the dictation flow (idle → recording → transcribing → delivery) |
| `heard/recorder.py` | GStreamer microphone capture, levels, silence stop, start/stop tones |
| `heard/engine.py`, `worker.py` | App-side client and the worker that runs faster-whisper |
| `heard/enginesetup.py` | Creates the engine virtualenv (used by `install.sh` and the welcome screen) |
| `heard/output.py`, `portal.py`, `platform.py` | Getting text into apps: extension, wtype/ydotool, RemoteDesktop portal, clipboard |
| `heard/text.py`, `transcripts.py` | Transcript clean-up and the Whisper prompt; history storage (pure Python, unit-tested) |
| `heard/indicator.py`, `shell.py` | The listening pill (via the extension, or a layer-shell window); the extension's D-Bus client |
| `heard/settings.py`, `welcome.py`, `history.py`, `tray.py`, `shortcuts*.py` | Preferences, first-run setup, history window, tray icon, GNOME keybindings |
| `gnome-extension/` | The GNOME Shell extension |
| `tools/` | Nested-shell harness, typing and end-to-end dictation tests, docs screenshot generator |
| `tests/` | Unit tests |

### The extension's D-Bus API

Bus name `io.github.jksnetwork.Heard.Shell`, object `/io/github/jksnetwork/Heard/Shell`, interface `io.github.jksnetwork.Heard.Shell`. `Version` is currently 1.

| Member | Signature | Purpose |
|---|---|---|
| `TypeText(text, mode, enter)` | `ssb → s` | Waits for the user to let go of modifier keys, then types (`mode` `type`) or pastes (`paste`: clipboard plus Ctrl+V, or Ctrl+Shift+V in terminals) into the focused window, then Enter if asked. Returns `typed` or `pasted`. |
| `SetState(state, text)` | `ss` | The pill: `recording` (timer, meter, stop/send/cancel), `transcribing`, `busy` or `hidden`. `text` replaces the timer. |
| `SetLevel(level)` | `d` | Microphone level 0–1 for the meter |
| `IndicatorClicked` (signal) | `s` | `stop`, `send` or `cancel` from the pill's buttons |
| `SetClipboardText(text)` | `s` | Set the clipboard without having focus |
| `FocusedApp()` | `→ ss` | WM class and title of the focused window |
| `ManageWindow(title)` | `s` | Raise Heard's window with this title when it opens (hotkey-opened windows have no activation token) |
| `Version` (property) | `u` | |

Typing uses `Clutter.VirtualInputDevice.notify_keyval`. Mutter can only type keysyms that exist in the current keyboard layout, which is why `output.py` pastes text that isn't plain ASCII.

## Tests

```bash
python3 -m unittest discover tests
```

The unit tests cover transcript clean-up and the prompt, history storage, the worker's protocol and the choice between typing and pasting. Please add tests next to anything you change that doesn't need a display.

### End-to-end tests without logging out

GNOME on Wayland only loads extensions at login. The `tools/` scripts run a throwaway GNOME Shell instead, with its own D-Bus bus and in-memory settings, so nothing touches your session. Use the headless mode: a windowed nested shell sends virtual keystrokes to your real session instead of its own.

```bash
./install.sh --no-engine     # puts the current extension where the nested shell loads it from
HEARD_NESTED_HEADLESS=1 tools/nested-shell.sh python3 tools/type_test.py
HEARD_NESTED_HEADLESS=1 tools/nested-shell.sh python3 tools/dictation_test.py SPEECH.wav "words you expect" [--send | --auto-stop]
```

`type_test.py` checks the extension types and pastes into a text window. `dictation_test.py` runs the real app with a temporary PipeWire microphone (`pw-loopback`), plays a recording into it, and checks the transcript arrives in a focused window. It needs the speech engine installed. It uses throwaway settings and history. GNOME's log goes to `/tmp/heard-nested-*.log`.

## Regenerating the documentation images

```bash
HEARD_NESTED_HEADLESS=1 tools/nested-shell.sh python3 tools/docs_screenshots.py [welcome settings history indicator]
```

It fills a temporary history with sample transcripts and photographs each window in a nested session, so the images never contain anyone's personal files. Update the script when the UI changes, rather than adding hand-made screenshots.

## Packaging and releases

- `packaging/build-deb.sh` builds `dist/heard_<version>_all.deb`: the app in `/usr/lib/heard`, `/usr/bin/heard`, the extension, icons, a systemd user unit and AppStream metadata. The speech engine isn't packaged; the welcome screen sets it up per user.
- `install.sh` is the per-user installer. Piped from curl it downloads the latest release tarball first. Updates replace only the app code; the engine and history stay.
- **Releasing:** bump `__version__` in `heard/__init__.py` and add a `<release>` to `data/io.github.jksnetwork.Heard.metainfo.xml`, then push a tag `v<version>`. The *Release* workflow checks the tag matches the version, builds the `.deb` and publishes a GitHub release with it attached.
- The *CI* workflow runs the tests, validates the desktop entry and AppStream data, and builds the package on every push and pull request.

## Code style

- Match the surrounding code: small modules, docstrings that explain *why*, comments only where something isn't obvious.
- Python is formatted for readability at about 110 columns. JavaScript follows GNOME Shell's style.
- Anything slow (transcription, subprocesses, D-Bus calls that wait on the user) runs asynchronously; the UI thread must never block.
