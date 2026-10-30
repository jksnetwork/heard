# SPDX-License-Identifier: GPL-3.0-or-later
"""Transcript history storage."""

import tempfile
import unittest
from pathlib import Path

from heard.transcripts import Transcripts, matches


class TranscriptsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Transcripts(Path(self.dir.name) / "history.jsonl")

    def tearDown(self):
        self.dir.cleanup()

    def test_newest_first_and_limit(self):
        for i in range(5):
            self.store.add(f"take {i}", limit=3, seconds=1.0)
        self.assertEqual([e["text"] for e in self.store.load()], ["take 4", "take 3", "take 2"])
        self.assertEqual(self.store.last()["text"], "take 4")

    def test_zero_limit_keeps_nothing(self):
        entry = self.store.add("secret", limit=0)
        self.assertEqual(entry["text"], "secret")
        self.assertEqual(self.store.load(), [])

    def test_remove_and_clear(self):
        a = self.store.add("a", limit=10)
        self.store.add("b", limit=10)
        self.store.remove(a["time"])
        self.assertEqual([e["text"] for e in self.store.load()], ["b"])
        self.store.clear()
        self.assertIsNone(self.store.last())

    def test_corrupt_lines_skipped(self):
        self.store.add("good", limit=10)
        with self.store.path.open("a") as f:
            f.write("not json\n{\"no\": \"text\"}\n")
        self.assertEqual([e["text"] for e in self.store.load()], ["good"])

    def test_unicode_kept(self):
        self.store.add("café — ok", limit=10)
        self.assertEqual(self.store.last()["text"], "café — ok")

    def test_matches(self):
        entry = {"text": "Refactor the Settings window"}
        self.assertTrue(matches(entry, "settings refactor"))
        self.assertFalse(matches(entry, "history"))
        self.assertTrue(matches(entry, ""))


if __name__ == "__main__":
    unittest.main()
