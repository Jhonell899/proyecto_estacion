from machine import Pin
import time


class SensorUltrasonico:
    def __init__(self, trig_pin, echo_pin, max_distance_cm=400):
        self.trig = Pin(trig_pin, Pin.OUT)
        self.echo = Pin(echo_pin, Pin.IN)
        self.max_distance_cm = max_distance_cm
        self.trig.value(0)
        time.sleep_us(2)

    def medir_distancia_cm(self):
        """Devuelve la distancia en cm o None si no hay lectura válida."""
        self.trig.value(0)
        time.sleep_us(2)

        self.trig.value(1)
        time.sleep_us(10)
        self.trig.value(0)

        timeout_us = 30000
        espera_inicio = time.ticks_us()

        while self.echo.value() == 0:
            if time.ticks_diff(time.ticks_us(), espera_inicio) > timeout_us:
                return None

        inicio_pulso = time.ticks_us()

        while self.echo.value() == 1:
            if time.ticks_diff(time.ticks_us(), inicio_pulso) > timeout_us:
                return None

        fin_pulso = time.ticks_us()
        duracion_us = time.ticks_diff(fin_pulso, inicio_pulso)

        if duracion_us <= 0:
            return None

        distancia_cm = (duracion_us * 0.0343) / 2

        if distancia_cm < 2 or distancia_cm > self.max_distance_cm:
            return None

        return distancia_cm

    def medir_distancia_promedio(self, cantidad=5, pausa_ms=30):
        """Toma varias lecturas y devuelve el promedio sin valores extremos."""
        lecturas = []

        for _ in range(cantidad):
            lectura = self.medir_distancia_cm()
            if lectura is not None:
                lecturas.append(lectura)
            time.sleep_ms(pausa_ms)

        if len(lecturas) == 0:
            return None

        if len(lecturas) <= 2:
            return sum(lecturas) / len(lecturas)

        lecturas.sort()
        lecturas_sin_extremos = lecturas[1:-1]
        return sum(lecturas_sin_extremos) / len(lecturas_sin_extremos)


class MedidorNivel:
    def __init__(self, sensor, altura_base_cm):
        self.sensor = sensor
        self.altura_base_cm = altura_base_cm
        self.nivel_anterior = None
        self.tiempo_anterior = None

    def leer_nivel_cm(self):
        distancia = self.sensor.medir_distancia_promedio()
        if distancia is None:
            return None

        nivel_actual = self.altura_base_cm - distancia
        if nivel_actual < 0:
            nivel_actual = 0

        return nivel_actual

    def calcular_velocidad_cm_s(self, nivel_actual, tiempo_actual):
        if self.nivel_anterior is None or self.tiempo_anterior is None:
            self.nivel_anterior = nivel_actual
            self.tiempo_anterior = tiempo_actual
            return 0

        delta_nivel = nivel_actual - self.nivel_anterior
        delta_tiempo = tiempo_actual - self.tiempo_anterior

        self.nivel_anterior = nivel_actual
        self.tiempo_anterior = tiempo_actual

        if delta_tiempo <= 0:
            return 0

        return delta_nivel / delta_tiempo


class MonitorNivel:
    def __init__(self, medidor, intervalo_segundos=2):
        self.medidor = medidor
        self.intervalo_segundos = intervalo_segundos

    def iniciar(self):
        print("Sistema listo. Midiendo nivel...")
        while True:
            nivel = self.medidor.leer_nivel_cm()
            tiempo_actual = time.time()

            if nivel is not None:
                velocidad = self.medidor.calcular_velocidad_cm_s(nivel, tiempo_actual)
                print("Nivel: {:.1f} cm | Cambio: {:.3f} cm/s".format(nivel, velocidad))
            else:
                print("Sin lectura válida del sensor")

            time.sleep(self.intervalo_segundos)


# ---------- Configuración ----------
TRIG_PIN = 5
ECHO_PIN = 18
ALTURA_BASE_CM = 30

sensor = SensorUltrasonico(TRIG_PIN, ECHO_PIN)
medidor = MedidorNivel(sensor, ALTURA_BASE_CM)
monitor = MonitorNivel(medidor, intervalo_segundos=2)
monitor.iniciar()