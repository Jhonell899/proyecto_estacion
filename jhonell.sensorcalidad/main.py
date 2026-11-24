from machine import Pin, I2C, UART, WDT
import gc
import json
import time

from Sensorgas import SensorGas
from SensorAmbiental import SensorAmbiental
from SensorDHT11 import SensorDHT11
from Comunicador import Comunicador
from Contador import Contador
from EnlacePC import EnlacePC
from AmbienteIdeal import AmbienteIdeal
from SensorUltrasonico import SensorUltrasonico
from ContadorPersonas import ContadorPersonas


class EstacionCalidadAire:
    """Clase principal: crea los sensores y la pantalla, y coordina el ciclo de medicion.

    Si falta algun dispositivo, solo se avisa por consola: el resto sigue midiendo.
    Ademas atiende los comandos del software de control de la PC (ver EnlacePC).
    """

    # ---------- Configuracion ----------
    # I2C compartido: SCD40 (0x62) + OLED SSD1306 (0x3C)
    I2C_SDA = 21
    I2C_SCL = 22
    # PMS5003: TX del sensor -> RX del ESP32 (GPIO16)
    PMS_RX = 16
    PMS_TX = 17
    # DHT11: pin de datos
    DHT_PIN = 4
    # HC-SR04 de la puerta (ECHO con divisor de voltaje a 3,3 V)
    PUERTA_EXT_TRIG = 5     # sensor del lado del pasillo
    PUERTA_EXT_ECHO = 18
    PUERTA_INT_TRIG = 19    # sensor del lado del aula
    PUERTA_INT_ECHO = 23

    INTERVALO_LECTURA_MS = 1000
    INTERVALO_PANTALLA_MS = 2000
    # Los ajustes cambiados desde la PC se guardan aqui y se recuperan al encender.
    ARCHIVO_AJUSTES = "ajustes.json"

    def __init__(self, altitud_m=None, usar_watchdog=False):
        """altitud_m: altitud del lugar; mejora la precision del CO2 en zonas altas.
        usar_watchdog: reinicia el ESP32 si el programa se cuelga mas de 8 s.
        Activalo solo cuando ya funcione: una vez encendido no se puede apagar."""
        i2c = I2C(0, sda=Pin(self.I2C_SDA), scl=Pin(self.I2C_SCL), freq=100000)
        direcciones = i2c.scan()
        print("Dispositivos I2C:", [hex(d) for d in direcciones])
        if 0x3C not in direcciones:
            print("Aviso: OLED no detectada en 0x3C")
        if 0x62 not in direcciones:
            print("Aviso: SCD40 no detectado en 0x62")

        uart = UART(2, baudrate=9600, rx=self.PMS_RX, tx=self.PMS_TX)

        self.gas = SensorGas(i2c, altitud_m=altitud_m)
        self.ambiental = SensorAmbiental(uart)
        self.dht = SensorDHT11(self.DHT_PIN)
        self.sensores = [self.ambiental, self.gas, self.dht]
        self.pantalla = Comunicador(i2c)
        self.enlace = EnlacePC()
        self.ideal = AmbienteIdeal()

        # Los sensores de la puerta se leen en cada vuelta (no cada 1 s) para
        # no perderse a nadie; por eso no estan en la lista self.sensores.
        self.puerta_ext = SensorUltrasonico("Puerta exterior", self.PUERTA_EXT_TRIG, self.PUERTA_EXT_ECHO)
        self.puerta_int = SensorUltrasonico("Puerta interior", self.PUERTA_INT_TRIG, self.PUERTA_INT_ECHO)
        self.personas = ContadorPersonas(self.puerta_ext, self.puerta_int)

        self.lectura = Contador(self.INTERVALO_LECTURA_MS)
        self.refresco = Contador(self.INTERVALO_PANTALLA_MS)
        self.wdt = WDT(timeout=8000) if usar_watchdog else None

        self._cargar_ajustes()

    # ---------- Ajustes ----------
    def _cambiar_intervalos(self, lectura_ms, pantalla_ms):
        lectura_ms = int(lectura_ms)
        pantalla_ms = int(pantalla_ms)
        if not 500 <= lectura_ms <= 60000:
            raise ValueError("Intervalo de lectura: entre 500 y 60000 ms")
        if not 1000 <= pantalla_ms <= 60000:
            raise ValueError("Intervalo de pantalla: entre 1000 y 60000 ms")
        self.lectura.intervalo_ms = lectura_ms
        self.refresco.intervalo_ms = pantalla_ms

    def _guardar_ajustes(self):
        ajustes = {
            "lim_co2": list(self.pantalla.LIMITES_CO2),
            "lim_pm25": list(self.pantalla.LIMITES_PM25),
            "t_lectura": self.lectura.intervalo_ms,
            "t_pantalla": self.refresco.intervalo_ms,
            "umbral_cm": self.personas.umbral_cm,
        }
        try:
            with open(self.ARCHIVO_AJUSTES, "w") as archivo:
                json.dump(ajustes, archivo)
        except OSError as error:
            print("No se pudieron guardar los ajustes:", error)

    def _cargar_ajustes(self):
        try:
            with open(self.ARCHIVO_AJUSTES) as archivo:
                ajustes = json.load(archivo)
            self.pantalla.cambiar_limites(ajustes["lim_co2"], ajustes["lim_pm25"])
            self._cambiar_intervalos(ajustes["t_lectura"], ajustes["t_pantalla"])
            if "umbral_cm" in ajustes:
                self.personas.cambiar_umbral(ajustes["umbral_cm"])
            print("Ajustes guardados recuperados")
        except OSError:
            pass  # aun no hay archivo: se usan los valores de fabrica
        except (ValueError, TypeError, KeyError) as error:
            print("Ajustes guardados no validos, se ignoran:", error)

    # ---------- Enlace con la PC ----------
    def _estado(self):
        estado = self.pantalla.resumen(self.gas, self.ambiental, self.dht)
        estado["t_lectura"] = self.lectura.intervalo_ms
        estado["t_pantalla"] = self.refresco.intervalo_ms
        estado["ideal"] = self.ideal.resumen()
        estado["personas"] = self.personas.resumen()
        return estado

    def _sensores_responden(self):
        """Para la prueba de funcionamiento: que dispositivo esta entregando datos."""
        return {
            "SCD40": self.gas.tiene_datos(),
            "PMS5003": self.ambiental.tiene_datos() and not self.ambiental.calentando(),
            "DHT11": self.dht.tiene_datos(),
            "OLED": self.pantalla.oled is not None,
            "PUERTA": self.puerta_ext.responde() and self.puerta_int.responde(),
        }

    def _comando_personas(self, comando):
        accion = comando.get("accion")
        if accion == "resetear":
            self.personas.resetear()
            return "Conteo de personas en cero"
        if accion == "umbral":
            self.personas.cambiar_umbral(comando.get("cm"))
            return "Umbral de la puerta: {} cm".format(self.personas.umbral_cm)
        raise ValueError("Accion desconocida para el conteo de personas")

    def _comando_ideal(self, comando):
        accion = comando.get("accion")
        if accion == "iniciar":
            # Para medir hacen falta las particulas: se despierta el PMS5003.
            if self.ambiental.dormido:
                self.ambiental.despertar()
            self.ideal.iniciar(comando.get("minutos", AmbienteIdeal.MINUTOS_POR_DEFECTO))
            return "Prueba de funcionamiento iniciada; luego medira {} min".format(
                self.ideal.resumen()["minutos"])
        if accion == "resetear":
            self.ideal.resetear()
            return "Ambiente ideal borrado"
        raise ValueError("Accion desconocida para el ambiente ideal")

    def _aplicar_comando(self, comando):
        try:
            nombre = comando.get("cmd")
            if nombre == "limites":
                self.pantalla.cambiar_limites(comando.get("co2"), comando.get("pm25"))
                mensaje = "Limites actualizados"
            elif nombre == "intervalos":
                self._cambiar_intervalos(comando.get("lectura"), comando.get("pantalla"))
                mensaje = "Intervalos actualizados"
            elif nombre == "ideal":
                mensaje = self._comando_ideal(comando)
            elif nombre == "personas":
                mensaje = self._comando_personas(comando)
            elif nombre == "pms":
                if comando.get("dormir") and self.ideal.midiendo():
                    raise ValueError("No se puede dormir el sensor de polvo y humo mientras se mide el ambiente ideal")
                if comando.get("dormir"):
                    self.ambiental.dormir()
                    mensaje = "Sensor de polvo y humo dormido"
                else:
                    self.ambiental.despertar()
                    mensaje = "Sensor de polvo y humo despierto, calentando 30 s"
            else:
                raise ValueError("Comando desconocido")
        except (ValueError, TypeError) as error:
            self.enlace.responder(False, str(error))
            return

        self._guardar_ajustes()
        self.enlace.responder(True, mensaje)
        self.enlace.enviar_datos(self._estado())

    # ---------- Ciclo ----------
    def paso(self):
        """Una vuelta del ciclo: atiende a la PC, lee los sensores y actualiza la pantalla."""
        try:
            for comando in self.enlace.recibir():
                self._aplicar_comando(comando)

            # La puerta se revisa en cada vuelta para no perderse a nadie.
            self.personas.actualizar()

            if self.lectura.listo():
                # Polimorfismo: cada sensor responde a leer() a su manera.
                for sensor in self.sensores:
                    sensor.leer()
                if self.ideal.midiendo():
                    self.ideal.actualizar(
                        self.pantalla.resumen(self.gas, self.ambiental, self.dht),
                        self._sensores_responden(),
                    )

            if self.refresco.listo():
                self.pantalla.mostrar(self.gas, self.ambiental, self.dht, self.ideal, self.personas)
                self.enlace.enviar_datos(self._estado())
                gc.collect()
        except Exception as error:
            # Un error inesperado no detiene el equipo; se informa y se sigue.
            print("Error en el ciclo:", error)

        if self.wdt:
            self.wdt.feed()

    def detener(self):
        for sensor in self.sensores:
            sensor.detener()

    def iniciar(self):
        print("Sistema listo. Midiendo calidad del aire...")
        try:
            while True:
                self.paso()
                # Pausa corta: la puerta necesita revisarse seguido.
                time.sleep_ms(20)
        except KeyboardInterrupt:
            print("Programa detenido desde Thonny")
        finally:
            self.detener()


if __name__ == "__main__":
    estacion = EstacionCalidadAire()
    estacion.iniciar()
