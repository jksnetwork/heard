# Security policy

Heard listens to your microphone and types into other apps, so security reports are taken seriously.

## Reporting a vulnerability

**Please don't open a public issue.** Report it privately instead:

1. Go to the repository's **Security** tab → **Report a vulnerability** ([direct link](https://github.com/jksnetwork/heard/security/advisories/new)).
2. Describe the problem, how to reproduce it, and what an attacker could do with it.

Only the maintainers can see these reports. You'll get a reply within a week. Once a fix is released, the advisory is published, with credit to you if you'd like.

## Supported versions

Fixes go into the latest release. Please check that the problem still happens with it before reporting.

## What's in scope

- Anything that lets another program or user hear recordings, read transcripts, or see the history they shouldn't. Recordings are written to `$XDG_RUNTIME_DIR/heard/` (mode 0700) and deleted as soon as they're transcribed; history is text only, in `~/.local/share/heard/history.jsonl`.
- Anything that sends audio or text off the computer. Heard is meant to work fully offline once the speech model is downloaded.
- The GNOME Shell extension's D-Bus interface (`io.github.jksnetwork.Heard.Shell`). It runs with the shell's privileges, and its `TypeText` method types into the focused window. That's by design for programs running as you on the session bus; a way for something *outside* that boundary (another user, a sandboxed app without session-bus access) to reach it would be in scope.
- The installer, the speech-engine setup and the packages (for example, writing files or running code somewhere unexpected).

Out of scope: problems that need an attacker who already controls your user account, and bugs in GNOME, faster-whisper, CTranslate2, or other projects Heard uses (please report those upstream).
