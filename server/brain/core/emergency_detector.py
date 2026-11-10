from typing import List, Tuple

class EmergencyDetector:
    def __init__(self, window_seconds: float = 30.0, threshold_deg: float = 5.0, pause_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self.threshold_deg = threshold_deg
        self.pause_seconds = pause_seconds
        self.readings: List[Tuple[float, float]] = []
        self.consecutive_alerts = 0
        self.has_filled_window = False
        self.paused_until: float = 0.0

    def process_temperature(self, timestamp: float, temp: float) -> bool:
        # Si estamos dentro del periodo de pausa de 60s tras un reset, no se detecta emergencia
        if timestamp < self.paused_until:
            self.readings.append((timestamp, temp))
            cutoff = timestamp - self.window_seconds
            self.readings = [r for r in self.readings if r[0] >= cutoff]
            return False

        self.readings.append((timestamp, temp))
        
        cutoff = timestamp - self.window_seconds
        self.readings = [r for r in self.readings if r[0] >= cutoff]

        if not self.has_filled_window:
            if self.readings and (timestamp - self.readings[0][0]) >= self.window_seconds:
                self.has_filled_window = True
            else:
                self.consecutive_alerts = 0
                return False

        min_temp = min(r[1] for r in self.readings)
        rise = temp - min_temp

        if rise >= self.threshold_deg:
            self.consecutive_alerts += 1
        else:
            self.consecutive_alerts = 0

        return self.consecutive_alerts >= 2

    def reset(self) -> None:
        # Pausa la detección durante 60 segundos a partir de la última lectura registrada
        if self.readings:
            last_ts = self.readings[-1][0]
            self.paused_until = last_ts + self.pause_seconds
        else:
            self.paused_until = 0.0
        self.readings.clear()
        self.consecutive_alerts = 0
        self.has_filled_window = False
