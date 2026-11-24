"""Exporta los registros de la estacion a un libro de Excel (.xlsx), con formulas. Es opcional.

Diseno sencillo: cada hoja muestra primero lo basico. El detalle (temperatura, humedad,
humo muy fino, los otros niveles de calidad...) esta en columnas o filas agrupadas que se
despliegan con el boton "+" de Excel.

Hojas:
- Resumen: lugar, fechas y los numeros principales.
- Registros: cada registro grabado (fecha, hora, alumnos, mediciones y calidad), con filtros.
- Por alumnos: para cada cantidad de alumnos en el aula, el promedio de CO2, humo y polvo y
  el porcentaje del tiempo con aire BUENO. Con graficos.
- Por dia: un renglon por dia.

Todo lo calculado son formulas que leen la hoja Registros: si se corrige un dato ahi, Excel
recalcula el resto. Necesita openpyxl (pip install openpyxl).
"""
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import Reference, ScatterChart, Series
from openpyxl.chart.axis import ChartLines
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.line import LineProperties
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

from estadisticas import VARIABLES, RegistroDatos


class Columna:
    """Una columna de una hoja: titulo, que poner en cada fila, formato, ancho y si es detalle."""

    def __init__(self, titulo, valor, formato=None, ancho=12, detalle=False):
        self.titulo = titulo
        self.valor = valor          # funcion (fila de Excel, dato de esa fila) -> valor o formula
        self.formato = formato
        self.ancho = ancho
        self.detalle = detalle


class ExportadorExcel:
    """Arma el libro de Excel a partir de las filas que lee Estadistica."""

    FUENTE = "Arial"
    TEXTO = "1D2430"
    SUAVE = "6F7782"
    LINEA = "C9D1DC"
    NIVELES = ("BUENO", "MODERADO", "MALO", "MUY MALO")
    COLOR_NIVEL = {"BUENO": "2E7D32", "MODERADO": "B28704", "MALO": "E65100", "MUY MALO": "C62828"}
    POR_CLAVE = {v.clave: v for v in VARIABLES}

    def __init__(self, filas, lugar=""):
        self.filas = sorted(filas, key=lambda f: f["momento"])
        self.lugar = lugar
        self.libro = Workbook()
        self._ultima = len(self.filas) + 1          # ultima fila con datos en Registros
        self.col = {}                                # letra de cada dato en la hoja Registros

    # ---------- Utilidades ----------
    def _rango(self, clave):
        """Rango absoluto de una columna de Registros, por ejemplo Registros!$D$2:$D$74."""
        return "Registros!${0}$2:${0}${1}".format(self.col[clave], max(2, self._ultima))

    def _fuente(self, negrita=False, color=None, tamano=10, cursiva=False):
        return Font(name=self.FUENTE, bold=negrita, italic=cursiva, size=tamano, color=color or self.TEXTO)

    @staticmethod
    def _formato(variable):
        return "0" if variable.decimales == 0 else "0.0"

    def _hoja_tabla(self, hoja, columnas, datos):
        """Escribe una tabla sencilla: encabezado con una linea debajo, sin rellenos.
        Las columnas de detalle van al final, agrupadas y plegadas."""
        columnas = [c for c in columnas if not c.detalle] + [c for c in columnas if c.detalle]
        for i, columna in enumerate(columnas, start=1):
            celda = hoja.cell(row=1, column=i, value=columna.titulo)
            celda.font = self._fuente(True)
            celda.alignment = Alignment(horizontal="left" if i == 1 else "right", vertical="bottom", wrap_text=True)
            celda.border = Border(bottom=Side(style="medium", color=self.TEXTO))
            hoja.column_dimensions[get_column_letter(i)].width = columna.ancho
        hoja.row_dimensions[1].height = 30
        for n, dato in enumerate(datos, start=2):
            for i, columna in enumerate(columnas, start=1):
                celda = hoja.cell(row=n, column=i, value=columna.valor(n, dato))
                celda.font = self._fuente()
                celda.border = Border(bottom=Side(style="thin", color=self.LINEA))
                celda.alignment = Alignment(horizontal="left" if i == 1 else "right")
                if columna.formato:
                    celda.number_format = columna.formato
        basicas = sum(1 for c in columnas if not c.detalle)
        if basicas < len(columnas):
            primera, ultima = get_column_letter(basicas + 1), get_column_letter(len(columnas))
            hoja.column_dimensions.group(primera, ultima, hidden=True, outline_level=1)
            hoja.sheet_properties.outlinePr.summaryRight = False     # el "+" queda junto a lo basico
        hoja.freeze_panes = "B2"
        hoja.sheet_view.showGridLines = False
        return columnas

    def _color_calidad(self, hoja, rango):
        """La calidad se escribe con el color de su nivel (sin rellenar la celda)."""
        for nivel, color in self.COLOR_NIVEL.items():
            hoja.conditional_formatting.add(rango, CellIsRule(
                operator="equal", formula=['"{}"'.format(nivel)], font=Font(name=self.FUENTE, bold=True, color=color)))

    def _nota(self, hoja, fila, texto):
        hoja.cell(row=fila, column=1, value=texto).font = self._fuente(color=self.SUAVE, tamano=9, cursiva=True)

    @staticmethod
    def _estilo_grafico(grafico):
        """Grilla gris clara solo horizontal, lineas finas y sin bordes redondeados."""
        grilla = ChartLines()
        grilla.spPr = GraphicalProperties(ln=LineProperties(solidFill="E6E9EE"))
        grafico.y_axis.majorGridlines = grilla
        grafico.x_axis.majorGridlines = None
        for serie in grafico.series:
            serie.graphicalProperties.line.width = 19050      # 1,5 pt
            serie.smooth = False
        grafico.roundedCorners = False
        if grafico.legend is not None:
            grafico.legend.overlay = False
        for eje in (grafico.x_axis, grafico.y_axis):
            eje.delete = False
            if eje.title is not None:
                eje.title.overlay = False
        if grafico.title is not None:
            grafico.title.overlay = False

    # ---------- Hojas ----------
    def _hoja_registros(self):
        hoja = self.libro.create_sheet("Registros")
        var = self.POR_CLAVE

        def medida(clave, detalle=False):
            v = var[clave]
            return Columna("{} ({})".format(v.etiqueta, v.unidad), lambda n, f, c=clave: f[c],
                           self._formato(v), 14, detalle)

        columnas = [
            Columna("Fecha", lambda n, f: f["momento"].date(), "dd/mm/yyyy", 12),
            Columna("Hora", lambda n, f: f["momento"].time(), "hh:mm", 8),
            Columna("Alumnos", lambda n, f: f["estudiantes"], "0", 10),
            medida("co2"), medida("humo"), medida("polvo"),
            Columna("Calidad", lambda n, f: f.get("calidad") or None, None, 12),
            Columna("Día", lambda n, f: RegistroDatos.DIAS[f["momento"].weekday()], None, 11, True),
            Columna("Lugar", lambda n, f: f["lugar"], None, 26, True),
            medida("temp", True), medida("hum", True), medida("humo_fino", True),
        ]
        orden = self._hoja_tabla(hoja, columnas, self.filas)
        claves = {"Fecha": "fecha", "Alumnos": "alumnos", "Calidad": "calidad"}
        for i, columna in enumerate(orden, start=1):
            clave = claves.get(columna.titulo) or next(
                (v.clave for v in VARIABLES if columna.titulo.startswith(v.etiqueta + " (")), None)
            if clave:
                self.col[clave] = get_column_letter(i)
        if self.filas:
            ultima_col = get_column_letter(len(orden))
            tabla = Table(displayName="Registros", ref="A1:{}{}".format(ultima_col, self._ultima))
            tabla.tableStyleInfo = TableStyleInfo(name="TableStyleLight1", showRowStripes=False)
            hoja.add_table(tabla)
            self._color_calidad(hoja, "{0}2:{0}{1}".format(self.col["calidad"], self._ultima))

    def _promedio(self, clave, criterio, n):
        return '=IFERROR(AVERAGEIFS({},{},$A{}),"")'.format(self._rango(clave), criterio, n)

    def _porcentaje(self, criterio, nivel, n, total="$B"):
        return '=IF({1}{0}=0,0,COUNTIFS({2},$A{0},{3},"{4}")/{1}{0})'.format(
            n, total, criterio, self._rango("calidad"), nivel)

    def _hoja_por_alumnos(self):
        hoja = self.libro.create_sheet("Por alumnos")
        alumnos = self._rango("alumnos")
        var = self.POR_CLAVE

        def promedio(clave, detalle=False):
            v = var[clave]
            return Columna("{} ({})".format(v.nombre, v.unidad), lambda n, d, c=clave: self._promedio(c, alumnos, n),
                           self._formato(v), 13, detalle)

        def nivel(nombre, detalle=True):
            return Columna("Aire {} (% del tiempo)".format(nombre),
                           lambda n, d, x=nombre: self._porcentaje(alumnos, x, n), "0%", 13, detalle)

        columnas = ([Columna("Alumnos en el aula", lambda n, d: d, "0", 11),
                     Columna("Registros", lambda n, d: "=COUNTIFS({},$A{})".format(alumnos, n), "0", 10),
                     promedio("co2"), promedio("humo"), promedio("polvo"), nivel("BUENO", False),
                     promedio("temp", True), promedio("hum", True), promedio("humo_fino", True)]
                    + [nivel(x) for x in self.NIVELES[1:]])
        cantidades = sorted({f["estudiantes"] for f in self.filas if f["estudiantes"] is not None})
        self._hoja_tabla(hoja, columnas, cantidades)
        ultima = len(cantidades) + 1
        self._nota(hoja, ultima + 2, "Promedio de todos los registros con esa cantidad de alumnos. "
                                     "Pulsa \"+\" arriba para ver temperatura, humedad, humo muy fino "
                                     "y los otros niveles.")
        if cantidades:
            self._graficos_por_alumnos(hoja, ultima)

    def _grafico(self, hoja, titulo, eje_y, series, ultima, ancla):
        grafico = ScatterChart()
        grafico.title = titulo
        grafico.style = 2
        grafico.x_axis.title = "Alumnos en el aula"
        grafico.y_axis.title = eje_y
        x = Reference(hoja, min_col=1, min_row=2, max_row=ultima)
        for columna, nombre, color in series:
            serie = Series(Reference(hoja, min_col=columna, min_row=2, max_row=ultima), x, title=nombre)
            serie.marker.symbol = "circle"
            serie.marker.size = 5
            serie.graphicalProperties.line.solidFill = color
            serie.marker.graphicalProperties.solidFill = color
            serie.marker.graphicalProperties.line.solidFill = color
            grafico.series.append(serie)
        if len(series) == 1:
            grafico.legend = None
        else:
            grafico.legend.position = "b"
        grafico.height, grafico.width = 7.5, 15
        self._estilo_grafico(grafico)
        hoja.add_chart(grafico, ancla)

    def _graficos_por_alumnos(self, hoja, ultima):
        fila = "A{}".format(ultima + 4)
        self._grafico(hoja, "CO2 según los alumnos en el aula", "CO2 (ppm)",
                      [(3, "CO2", "2A78D6")], ultima, fila)
        self._grafico(hoja, "Humo y polvo según los alumnos en el aula", "µg/m³",
                      [(4, "Humo (PM2.5)", "EB6834"), (5, "Polvo (PM10)", "1BAF7A")], ultima,
                      "H{}".format(ultima + 4))

    def _hoja_por_dia(self):
        hoja = self.libro.create_sheet("Por día")
        fecha = self._rango("fecha")

        def calculo(funcion, clave, formato, titulo, detalle=False):
            return Columna(titulo, lambda n, d: '=IFERROR({}({},{},$A{}),"")'.format(
                funcion, self._rango(clave), fecha, n), formato, 13, detalle)

        columnas = [
            Columna("Fecha", lambda n, d: d, "dd/mm/yyyy", 12),
            Columna("Registros", lambda n, d: "=COUNTIFS({},$A{})".format(fecha, n), "0", 10),
            calculo("_xlfn.MAXIFS", "alumnos", "0", "Máximo de alumnos"),
            calculo("AVERAGEIFS", "co2", "0", "CO2 promedio (ppm)"),
            Columna("Aire BUENO (% del tiempo)", lambda n, d: self._porcentaje(fecha, "BUENO", n), "0%", 13),
            Columna("Día", lambda n, d: RegistroDatos.DIAS[d.weekday()], None, 11, True),
            calculo("_xlfn.MAXIFS", "co2", "0", "CO2 máximo (ppm)", True),
            calculo("AVERAGEIFS", "humo", "0.0", "Humo (PM2.5) promedio (µg/m³)", True),
            calculo("AVERAGEIFS", "polvo", "0.0", "Polvo (PM10) promedio (µg/m³)", True),
        ]
        self._hoja_tabla(hoja, columnas, sorted({f["momento"].date() for f in self.filas}))

    def _hoja_resumen(self):
        hoja = self.libro.active
        hoja.title = "Resumen"
        hoja.sheet_view.showGridLines = False
        hoja.column_dimensions["A"].width = 32
        hoja.column_dimensions["B"].width = 24
        hoja["A1"] = "Calidad del aire y alumnos en el aula"
        hoja["A1"].font = self._fuente(True, tamano=14)
        hoja["A2"] = "Exportado el {}".format(datetime.now().strftime("%d/%m/%Y %H:%M"))
        hoja["A2"].font = self._fuente(color=self.SUAVE, tamano=9)
        alumnos, co2, fecha = self._rango("alumnos"), self._rango("co2"), self._rango("fecha")
        total = "$B$7"                      # fila de "Registros grabados"

        def porcentaje(nivel):
            return '=IF({0}=0,0,COUNTIFS({1},"{2}")/{0})'.format(total, self._rango("calidad"), nivel)

        basicas = [
            ("Lugar", self.lugar or "Todos", None),
            ("Desde", "=MIN({})".format(fecha), "dd/mm/yyyy"),
            ("Hasta", "=MAX({})".format(fecha), "dd/mm/yyyy"),
            ("Registros grabados", "=COUNTA({})".format(fecha), "0"),
            ("Máximo de alumnos a la vez", "=MAX({})".format(alumnos), "0"),
            ("CO2 promedio (ppm)", '=IFERROR(AVERAGE({}),"")'.format(co2), "0"),
            ("Aire BUENO (% del tiempo)", porcentaje("BUENO"), "0%"),
        ]
        detalle = [
            ("Alumnos en promedio", '=IFERROR(AVERAGE({}),"")'.format(alumnos), "0.0"),
            ("CO2 máximo (ppm)", "=MAX({})".format(co2), "0"),
            ("Humo (PM2.5) promedio (µg/m³)", '=IFERROR(AVERAGE({}),"")'.format(self._rango("humo")), "0.0"),
            ("Polvo (PM10) promedio (µg/m³)", '=IFERROR(AVERAGE({}),"")'.format(self._rango("polvo")), "0.0"),
        ] + [("Aire {} (% del tiempo)".format(n), porcentaje(n), "0%") for n in self.NIVELES[1:]]
        n = 3
        for n, (texto, valor, formato) in enumerate(basicas + detalle, start=4):
            hoja.cell(row=n, column=1, value=texto).font = self._fuente(color=self.SUAVE)
            celda = hoja.cell(row=n, column=2, value=valor)
            celda.font = self._fuente(True)
            celda.alignment = Alignment(horizontal="right")
            if formato:
                celda.number_format = formato
            for c in (1, 2):
                hoja.cell(row=n, column=c).border = Border(bottom=Side(style="thin", color=self.LINEA))
        primera_detalle = 4 + len(basicas)
        hoja.row_dimensions.group(primera_detalle, n, hidden=True, outline_level=1)
        hoja.sheet_properties.outlinePr.summaryBelow = False          # el "+" queda arriba del detalle
        self._nota(hoja, n + 2, "Pulsa \"+\" a la izquierda para ver más datos. Hojas: Registros, "
                                "Por alumnos (con gráficos) y Por día.")

    # ---------- Uso ----------
    def guardar(self, archivo):
        """Arma todas las hojas y guarda el .xlsx. Devuelve la ruta."""
        self._hoja_registros()          # primero: define en que columna esta cada dato
        self._hoja_resumen()
        self._hoja_por_alumnos()
        self._hoja_por_dia()
        self.libro.move_sheet("Resumen", offset=-self.libro.index(self.libro["Resumen"]))
        self.libro.active = 0
        self.libro.save(archivo)
        return archivo
