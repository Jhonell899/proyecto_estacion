from Contador import Contador


class Comunicador:
    """Califica el aire y lo muestra en la OLED SSD1306 (128x64, I2C 0x3C) y en la consola.

    La pantalla rota entre 5 paginas cada 5 s:
      0. CO2, temperatura y humedad
      1. Polvo y humo: su nivel y que hacer; el titulo avisa si hay alerta
      2. Estado del aire (general, por CO2 y por humo)
      3. PERSONAS: dentro, entraron y salieron
      4. VS IDEAL: progreso de la medicion o diferencia con el ambiente ideal
    Los primeros 16 pixeles de arriba (franja amarilla en las OLED bicolor)
    se usan para el titulo de cada pagina.
    """

    NIVELES = ("BUENO", "MODERADO", "MALO", "MUY MALO")

    # Limite superior de cada nivel; por encima del ultimo es "MUY MALO".
    LIMITES_PM25 = (12, 35.4, 55.4)     # ug/m3, cortes del indice de la EPA
    LIMITES_PM10 = (54, 154, 254)       # ug/m3, cortes del indice de la EPA
    LIMITES_CO2 = (799, 1199, 1999)     # ppm, referencia para interiores
    # El PM1.0 no tiene limites oficiales: se califica con los del PM2.5.

    # Alertas de particulas: aparecen cuando un PM llega a MALO o peor.
    #   PM2.5 / PM1.0 (particulas finas)  -> humo o contaminacion
    #   PM10 (particulas gruesas)         -> polvo
    NIVEL_ALERTA = 2
    TITULOS_ALERTA = {"HUMO": "ALERTA: HUMO", "POLVO": "ALERTA: POLVO", "HUMO_POLVO": "HUMO Y POLVO!"}
    # Que hacer, en pocas palabras (maximo 16 letras para la OLED).
    CONSEJOS = {None: "Sin alertas", "HUMO": "Cierra ventanas", "POLVO": "Ventila el aula",
                "HUMO_POLVO": "Revisa el origen"}

    # En pantalla se usan nombres simples en vez de PM1.0, PM2.5 y PM10:
    #   PM10 -> POLVO     PM2.5 y PM1.0 -> HUMO (se muestra el peor de los dos)

    CAMBIO_PAGINA_MS = 5000
    ANCHO = 128

    def __init__(self, i2c, ancho=128, alto=64, direccion=0x3C):
        self.oled = None
        try:
            import ssd1306
            self.oled = ssd1306.SSD1306_I2C(ancho, alto, i2c, addr=direccion)
        except ImportError:
            print("Falta ssd1306.py en la placa (mpremote mip install ssd1306)")
        except OSError as error:
            print("OLED no disponible, se continua solo con consola:", error)

        self.pagina = 0
        self._cambio = Contador(self.CAMBIO_PAGINA_MS)

    # ---------- Calificacion del aire ----------
    @staticmethod
    def _nivel(valor, limites):
        """Devuelve 0-3 segun en que tramo cae el valor, o None si no hay dato."""
        if valor is None:
            return None
        for nivel, limite in enumerate(limites):
            if valor <= limite:
                return nivel
        return len(limites)

    def _nombre(self, nivel):
        return "--" if nivel is None else self.NIVELES[nivel]

    def nivel_co2(self, co2):
        return self._nivel(co2, self.LIMITES_CO2)

    def nivel_pm25(self, pm25):
        return self._nivel(pm25, self.LIMITES_PM25)

    def nivel_pm1(self, pm1):
        return self._nivel(pm1, self.LIMITES_PM25)

    def nivel_pm10(self, pm10):
        return self._nivel(pm10, self.LIMITES_PM10)

    def nivel_humo(self, pm1, pm25):
        """Nivel de "humo" para mostrar: el peor entre PM1.0 y PM2.5 (particulas finas)."""
        niveles = [n for n in (self.nivel_pm1(pm1), self.nivel_pm25(pm25)) if n is not None]
        return max(niveles) if niveles else None

    def calidad_aire(self, pm25, co2, pm10=None):
        """Devuelve el peor nivel entre PM2.5, PM10 y CO2, o '---' si aun no hay datos."""
        niveles = [n for n in (self.nivel_pm25(pm25), self.nivel_pm10(pm10), self.nivel_co2(co2))
                   if n is not None]
        if not niveles:
            return "---"
        return self.NIVELES[max(niveles)]

    def alerta_particulas(self, pm1, pm25, pm10):
        """Devuelve "HUMO", "POLVO", "HUMO_POLVO" o None segun que particulas estan altas."""
        finas = [n for n in (self.nivel_pm1(pm1), self.nivel_pm25(pm25)) if n is not None]
        humo = bool(finas) and max(finas) >= self.NIVEL_ALERTA
        n_pm10 = self.nivel_pm10(pm10)
        polvo = n_pm10 is not None and n_pm10 >= self.NIVEL_ALERTA
        if humo and polvo:
            return "HUMO_POLVO"
        if humo:
            return "HUMO"
        if polvo:
            return "POLVO"
        return None

    @staticmethod
    def _validar_limites(limites, nombre):
        if limites is None:
            return None
        if len(limites) != 3:
            raise ValueError("Se necesitan 3 limites de " + nombre)
        valores = tuple(float(v) for v in limites)
        if not 0 < valores[0] < valores[1] < valores[2]:
            raise ValueError("Los limites de " + nombre + " deben ir de menor a mayor")
        return valores

    def cambiar_limites(self, co2=None, pm25=None):
        """Cambia los limites de la calificacion. Lanza ValueError si no son validos."""
        co2 = self._validar_limites(co2, "CO2")
        pm25 = self._validar_limites(pm25, "humo")
        if co2:
            self.LIMITES_CO2 = co2
        if pm25:
            self.LIMITES_PM25 = pm25

    # ---------- Armado del contenido ----------
    @staticmethod
    def _fmt(valor, formato):
        return "--" if valor is None else formato.format(valor)

    @staticmethod
    def _temp_hum(gas, dht):
        """Usa el SCD40 (mas preciso); si no tiene dato, recurre al DHT11."""
        if gas.temperatura is not None or dht is None:
            return gas.temperatura, gas.humedad
        return dht.temperatura, dht.humedad

    def _estado(self, gas, ambiental):
        if ambiental.calentando():
            return "CALENTANDO"
        return self.calidad_aire(ambiental.pm25, gas.co2, ambiental.pm10)

    def _alerta(self, ambiental):
        """Alerta de particulas, salvo mientras el PMS5003 se calienta."""
        if ambiental.calentando():
            return None
        return self.alerta_particulas(ambiental.pm1, ambiental.pm25, ambiental.pm10)

    def resumen(self, gas, ambiental, dht=None):
        """Diccionario con las lecturas y la calificacion, para enviar a la PC."""
        temperatura, humedad = self._temp_hum(gas, dht)
        return {
            "co2": gas.co2,
            "temp": None if temperatura is None else round(temperatura, 1),
            "hum": None if humedad is None else round(humedad),
            "pm1": ambiental.pm1,
            "pm25": ambiental.pm25,
            "pm10": ambiental.pm10,
            "estado": self._estado(gas, ambiental),
            "n_co2": self.nivel_co2(gas.co2),
            "n_pm25": self.nivel_pm25(ambiental.pm25),
            "n_pm1": self.nivel_pm1(ambiental.pm1),
            "n_pm10": self.nivel_pm10(ambiental.pm10),
            "alerta_pm": self._alerta(ambiental),
            "calentando": ambiental.calentando(),
            "pms_dormido": ambiental.dormido,
            "lim_co2": list(self.LIMITES_CO2),
            "lim_pm25": list(self.LIMITES_PM25),
        }

    @staticmethod
    def _diferencia(actual, ideal, formato):
        """Texto de cuanto se aleja la lectura actual del ideal, por ejemplo '+120'."""
        if actual is None or ideal is None:
            return "--"
        return formato.format(actual - ideal)

    def _pagina_ideal(self, gas, ambiental, temperatura, humedad, ideal):
        """Pagina 4: progreso de la medicion o comparacion con el ambiente ideal."""
        if ideal.estado == ideal.PROBANDO:
            lineas = ["Probando", "sensores...", ""]
        elif ideal.estado == ideal.MIDIENDO:
            porcentaje, restante_s = ideal.progreso()
            lineas = ["Midiendo {}%".format(porcentaje),
                      "Faltan {} min".format((restante_s + 59) // 60), "No ventilar"]
        elif ideal.estado == ideal.FALLO:
            lineas = ["Fallo la prueba", "Revisa sensores", "y la PC"]
        elif ideal.ideal is None:
            lineas = ["Sin medir", "Inicialo desde", "la PC"]
        else:
            lineas = [
                "CO2:" + self._diferencia(gas.co2, ideal.valor("co2"), "{:+.0f} ppm"),
                "HUMO:" + self._diferencia(ambiental.pm25, ideal.valor("pm25"), "{:+.0f}"),
                "T:" + self._diferencia(temperatura, ideal.valor("temp"), "{:+.1f}")
                + " H:" + self._diferencia(humedad, ideal.valor("hum"), "{:+.0f}"),
            ]
        return ("VS IDEAL", lineas)

    def _pagina_particulas(self, ambiental):
        """Pagina de polvo y humo como alertas: el nivel en vez del numero, con
        nombres simples, y que hacer. Si hay humo o polvo, el titulo lo avisa."""
        if ambiental.calentando():
            return ("POLVO Y HUMO", ["Calentando", "el sensor...", "(30 s)"])
        alerta = self._alerta(ambiental)
        titulo = self.TITULOS_ALERTA[alerta] if alerta else "POLVO Y HUMO"
        sin_datos = ambiental.pm25 is None and ambiental.pm10 is None
        return (titulo, [
            "POLVO: " + self._nombre(self.nivel_pm10(ambiental.pm10)),
            "HUMO: " + self._nombre(self.nivel_humo(ambiental.pm1, ambiental.pm25)),
            "" if sin_datos else self.CONSEJOS[alerta],
        ])

    def _linea_consola(self, gas, ambiental, dht):
        """Una linea con todos los numeros, para Thonny."""
        temperatura, humedad = self._temp_hum(gas, dht)
        alerta = self._alerta(ambiental)
        partes = [
            "CO2: " + self._fmt(gas.co2, "{} ppm"),
            "TEMP: " + self._fmt(temperatura, "{:.1f} C"),
            "HUM: " + self._fmt(humedad, "{:.0f} %"),
            "PM1.0: " + self._fmt(ambiental.pm1, "{} ug/m3"),
            "PM2.5: " + self._fmt(ambiental.pm25, "{} ug/m3"),
            "PM10: " + self._fmt(ambiental.pm10, "{} ug/m3"),
            "AIRE: " + self._estado(gas, ambiental),
        ]
        if alerta:
            partes.append(self.TITULOS_ALERTA[alerta])
        return " | ".join(partes)

    @staticmethod
    def _pagina_personas(personas):
        """Pagina de la puerta: cuantas personas hay dentro, entraron y salieron."""
        return ("PERSONAS", [
            "DENTRO: {}".format(personas.dentro),
            "ENTRARON: {}".format(personas.entradas),
            "SALIERON: {}".format(personas.salidas),
        ])

    def _paginas(self, gas, ambiental, dht, ideal=None, personas=None):
        temperatura, humedad = self._temp_hum(gas, dht)
        estado = self._estado(gas, ambiental)

        paginas = [
            ("CALIDAD DE AIRE", [
                "CO2: " + self._fmt(gas.co2, "{} ppm"),
                "TEMP: " + self._fmt(temperatura, "{:.1f} C"),
                "HUM: " + self._fmt(humedad, "{:.0f} %"),
            ]),
            self._pagina_particulas(ambiental),
            ("ESTADO DEL AIRE", [
                "AIRE: " + estado,
                "CO2: " + self._nombre(self.nivel_co2(gas.co2)),
                "HUMO: " + self._nombre(self.nivel_humo(ambiental.pm1, ambiental.pm25)),
            ]),
        ]
        if personas is not None:
            paginas.append(self._pagina_personas(personas))
        if ideal is not None:
            paginas.append(self._pagina_ideal(gas, ambiental, temperatura, humedad, ideal))
        return paginas

    # ---------- Salida ----------
    def _dibujar(self, titulo, lineas):
        if not self.oled:
            return
        try:
            self.oled.fill(0)
            # Titulo centrado en la franja superior (cada letra mide 8 px).
            self.oled.text(titulo, max(0, (self.ANCHO - len(titulo) * 8) // 2), 3)
            for fila, texto in enumerate(lineas):
                self.oled.text(texto[:16], 0, 20 + fila * 15)
            self.oled.show()
        except OSError as error:
            # Un fallo de la pantalla no debe detener las mediciones.
            print("OLED: fallo al dibujar ({})".format(error))

    def mostrar(self, gas, ambiental, dht=None, ideal=None, personas=None):
        paginas = self._paginas(gas, ambiental, dht, ideal, personas)
        if self._cambio.listo():
            self.pagina += 1
        self.pagina %= len(paginas)

        # Consola: todas las lecturas (con numeros) en una sola linea.
        print(self._linea_consola(gas, ambiental, dht))
        self._dibujar(*paginas[self.pagina])
