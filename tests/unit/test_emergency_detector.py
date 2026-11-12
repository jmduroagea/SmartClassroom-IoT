"""Unit tests of the emergency detector (server/brain/core/emergency_detector.py):
a jump between two readings, confirmed by the next one."""

import unittest

from server.brain.core.emergency_detector import (
    HISTORY_SECONDS,
    JUMP_THRESHOLD_DEGREES,
    PAUSE_AFTER_RESET_SECONDS,
    EmergencyDetector,
)

BASE = 20.0            # room temperature in the tests
READING_PERIOD = 2     # the Room Pi sends a reading every 2 s
JUMP = JUMP_THRESHOLD_DEGREES


class TestEmergencyDetector(unittest.TestCase):
    def setUp(self):
        self.detector = EmergencyDetector()
        self.now = 0.0

    def read(self, temp):
        """One reading, READING_PERIOD after the previous one."""
        result = self.detector.process_temperature(self.now, temp)
        self.now += READING_PERIOD
        return result

    # --- The rule ------------------------------------------------------------

    def test_a_jump_confirmed_by_the_next_reading_is_an_emergency(self):
        self.read(BASE)
        self.assertFalse(self.read(BASE + JUMP))   # the jump alone is not enough
        self.assertTrue(self.read(BASE + JUMP))    # it stays high: confirmed

    def test_the_confirming_reading_does_not_need_to_jump_again(self):
        """It is compared with the reading before the jump, not with the jump."""
        self.read(BASE)
        self.read(BASE + 6)
        self.assertTrue(self.read(BASE + 6.5))

    def test_a_reading_that_keeps_rising_also_confirms(self):
        self.read(BASE)
        self.read(BASE + 6)
        self.assertTrue(self.read(BASE + 12))

    def test_a_jump_just_under_the_threshold_does_not_count(self):
        self.read(BASE)
        self.assertFalse(self.read(BASE + JUMP - 0.1))
        self.assertFalse(self.read(BASE + JUMP - 0.1))

    def test_no_emergency_from_the_very_first_reading(self):
        """There is nothing before it to jump from."""
        self.assertFalse(self.read(BASE + 50))
        self.assertFalse(self.read(BASE + 50))

    def test_a_jump_right_after_start_up_is_detected(self):
        """No warm-up is needed: two readings before the jump are enough."""
        self.read(BASE)
        self.read(BASE + JUMP)
        self.assertTrue(self.read(BASE + JUMP))

    # --- What is not a fire --------------------------------------------------

    def test_single_spike_does_not_trigger(self):
        """T15: one high reading that falls back is not a fire."""
        self.read(BASE)
        self.assertFalse(self.read(BASE + 10))
        for _ in range(10):
            self.assertFalse(self.read(BASE))

    def test_falling_back_below_the_threshold_cancels_the_jump(self):
        self.read(BASE)
        self.read(BASE + 6)
        self.assertFalse(self.read(BASE + JUMP - 1))   # cancelled
        self.assertFalse(self.read(BASE + 6))          # only 1 °C above the previous one

    def test_slow_ramp_does_not_trigger(self):
        """T14: 1 °C every 10 s never jumps between two readings."""
        for _ in range(90):
            self.assertFalse(self.read(BASE + self.now / 10))

    def test_two_smaller_steps_do_not_trigger(self):
        """The rule needs one jump: +3 and +3 is a fast climb (the web warns), not a jump."""
        self.read(BASE)
        self.assertFalse(self.read(BASE + 3))
        self.assertFalse(self.read(BASE + 6))
        self.assertFalse(self.read(BASE + 6))

    # --- After an emergency --------------------------------------------------

    def test_reset_pauses_detection(self):
        self.read(BASE)
        self.read(BASE + 6)
        self.assertTrue(self.read(BASE + 6))
        self.detector.reset()
        pause_ends = self.now - READING_PERIOD + PAUSE_AFTER_RESET_SECONDS
        while self.now < pause_ends - READING_PERIOD:
            self.read(BASE)
        self.assertFalse(self.read(BASE + 10))   # a jump inside the pause
        self.assertFalse(self.read(BASE + 10))

    def test_after_the_pause_a_new_jump_is_detected(self):
        self.read(BASE)
        self.read(BASE + 6)
        self.read(BASE + 6)
        self.detector.reset()
        pause_ends = self.now - READING_PERIOD + PAUSE_AFTER_RESET_SECONDS
        while self.now < pause_ends:
            self.read(BASE)
        self.read(BASE)
        self.read(BASE + 6)
        self.assertTrue(self.read(BASE + 6))

    def test_reset_forgets_the_history(self):
        self.read(BASE)
        self.detector.reset()
        self.assertEqual(self.detector.readings, [])

    # --- History for the emergency record ------------------------------------

    def test_only_the_last_readings_are_kept_for_the_record(self):
        for _ in range(40):
            self.read(BASE)
        oldest = self.detector.readings[0][0]
        newest = self.detector.readings[-1][0]
        self.assertLessEqual(newest - oldest, HISTORY_SECONDS)


if __name__ == "__main__":
    unittest.main()
