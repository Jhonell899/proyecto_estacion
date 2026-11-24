import struct
import time

from Sensor import Sensor


class SensorAmbiental(Sensor):
    """PMS5003: material particulado PM1.0, PM2.5 y PM10 (ug/m3). UART a 9600 baudios.

    - El sensor envia solo una trama de 32 bytes cada ~1 s.
    - Los valores publicados son el promedio de las ultimas VENTANA tramas,
      para que la lectura no salte.
    - calentando() es True los primeros 30 s: el ventilador aun no estabiliza el flujo.
    - Si pasan CADUCIDAD_MS sin tramas validas (cable suelto), los valores vuelven a None.
    - dormir() apaga el ventilador y el laser para alargar su vida; despertar()
      los enciende. Se hace por el pin SET si se paso pin_set, o si no con un
      comando por el puerto serie (necesita el cable ESP32 TX -> RX del sensor).
    """

    LARGO_TRAMA = 32
    CABECERA = b"\x42\x4d"

    CALENTAMIENTO_MS = 30000
    CADUCIDAD_MS = 10000
    VENTANA = 5

    CMD_DORMIR = b"\x42\x4d\xe4\x00\x00\x01\x73"
    CMD_DESPERTAR = b"\x42\x4d\xe4\x00\x01\x01\x74"

    def __init__(self, uart, pin_set=None):
        super().__init__("PMS5003")
        self.uart = uart
        self.pin_set = pin_set

        self.pm1 = None
        self.pm25 = None
        self.pm10 = None
        self.tramas_ok = 0
        self.tramas_malas = 0
        self.dormido = False

        self._buffer = b""
        self._historial = []
        self._inicio_ms = time.ticks_ms()

        if pin_set is not None:
            pin_set.value(1)

    # ---------- Estado ----------
    def calentando(self):
        if self.dormido:
            return False
        return time.ticks_diff(time.ticks_ms(), self._inicio_ms) < self.CALENTAMIENTO_MS

    def dormir(self):
        """Apaga ventilador y laser."""
        if self.pin_set is not None:
            self.pin_set.value(0)
        else:
            self.uart.write(self.CMD_DORMIR)
        self.dormido = True
        self._borrar_datos()

    def despertar(self):
        """Enciende el sensor; vuelve a necesitar 30 s de calentamiento."""
        if self.pin_set is not None:
            self.pin_set.value(1)
        else:
            self.uart.write(self.CMD_DESPERTAR)
        self.dormido = False
        self._inicio_ms = time.ticks_ms()

    def _borrar_datos(self):
        self.pm1 = self.pm25 = self.pm10 = None
        self._historial = []
        self._ultima_ms = None
        self._buffer = b""

    # ---------- Lectura ----------
    def _trama_valida(self, trama):
        if (trama[2] << 8 | trama[3]) != 28:
            return False
        suma = sum(trama[0:30]) & 0xFFFF
        return suma == (trama[30] << 8 | trama[31])

    def _extraer_trama(self):
        """Devuelve la trama valida mas reciente del buffer, o None."""
        trama_ok = None
        while True:
            i = self._buffer.find(self.CABECERA)
            if i < 0:
                self._buffer = self._buffer[-1:]
                break
            if len(self._buffer) - i < self.LARGO_TRAMA:
                self._buffer = self._buffer[i:]
                break
            candidata = self._buffer[i:i + self.LARGO_TRAMA]
            if self._trama_valida(candidata):
                trama_ok = candidata
                self.tramas_ok += 1
                self._buffer = self._buffer[i + self.LARGO_TRAMA:]
            else:
                self.tramas_malas += 1
                self._buffer = self._buffer[i + 1:]
        return trama_ok

    def leer(self):
        """Procesa lo recibido por UART. Devuelve (pm1, pm25, pm10) si llego una trama nueva."""
        ahora = time.ticks_ms()

        if self.uart.any():
            nuevos = self.uart.read()
            if nuevos:
                self._buffer += nuevos

        # Evita que el buffer crezca sin limite si no llegan tramas validas.
        if len(self._buffer) > 4 * self.LARGO_TRAMA:
            self._buffer = self._buffer[-2 * self.LARGO_TRAMA:]

        trama = self._extraer_trama()

        if trama is None:
            if self._caducado(ahora):
                self._aviso("sin datos, revisa el cableado")
                self._borrar_datos()
            return None

        valores = struct.unpack(">13H", trama[4:30])
        # Indices 3, 4 y 5: concentraciones en condiciones atmosfericas.
        self._historial.append(valores[3:6])
        if len(self._historial) > self.VENTANA:
            self._historial.pop(0)

        cantidad = len(self._historial)
        self.pm1 = round(sum(v[0] for v in self._historial) / cantidad)
        self.pm25 = round(sum(v[1] for v in self._historial) / cantidad)
        self.pm10 = round(sum(v[2] for v in self._historial) / cantidad)
        self._ultima_ms = ahora
        return self.pm1, self.pm25, self.pm10
