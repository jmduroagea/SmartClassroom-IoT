"""Voice: from the phrase the recogniser heard to a command of the contract.

Every command starts with the wake word ("Ok Computer, I'm hot"). Without it the
phrase is ignored (test T27), so the speaker's own sentences, which never contain
"computer", cannot trigger anything.

Pure functions with no bus and no state, so they are tested on their own.
"""

from __future__ import annotations

from typing import Optional

# The recogniser may write "ok" or "okay": both are accepted until Thursday's test.
WAKE_WORDS = ("ok computer", "okay computer")

# What the person says after the wake word -> command of the contract
PHRASES = {
    "i'm hot": "hot",
    "i'm cold": "cold",
    "what's the temperature": "temp",
    "help": "help",
}

# Every full phrase the recogniser must know. The Vosk grammar is built from it.
ALL_PHRASES = tuple(f"{wake} {phrase}" for wake in WAKE_WORDS for phrase in PHRASES)


def normalize(text: str) -> str:
    """Lower case, one space between words, no spaces at the ends."""
    return " ".join(text.lower().split())


def command_for(text: str) -> Optional[str]:
    """The command in a phrase, or None without a wake word or a known phrase."""
    text = normalize(text)
    for wake in WAKE_WORDS:
        prefix = wake + " "
        if text.startswith(prefix):
            return PHRASES.get(text[len(prefix):])
    return None
