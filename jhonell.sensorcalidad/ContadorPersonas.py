import json
import time


class ContadorPersonas:
    """Cuenta las personas que entran y salen del aula con dos TCRT5000 en la puerta.

    Montaje: los dos sensores en el marco de la puerta, separados unos 8 cm:
      - EXTERIOR (sensor B): el que queda del lado del pasillo.
      - INTERIOR (sensor A): el que queda del lado del aula.

        EXTERIOR -> INTERIOR = ENTRADA (+1)
        INTERIOR -> EXTERIOR = SALIDA  (-1)

    Maquina de estados (logica comprobada con los sensores reales):
      BLOQUEADO -> LISTO -> ESPERANDO_SEGUNDO -> AMBOS / SOLO_SEGUNDO
                -> CONFIRMANDO -> se cuenta
    - Admite espacio libre entre sensores y los dos activos a la vez a mitad del cruce.
    - Cancela retrocesos, inicios simultaneos ambiguos y cruces de mas de CRUCE_MAX_MS.
    - Limitacion: dos personas que pasan juntas no se distinguen con fiabilidad.

    Los totales se guardan en conteo.json y se recuperan al encender.
    """

    ARCHIVO = "conteo.json"
    CRUCE_MAX_MS = 8000
    LIBRE_INICIAL_MS = 200
    CONFIRMACION_MS = 250
    DEPURAR = False   # True para ver cada paso del cruce en la consola de Thonny

    def __init__(self, exterior, interior):
        self.exterior = exterior
        self.interior = interior
        self.dentro = 0
        self.entradas = 0
        self.salidas = 0
        self.cancelaciones = 0

        self.estado = "BLOQUEADO"
        self._origen = None
        self._primero_se_libero = False
        self._inicio = time.ticks_ms()
        self._libre_desde = None
        self._cargar()

    # ---------- Archivo ----------
    def _cargar(self):
        try:
            with open(self.ARCHIVO) as archivo:
                datos = json.load(archivo)
            self.dentro = int(datos["dentro"])
            self.entradas = int(datos["entradas"])
            self.salidas = int(datos["salidas"])
        except OSError:
            pass  # aun no se conto a nadie
        except (ValueError, KeyError, TypeError) as error:
            print("Conteo guardado no valido, se empieza de cero:", error)

    def _guardar(self):
        try:
            with open(self.ARCHIVO, "w") as archivo:
                json.dump({"dentro": self.dentro, "entradas": self.entradas,
                           "salidas": self.salidas}, archivo)
        except OSError as error:
            print("No se pudo guardar el conteo:", error)

    def _depurar(self, *texto):
        if self.DEPURAR:
            print(*texto)

    # ---------- Control ----------
    def resetear(self):
        """Pone los contadores en cero (por ejemplo, al empezar el dia)."""
        self.dentro = self.entradas = self.salidas = self.cancelaciones = 0
        self._bloquear()
        self._guardar()

    # ---------- Maquina de estados ----------
    def _bloquear(self):
        self.estado = "BLOQUEADO"
        self._origen = None
        self._libre_desde = None
        self._primero_se_libero = False

    def _cancelar(self, motivo):
        self.cancelaciones += 1
        self._depurar("Cruce cancelado:", motivo)
        self._bloquear()

    def _iniciar(self, origen, ahora):
        self._origen = origen
        self._inicio = ahora
        self._primero_se_libero = False
        self.estado = "ESPERANDO_SEGUNDO"
        self._depurar("Posible", "ENTRADA" if origen == "EXTERIOR" else "SALIDA")

    def _confirmar(self):
        evento = None
        if self._origen == "EXTERIOR":
            self.entradas += 1
            self.dentro += 1
            evento = "ENTRADA"
            print("Entro una persona. Dentro:", self.dentro)
        elif self.dentro > 0:
            self.salidas += 1
            self.dentro -= 1
            evento = "SALIDA"
            print("Salio una persona. Dentro:", self.dentro)
        else:
            self._depurar("Salida detectada, pero no habia nadie dentro")
        if evento:
            self._guardar()
        self._bloquear()
        return evento

    def actualizar(self):
        """Se llama muy seguido (cada pocos ms). Devuelve "ENTRADA", "SALIDA" o None."""
        ahora = time.ticks_ms()
        ext = self.exterior.leer(ahora)
        inte = self.interior.leer(ahora)

        if self.estado == "BLOQUEADO":
            # Espera a que la puerta este libre un momento antes de aceptar un cruce.
            if not ext and not inte:
                if self._libre_desde is None:
                    self._libre_desde = ahora
                elif time.ticks_diff(ahora, self._libre_desde) >= self.LIBRE_INICIAL_MS:
                    self.estado = "LISTO"
                    self._libre_desde = None
            else:
                self._libre_desde = None
            return None

        if self.estado == "LISTO":
            if ext and not inte:
                self._iniciar("EXTERIOR", ahora)
            elif inte and not ext:
                self._iniciar("INTERIOR", ahora)
            elif ext and inte:
                self._cancelar("inicio simultaneo ambiguo")
            return None

        if (self.estado != "CONFIRMANDO"
                and time.ticks_diff(ahora, self._inicio) > self.CRUCE_MAX_MS):
            self._cancelar("tiempo maximo superado")
            return None

        primero = ext if self._origen == "EXTERIOR" else inte
        segundo = inte if self._origen == "EXTERIOR" else ext

        if self.estado == "ESPERANDO_SEGUNDO":
            if self._primero_se_libero and primero:
                self._cancelar("retroceso al primer sensor")
            elif segundo:
                self.estado = "AMBOS" if primero else "SOLO_SEGUNDO"
            elif not primero:
                self._primero_se_libero = True
            return None

        if self.estado == "AMBOS":
            if not primero and segundo:
                self.estado = "SOLO_SEGUNDO"
            elif primero and not segundo:
                self._cancelar("retroceso hacia el origen")
            elif not primero and not segundo:
                self._cancelar("ambos libres sin definir direccion")
            return None

        if self.estado == "SOLO_SEGUNDO":
            if primero:
                self._cancelar("regreso al primer sensor")
            elif not segundo:
                self.estado = "CONFIRMANDO"
                self._libre_desde = ahora
            return None

        if self.estado == "CONFIRMANDO":
            if ext or inte:
                self._cancelar("nueva deteccion durante la confirmacion")
            elif time.ticks_diff(ahora, self._libre_desde) >= self.CONFIRMACION_MS:
                return self._confirmar()
        return None

    # ---------- Consulta ----------
    def cruzando(self):
        """True si hay alguien a mitad de un cruce (conviene no hacer tareas lentas)."""
        return self.estado not in ("LISTO", "BLOQUEADO")

    def resumen(self):
        return {
            "dentro": self.dentro,
            "entradas": self.entradas,
            "salidas": self.salidas,
            "canceladas": self.cancelaciones,
            "exterior_ok": self.exterior.responde(),
            "interior_ok": self.interior.responde(),
        }
