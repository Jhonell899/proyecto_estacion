import time

import dht
from machine import Pin

from Sensor import Sensor


class SensorDHT11(Sensor):
    """DHT11: temperatura (C) y humedad relativa (%) por un solo cable de datos.

    - Precision baja (+-2 C, +-5 %) y valores enteros; el SCD40 es mas preciso,
      por eso la pantalla usa el DHT11 solo cuando el SCD40 no tiene dato.
    - Admite como maximo una lectura cada ~2 s; leer() se encarga de respetarlo.
    """

    CADUCIDAD_MS = 10000
    INTERVALO_MS = 2500

    def __init__(self, pin=15):
        super().__init__("DHT11")
        self._sensor = dht.DHT11(Pin(pin))
        self.temperatura = None
        self.humedad = None
        self._intento_ms = time.ticks_ms()

    def _borrar_datos(self):
        self._ultima_ms = None
        self.temperatura = self.humedad = None

    def leer(self):
        """Devuelve (temperatura, humedad) si hizo una lectura nueva; si no, None."""
        ahora = time.ticks_ms()
        if self._caducado(ahora):
            self._borrar_datos()

        if time.ticks_diff(ahora, self._intento_ms) < self.INTERVALO_MS:
            return None
        self._intento_ms = ahora

        try:
            self._sensor.measure()
        except OSError as error:
            self._aviso("fallo de lectura ({})".format(error))
            return None

        self.temperatura = self._sensor.temperature()
        self.humedad = self._sensor.humidity()
        self._ultima_ms = ahora
        return self.temperatura, self.humedad
