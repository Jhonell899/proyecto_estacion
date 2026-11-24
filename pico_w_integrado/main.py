# -*- coding: utf-8 -*-
"""
PROYECTO: CALIDAD DEL AIRE Y OCUPACION DE UN LABORATORIO
Hardware: Raspberry Pi Pico W, MicroPython, Thonny
Programacion orientada a objetos (POO).

Conexiones (GPxx = numero del GPIO; entre parentesis, el pin fisico):
  OLED SSD1306 (I2C0 0x3C)      SDA=GP4 (6), SCL=GP5 (7)    VCC=3V3 OUT (36)
  SCD40 (CO2, I2C0 0x62)        SDA=GP4 (6), SCL=GP5 (7)    VCC=3V3 OUT (36)
  DHT11 (temperatura/humedad)   DATA=GP15 (20)              VCC=3V3 OUT (36)
  PMS5003 (PM1, PM2.5, PM10)    TX sensor -> GP1 (2)        VCC=VBUS 5 V (40)
                                RX sensor <- GP0 (1) (opcional)
  TCRT5000 A (0=detecta)        DO -> GP16 (21)             VCC=3V3 OUT (36)
  TCRT5000 B (0=detecta)        DO -> GP17 (22)             VCC=3V3 OUT (36)
  GND de todos: cualquier GND del Pico (3, 8, 13, 18, 23, 28, 33, 38)

IMPORTANTE: los pines del Pico W NO soportan 5 V.
  - Alimenta los TCRT5000 con 3,3 V: si van a 5 V, su salida DO entrega 5 V.
  - No uses GP23, GP24, GP25 ni GP29: el Pico W los usa para el WiFi.

Direcciones del contador:
  B -> A = ENTRADA (+1)
  A -> B = SALIDA (-1)

La pantalla rota 3 vistas cada 5 s. Al confirmar un cruce muestra
una persona y una puerta durante 1.5 s. No almacena CSV todavia.

REQUISITO: guardar ssd1306.py en el Pico W.
NOTA: Los TCRT5000 sirven para un prototipo de corto alcance.
No distinguen con fiabilidad dos personas que pasan juntas.
"""

from machine import Pin, I2C, UART
from time import ticks_ms, ticks_diff, sleep_ms
import dht
import ssd1306


# =============================================
# CLASE 0: CONFIGURACION (pines y tiempos)
# =============================================
class Configuracion:
    """Todos los pines y tiempos en un solo lugar. Para cambiar un pin,
    se cambia aqui y nada mas."""

    # --- Pines del Raspberry Pi Pico W ---
    I2C_ID = 0          # I2C0
    PIN_SDA = 4         # GP4  (pin 6)
    PIN_SCL = 5         # GP5  (pin 7)
    PIN_DHT = 15        # GP15 (pin 20)
    UART_ID = 0         # UART0
    PIN_PMS_TX = 0      # GP0  (pin 1)  -> RX del PMS5003 (opcional)
    PIN_PMS_RX = 1      # GP1  (pin 2)  <- TX del PMS5003
    PIN_A = 16          # GP16 (pin 21) TCRT5000 A
    PIN_B = 17          # GP17 (pin 22) TCRT5000 B

    DIR_OLED = 0x3C
    DIR_SCD40 = 0x62

    # La OLED con figura humana ya funciono a 400 kHz.
    # Si aparecen errores I2C, probar 100000.
    FRECUENCIA_I2C = 400000

    # --- Contador de personas ---
    OCUPACION_INICIAL = 0      # Cambiar si ya hay personas dentro
    REBOTE_MS = 30
    CRUCE_MAX_MS = 8000
    LIBRE_INICIAL_MS = 200
    CONFIRMACION_MS = 250

    # --- Pantalla y consola ---
    CAMBIO_PAGINA_MS = 5000
    DURACION_EVENTO_MS = 1500
    REFRESCO_OLED_MS = 1500
    REPORTE_CONSOLA_MS = 5000
    MOSTRAR_SENSORES = False  # True para diagnosticar los cruces


def texto(valor):
    """Evita mostrar 'None' cuando un sensor aun no tiene lectura."""
    return "--" if valor is None else str(valor)


# =============================================
# CLASE 1: SENSOR (clase base)
# =============================================
class Sensor:
    """Clase base: todo sensor tiene un nombre, se actualiza y se puede detener.
    Cada clase hija implementa actualizar() a su manera (polimorfismo)."""

    def __init__(self, nombre):
        self.nombre = nombre

    def actualizar(self, ahora=None):
        raise NotImplementedError("Cada sensor implementa actualizar()")

    def detener(self):
        """Por defecto no hace nada; el SCD40 lo sobrescribe."""
        pass


# =============================================
# CLASE 2: SENSOR DHT11 (hereda de Sensor)
# =============================================
class SensorDHT11(Sensor):
    def __init__(self, gpio):
        super().__init__("DHT11")
        self.dispositivo = dht.DHT11(Pin(gpio))
        self.temperatura = None
        self.humedad = None
        self.ultima_lectura = None
        self.ultimo_intento = ticks_ms()

    def actualizar(self, ahora=None):
        ahora = ticks_ms()
        if ticks_diff(ahora, self.ultimo_intento) < 2500:
            return
        self.ultimo_intento = ahora
        try:
            self.dispositivo.measure()
            self.temperatura = self.dispositivo.temperature()
            self.humedad = self.dispositivo.humidity()
            self.ultima_lectura = ticks_ms()
        except OSError as error:
            print("Error DHT11:", error)

    def valores(self):
        if self.ultima_lectura is None:
            return None, None
        if ticks_diff(ticks_ms(), self.ultima_lectura) > 10000:
            return None, None
        return self.temperatura, self.humedad


# =============================================
# CLASE 3: SENSOR SCD40 (I2C, CO2) (hereda de Sensor)
# =============================================
class SensorSCD40(Sensor):
    def __init__(self, i2c, direccion):
        super().__init__("SCD40")
        self.i2c = i2c
        self.direccion = direccion
        self.co2 = None
        self.ultima_lectura = None
        self.ultimo_intento = ticks_ms()
        self.iniciado = False

    @staticmethod
    def crc8(datos):
        crc = 0xFF
        for byte in datos:
            crc ^= byte
            for _ in range(8):
                if crc & 0x80:
                    crc = ((crc << 1) ^ 0x31) & 0xFF
                else:
                    crc = (crc << 1) & 0xFF
        return crc

    def iniciar(self):
        # Detiene cualquier medicion anterior, por ejemplo tras Ctrl+C.
        try:
            self.i2c.writeto(self.direccion, b'\x3F\x86')
        except OSError:
            pass
        sleep_ms(600)  # Solo se realiza al iniciar, no durante el conteo.
        self.i2c.writeto(self.direccion, b'\x21\xB1')
        self.ultimo_intento = ticks_ms()
        self.iniciado = True
        print("SCD40 iniciado (lectura periodica)")

    def actualizar(self, ahora=None):
        if not self.iniciado:
            return
        ahora = ticks_ms()
        if ticks_diff(ahora, self.ultimo_intento) < 1000:
            return
        self.ultimo_intento = ahora
        try:
            # 0xE4B8: get_data_ready_status
            self.i2c.writeto(self.direccion, b'\xE4\xB8')
            sleep_ms(2)
            estado = self.i2c.readfrom(self.direccion, 3)
            if self.crc8(estado[:2]) != estado[2]:
                raise ValueError("CRC de disponibilidad")
            palabra = (estado[0] << 8) | estado[1]
            if (palabra & 0x07FF) == 0:
                return

            # 0xEC05: read_measurement
            self.i2c.writeto(self.direccion, b'\xEC\x05')
            sleep_ms(2)
            datos = self.i2c.readfrom(self.direccion, 9)
            for pos in (0, 3, 6):
                if self.crc8(datos[pos:pos + 2]) != datos[pos + 2]:
                    raise ValueError("CRC de medicion")
            self.co2 = (datos[0] << 8) | datos[1]
            self.ultima_lectura = ticks_ms()
        except (OSError, ValueError) as error:
            print("Error SCD40:", error)

    def valor_co2(self):
        if self.ultima_lectura is None:
            return None
        if ticks_diff(ticks_ms(), self.ultima_lectura) > 15000:
            return None
        return self.co2

    def detener(self):
        if not self.iniciado:
            return
        try:
            self.i2c.writeto(self.direccion, b'\x3F\x86')
            sleep_ms(600)
        except OSError:
            pass
        self.iniciado = False


# =============================================
# CLASE 4: SENSOR PMS5003 (UART) (hereda de Sensor)
# =============================================
class SensorPMS5003(Sensor):
    def __init__(self, uart_id, pin_tx, pin_rx):
        super().__init__("PMS5003")
        # En el Pico W: UART0 con TX=GP0 y RX=GP1.
        self.uart = UART(uart_id, baudrate=9600,
                         tx=Pin(pin_tx), rx=Pin(pin_rx),
                         timeout=0, rxbuf=512)
        self.buffer = bytearray()
        self.pm1 = None
        self.pm25 = None
        self.pm10 = None
        self.ultima_lectura = None

    @staticmethod
    def entero(datos, pos):
        return (datos[pos] << 8) | datos[pos + 1]

    def actualizar(self, ahora=None):
        nuevos = self.uart.read()
        if nuevos:
            self.buffer.extend(nuevos)
        if len(self.buffer) > 512:
            self.buffer = self.buffer[-96:]

        while len(self.buffer) >= 32:
            if self.buffer[0] != 0x42 or self.buffer[1] != 0x4D:
                self.buffer = self.buffer[1:]
                continue
            if self.entero(self.buffer, 2) != 28:
                self.buffer = self.buffer[1:]
                continue

            trama = self.buffer[:32]
            checksum_calculado = sum(trama[:30]) & 0xFFFF
            checksum_recibido = self.entero(trama, 30)
            if checksum_calculado != checksum_recibido:
                self.buffer = self.buffer[1:]
                continue

            # Valores atmosfericos, no los valores CF=1.
            self.pm1 = self.entero(trama, 10)
            self.pm25 = self.entero(trama, 12)
            self.pm10 = self.entero(trama, 14)
            self.ultima_lectura = ticks_ms()

            # Compatible con MicroPython: sin 'del buffer[:32]'.
            self.buffer = self.buffer[32:]

    def valores(self):
        if self.ultima_lectura is None:
            return None, None, None
        if ticks_diff(ticks_ms(), self.ultima_lectura) > 15000:
            return None, None, None
        return self.pm1, self.pm25, self.pm10


# =============================================
# CLASE 5: SENSOR TCRT5000 (hereda de Sensor)
# =============================================
class SensorTCRT5000(Sensor):
    def __init__(self, nombre, gpio, rebote_ms):
        super().__init__(nombre)
        self.pin = Pin(gpio, Pin.IN, Pin.PULL_UP)
        self.rebote_ms = rebote_ms
        # Confirmado con multimetro: 0 V = detecta, 3.3 V = libre.
        self.crudo = (self.pin.value() == 0)
        self.estable = self.crudo
        self.ultimo_cambio = ticks_ms()

    def actualizar(self, ahora=None):
        if ahora is None:
            ahora = ticks_ms()
        lectura = (self.pin.value() == 0)
        if lectura != self.crudo:
            self.crudo = lectura
            self.ultimo_cambio = ahora
        if ticks_diff(ahora, self.ultimo_cambio) >= self.rebote_ms:
            self.estable = self.crudo
        return self.estable


# =============================================
# CLASE 6: CONTADOR DE PERSONAS
# =============================================
class ContadorPersonas:
    """Logica comprobada con los dos TCRT5000, separados 8 cm.

    B -> A: ENTRADA
    A -> B: SALIDA
    Admite espacio libre y activacion simultanea intermedia.
    Rechaza retrocesos detectables, secuencias ambiguas y expiraciones.
    Composicion: el contador contiene a sus dos sensores TCRT5000.
    """
    def __init__(self, sensor_a, sensor_b, config):
        self.sensor_a = sensor_a
        self.sensor_b = sensor_b
        self.config = config
        self.personas = max(0, config.OCUPACION_INICIAL)
        self.entradas = 0
        self.salidas = 0
        self.cancelaciones = 0
        self.estado = "BLOQUEADO"
        self.origen = None
        self.primero_se_libero = False
        self.inicio = ticks_ms()
        self.libre_desde = None
        self.ultimo_patron = -1

    def bloquear(self):
        self.estado = "BLOQUEADO"
        self.origen = None
        self.libre_desde = None
        self.primero_se_libero = False

    def cancelar(self, motivo):
        self.cancelaciones += 1
        print("CANCELADO:", motivo)
        self.bloquear()

    def iniciar(self, origen, ahora):
        self.origen = origen
        self.inicio = ahora
        self.primero_se_libero = False
        self.estado = "ESPERANDO_SEGUNDO"
        print("Posible", "SALIDA" if origen == "A" else "ENTRADA")

    def confirmar(self):
        evento = None
        if self.origen == "B":
            self.entradas += 1
            self.personas += 1
            evento = "ENTRADA"
            print(">>> ENTRADA +1")
        elif self.origen == "A":
            if self.personas > 0:
                self.salidas += 1
                self.personas -= 1
                evento = "SALIDA"
                print("<<< SALIDA -1")
            else:
                print("SALIDA detectada, pero ocupacion es cero")

        print("Entradas:", self.entradas,
              "| Salidas:", self.salidas,
              "| Dentro:", self.personas,
              "| Canceladas:", self.cancelaciones)
        self.bloquear()
        return evento

    def actualizar(self):
        cfg = self.config
        ahora = ticks_ms()
        a = self.sensor_a.actualizar(ahora)
        b = self.sensor_b.actualizar(ahora)
        patron = (1 if a else 0) + (2 if b else 0)
        if cfg.MOSTRAR_SENSORES and patron != self.ultimo_patron:
            print("A:", int(a), "B:", int(b), "Estado:", self.estado)
        self.ultimo_patron = patron

        if self.estado == "BLOQUEADO":
            if not a and not b:
                if self.libre_desde is None:
                    self.libre_desde = ahora
                elif ticks_diff(ahora, self.libre_desde) >= cfg.LIBRE_INICIAL_MS:
                    self.estado = "LISTO"
                    self.libre_desde = None
            else:
                self.libre_desde = None
            return None

        if self.estado == "LISTO":
            if a and not b:
                self.iniciar("A", ahora)
            elif b and not a:
                self.iniciar("B", ahora)
            elif a and b:
                self.cancelar("Inicio simultaneo ambiguo")
            return None

        if (self.estado != "CONFIRMANDO" and
                ticks_diff(ahora, self.inicio) > cfg.CRUCE_MAX_MS):
            self.cancelar("Tiempo maximo superado")
            return None

        primero = a if self.origen == "A" else b
        segundo = b if self.origen == "A" else a

        if self.estado == "ESPERANDO_SEGUNDO":
            if self.primero_se_libero and primero:
                self.cancelar("Retroceso al primer sensor")
            elif segundo:
                if primero:
                    self.estado = "AMBOS"
                    print("Ambos sensores activos")
                else:
                    self.estado = "SOLO_SEGUNDO"
                    print("Segundo sensor detectado (espacio libre)")
            elif not primero and not self.primero_se_libero:
                self.primero_se_libero = True
                print("Espacio libre entre sensores")
            return None

        if self.estado == "AMBOS":
            if not primero and segundo:
                self.estado = "SOLO_SEGUNDO"
                print("Primer sensor liberado")
            elif primero and not segundo:
                self.cancelar("Retroceso hacia el origen")
            elif not primero and not segundo:
                self.cancelar("Ambos libres sin definir direccion")
            return None

        if self.estado == "SOLO_SEGUNDO":
            if primero:
                self.cancelar("Regreso al primer sensor")
            elif not segundo:
                self.estado = "CONFIRMANDO"
                self.libre_desde = ahora
                print("Cruce terminado; confirmando...")
            return None

        if self.estado == "CONFIRMANDO":
            if a or b:
                self.cancelar("Nueva deteccion durante confirmacion")
            elif ticks_diff(ahora, self.libre_desde) >= cfg.CONFIRMACION_MS:
                return self.confirmar()
            return None

        return None


# =============================================
# CLASE 7: PANTALLA OLED CON ANIMACION
# =============================================
class PantallaOLED:
    """Tres pantallas + aviso temporal de entrada/salida."""
    def __init__(self, i2c, config):
        self.config = config
        self.oled = ssd1306.SSD1306_I2C(128, 64, i2c, addr=config.DIR_OLED)
        self.pagina = 0  # 0=CO2, 1=PM, 2=aforo
        self.ultimo_cambio = ticks_ms()
        self.ultimo_dibujo = None
        self.evento_visible = None
        self.evento_desde = ticks_ms()

    def persona(self, x, y):
        d = self.oled
        d.fill_rect(x + 5, y, 5, 5, 1)
        d.vline(x + 7, y + 5, 8, 1)
        d.line(x + 7, y + 7, x + 1, y + 10, 1)
        d.line(x + 7, y + 7, x + 13, y + 10, 1)
        d.line(x + 7, y + 12, x + 2, y + 19, 1)
        d.line(x + 7, y + 12, x + 12, y + 19, 1)

    def puerta(self, x, y):
        d = self.oled
        d.rect(x, y, 16, 21, 1)
        d.vline(x + 3, y + 1, 19, 1)
        d.pixel(x + 12, y + 11, 1)

    def flecha(self, x, y, derecha=True):
        d = self.oled
        d.hline(x, y, 22, 1)
        if derecha:
            d.line(x + 21, y, x + 16, y - 4, 1)
            d.line(x + 21, y, x + 16, y + 4, 1)
        else:
            d.line(x, y, x + 5, y - 4, 1)
            d.line(x, y, x + 5, y + 4, 1)

    def mostrar_inicio(self):
        d = self.oled
        d.fill(0)
        d.text("CALIDAD DE AIRE", 4, 3)
        d.text("PICO W + POO", 16, 24)
        d.text("INICIANDO...", 12, 43)
        d.show()

    def mostrar_evento(self, evento, contador):
        d = self.oled
        d.fill(0)
        d.text("AFORO LAB", 28, 3)
        if evento == "ENTRADA":
            d.text("ENTRANDO", 32, 18)
            self.persona(19, 31)
            self.flecha(52, 40, True)
            self.puerta(92, 30)
        elif evento == "SALIDA":
            d.text("SALIENDO", 32, 18)
            self.puerta(19, 30)
            self.flecha(52, 40, True)
            self.persona(92, 31)
        d.text("DENTRO: {}".format(contador.personas), 22, 54)
        d.show()

    def dibujar_pagina(self, sistema):
        d = self.oled
        d.fill(0)
        if self.pagina == 0:
            temperatura, humedad = sistema.dht.valores()
            co2 = sistema.scd.valor_co2()
            d.text("CALIDAD DE AIRE", 4, 3)
            d.text("CO2: {} ppm".format(texto(co2)), 0, 20)
            d.text("TEMP: {} C".format(texto(temperatura)), 0, 35)
            d.text("HUM: {} %".format(texto(humedad)), 0, 50)
        elif self.pagina == 1:
            pm1, pm25, pm10 = sistema.pms.valores()
            d.text("PARTICULAS PM", 8, 3)
            d.text("PM1.0:{}ug/m3".format(texto(pm1)), 0, 20)
            d.text("PM2.5:{}ug/m3".format(texto(pm25)), 0, 35)
            d.text("PM10:{}ug/m3".format(texto(pm10)), 0, 50)
        else:
            c = sistema.contador
            d.text("AFORO LAB", 28, 3)
            d.text("DENTRO: {}".format(c.personas), 0, 18)
            d.text("ENTRADAS: {}".format(c.entradas), 0, 30)
            d.text("SALIDAS: {}".format(c.salidas), 0, 42)
            d.text("CANCELADAS: {}".format(c.cancelaciones), 0, 54)
        d.show()

    def actualizar(self, sistema, evento):
        cfg = self.config
        ahora = ticks_ms()
        c = sistema.contador

        # Evento confirmado: prioridad sobre la rotacion de pantallas.
        if evento is not None:
            self.evento_visible = evento
            self.evento_desde = ahora
            self.mostrar_evento(evento, c)
            return

        if self.evento_visible is not None:
            if ticks_diff(ahora, self.evento_desde) < cfg.DURACION_EVENTO_MS:
                return
            # No redibujar si alguien esta cruzando.
            if c.estado != "LISTO":
                return
            self.evento_visible = None
            self.ultimo_dibujo = None
            self.ultimo_cambio = ahora  # Reanudar rotacion desde este momento.

        # Evitar que el OLED bloquee las lecturas durante un cruce.
        if c.estado != "LISTO":
            return

        if ticks_diff(ahora, self.ultimo_cambio) >= cfg.CAMBIO_PAGINA_MS:
            self.pagina = (self.pagina + 1) % 3
            self.ultimo_cambio = ahora
            self.ultimo_dibujo = None

        if self.ultimo_dibujo is not None:
            if ticks_diff(ahora, self.ultimo_dibujo) < cfg.REFRESCO_OLED_MS:
                return

        self.dibujar_pagina(sistema)
        self.ultimo_dibujo = ticks_ms()


# =============================================
# CLASE 8: SISTEMA PRINCIPAL
# =============================================
class SistemaCalidadAire:
    """Composicion: el sistema contiene los sensores, el contador y la pantalla."""

    def __init__(self, config=Configuracion):
        self.config = config
        # Pico W: I2C0 por hardware en GP4 (SDA) y GP5 (SCL).
        self.i2c = I2C(config.I2C_ID, sda=Pin(config.PIN_SDA),
                       scl=Pin(config.PIN_SCL), freq=config.FRECUENCIA_I2C)
        encontrados = self.i2c.scan()
        print("I2C:", [hex(x) for x in encontrados])
        if config.DIR_OLED not in encontrados:
            raise OSError("OLED no detectada en 0x3C")
        if config.DIR_SCD40 not in encontrados:
            raise OSError("SCD40 no detectado en 0x62")

        sensor_a = SensorTCRT5000("A", config.PIN_A, config.REBOTE_MS)
        sensor_b = SensorTCRT5000("B", config.PIN_B, config.REBOTE_MS)
        self.contador = ContadorPersonas(sensor_a, sensor_b, config)
        self.dht = SensorDHT11(config.PIN_DHT)
        self.scd = SensorSCD40(self.i2c, config.DIR_SCD40)
        self.pms = SensorPMS5003(config.UART_ID, config.PIN_PMS_TX, config.PIN_PMS_RX)
        # Mismo orden que el programa original: PMS5003, DHT11, SCD40.
        self.sensores_aire = [self.pms, self.dht, self.scd]
        self.pantalla = PantallaOLED(self.i2c, config)
        self.ultimo_reporte = ticks_ms()

    def imprimir_mediciones(self):
        temp, hum = self.dht.valores()
        pm1, pm25, pm10 = self.pms.valores()
        print("------------------------------")
        print("CO2:", self.scd.valor_co2(), "ppm")
        print("Temperatura:", temp, "C | Humedad:", hum, "%")
        print("PM1:", pm1, "PM2.5:", pm25, "PM10:", pm10)
        print("Dentro:", self.contador.personas,
              "Entradas:", self.contador.entradas,
              "Salidas:", self.contador.salidas,
              "Canceladas:", self.contador.cancelaciones)

    def ejecutar(self):
        print("SISTEMA INTEGRADO - CALIDAD DE AIRE + AFORO (Pico W)")
        print("A -> B = SALIDA | B -> A = ENTRADA")
        print("Pantallas: CO2 / PARTICULAS / PERSONAS")
        self.pantalla.mostrar_inicio()
        self.scd.iniciar()

        try:
            while True:
                # Primera prioridad: conteo y deteccion de retrocesos.
                evento = self.contador.actualizar()

                # Polimorfismo: cada sensor se actualiza a su manera.
                # Despues de cada uno se revisa de nuevo la puerta.
                for sensor in self.sensores_aire:
                    sensor.actualizar()
                    segundo_evento = self.contador.actualizar()
                    if segundo_evento is not None:
                        evento = segundo_evento

                # Evita mostrar un evento antiguo o bloquear el bucle
                # durante 1.5 segundos: solo cambia una marca de tiempo.
                self.pantalla.actualizar(self, evento)

                ahora = ticks_ms()
                if ticks_diff(ahora, self.ultimo_reporte) >= self.config.REPORTE_CONSOLA_MS:
                    self.ultimo_reporte = ahora
                    self.imprimir_mediciones()

                sleep_ms(5)

        except KeyboardInterrupt:
            print("Programa detenido desde Thonny")
            print("Ocupacion final:", self.contador.personas)
        finally:
            # Polimorfismo: solo el SCD40 hace algo al detenerse.
            for sensor in self.sensores_aire:
                sensor.detener()


# =============================================
# EJECUCION
# =============================================
if __name__ == "__main__":
    sistema = SistemaCalidadAire()
    sistema.ejecutar()
