# SPDX-License-Identifier: GPL-3.0-or-later
"""Transcript clean-up and the Whisper prompt."""

import unittest

from heard import text


class PromptTest(unittest.TestCase):
    def test_no_vocabulary(self):
        self.assertEqual(text.build_prompt(""), text.BASE_PROMPT)
        self.assertEqual(text.build_prompt(None), text.BASE_PROMPT)

    def test_vocabulary_list(self):
        self.assertEqual(text.build_prompt("Claude,  PipeWire;GNOME\n"), "Hello, welcome. Claude, PipeWire, GNOME.")


class CleanTest(unittest.TestCase):
    def test_whitespace_and_punctuation(self):
        self.assertEqual(text.clean("  It’s  “fine”—really…\n"), "It's \"fine\" - really...")

    def test_keeps_typography_when_asked(self):
        self.assertEqual(text.clean("It’s", plain_punctuation=False), "It’s")

    def test_hallucinations_dropped(self):
        for noise in ("Thank you.", " you ", "[BLANK_AUDIO]", "..."):
            self.assertEqual(text.clean(noise), "", noise)

    def test_real_sentence_kept(self):
        self.assertEqual(text.clean("Thank you for the review."), "Thank you for the review.")


class FinishTest(unittest.TestCase):
    def test_trailing_space(self):
        self.assertEqual(text.finish("Hi."), "Hi. ")
        self.assertEqual(text.finish("Hi.", trailing_space=False), "Hi.")
        self.assertEqual(text.finish(""), "")

    def test_typeable(self):
        self.assertTrue(text.typeable("Fix the bug in app.py, then run `make test` ~ok?"))
        self.assertFalse(text.typeable("café"))
        self.assertFalse(text.typeable("line\nbreak"))

    def test_preview(self):
        self.assertEqual(text.preview("short"), "“short”")
        self.assertTrue(text.preview("x" * 100, limit=10).endswith("…”"))


if __name__ == "__main__":
    unittest.main()
