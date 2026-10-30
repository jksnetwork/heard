# SPDX-License-Identifier: GPL-3.0-or-later
"""Transcript history: one JSON object per line in ~/.local/share/heard/history.jsonl.
Only text is kept, never audio. No GTK here."""

import json
import time
from pathlib import Path

from .paths import HISTORY_FILE


class Transcripts:
    def __init__(self, path=HISTORY_FILE):
        self.path = Path(path)

    def load(self):
        """Entries, newest first."""
        try:
            lines = self.path.read_text().splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("text"):
                out.append(entry)
        out.reverse()
        return out

    def add(self, text, limit, **details):
        """Record a transcript (details: seconds, elapsed, model, device, method). Returns the entry."""
        entry = {"time": round(time.time(), 3), "text": text, **details}
        if limit <= 0:
            return entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        entries = self.load()
        if len(entries) > limit:
            self._write(entries[:limit])
        return entry

    def last(self):
        entries = self.load()
        return entries[0] if entries else None

    def remove(self, stamp):
        self._write([e for e in self.load() if e.get("time") != stamp])

    def clear(self):
        try:
            self.path.unlink()
        except OSError:
            pass

    def _write(self, newest_first):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in reversed(newest_first)))
        tmp.replace(self.path)


def matches(entry, query):
    return all(word in entry.get("text", "").lower() for word in query.lower().split())
