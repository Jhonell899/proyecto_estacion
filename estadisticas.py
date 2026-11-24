"""Registro y estadisticas de la estacion (se ejecuta en la PC, junto a control_estacion.py).

- RegistroDatos guarda, cada 5 minutos (se puede cambiar), el promedio de las lecturas con
  fecha, hora, lugar y cantidad de estudiantes, en un archivo por dia: registros/AAAA-MM-DD.csv
  (separado por ";" y con coma decimal, para abrirlo directo en Excel).
- Estadistica lee esos archivos.
- PanelEstadistica muestra los graficos (ultima hora o todo el dia) y la tabla.

Solo usa la biblioteca estandar de Python (los graficos se dibujan con tkinter).
"""
import csv
import math
import os
import time
import tkinter as tk
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk

from componentes import BotonIcono, Icono, Panel, Pestanas, Referencias, Tema


def numero(valor, decimales=1):
    """Numero con coma decimal, como se escribe en espanol: 24.5 -> '24,5'."""
    if valor is None:
        return "--"
    texto = "{:.{}f}".format(valor, decimales)
    return texto.replace(".", ",")


# =====================================================================
# Variables que se analizan
# =====================================================================
class Variable:
    """Una medicion que se analiza: su clave, como se llama y su unidad."""

    def __init__(self, clave, nombre, unidad, columna, dato, decimales=1, tecnico=""):
        self.clave = clave          # nombre interno
        self.nombre = nombre        # nombre simple para mostrar
        self.unidad = unidad
        self.columna = columna      # columna en el archivo CSV
        self.dato = dato            # clave en los DATOS que envia la estacion
        self.decimales = decimales
        self.tecnico = tecnico      # nombre tecnico (PM2.5...), como referencia

    @property
    def etiqueta(self):
        """Nombre simple con el tecnico entre parentesis: "Humo (PM2.5)"."""
        return "{} ({})".format(self.nombre, self.tecnico) if self.tecnico else self.nombre


VARIABLES = [
    Variable("co2", "CO2", "ppm", "co2_ppm", "co2", 0),
    Variable("temp", "Temperatura", "°C", "temperatura_c", "temp", 1),
    Variable("hum", "Humedad", "%", "humedad_pct", "hum", 0),
    Variable("humo", "Humo", "µg/m³", "humo_pm25", "pm25", 1, "PM2.5"),
    Variable("humo_fino", "Humo muy fino", "µg/m³", "humo_fino_pm1", "pm1", 1, "PM1.0"),
    Variable("polvo", "Polvo", "µg/m³", "polvo_pm10", "pm10", 1, "PM10"),
]


# =====================================================================
# Grabacion
# =====================================================================
class RegistroDatos:
    """Junta las lecturas que llegan y guarda una fila por intervalo (1 min por defecto).

    Cada fila tiene el promedio de lo medido en ese intervalo. La cantidad de
    estudiantes es el promedio de las personas dentro, redondeado.
    """

    COLUMNAS = (["fecha", "hora", "dia", "lugar", "estudiantes"]
                + [v.columna for v in VARIABLES] + ["calidad"])
    DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")

    def __init__(self, carpeta, lugar="Laboratorio A", minutos=5, reloj=datetime.now):
        self.carpeta = Path(carpeta)
        self.lugar = lugar
        self.minutos = minutos
        self.activo = True
        self._reloj = reloj
        self._bloque = None
        self._reiniciar()
        self.filas_hoy = self._contar_filas(self._archivo(self._reloj()))

    # ---------- Archivos ----------
    def _archivo(self, momento):
        return self.carpeta / "{}.csv".format(momento.strftime("%Y-%m-%d"))

    def archivo_actual(self):
        return self._archivo(self._reloj())

    @staticmethod
    def _contar_filas(archivo):
        try:
            with open(archivo, encoding="utf-8-sig") as f:
                return max(0, sum(1 for _ in f) - 1)
        except OSError:
            return 0

    # ---------- Acumulacion ----------
    def _reiniciar(self):
        self._sumas = {v.clave: 0.0 for v in VARIABLES}
        self._cuentas = {v.clave: 0 for v in VARIABLES}
        self._suma_estudiantes = 0
        self._cuenta_estudiantes = 0
        self._calidad = ""

    def _inicio_bloque(self, momento):
        minuto = (momento.minute // self.minutos) * self.minutos
        return momento.replace(minute=minuto, second=0, microsecond=0)

    def agregar(self, datos):
        """Recibe los DATOS de la estacion (un diccionario) y los acumula."""
        if not self.activo:
            return
        ahora = self._reloj()
        bloque = self._inicio_bloque(ahora)
        if self._bloque is not None and bloque != self._bloque:
            self.guardar()
        self._bloque = bloque

        # Mientras el sensor de polvo y humo se calienta, sus valores no son confiables.
        omitir = ("pm1", "pm25", "pm10") if datos.get("calentando") else ()
        for variable in VARIABLES:
            valor = None if variable.dato in omitir else datos.get(variable.dato)
            if valor is not None:
                self._sumas[variable.clave] += valor
                self._cuentas[variable.clave] += 1
        personas = datos.get("personas") or {}
        if personas.get("dentro") is not None:
            self._suma_estudiantes += personas["dentro"]
            self._cuenta_estudiantes += 1
        if datos.get("estado"):
            self._calidad = datos["estado"]

    def guardar(self):
        """Escribe la fila del intervalo actual (si tiene lecturas) y empieza otro."""
        if self._bloque is None or (not self._cuenta_estudiantes and not any(self._cuentas.values())):
            self._reiniciar()
            return
        momento = self._bloque
        fila = [
            momento.strftime("%Y-%m-%d"),
            momento.strftime("%H:%M"),
            self.DIAS[momento.weekday()],
            self.lugar,
            round(self._suma_estudiantes / self._cuenta_estudiantes) if self._cuenta_estudiantes else "",
        ]
        for variable in VARIABLES:
            cuenta = self._cuentas[variable.clave]
            fila.append(numero(self._sumas[variable.clave] / cuenta, variable.decimales) if cuenta else "")
        fila.append(self._calidad)

        archivo = self._archivo(momento)
        nuevo = not archivo.exists()
        self.carpeta.mkdir(parents=True, exist_ok=True)
        with open(archivo, "a", newline="", encoding="utf-8-sig" if nuevo else "utf-8") as f:
            escritor = csv.writer(f, delimiter=";")
            if nuevo:
                escritor.writerow(self.COLUMNAS)
            escritor.writerow(fila)
        if archivo == self.archivo_actual():
            self.filas_hoy = self._contar_filas(archivo)
        self._reiniciar()

    def cerrar(self):
        """Guarda lo que quede pendiente (al desconectar o cerrar el programa)."""
        self.guardar()
        self._bloque = None


# =====================================================================
# Calculo
# =====================================================================
class Estadistica:
    """Lee los registros guardados y los filtra por dia y lugar."""

    def __init__(self, filas):
        self.filas = filas

    # ---------- Lectura ----------
    @staticmethod
    def _numero(texto):
        texto = (texto or "").strip()
        if not texto:
            return None
        try:
            return float(texto.replace(",", "."))
        except ValueError:
            return None

    @classmethod
    def leer_carpeta(cls, carpeta):
        """Todas las filas de todos los dias guardados."""
        filas = []
        for archivo in sorted(Path(carpeta).glob("*.csv")):
            try:
                with open(archivo, encoding="utf-8-sig", newline="") as f:
                    for crudo in csv.DictReader(f, delimiter=";"):
                        fila = cls._convertir(crudo)
                        if fila:
                            filas.append(fila)
            except OSError:
                continue
        return filas

    @classmethod
    def _convertir(cls, crudo):
        try:
            momento = datetime.strptime(crudo["fecha"] + " " + crudo["hora"], "%Y-%m-%d %H:%M")
        except (KeyError, TypeError, ValueError):
            return None
        estudiantes = cls._numero(crudo.get("estudiantes"))
        fila = {
            "momento": momento,
            "fecha": crudo["fecha"],
            "lugar": crudo.get("lugar", ""),
            "estudiantes": None if estudiantes is None else int(estudiantes),
            "calidad": crudo.get("calidad", ""),
        }
        for variable in VARIABLES:
            fila[variable.clave] = cls._numero(crudo.get(variable.columna))
        return fila

    def filtrar(self, fecha=None, lugar=None):
        return Estadistica([f for f in self.filas
                            if (fecha is None or f["fecha"] == fecha)
                            and (lugar is None or f["lugar"] == lugar)])

    def fechas(self):
        return sorted({f["fecha"] for f in self.filas}, reverse=True)

    def lugares(self):
        return sorted({f["lugar"] for f in self.filas if f["lugar"]})

    def serie_tiempo(self, clave):
        filas = sorted(self.filas, key=lambda f: f["momento"])
        return [f["momento"] for f in filas], [f[clave] for f in filas]


# =====================================================================
# Grafico
# =====================================================================
class GraficoLinea(tk.Canvas):
    """Grafico de linea, dibujado con tkinter. Una sola serie y un solo eje.

    Al pasar el mouse muestra una linea vertical y el valor del punto mas cercano.
    eje_x: "numero" (por ejemplo estudiantes) o "tiempo" (valores datetime).
    relleno: pinta suave el area bajo la linea. icono: icono junto al titulo.
    """

    SUPERFICIE = Tema.TARJETA
    GRILLA = "#2c2f34"
    EJE = Tema.BORDE
    TEXTO = Tema.TEXTO
    TEXTO_SUAVE = Tema.TEXTO_SUAVE
    TEXTO_EJE = "#9a9da3"
    SERIE = Tema.TEXTO
    RELLENO = "#232427"
    IZQ, DER, ARRIBA, ABAJO = 44, 8, 40, 26
    MAX_MARCADORES = 40

    def __init__(self, padre, titulo, unidad, ancho=300, alto=190, eje_x="numero", nombre_x="",
                 titulo_y="", relleno=False, icono=None, mostrar_unidad=True):
        super().__init__(padre, width=ancho, height=alto, bg=self.SUPERFICIE, highlightthickness=0, bd=0)
        self.titulo = titulo
        self.unidad = unidad
        self.eje_x = eje_x
        self.nombre_x = nombre_x
        self.titulo_y = titulo_y
        self.relleno = relleno
        self.icono = icono
        self.mostrar_unidad = mostrar_unidad
        self.decimales = 1
        self._ancho, self._alto = ancho, alto
        self._puntos = []
        self.bind("<Motion>", self._mover)
        self.bind("<Leave>", lambda e: self.delete("hover"))

    # ---------- Escalas ----------
    @staticmethod
    def marcas(minimo, maximo, cantidad=4):
        """Valores "redondos" para las lineas de la grilla."""
        if maximo == minimo:
            maximo = minimo + 1
        bruto = (maximo - minimo) / cantidad
        exponente = 10 ** math.floor(math.log10(bruto))
        paso = exponente
        for m in (1, 2, 2.5, 5, 10):
            paso = m * exponente
            if paso >= bruto:
                break
        inicio = math.floor(minimo / paso) * paso
        fin = math.ceil(maximo / paso) * paso
        valores, v = [], inicio
        while v <= fin + paso / 1000:
            valores.append(round(v, 10))
            v += paso
        return valores

    @staticmethod
    def marcas_tiempo(inicio, fin, cantidad=6):
        """Horas "redondas" (cada 5, 10, 15, 30 min, 1 h...) entre dos datetime."""
        total_min = max(1, (fin - inicio).total_seconds() / 60)
        for paso in (5, 10, 15, 30, 60, 120, 180, 240, 360, 720, 1440, 2880, 10080):
            if total_min / paso <= cantidad:
                break
        base = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
        primero = math.ceil((inicio - base).total_seconds() / 60 / paso) * paso
        marcas, m = [], primero
        while True:
            momento = datetime.fromtimestamp(base.timestamp() + m * 60)
            if momento > fin:
                break
            marcas.append(momento)
            m += paso
        return marcas

    def _izq(self):
        return self.IZQ + (16 if self.titulo_y else 0)

    def _der(self):
        return self._ancho - self.DER

    def _abajo(self):
        """Margen inferior: mas alto si hay que escribir el nombre del eje X."""
        return self.ABAJO + (16 if self.nombre_x else 0)

    def _valor_x(self, x):
        return x.timestamp() if self.eje_x == "tiempo" else x

    def _texto_x(self, x, varios_dias=False):
        if self.eje_x == "tiempo":
            return x.strftime("%d/%m %H:%M" if varios_dias else "%H:%M")
        return "{:g}".format(x)

    # ---------- Piezas comunes ----------
    def _titulo(self):
        x = 2
        self.create_text(x, 8, anchor="nw", fill=self.TEXTO, font=Tema.fuente(10), text=self.titulo.upper())

    def _sin_datos(self):
        self.create_text(self._ancho / 2, self._alto / 2, fill=self.TEXTO_EJE,
                         font=Tema.fuente(9), text="SIN DATOS TODAVÍA")

    def _ejes(self, x0, x1, marcas_y, primero=None, ultimo=None, valores_x=()):
        """Dibuja grilla, valores de los ejes y sus titulos. Devuelve las funciones px, py."""
        izq, der = self._izq(), self._der()
        arriba, abajo = self.ARRIBA, self._alto - self._abajo()
        y0, y1 = marcas_y[0], marcas_y[-1]
        if y0 == y1:
            y1 = y0 + 1

        def px(v):
            return izq + (v - x0) / (x1 - x0) * (der - izq)

        def py(v):
            return abajo - (v - y0) / (y1 - y0) * (abajo - arriba)

        for m in marcas_y:
            y = py(m)
            self.create_line(izq, y, der, y, fill=self.GRILLA)
            self.create_text(izq - 6, y, anchor="e", fill=self.TEXTO_EJE, font=Tema.fuente(9),
                             text=numero(m, 0 if float(m).is_integer() else 1))
        self.create_line(izq, abajo, der, abajo, fill=self.EJE)

        varios = False
        if self.eje_x == "tiempo" and primero is not None:
            varios = primero.date() != ultimo.date()
            for m in self.marcas_tiempo(primero, ultimo, 4 if varios else 6):
                self.create_text(px(m.timestamp()), abajo + 5, anchor="n", fill=self.TEXTO_EJE,
                                 font=Tema.fuente(9), text=self._texto_x(m, varios))
        elif valores_x:
            enteros = [int(v) for v in valores_x]
            rango = max(enteros) - min(enteros)
            paso = 1 if rango <= 8 else 2 if rango <= 16 else 5 if rango <= 40 else 10
            inicio = math.ceil(min(enteros) / paso) * paso
            for m in range(inicio, max(enteros) + 1, paso):
                self.create_text(px(m), abajo + 5, anchor="n", fill=self.TEXTO_EJE,
                                 font=Tema.fuente(8), text=str(m))
        if self.nombre_x:
            self.create_text((izq + der) / 2, abajo + 22, anchor="n", fill=self.TEXTO_SUAVE,
                             font=Tema.fuente(8), text=self.nombre_x)
        if self.titulo_y:
            self.create_text(12, (arriba + abajo) / 2, angle=90, fill=self.TEXTO_SUAVE,
                             font=Tema.fuente(8), text=self.titulo_y)
        return px, py, varios

    # ---------- Dibujo ----------
    def mostrar(self, xs, ys, decimales=1, notas=None):
        """xs, ys: listas de igual largo (los None se saltan). notas: texto extra por punto."""
        self.delete("all")
        self.decimales = decimales
        self._puntos = []
        self._titulo()
        datos = [(x, y, (notas[i] if notas else "")) for i, (x, y) in enumerate(zip(xs, ys))
                 if x is not None and y is not None]
        if not datos:
            self._sin_datos()
            return

        vx = [self._valor_x(x) for x, _, _ in datos]
        vy = [y for _, y, _ in datos]
        x0, x1 = min(vx), max(vx)
        if x0 == x1:
            x0, x1 = x0 - 1, x1 + 1
        px, py, varios = self._ejes(x0, x1, self.marcas(min(vy), max(vy)),
                                    datos[0][0], datos[-1][0], vx)

        coords = []
        for (x, y, nota), v in zip(datos, vx):
            coords += [px(v), py(y)]
            self._puntos.append((px(v), py(y), x, y, nota, varios))
        abajo = self._alto - self._abajo()
        if self.relleno and len(datos) > 1:
            self.create_polygon(coords[0], abajo, *coords, coords[-2], abajo, fill=self.RELLENO, outline="")
        if len(datos) > 1:
            self.create_line(*coords, fill=self.SERIE, width=2)
        if len(datos) <= self.MAX_MARCADORES:
            for cx, cy, *_ in self._puntos:
                self.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=self.SERIE,
                                 outline=self.SUPERFICIE, width=2)

    def _tooltip(self, cx, cy, texto):
        caja = self.create_text(0, 0, anchor="nw", text=texto, fill=self.TEXTO,
                                font=Tema.fuente(8), tags="hover")
        x1, y1, x2, y2 = self.bbox(caja)
        ancho, alto = x2 - x1 + 12, y2 - y1 + 8
        tx = cx + 10 if cx + 10 + ancho < self._ancho else cx - 10 - ancho
        ty = max(4, min(cy - alto - 8, self._alto - alto - 4))
        self.coords(caja, tx + 6, ty + 4)
        fondo = self.create_rectangle(tx, ty, tx + ancho, ty + alto, fill="white",
                                      outline=self.EJE, tags="hover")
        self.tag_raise(caja, fondo)

    def _mover(self, evento):
        """Tooltip: linea vertical y valor del punto mas cercano al mouse."""
        self.delete("hover")
        if not self._puntos:
            return
        cx, cy, x, y, nota, varios = min(self._puntos, key=lambda p: abs(p[0] - evento.x))
        self.create_line(cx, self.ARRIBA, cx, self._alto - self._abajo(), fill=self.EJE, tags="hover")
        self.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=self.SERIE, outline=self.SUPERFICIE,
                         width=2, tags="hover")
        etiqueta = self._texto_x(x, varios)
        if self.eje_x != "tiempo" and self.nombre_x:
            etiqueta += " " + self.nombre_x.lower()
        texto = "{}: {} {}".format(etiqueta, numero(y, self.decimales), self.unidad)
        if nota:
            texto += "\n" + nota
        self._tooltip(cx, cy, texto)


class GraficoTiempo(GraficoLinea):
    """Una o varias mediciones de la misma unidad a lo largo del tiempo.

    Arriba a la derecha, una tabla con el promedio y el ultimo valor de cada una.
    Al pasar el mouse: linea vertical, un punto en cada serie y un recuadro con
    la fecha, la hora y el valor de cada medicion.
    """

    # Orden fijo de colores (paleta validada para daltonismo en graficos de lineas).
    COLORES = (Tema.TEXTO, Tema.ACENTO, "#7d8087", Tema.AMBAR)
    MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
    ALTO_FILA = 20
    COL_PROMEDIO, COL_ULTIMO = 112, 0          # distancia desde el borde derecho

    def __init__(self, padre, titulo, unidad, ancho=470, alto=270, **opciones):
        super().__init__(padre, titulo, unidad, ancho, alto, eje_x="tiempo", **opciones)
        self._series = []
        self.ARRIBA = 34

    @classmethod
    def fecha_hora(cls, momento, segundos=True):
        """20 nov 2026 15:19:44"""
        return "{} {} {} {}".format(momento.day, cls.MESES[momento.month - 1], momento.year,
                                    momento.strftime("%H:%M:%S" if segundos else "%H:%M"))

    def mostrar_series(self, series, segundos=True, referencias=(), clave=None):
        """series: lista de (nombre, momentos, valores, decimales). Todas en la unidad del grafico.
        referencias: lineas de limite [(valor, texto, "max" o "min")] (lo que se supone que deberia haber)."""
        self._series = [(n, [(m, v) for m, v in zip(ms, vs) if v is not None], d) for n, ms, vs, d in series]
        self._segundos = segundos
        self.referencias = list(referencias)
        self.clave = clave          # si se da, la linea se pinta con el color de cada nivel
        self._dibujar()

    def _color(self, i):
        return self.COLORES[i % len(self.COLORES)]

    def _dibujar(self):
        self.delete("all")
        self._puntos = []
        self.ARRIBA = 34 + self.ALTO_FILA * len(self._series)
        self._titulo()
        self._tabla_resumen()
        momentos = sorted(m for _, puntos, _ in self._series for m, _ in puntos)
        if not momentos:
            self._sin_datos()
            return
        x0, x1 = momentos[0].timestamp(), momentos[-1].timestamp()
        if x0 == x1:
            x0, x1 = x0 - 60, x1 + 60
        valores = [v for _, puntos, _ in self._series for _, v in puntos]
        limites = [r[0] for r in getattr(self, "referencias", [])]
        self._px, self._py, self._varios = self._ejes(
            x0, x1, self.marcas(min([0] + valores), max(valores + limites)), momentos[0], momentos[-1])
        # Lineas de limite: lo recomendado. Lo que queda del lado malo se marca en naranja.
        izq, der = self._izq(), self._der()
        for valor, texto, _tipo in getattr(self, "referencias", []):
            y = self._py(valor)
            self.create_line(izq, y, der, y, fill="#8a3a28", dash=(5, 4), width=1.2)
            self.create_text(izq + 4, y - 2, anchor="sw", text=texto, fill=Tema.ACENTO, font=Tema.fuente(8))
        # Cada serie es una linea continua; el ultimo valor lleva un punto.
        for i, (_, puntos, _) in enumerate(self._series):
            coords = [(self._px(m.timestamp()), self._py(v)) for m, v in puntos]
            if getattr(self, "clave", None) and len(self._series) == 1:
                self._colorear_niveles(puntos, coords)
            elif len(coords) > 1:
                self.create_line(*[c for p in coords for c in p], fill=self._color(i), width=2.2)
            if coords:
                cx, cy = coords[-1]
                self.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=self._color(i), outline=self.SUPERFICIE,
                                 width=2)
        self._puntos = momentos

    def _colorear_niveles(self, puntos, coords):
        """Cada tramo de la linea con el color de su nivel: verde, amarillo, naranja o rojo."""
        tramo, color_tramo = [], None
        for (_, valor), punto in zip(puntos, coords):
            color = Referencias.color(self.clave, valor)
            if color != color_tramo and tramo:
                tramo.append(punto)            # une con el tramo siguiente
                if len(tramo) > 1:
                    self.create_line(*[c for p in tramo for c in p], fill=color_tramo, width=2.4)
                tramo = []
            tramo.append(punto)
            color_tramo = color
        if len(tramo) > 1:
            self.create_line(*[c for p in tramo for c in p], fill=color_tramo, width=2.4)

    def _tabla_resumen(self):
        """Promedio y ultimo valor de cada serie, como en los paneles de monitoreo."""
        der = self._ancho - 4
        fuente = Tema.fuente(8)
        self.create_text(der - self.COL_PROMEDIO, 24, anchor="se", fill=self.TEXTO_EJE, font=fuente, text="PROMEDIO")
        self.create_text(der - self.COL_ULTIMO, 24, anchor="se", fill=self.TEXTO_EJE, font=fuente, text="ÚLTIMO")
        for i, (nombre, puntos, decimales) in enumerate(self._series):
            y = 24 + self.ALTO_FILA * i + 10
            valores = [v for _, v in puntos]
            promedio = sum(valores) / len(valores) if valores else None
            ultimo = valores[-1] if valores else None
            if len(self._series) > 1:      # con una sola serie el titulo ya la nombra
                x = der - self.COL_PROMEDIO - 86
                self.create_oval(x - 14, y - 3, x - 8, y + 3, fill=self._color(i), outline="")
                self.create_text(x - 20, y, anchor="e", fill=self.TEXTO, font=Tema.fuente(9), text=nombre)
            for columna, valor in ((self.COL_PROMEDIO, promedio), (self.COL_ULTIMO, ultimo)):
                texto = "--" if valor is None else "{} {}".format(numero(valor, decimales), self.unidad)
                self.create_text(der - columna, y, anchor="e", fill=self.TEXTO,
                                 font=Tema.fuente(11, True), text=texto)

    def _mover(self, evento):
        """Recuadro con la fecha, la hora y el valor de cada serie en el punto mas cercano."""
        self.delete("hover")
        if not self._puntos or not self._izq() <= evento.x <= self._der():
            return
        objetivo = min(self._puntos, key=lambda m: abs(self._px(m.timestamp()) - evento.x))
        cx = self._px(objetivo.timestamp())
        self.create_line(cx, self.ARRIBA, cx, self._alto - self._abajo(), fill=self.EJE, tags="hover")
        filas = []
        for i, (nombre, puntos, decimales) in enumerate(self._series):
            if not puntos:
                continue
            m, v = min(puntos, key=lambda p: abs((p[0] - objetivo).total_seconds()))
            cy = self._py(v)
            self.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, outline=self._color(i), fill=self.SUPERFICIE,
                             width=2, tags="hover")
            filas.append((self._color(i), nombre, "{} {}".format(numero(v, decimales), self.unidad)))
        self._recuadro(cx, evento.y, self.fecha_hora(objetivo, self._segundos), filas)

    def _recuadro(self, cx, cy, encabezado, filas):
        fuente = Tema.fuente(9)
        ancho = max([self._medir(encabezado, fuente)]
                    + [self._medir(n, fuente) + self._medir(t, fuente) + 46 for _, n, t in filas]) + 16
        alto = 26 + 19 * len(filas)
        tx = cx + 12 if cx + 12 + ancho < self._ancho else cx - 12 - ancho
        ty = max(4, min(cy - alto / 2, self._alto - alto - 4))
        self.create_rectangle(tx, ty, tx + ancho, ty + alto, fill=Tema.CAMPO, outline=Tema.BORDE, tags="hover")
        self.create_text(tx + 8, ty + 6, anchor="nw", fill=self.TEXTO_SUAVE, font=fuente, text=encabezado,
                         tags="hover")
        for j, (color, nombre, texto) in enumerate(filas):
            y = ty + 33 + 19 * j
            self.create_oval(tx + 9, y - 3, tx + 15, y + 3, fill=color, outline="", tags="hover")
            self.create_text(tx + 26, y, anchor="w", fill=self.TEXTO_SUAVE, font=fuente, text=nombre, tags="hover")
            self.create_text(tx + ancho - 8, y, anchor="e", fill=self.TEXTO, font=Tema.fuente(9, True),
                             text=texto, tags="hover")

    def _medir(self, texto, fuente):
        prueba = self.create_text(-1000, -1000, text=texto, font=fuente)
        x1, _, x2, _ = self.bbox(prueba)
        self.delete(prueba)
        return x2 - x1


# =====================================================================
# Panel de la ventana principal
# =====================================================================
class PanelEstadistica(Panel):
    """Panel "Historial" de la ventana principal.

    Graficos: particulas, CO2, alumnos en el aula y temperatura, de la ultima hora
    (cada lectura que llega, con segundos) o de todo el dia (lo grabado cada 5 min).
    Tabla de datos: lo grabado hoy.
    lugar: funcion que devuelve el lugar que se esta grabando (para filtrar).
    exportar: funcion del boton "Exportar a Excel" (opcional).
    """

    ULTIMA_HORA, HOY = "hora", "hoy"
    VENTANA_S = 3600
    REDIBUJO_S = 2
    # (titulo, unidad, icono, [(nombre, clave en DATOS, clave en el registro, decimales)])
    GRAFICOS = (
        ("Partículas", "µg/m³", "particulas", [("Humo muy fino (PM1.0)", "pm1", "humo_fino", 0),
                                               ("Humo (PM2.5)", "pm25", "humo", 0),
                                               ("Polvo (PM10)", "pm10", "polvo", 0)]),
        ("CO2", "ppm", "nube", [("CO2", "co2", "co2", 0)]),
        ("Alumnos en el aula", "alumnos", "personas", [("Alumnos", "dentro", "estudiantes", 0)]),
        ("Temperatura", "°C", "termometro", [("Temperatura", "temp", "temp", 1)]),
    )

    def __init__(self, padre, carpeta, lugar, exportar=None):
        super().__init__(padre, "Historial", numero=9)
        self.carpeta = Path(carpeta)
        self._lugar = lugar
        self._exportar = exportar
        self.datos = Estadistica([])
        self.lecturas = deque()          # (momento, {clave: valor}) de la ultima hora
        self._ultimo_dibujo = 0
        self.rango = tk.StringVar(value=self.ULTIMA_HORA)
        self.pestanas = Pestanas(self.cuerpo)
        self.pestanas.pack(fill="both", expand=True, pady=(4, 0))
        self._crear_graficos(self.pestanas.agregar("Gráficos", "barras"))
        self._crear_tabla(self.pestanas.agregar("Tabla de datos", "tabla"))
        self._crear_selector()
        self.pestanas.fijar_tamano()

    # ---------- Construccion ----------
    @staticmethod
    def _tabla(padre, columnas, alto, anchos):
        tabla = ttk.Treeview(padre, columns=[c for c, _ in columnas], show="headings", height=alto)
        for (clave, titulo), ancho in zip(columnas, anchos):
            tabla.heading(clave, text=titulo, anchor="w" if clave == "hora" else "e")
            tabla.column(clave, width=ancho, minwidth=ancho, anchor="w" if clave == "hora" else "e", stretch=True)
        return tabla

    def _crear_selector(self):
        """"Ultima hora" / "Hoy", a la derecha de las pestanas."""
        marco = tk.Frame(self.cabecera_derecha, bg=Tema.TARJETA)
        marco.pack(side="right")
        for texto, valor in (("ÚLTIMA HORA", self.ULTIMA_HORA), ("HOY", self.HOY)):
            tk.Radiobutton(marco, text=texto, value=valor, variable=self.rango, indicatoron=False,
                           command=self.dibujar_graficos, font=Tema.fuente(9), padx=10, pady=3,
                           bd=0, relief="flat", bg=Tema.TARJETA, fg=Tema.TEXTO_SUAVE, selectcolor=Tema.CAMPO,
                           activebackground=Tema.CAMPO_HOVER, activeforeground=Tema.TEXTO,
                           offrelief="flat", cursor="hand2").pack(side="left", padx=(4, 0))
        self._marcar_selector(marco)
        self.rango.trace_add("write", lambda *a: self._marcar_selector(marco))

    def _marcar_selector(self, marco):
        """Texto blanco en la opcion elegida (el fondo azul lo pone selectcolor)."""
        for boton in marco.winfo_children():
            if isinstance(boton, tk.Radiobutton):
                elegido = boton.cget("value") == self.rango.get()
                boton.config(fg=Tema.ACENTO if elegido else Tema.TEXTO_SUAVE)

    def _crear_graficos(self, pagina):
        self.graficos = []
        for i, (titulo, unidad, icono, _series) in enumerate(self.GRAFICOS):
            grafico = GraficoTiempo(pagina, titulo, unidad, ancho=560, alto=222)
            grafico.grid(row=i // 2, column=i % 2, padx=(0 if i % 2 == 0 else 24, 0),
                         pady=(0 if i < 2 else 14, 0))
            self.graficos.append(grafico)

    # Columnas de la tabla: primero las basicas; "Ver detalle" agrega las demas.
    TABLA_BASICA = ("hora", "alumnos", "co2", "humo", "polvo", "calidad")
    TABLA_DETALLE = ("temp", "hum", "humo_fino")

    def _crear_tabla(self, pagina):
        nombres = {v.clave: "{} ({})".format(v.nombre, v.unidad) for v in VARIABLES}
        nombres.update(hora="Hora", alumnos="Alumnos", calidad="Calidad")
        claves = self.TABLA_BASICA + self.TABLA_DETALLE
        anchos = {"hora": 70, "alumnos": 80, "calidad": 110}
        botones = tk.Frame(pagina, bg=Tema.TARJETA)
        botones.pack(fill="x", pady=(0, 8))
        self.boton_detalle = BotonIcono(botones, "Ver detalle", "lista", self.alternar_detalle)
        self.boton_detalle.pack(side="left")
        if self._exportar:
            BotonIcono(botones, "Exportar a Excel (opcional)", "tabla", self._exportar).pack(side="left", padx=8)
        marco = tk.Frame(pagina, bg=Tema.TARJETA)
        marco.pack(fill="both", expand=True)
        self.tabla_datos = self._tabla(marco, [(c, nombres[c]) for c in claves], 13,
                                       [anchos.get(c, 100) for c in claves])
        self.detalle = False
        self.tabla_datos.configure(displaycolumns=self.TABLA_BASICA)
        for indice, color in enumerate(Tema.COLOR_NIVEL):
            self.tabla_datos.tag_configure("nivel{}".format(indice), foreground=color)
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.tabla_datos.yview)
        self.tabla_datos.configure(yscrollcommand=barra.set)
        self.tabla_datos.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

    # ---------- Datos ----------
    def agregar_lectura(self, datos, momento=None):
        """Guarda en memoria cada lectura que llega (para "Ultima hora")."""
        momento = momento or datetime.now()
        personas = datos.get("personas") or {}
        lectura = {clave: datos.get(clave) for clave in ("co2", "temp", "hum", "pm1", "pm25", "pm10")}
        if datos.get("calentando"):
            lectura.update(pm1=None, pm25=None, pm10=None)
        lectura["dentro"] = personas.get("dentro")
        self.lecturas.append((momento, lectura))
        while self.lecturas and (momento - self.lecturas[0][0]).total_seconds() > self.VENTANA_S:
            self.lecturas.popleft()
        if self.rango.get() == self.ULTIMA_HORA and time.time() - self._ultimo_dibujo >= self.REDIBUJO_S:
            self.dibujar_graficos()

    def dibujar_graficos(self):
        self._ultimo_dibujo = time.time()
        en_vivo = self.rango.get() == self.ULTIMA_HORA
        for grafico, (_titulo, _unidad, _icono, series) in zip(self.graficos, self.GRAFICOS):
            datos = []
            for nombre, clave_vivo, clave_registro, decimales in series:
                if en_vivo:
                    momentos = [m for m, _ in self.lecturas]
                    valores = [l.get(clave_vivo) for _, l in self.lecturas]
                else:
                    momentos, valores = self.datos.serie_tiempo(clave_registro)
                datos.append((nombre, momentos, valores, decimales))
            claves = [c for _n, c, _r, _d in series if c != "pm1"]       # el humo fino usa el limite del humo
            grafico.mostrar_series(datos, segundos=en_vivo, referencias=Referencias.lineas(claves),
                                   clave=claves[0] if len(series) == 1 else None)

    def actualizar(self):
        """Vuelve a leer los registros de hoy del lugar actual y redibuja todo."""
        hoy = datetime.now().strftime("%Y-%m-%d")
        self.datos = Estadistica(Estadistica.leer_carpeta(self.carpeta)).filtrar(hoy, self._lugar())
        self.dibujar_graficos()
        filas = sorted(self.datos.filas, key=lambda f: f["momento"])
        por_clave = {v.clave: v for v in VARIABLES}
        self.tabla_datos.delete(*self.tabla_datos.get_children())
        for fila in reversed(filas):
            valores = {"hora": fila["momento"].strftime("%H:%M"),
                       "alumnos": "--" if fila["estudiantes"] is None else fila["estudiantes"],
                       "calidad": fila.get("calidad", "")}
            for clave, v in por_clave.items():
                valores[clave] = numero(fila[clave], v.decimales)
            indice = Tema.indice(valores["calidad"])
            valores["calidad"] = Tema.nombre(valores["calidad"])
            self.tabla_datos.insert("", "end", values=[valores[c] for c in self.TABLA_BASICA + self.TABLA_DETALLE],
                                    tags=("nivel{}".format(indice),) if indice is not None else ())

    def alternar_detalle(self):
        """Muestra u oculta las columnas de detalle (temperatura, humedad, humo muy fino)."""
        self.detalle = not self.detalle
        self.tabla_datos.configure(displaycolumns=self.TABLA_BASICA + (self.TABLA_DETALLE if self.detalle else ()))
        self.boton_detalle.config(text="Ver menos" if self.detalle else "Ver detalle")
