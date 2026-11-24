import json
import os
import time


class AmbienteIdeal:
    """Prueba de funcionamiento y medicion del ambiente ideal (linea base).

    Al iniciar() pasa por estas etapas:
      1. PROBANDO: comprueba que los sensores respondan. El SCD40 y el PMS5003
         son obligatorios; el DHT11 y la OLED solo se informan. Si en
         PRUEBA_MAX_MS no responden los obligatorios, termina en FALLO.
      2. MIDIENDO: durante la duracion pedida (60 min por defecto) promedia
         todas las lecturas del ambiente.
      3. LISTO: guarda los promedios en ideal.json como el "ambiente ideal".
         Se recupera al encender y se borra con resetear().

    Si se reinicia el ESP32 a mitad de la medicion, esa medicion se pierde
    (el ideal guardado antes, si habia uno, se conserva).
    """

    ARCHIVO = "ideal.json"
    PRUEBA_MAX_MS = 90000
    MINUTOS_POR_DEFECTO = 60
    MINUTOS_MAXIMOS = 240

    VARIABLES = ("co2", "temp", "hum", "pm1", "pm25", "pm10")
    OBLIGATORIAS = ("co2", "pm25")
    SENSORES_OBLIGATORIOS = ("SCD40", "PMS5003")

    SIN_IDEAL = "SIN_IDEAL"
    PROBANDO = "PROBANDO"
    MIDIENDO = "MIDIENDO"
    LISTO = "LISTO"
    FALLO = "FALLO"

    def __init__(self):
        self.ideal = None
        self.estado = self.SIN_IDEAL
        self.mensaje = "Aun no se midio el ambiente ideal"
        self.prueba = {}
        self._inicio_ms = None
        self._duracion_ms = self.MINUTOS_POR_DEFECTO * 60000
        self._reiniciar_acumulados()
        self._cargar()

    # ---------- Archivo ----------
    def _cargar(self):
        try:
            with open(self.ARCHIVO) as archivo:
                ideal = json.load(archivo)
            if not all(v in ideal["valores"] for v in self.OBLIGATORIAS):
                raise ValueError("faltan valores")
        except OSError:
            return  # aun no se midio
        except (ValueError, KeyError, TypeError) as error:
            print("Ambiente ideal guardado no valido, se ignora:", error)
            return
        self.ideal = ideal
        self.estado = self.LISTO
        self.mensaje = "Ambiente ideal guardado ({} min)".format(ideal.get("minutos"))

    def _guardar(self):
        try:
            with open(self.ARCHIVO, "w") as archivo:
                json.dump(self.ideal, archivo)
        except OSError as error:
            print("No se pudo guardar el ambiente ideal:", error)

    # ---------- Control ----------
    def midiendo(self):
        """True mientras dura la prueba o la medicion."""
        return self.estado in (self.PROBANDO, self.MIDIENDO)

    def iniciar(self, minutos=MINUTOS_POR_DEFECTO):
        """Empieza la prueba de funcionamiento y luego la medicion."""
        if self.midiendo():
            raise ValueError("Ya se esta midiendo; resetea para cancelar")
        minutos = int(minutos)
        if not 1 <= minutos <= self.MINUTOS_MAXIMOS:
            raise ValueError("La duracion debe ser de 1 a {} minutos".format(self.MINUTOS_MAXIMOS))
        self._duracion_ms = minutos * 60000
        self._reiniciar_acumulados()
        self.prueba = {}
        self._inicio_ms = time.ticks_ms()
        self.estado = self.PROBANDO
        self.mensaje = "Prueba de funcionamiento en curso"

    def resetear(self):
        """Cancela una medicion en curso y borra el ambiente ideal guardado."""
        try:
            os.remove(self.ARCHIVO)
        except OSError:
            pass
        self.ideal = None
        self.prueba = {}
        self._reiniciar_acumulados()
        self.estado = self.SIN_IDEAL
        self.mensaje = "Ambiente ideal borrado"

    # ---------- Ciclo ----------
    def _reiniciar_acumulados(self):
        self._suma = {}
        self._cuenta = {}
        self._minimo = {}
        self._maximo = {}

    def _acumular(self, lecturas):
        for variable in self.VARIABLES:
            valor = lecturas.get(variable)
            if valor is None:
                continue
            self._suma[variable] = self._suma.get(variable, 0) + valor
            self._cuenta[variable] = self._cuenta.get(variable, 0) + 1
            self._minimo[variable] = min(self._minimo.get(variable, valor), valor)
            self._maximo[variable] = max(self._maximo.get(variable, valor), valor)

    def _fallar(self, mensaje):
        self.estado = self.FALLO
        self.mensaje = mensaje
        print("Ambiente ideal:", mensaje)

    def _terminar(self):
        sin_datos = [v for v in self.OBLIGATORIAS if not self._cuenta.get(v)]
        if sin_datos:
            self._fallar("No hubo lecturas de " + ", ".join(sin_datos))
            return
        self.ideal = {
            "valores": {v: round(self._suma[v] / self._cuenta[v], 1) for v in self._suma},
            "minimos": self._minimo,
            "maximos": self._maximo,
            "muestras": max(self._cuenta.values()),
            "minutos": self._duracion_ms // 60000,
        }
        self._guardar()
        self.estado = self.LISTO
        self.mensaje = "Ambiente ideal guardado ({} min)".format(self.ideal["minutos"])
        print("Ambiente ideal:", self.mensaje, self.ideal["valores"])

    def actualizar(self, lecturas, sensores):
        """Se llama en cada lectura.
        lecturas: diccionario con co2, temp, hum, pm1, pm25, pm10 y calentando.
        sensores: diccionario {"SCD40": True/False, ...} indicando si responde."""
        if not self.midiendo():
            return
        ahora = time.ticks_ms()
        transcurrido = time.ticks_diff(ahora, self._inicio_ms)

        if self.estado == self.PROBANDO:
            self.prueba = dict(sensores)
            if all(sensores.get(n) for n in self.SENSORES_OBLIGATORIOS):
                self.estado = self.MIDIENDO
                self._inicio_ms = ahora
                self.mensaje = "Prueba superada, midiendo el ambiente"
                print("Ambiente ideal:", self.mensaje, self.prueba)
            elif transcurrido > self.PRUEBA_MAX_MS:
                faltan = [n for n in self.SENSORES_OBLIGATORIOS if not sensores.get(n)]
                self._fallar("Prueba fallida: no responde " + ", ".join(faltan))
            return

        # MIDIENDO: durante el calentamiento del PMS5003 las particulas no son fiables.
        if not lecturas.get("calentando"):
            self._acumular(lecturas)
        if transcurrido >= self._duracion_ms:
            self._terminar()

    # ---------- Consulta ----------
    def progreso(self):
        """Porcentaje (0-100) y segundos restantes de la medicion."""
        if self.estado != self.MIDIENDO:
            return 0, 0
        transcurrido = time.ticks_diff(time.ticks_ms(), self._inicio_ms)
        porcentaje = min(100, transcurrido * 100 // self._duracion_ms)
        restante_s = max(0, (self._duracion_ms - transcurrido) // 1000)
        return porcentaje, restante_s

    def valor(self, variable):
        """Valor ideal de una variable, o None si no hay ideal guardado."""
        if self.ideal is None:
            return None
        return self.ideal["valores"].get(variable)

    def resumen(self):
        porcentaje, restante_s = self.progreso()
        return {
            "estado": self.estado,
            "mensaje": self.mensaje,
            "progreso": porcentaje,
            "restante_s": restante_s,
            "minutos": self._duracion_ms // 60000,
            "prueba": self.prueba,
            "valores": None if self.ideal is None else self.ideal["valores"],
        }
