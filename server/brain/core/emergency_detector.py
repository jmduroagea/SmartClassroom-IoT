"""Emergency detector: decides from the temperature readings whether there is a fire.

Rule (specification v4): the rise is the current reading minus the lowest reading
of the last WINDOW_SECONDS. If it is RISE_THRESHOLD_DEGREES or more in
CONSECUTIVE_READINGS readings in a row, there is an emergency. Nothing is decided
until the buffer holds a full window (at start-up or after a reset), and after a
reset detection pauses for PAUSE_AFTER_RESET_SECONDS, so the still-hot probe does
not trigger another emergency at once.

Pure logic: timestamps are seconds given by the caller, so tests need no clock.
"""

from typing import List, Tuple

WINDOW_SECONDS = 30.0
RISE_THRESHOLD_DEGREES = 5.0
CONSECUTIVE_READINGS = 2
PAUSE_AFTER_RESET_SECONDS = 60.0


class EmergencyDetector:
    def __init__(
        self,
        window_seconds: float = WINDOW_SECONDS,
        threshold_deg: float = RISE_THRESHOLD_DEGREES,
        pause_seconds: float = PAUSE_AFTER_RESET_SECONDS,
        consecutive_needed: int = CONSECUTIVE_READINGS,
    ):
        self.window_seconds = window_seconds
        self.threshold_deg = threshold_deg
        self.pause_seconds = pause_seconds
        self.consecutive_needed = consecutive_needed
        self.readings: List[Tuple[float, float]] = []
        self.consecutive_alerts = 0
        self.has_filled_window = False
        self.paused_until: float = 0.0

    def process_temperature(self, timestamp: float, temp: float) -> bool:
        """Add a reading. True when this reading confirms an emergency."""
        self._remember(timestamp, temp)

        # During the pause after a reset the readings are kept, but nothing is decided.
        if timestamp < self.paused_until:
            return False

        if not self.has_filled_window:
            if timestamp - self.readings[0][0] >= self.window_seconds:
                self.has_filled_window = True
            else:
                self.consecutive_alerts = 0
                return False

        rise = temp - min(reading for _, reading in self.readings)
        if rise >= self.threshold_deg:
            self.consecutive_alerts += 1
        else:
            self.consecutive_alerts = 0
        return self.consecutive_alerts >= self.consecutive_needed

    def reset(self) -> None:
        """Start again after an emergency: empty buffer and a pause from the last reading."""
        if self.readings:
            self.paused_until = self.readings[-1][0] + self.pause_seconds
        else:
            self.paused_until = 0.0
        self.readings.clear()
        self.consecutive_alerts = 0
        self.has_filled_window = False

    def _remember(self, timestamp: float, temp: float) -> None:
        """Add the reading and forget the ones older than the window."""
        self.readings.append((timestamp, temp))
        cutoff = timestamp - self.window_seconds
        self.readings = [r for r in self.readings if r[0] >= cutoff]
