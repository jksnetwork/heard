# Heard user guide

## Dictating

1. Put the cursor where the text should go: a terminal, a chat box, a prompt.
2. Press <kbd>Shift</kbd>+<kbd>Super</kbd>+<kbd>H</kbd>. You hear a short rising tone, and a pill appears at the top of the screen with a timer and a level meter.
3. Speak naturally, with punctuation in your voice; Whisper adds commas and full stops itself.
4. Press the shortcut again (or click ■ on the pill). A falling tone plays, the pill turns amber while it transcribes, and the text is typed at the cursor.

Click ✕ on the pill to throw a dictation away. If you said nothing (or the microphone is muted), nothing is typed and a notification tells you.

Pressing the shortcut while a dictation is being transcribed does nothing, so a double press can't start a stray recording.

## Getting the text right

- **Vocabulary** (Settings → Speech recognition): names and jargon separated by commas, e.g. `Claude, Kubernetes, PipeWire, screend`. Whisper will prefer these spellings.
- **Language:** set it to the language you speak. "Detect automatically" works, but it guesses wrong on very short dictations.
- **Plain punctuation** (on by default) turns curly quotes, em dashes and ellipses into `'`, `"`, ` - ` and `...`. It keeps the text typeable everywhere and avoids surprises in terminals.

## Models

| Model | Size | Notes |
|---|---|---|
| Large v3 Turbo (default) | 1.6 GB | Near the best accuracy at a fraction of the cost. ~0.5 s per dictation on a laptop RTX 4060. |
| Distil Large v3 | 1.5 GB | English only, a little faster. |
| Large v3 | 3 GB | The most accurate; about 3x slower. |
| Medium | 1.5 GB | |
| Small / Small English | 480 MB | Good choice without a GPU. |
| Base English, Tiny English | 150 / 75 MB | Fastest on slow CPUs; noticeably less accurate. |

Models download on first use into `~/.cache/heard/models`. "Run on" chooses the GPU or CPU; Automatic uses the GPU when the engine can load there and falls back to the CPU otherwise.

The model is loaded when Heard starts (so the first dictation is instant) and freed after 30 idle minutes to give the GPU memory back. Both are adjustable.

## Output

"Put the text" decides how the transcript reaches the app:

- **Type it** (default): typed as keystrokes. When the text has characters a keyboard can't type (accented letters with plain punctuation off, other scripts), it's pasted instead.
- **Always type / Always paste.** Paste uses <kbd>Ctrl</kbd>+<kbd>V</kbd>, or <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd> in terminals.
- **Only copy to the clipboard.**

Other output options:

- **Press Enter after typing** sends chat prompts right away.
- **Add a space after** keeps consecutive dictations from running together.
- **Also copy to the clipboard** keeps the last transcript there as well.

> **VS Code's terminal:** typing works. Pasting there needs <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>V</kbd>, which Heard can't tell apart from VS Code's editor (where that key opens a Markdown preview). With the default settings English is always typed, so this only matters for "Always paste" or non-ASCII text.

## Recording

- **Microphone:** "System default" follows your sound settings. Pick a specific one to pin it.
- **Stop after seconds of silence:** once you've started speaking, a pause this long stops the dictation as if you'd pressed the shortcut. 0 turns it off.
- **Longest dictation:** a safety limit (5 minutes by default).

## History

`heard history`, or History in the tray menu. Click a transcript to copy it, search with <kbd>Ctrl</kbd>+<kbd>F</kbd>, remove single entries or clear them all. Only text, timing and the model used are stored, in `~/.local/share/heard/history.jsonl`. Set "Transcripts to keep" to 0 to keep nothing.

## Command line

```
heard toggle     start, or stop and type (the default action)
heard start      start if idle
heard stop       stop and type if recording
heard cancel     discard the current dictation
heard again      type the last transcript again
heard history | settings | welcome | quit
```

All of these talk to the running instance (and start it if needed), so they're what you bind keys to on other desktops.

## Other desktops

- **KDE Plasma:** install `ydotool` and enable its daemon (`systemctl --user enable --now ydotool` on most distros; your user needs access to `/dev/uinput`). The shortcut comes from Heard's menu entry; change it in System Settings → Keyboard → Shortcuts. Install `gtk4-layer-shell` for the listening pill.
- **Hyprland / Sway:** install `wtype` and `gtk4-layer-shell`, then bind a key:
  - Hyprland: `bind = SUPER SHIFT, H, exec, heard toggle`
  - Sway: `bindsym $mod+Shift+h exec heard toggle`
- Without a typing tool, transcripts go to the clipboard (install `wl-clipboard` so that works without focus).

## Troubleshooting

**GNOME asks to "allow remote interaction".** The extension isn't running yet (it loads at your next login), so Heard types through the desktop's remote-input portal instead. Allow it once; the choice is remembered. Once you've logged out and in, the extension takes over and the portal isn't used. Text typed through the portal isn't also copied to the clipboard, and characters your keyboard layout can't produce are skipped.

**Nothing is typed, the text lands on the clipboard.** Neither the extension nor the portal could type (you declined the portal's dialog, for instance). Log out and back in once after installing; Settings → Shortcuts & Engine shows the extension's status.

**"Didn't hear anything."** The microphone is muted, too quiet, or the wrong one. Pick it explicitly in Settings → Recording, and check the level meter on the pill moves when you speak.

**The first dictation is slow.** The model is downloading (the pill says so) or loading. Turn on "Load the model when Heard starts" and start at login.

**It runs on the CPU although I have an NVIDIA GPU.** Check the tray menu → About Heard → Troubleshooting for the device. Reinstall the engine from Settings → Shortcuts & Engine (it adds the CUDA libraries when `nvidia-smi` works), and make sure the NVIDIA driver is loaded.

**Debugging:** run `HEARD_DEBUG=1 heard daemon` from a terminal (after `heard quit`) to see per-dictation timings and errors. `HEARD_NO_SHELL=1` makes Heard ignore the GNOME extension, to try the other desktops' paths.

## Uninstalling

`~/.local/share/heard/install.sh --uninstall`, or `sudo apt remove heard` for the package. Settings and history stay. The downloaded models are in `~/.cache/heard`; delete that folder to free the space.
