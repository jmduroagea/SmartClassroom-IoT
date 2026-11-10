import unittest
from server.brain.core.emergency_detector import EmergencyDetector

class TestEmergencyDetector(unittest.TestCase):
    def test_no_detection_before_window_fills(self):
        detector = EmergencyDetector()
        self.assertFalse(detector.process_temperature(0.0, 20.0))
        self.assertFalse(detector.process_temperature(15.0, 22.0))

    def test_emergency_triggered_after_consecutive_readings(self):
        detector = EmergencyDetector()
        # Llenar la ventana de 30s
        detector.process_temperature(0.0, 20.0)
        detector.process_temperature(15.0, 20.0)
        detector.process_temperature(30.0, 20.0)

        # Dos lecturas con subida brusca (>= 5 °C) consecutivas
        self.assertFalse(detector.process_temperature(32.0, 26.0))
        self.assertTrue(detector.process_temperature(34.0, 26.0))

    def test_reset_pauses_detection_for_sixty_seconds(self):
        detector = EmergencyDetector()
        # Llenar ventana y disparar emergencia en t=34
        detector.process_temperature(0.0, 20.0)
        detector.process_temperature(15.0, 20.0)
        detector.process_temperature(30.0, 20.0)
        detector.process_temperature(32.0, 26.0)
        self.assertTrue(detector.process_temperature(34.0, 26.0))

        # Reset en t=34 (activa pausa hasta t=94)
        detector.reset()

        # Intentar simular subida en t=50 (dentro de la pausa de 60s) -> No debe disparar
        detector.process_temperature(35.0, 20.0)
        detector.process_temperature(50.0, 20.0)
        self.assertFalse(detector.process_temperature(52.0, 30.0))

if __name__ == '__main__':
    unittest.main()
