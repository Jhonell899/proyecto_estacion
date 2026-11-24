import json


class ContadorPersonas:
    """Cuenta las personas que entran y salen del aula con dos HC-SR04 en la puerta.

    Montaje: los dos sensores en el marco de la puerta, a la altura de la cintura,
    apuntando hacia el otro lado y separados unos 15-20 cm:
      - EXTERIOR: el que queda del lado del pasillo.
      - INTERIOR: el que queda del lado del aula.

    Como funciona:
      - Un sensor esta "activo" cuando tiene algo a menos de umbral_cm.
      - El primero en activarse indica de donde viene la persona.
      - Se cuenta solo cuando la puerta queda libre y el ultimo sensor en
        liberarse es el contrario al primero, es decir, la persona cruzo:
            EXTERIOR -> INTERIOR = entrada
            INTERIOR -> EXTERIOR = salida
        Si alguien se asoma y se regresa, el primero y el ultimo coinciden y
        no se cuenta.
      - Para ignorar ruido, un cambio debe repetirse FILTRO lecturas seguidas.

    Los totales se guardan en conteo.json y se recuperan al encender.
    """

    ARCHIVO = "conteo.json"
    UMBRAL_CM = 70
    UMBRAL_MIN_CM = 10
    UMBRAL_MAX_CM = 190
    FILTRO = 2

    EXTERIOR = 0
    INTERIOR = 1

    def __init__(self, exterior, interior, umbral_cm=UMBRAL_CM):
        self._sensores = (exterior, interior)
        self.umbral_cm = umbral_cm
        self.dentro = 0
        self.entradas = 0
        self.salidas = 0

        self._activo = [False, False]
        self._seguidas = [0, 0]
        self._turno = 0
        self._primero = None
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

    # ---------- Control ----------
    def resetear(self):
        """Pone los contadores en cero (por ejemplo, al empezar el dia)."""
        self.dentro = self.entradas = self.salidas = 0
        self._primero = None
        self._guardar()

    def cambiar_umbral(self, umbral_cm):
        umbral_cm = int(umbral_cm)
        if not self.UMBRAL_MIN_CM <= umbral_cm <= self.UMBRAL_MAX_CM:
            raise ValueError("El umbral de la puerta debe ser de {} a {} cm".format(
                self.UMBRAL_MIN_CM, self.UMBRAL_MAX_CM))
        self.umbral_cm = umbral_cm

    # ---------- Deteccion ----------
    def actualizar(self):
        """Se llama en cada vuelta del ciclo (cada ~20 ms).

        Lee un solo sensor por vuelta, alternandolos, para que el eco de uno
        no confunda al otro."""
        i = self._turno
        self._turno = 1 - i
        distancia = self._sensores[i].leer()
        cerca = distancia is not None and distancia < self.umbral_cm

        if cerca == self._activo[i]:
            self._seguidas[i] = 0
            return
        self._seguidas[i] += 1
        if self._seguidas[i] >= self.FILTRO:
            self._seguidas[i] = 0
            self._activo[i] = cerca
            self._cambio(i, cerca)

    def _cambio(self, sensor, activo):
        if activo:
            if self._primero is None:
                self._primero = sensor
            return

        # Un sensor se libero: si la puerta quedo libre, se decide si cruzo.
        if any(self._activo):
            return
        primero, ultimo = self._primero, sensor
        self._primero = None
        if primero == self.EXTERIOR and ultimo == self.INTERIOR:
            self.entradas += 1
            self.dentro += 1
            self._guardar()
            print("Entro una persona. Dentro:", self.dentro)
        elif primero == self.INTERIOR and ultimo == self.EXTERIOR:
            self.salidas += 1
            self.dentro = max(0, self.dentro - 1)
            self._guardar()
            print("Salio una persona. Dentro:", self.dentro)

    # ---------- Consulta ----------
    def resumen(self):
        return {
            "dentro": self.dentro,
            "entradas": self.entradas,
            "salidas": self.salidas,
            "umbral_cm": self.umbral_cm,
            "exterior_ok": self._sensores[self.EXTERIOR].responde(),
            "interior_ok": self._sensores[self.INTERIOR].responde(),
        }
