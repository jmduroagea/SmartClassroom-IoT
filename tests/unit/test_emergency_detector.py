import unittest
from server.brain.core.emergency_detector import EmergencyDetector

BASE = 20.0            # room temperature in the tests
READING_PERIOD = 2     # the Room Pi sends a reading every 2 s

class TestEmergencyDetector(unittest.TestCase):
    def test_no_detection_before_window_fills(self):
        detector = EmergencyDetector()
        self.assertFalse(detector.process_temperature(0.0, 20.0))
        self.assertFalse(detector.process_temperature(15.0, 22.0))

    def test_emergency_triggered_after_consecutive_readings(self):
        detector = EmergencyDetector()
        # Fill the 30 s window
        detector.process_temperature(0.0, 20.0)
        detector.process_temperature(15.0, 20.0)
        detector.process_temperature(30.0, 20.0)

        # Two readings in a row with a rise of 5 °C or more
        self.assertFalse(detector.process_temperature(32.0, 26.0))
        self.assertTrue(detector.process_temperature(34.0, 26.0))

    def test_reset_pauses_detection_for_sixty_seconds(self):
        detector = EmergencyDetector()
        # Fill the window and trigger an emergency at t=34
        detector.process_temperature(0.0, 20.0)
        detector.process_temperature(15.0, 20.0)
        detector.process_temperature(30.0, 20.0)
        detector.process_temperature(32.0, 26.0)
        self.assertTrue(detector.process_temperature(34.0, 26.0))

        # Reset at t=34: pause until t=94
        detector.reset()

        # Try to simulate a rise in t=50 (within the 60s pause) -> Should not trigger
        detector.process_temperature(35.0, 20.0)
        detector.process_temperature(50.0, 20.0)
        self.assertFalse(detector.process_temperature(52.0, 30.0))

    def test_slow_ramp_does_not_trigger(self):
        """T14: 1 °C every 10 s, read every 2 s, is only 3 °C per 30 s."""
        detector = EmergencyDetector()
        for second in range(0, 181, READING_PERIOD):
            temp = BASE + second / 10
            self.assertFalse(detector.process_temperature(float(second), temp), f"t={second}")

    def test_single_spike_does_not_trigger(self):
        """T15: one high reading alone is not enough, 2 in a row are needed."""
        detector = EmergencyDetector()
        for second in range(0, 31, READING_PERIOD):
            detector.process_temperature(float(second), BASE)
        self.assertFalse(detector.process_temperature(32.0, BASE + 10))
        for second in range(34, 61, READING_PERIOD):
            self.assertFalse(detector.process_temperature(float(second), BASE), f"t={second}")

    def test_a_rise_of_exactly_5_degrees_counts(self):
        detector = EmergencyDetector()
        for second in range(0, 31, READING_PERIOD):
            detector.process_temperature(float(second), BASE)
        self.assertFalse(detector.process_temperature(32.0, BASE + 5))
        self.assertTrue(detector.process_temperature(34.0, BASE + 5))

    def test_a_rise_just_under_5_degrees_does_not_count(self):
        detector = EmergencyDetector()
        for second in range(0, 31, READING_PERIOD):
            detector.process_temperature(float(second), BASE)
        self.assertFalse(detector.process_temperature(32.0, BASE + 4.9))
        self.assertFalse(detector.process_temperature(34.0, BASE + 4.9))

if __name__ == '__main__':
    unittest.main()
