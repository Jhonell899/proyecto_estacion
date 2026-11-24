import time

from machine import Pin, time_pulse_us

from Sensor import Sensor


class SensorUltrasonico(Sensor):
    """HC-SR04: mide la distancia (cm) al objeto que tiene enfrente.

    - Envia un pulso de ultrasonido y mide cuanto tarda en volver el eco.
    - El pin ECHO entrega 5 V: conectarlo al Pico W con un divisor de voltaje
      (por ejemplo 1 kOhm y 2 kOhm) para bajarlo a 3,3 V.
    - Solo espera el eco hasta distancia_max_cm: mas lejos se considera "libre".
      Asi cada lectura tarda pocos milisegundos y no frena el programa.
    """

    VELOCIDAD_CM_US = 0.0343   # velocidad del sonido
    DISTANCIA_MIN_CM = 2       # mas cerca, el HC-SR04 no mide bien
    CADUCIDAD_MS = 2000
    MAX_FALLOS = 10

    def __init__(self, nombre, trig, echo, distancia_max_cm=200):
        super().__init__(nombre)
        self._trig = Pin(trig, Pin.OUT)
        self._echo = Pin(echo, Pin.IN)
        self._trig.value(0)
        # Ida y vuelta del sonido hasta la distancia maxima.
        self._espera_us = int(distancia_max_cm * 2 / self.VELOCIDAD_CM_US)
        self.distancia = None
        self._fallos = 0

    def _borrar_datos(self):
        self._ultima_ms = None
        self.distancia = None

    def responde(self):
        """True si el sensor esta contestando (haya o no algo enfrente)."""
        return self.tiene_datos()

    def leer(self):
        """Devuelve la distancia en cm, o None si no hay nada dentro del alcance."""
        self._trig.value(0)
        time.sleep_us(2)
        self._trig.value(1)
        time.sleep_us(10)
        self._trig.value(0)
        duracion = time_pulse_us(self._echo, 1, self._espera_us)
        ahora = time.ticks_ms()

        if duracion == -2:
            # El eco nunca empezo: el sensor no responde (cable suelto o sin energia).
            self._fallos += 1
            if self._fallos == self.MAX_FALLOS:
                self._aviso("no responde, revisa TRIG/ECHO y los 5 V")
            if self._caducado(ahora):
                self._borrar_datos()
            self.distancia = None
            return None

        self._fallos = 0
        self._ultima_ms = ahora
        if duracion == -1:
            self.distancia = None  # nada dentro del alcance: la puerta esta libre
            return None

        distancia = duracion * self.VELOCIDAD_CM_US / 2
        self.distancia = distancia if distancia >= self.DISTANCIA_MIN_CM else None
        return self.distancia
