# SPDX-License-Identifier: GPL-3.0-or-later
"""Turning what Whisper hears into what gets typed. Pure functions, no GTK."""

import re

# Whisper copies the style of its prompt: a short punctuated one gets
# punctuated, capitalised output. Longer prompts make it skip the start of speech.
BASE_PROMPT = "Hello, welcome."

PLAIN = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": " - ", "−": "-",
    "…": "...", " ": " ", " ": " ", " ": " ",
})

# what Whisper writes for silence, noise or music when the VAD lets something through
HALLUCINATIONS = {
    "you", "thank you", "thank you.", "thanks for watching!", "thanks for watching.",
    "thank you for watching.", "thank you for watching!", "bye.", "bye!", ".", "...",
    "[blank_audio]", "[music]", "(music)", "[silence]", "subtitles by the amara.org community",
}


def build_prompt(vocabulary):
    """The initial prompt for Whisper: the style hint plus the user's vocabulary."""
    words = [w.strip() for w in re.split(r"[,\n;]+", vocabulary or "") if w.strip()]
    if not words:
        return BASE_PROMPT
    return f"{BASE_PROMPT} {', '.join(words)}."


def clean(text, plain_punctuation=True):
    """Tidy a transcript: one line, single spaces, optional ASCII punctuation.
    Returns "" for nothing or Whisper's stock hallucinations."""
    if plain_punctuation:
        text = text.translate(PLAIN)
    text = " ".join(text.split())
    if text.lower() in HALLUCINATIONS:
        return ""
    return text


def finish(text, trailing_space=True):
    """What actually gets typed or pasted."""
    return text + " " if text and trailing_space else text


def typeable(text):
    """True if every character is printable ASCII, which a virtual keyboard can
    always type. Anything else (accents, symbols) goes through the clipboard."""
    return all(" " <= ch <= "~" for ch in text)


def preview(text, limit=60):
    flat = " ".join(text.split())
    more = "…" if len(flat) > limit else ""
    return f"“{flat[:limit]}{more}”"
