"""The real speech recogniser: the USB microphone and Vosk, fully offline.

Vosk only listens for our phrases: the grammar is voice.ALL_PHRASES plus
"[unk]", which absorbs everything else. That makes recognition far more
reliable on a Pi 3.

Vosk gives a confidence for each word. A phrase is accepted only if no word
is very doubtful AND the phrase as a whole was heard clearly, so one word
heard a bit worse does not spoil the rest. Both thresholds are provisional
until Thursday's recordings (#70).
"""

from __future__ import annotations

import json
import logging
import os
import queue
from typing import Callable, Optional

from room.core import voice

# Audio format the small English model expects
SAMPLE_RATE_HZ = 16000
BLOCK_SIZE_FRAMES = 8000        # half a second of audio per block
AUDIO_CHANNELS = 1
SAMPLE_FORMAT = "int16"
UNKNOWN_WORD = "[unk]"

# Confidence rule (provisional, #70)
WORD_MIN_CONFIDENCE = 0.4       # no word may be below this
AVERAGE_MIN_CONFIDENCE = 0.7    # the average of the words must reach this

logger = logging.getLogger(__name__)


def grammar() -> str:
    """The phrases Vosk may recognise, as the JSON list it expects."""
    return json.dumps(list(voice.ALL_PHRASES) + [UNKNOWN_WORD])


def accepted_text(
    result_json: str,
    word_min: float = WORD_MIN_CONFIDENCE,
    average_min: float = AVERAGE_MIN_CONFIDENCE,
) -> Optional[str]:
    """The text of a Vosk result if it was heard clearly enough, else None."""
    result = json.loads(result_json)
    text = result.get("text", "")
    confidences = [word["conf"] for word in result.get("result", [])]
    if not text or not confidences:
        return None  # silence
    lowest = min(confidences)
    average = sum(confidences) / len(confidences)
    if lowest < word_min or average < average_min:
        # Logged so Thursday's tests show what real confidences look like
        logger.info("phrase %r rejected: lowest %.2f, average %.2f", text, lowest, average)
        return None
    return text


class VoskMicrophone:
    def __init__(self, model_path: str) -> None:
        # Checked at start, so a wrong VOSK_MODEL_PATH fails at once with a clear message
        if not os.path.isdir(model_path):
            raise FileNotFoundError(f"Vosk model not found at {model_path!r}: check VOSK_MODEL_PATH")
        self._model_path = model_path

    def listen(self, on_phrase: Callable[[str], None]) -> None:
        import sounddevice  # only installed on the Room Pi
        import vosk

        model = vosk.Model(self._model_path)
        recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE_HZ, grammar())
        recognizer.SetWords(True)  # a confidence for each word
        blocks: queue.Queue = queue.Queue()

        def on_audio(data, _frames, _time, status) -> None:
            # Runs in the audio thread: only hand the block over, never block here
            if status:
                logger.warning("microphone: %s", status)
            blocks.put(bytes(data))

        with sounddevice.RawInputStream(
            samplerate=SAMPLE_RATE_HZ,
            blocksize=BLOCK_SIZE_FRAMES,
            dtype=SAMPLE_FORMAT,
            channels=AUDIO_CHANNELS,
            callback=on_audio,
        ):
            logger.info("listening")
            while True:
                if recognizer.AcceptWaveform(blocks.get()):
                    text = accepted_text(recognizer.Result())
                    if text:
                        on_phrase(text)
