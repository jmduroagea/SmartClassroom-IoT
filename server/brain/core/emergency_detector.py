"""Emergency detector: decides from the temperature readings whether there is a fire.

Rule: a JUMP is a reading JUMP_THRESHOLD_DEGREES or more above the reading just
before it (the Room Pi reads every 2 s, so it is a jump within one reading
period). The reading before the jump is kept as the base. The emergency is
confirmed when CONFIRMING_READINGS readings in a row, the jump included, stay at
least JUMP_THRESHOLD_DEGREES above that base: the next reading only has to stay
high, it does not have to jump again. A reading that falls back below that level
cancels the jump, so a single spike of the probe is not a fire.

A slow climb, even a large one, is never a jump: the web shows it as an early
warning instead. After a reset, detection pauses for PAUSE_AFTER_RESET_SECONDS,
so the still-hot probe does not trigger another emergency at once.

The readings of the last HISTORY_SECONDS are kept, because the emergency record
starts with them (service.py). They play no part in the rule.

Pure logic: timestamps are seconds given by the caller, so tests need no clock.
"""

from typing import List, Optional, Tuple

JUMP_THRESHOLD_DEGREES = 4.0
CONFIRMING_READINGS = 2
PAUSE_AFTER_RESET_SECONDS = 60.0
HISTORY_SECONDS = 30.0


class EmergencyDetector:
    def __init__(
        self,
        threshold_deg: float = JUMP_THRESHOLD_DEGREES,
        confirming_readings: int = CONFIRMING_READINGS,
        pause_seconds: float = PAUSE_AFTER_RESET_SECONDS,
        history_seconds: float = HISTORY_SECONDS,
    ):
        self.threshold_deg = threshold_deg
        self.confirming_readings = confirming_readings
        self.pause_seconds = pause_seconds
        self.history_seconds = history_seconds
        self.readings: List[Tuple[float, float]] = []
        self.paused_until: float = 0.0
        self._previous: Optional[float] = None   # the last reading before this one
        self._base: Optional[float] = None       # the reading before the jump, if there was one
        self._high_readings = 0                  # readings in a row above base + threshold

    def process_temperature(self, timestamp: float, temp: float) -> bool:
        """Add a reading. True when this reading confirms an emergency."""
        previous, self._previous = self._previous, temp
        self._remember(timestamp, temp)

        # During the pause after a reset the readings are kept, but nothing is decided.
        if timestamp < self.paused_until:
            return False

        if self._base is not None:
            if temp - self._base >= self.threshold_deg:
                self._high_readings += 1
            else:
                self._cancel_jump()

        if self._base is None and previous is not None and temp - previous >= self.threshold_deg:
            self._base = previous
            self._high_readings = 1

        return self._high_readings >= self.confirming_readings

    def reset(self) -> None:
        """Start again after an emergency: no history, no jump, and a pause from the last reading."""
        if self.readings:
            self.paused_until = self.readings[-1][0] + self.pause_seconds
        else:
            self.paused_until = 0.0
        self.readings.clear()
        self._previous = None
        self._cancel_jump()

    def _cancel_jump(self) -> None:
        self._base = None
        self._high_readings = 0

    def _remember(self, timestamp: float, temp: float) -> None:
        """Add the reading and forget the ones older than the history."""
        self.readings.append((timestamp, temp))
        cutoff = timestamp - self.history_seconds
        self.readings = [r for r in self.readings if r[0] >= cutoff]
