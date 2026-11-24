import time


class Sensor:
    """Clase base de todos los sensores del proyecto.

    Reune lo que es comun a cualquier sensor: nombre, control de datos caducados
    y avisos por consola. Cada sensor concreto hereda de esta clase y define
    su propia forma de leer() y de _borrar_datos().
    """

    # Tiempo maximo sin datos nuevos; cada clase hija lo ajusta a su sensor.
    CADUCIDAD_MS = 30000

    def __init__(self, nombre):
        self.nombre = nombre
        self._ultima_ms = None

    def leer(self):
        """Toma una lectura. Cada sensor la implementa a su manera."""
        raise NotImplementedError("La clase hija debe implementar leer()")

    def _borrar_datos(self):
        """Pone los valores en None. Cada sensor la implementa a su manera."""
        raise NotImplementedError("La clase hija debe implementar _borrar_datos()")

    def detener(self):
        """Apaga el sensor al cerrar el programa. Por defecto no hace nada;
        las clases hijas que lo necesiten la sobrescriben."""
        pass

    def tiene_datos(self):
        return self._ultima_ms is not None

    def _caducado(self, ahora):
        """True si ya paso demasiado tiempo desde la ultima lectura valida."""
        return (
            self._ultima_ms is not None
            and time.ticks_diff(ahora, self._ultima_ms) > self.CADUCIDAD_MS
        )

    def _aviso(self, mensaje):
        print("{}: {}".format(self.nombre, mensaje))
