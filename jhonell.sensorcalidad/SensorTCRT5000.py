import time

from machine import Pin

from Sensor import Sensor


class SensorTCRT5000(Sensor):
    """TCRT5000: sensor infrarrojo de reflexion; detecta si hay algo enfrente.

    - Salida digital DO: 0 V = detecta, 3,3 V = libre (confirmado con multimetro).
    - Alimentarlo con 3,3 V: con 5 V la salida DO entrega 5 V y puede danar el Pico W.
    - Antirrebote: un cambio solo se acepta si dura rebote_ms.
    - Si queda detectando sin parar mas de BLOQUEO_MS, se avisa: lo mas
      probable es que este tapado, desalineado o mal conectado.
    """

    REBOTE_MS = 30
    BLOQUEO_MS = 30000

    def __init__(self, nombre, gpio, rebote_ms=REBOTE_MS):
        super().__init__(nombre)
        self._pin = Pin(gpio, Pin.IN, Pin.PULL_UP)
        self.rebote_ms = rebote_ms
        ahora = time.ticks_ms()
        self._crudo = self._pin.value() == 0
        self.detecta = self._crudo
        self._ultimo_cambio = ahora
        self._detecta_desde = ahora if self.detecta else None
        self._ultima_ms = ahora
        self._avisado = False

    def _borrar_datos(self):
        self.detecta = False

    def leer(self, ahora=None):
        """Devuelve True si detecta algo (ya sin rebotes)."""
        if ahora is None:
            ahora = time.ticks_ms()
        lectura = self._pin.value() == 0
        if lectura != self._crudo:
            self._crudo = lectura
            self._ultimo_cambio = ahora
        if (self._crudo != self.detecta
                and time.ticks_diff(ahora, self._ultimo_cambio) >= self.rebote_ms):
            self.detecta = self._crudo
            self._detecta_desde = ahora if self.detecta else None
            self._avisado = False
        self._ultima_ms = ahora
        if not self.responde() and not self._avisado:
            self._avisado = True
            self._aviso("detecta sin parar; revisa que no este tapado o desalineado")
        return self.detecta

    def responde(self):
        """False si lleva demasiado tiempo detectando sin soltar."""
        if self._detecta_desde is None:
            return True
        return time.ticks_diff(time.ticks_ms(), self._detecta_desde) < self.BLOQUEO_MS
