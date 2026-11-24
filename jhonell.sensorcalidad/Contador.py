import time


class Contador:
    """Temporizador no bloqueante: listo() devuelve True cada `intervalo_ms`."""

    def __init__(self, intervalo_ms):
        self.intervalo_ms = intervalo_ms
        self._ultimo = time.ticks_ms()

    def listo(self):
        ahora = time.ticks_ms()
        if time.ticks_diff(ahora, self._ultimo) >= self.intervalo_ms:
            self._ultimo = ahora
            return True
        return False
