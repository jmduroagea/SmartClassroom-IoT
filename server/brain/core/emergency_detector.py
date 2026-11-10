from typing import List, Tuple

class EmergencyDetector:
    def __init__(self, window_seconds: float = 30.0, threshold_deg: float = 5.0):
        self.window_seconds = window_seconds
        self.threshold_deg = threshold_deg
        self.readings: List[Tuple[float, float]] = []
        self.consecutive_alerts = 0
        self.has_filled_window = False

    def process_temperature(self, timestamp: float, temp: float) -> bool:
        self.readings.append((timestamp, temp))
        
        # Eliminar lecturas más antiguas que los 30 segundos
        cutoff = timestamp - self.window_seconds
        self.readings = [r for r in self.readings if r[0] >= cutoff]

        # Marcar la ventana como llena una vez transcurridos 30s desde la primera lectura
        if not self.has_filled_window:
            if (timestamp - self.readings[0][0]) >= self.window_seconds:
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
        self.readings.clear()
        self.consecutive_alerts = 0
        self.has_filled_window = False
