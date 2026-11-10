import unittest
from server.brain.core.emergency_detector import EmergencyDetector

class TestEmergencyDetector(unittest.TestCase):
    def test_no_detection_before_window_fills(self):
        detector = EmergencyDetector()
        self.assertFalse(detector.process_temperature(0.0, 20.0))
        self.assertFalse(detector.process_temperature(5.0, 30.0))
        self.assertFalse(detector.process_temperature(10.0, 35.0))

    def test_emergency_triggered_after_consecutive_readings(self):
        detector = EmergencyDetector()
        detector.process_temperature(0.0, 20.0)
        detector.process_temperature(15.0, 20.0)
        detector.process_temperature(30.0, 20.0)

        self.assertFalse(detector.process_temperature(32.0, 26.0))
        self.assertTrue(detector.process_temperature(34.0, 26.0))

    def test_reset_clears_state(self):
        detector = EmergencyDetector()
        detector.process_temperature(0.0, 20.0)
        detector.process_temperature(30.0, 20.0)
        detector.reset()
        self.assertEqual(len(detector.readings), 0)

if __name__ == '__main__':
    unittest.main()
