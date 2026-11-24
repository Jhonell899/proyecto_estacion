import time

from Sensor import Sensor


class SensorGas(Sensor):
    """SCD40: CO2 (ppm), temperatura (C) y humedad relativa (%). Bus I2C, direccion 0x62.

    - Mide de forma periodica cada ~5 s; leer() devuelve None mientras no haya dato nuevo.
    - Si el sensor no responde, no detiene el programa: reintenta conectarse solo.
    - Si pasan CADUCIDAD_MS sin datos nuevos, los valores vuelven a None para no
      mostrar lecturas viejas como si fueran actuales.
    """

    DIRECCION = 0x62

    CMD_INICIAR = 0x21B1
    CMD_DETENER = 0x3F86
    CMD_DATO_LISTO = 0xE4B8
    CMD_LEER = 0xEC05
    CMD_ALTITUD = 0x2427
    CMD_OFFSET_TEMP = 0x241D

    CADUCIDAD_MS = 30000
    REINTENTO_MS = 5000
    MAX_FALLOS = 5

    def __init__(self, i2c, direccion=DIRECCION, altitud_m=None, offset_temp_c=None):
        """altitud_m: altitud del lugar (mejora la precision del CO2 en zonas altas).
        offset_temp_c: grados que el sensor se calienta por estar en una caja (fabrica: 4)."""
        super().__init__("SCD40")
        self.i2c = i2c
        self.direccion = direccion
        self.altitud_m = altitud_m
        self.offset_temp_c = offset_temp_c

        self.co2 = None
        self.temperatura = None
        self.humedad = None
        self.conectado = False

        self._fallos = 0
        self._reintento_ms = time.ticks_ms()
        self._iniciar()

    # ---------- Comunicacion I2C ----------
    def _comando(self, cmd):
        self.i2c.writeto(self.direccion, bytes([cmd >> 8, cmd & 0xFF]))

    def _escribir(self, cmd, palabra):
        dato = bytes([palabra >> 8, palabra & 0xFF])
        self.i2c.writeto(
            self.direccion, bytes([cmd >> 8, cmd & 0xFF]) + dato + bytes([self._crc(dato)])
        )
        time.sleep_ms(1)

    def _leer_palabras(self, cmd, cantidad):
        self._comando(cmd)
        time.sleep_ms(1)
        datos = self.i2c.readfrom(self.direccion, cantidad * 3)
        palabras = []
        for i in range(0, len(datos), 3):
            if self._crc(datos[i:i + 2]) != datos[i + 2]:
                raise ValueError("CRC invalido")
            palabras.append((datos[i] << 8) | datos[i + 1])
        return palabras

    @staticmethod
    def _crc(datos):
        crc = 0xFF
        for byte in datos:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ 0x31) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc

    # ---------- Arranque y reconexion ----------
    def _iniciar(self):
        """Configura el sensor y arranca la medicion. Devuelve True si lo logro."""
        try:
            if self.direccion not in self.i2c.scan():
                raise OSError("no responde en 0x{:02X}".format(self.direccion))

            # La configuracion solo se acepta con la medicion detenida.
            self._comando(self.CMD_DETENER)
            time.sleep_ms(500)
            if self.altitud_m is not None:
                self._escribir(self.CMD_ALTITUD, int(self.altitud_m))
            if self.offset_temp_c is not None:
                self._escribir(self.CMD_OFFSET_TEMP, int(self.offset_temp_c * 65535 / 175))
            self._comando(self.CMD_INICIAR)
        except OSError as error:
            self._aviso(error)
            self._desconectar()
            return False

        self.conectado = True
        self._fallos = 0
        return True

    def _desconectar(self):
        self.conectado = False
        self._borrar_datos()

    def _borrar_datos(self):
        self._ultima_ms = None
        self.co2 = self.temperatura = self.humedad = None

    # ---------- Lectura ----------
    def leer(self):
        """Devuelve (co2, temperatura, humedad) si hay dato nuevo; si no, None."""
        ahora = time.ticks_ms()

        if not self.conectado:
            if time.ticks_diff(ahora, self._reintento_ms) < self.REINTENTO_MS:
                return None
            self._reintento_ms = ahora
            if not self._iniciar():
                return None

        if self._caducado(ahora):
            self._borrar_datos()

        try:
            if (self._leer_palabras(self.CMD_DATO_LISTO, 1)[0] & 0x07FF) == 0:
                self._fallos = 0
                return None
            co2, temp_raw, hum_raw = self._leer_palabras(self.CMD_LEER, 3)
        except (OSError, ValueError) as error:
            self._fallos += 1
            self._aviso("fallo de lectura {}/{} ({})".format(self._fallos, self.MAX_FALLOS, error))
            if self._fallos >= self.MAX_FALLOS:
                self._desconectar()
                self._reintento_ms = ahora
            return None

        self._fallos = 0
        if co2 == 0:
            return None  # el sensor entrega 0 cuando la medicion no es valida

        self.co2 = co2
        self.temperatura = -45 + 175 * temp_raw / 65535
        self.humedad = 100 * hum_raw / 65535
        self._ultima_ms = ahora
        return self.co2, self.temperatura, self.humedad

    def detener(self):
        """Detiene la medicion periodica (se llama al parar el programa desde Thonny)."""
        if not self.conectado:
            return
        try:
            self._comando(self.CMD_DETENER)
            time.sleep_ms(500)
        except OSError:
            pass
        self._desconectar()
