"""Piezas visuales del software de control (tema oscuro, estilo "matriz de puntos").

- Tema: colores y letras.
- MatrizPuntos: dibuja numeros y letras grandes hechos de puntos, como un panel LED.
- Caja / Panel: tarjeta oscura de esquinas redondeadas, con titulo numerado ("01  CO2").
- BotonIcono, Pestanas, Aviso: controles con el mismo estilo.
- Tarjetas de lecturas: estado del aire, CO2, particulas, alumnos y ambiente.

Todo se dibuja con tkinter (viene con Python). Los iconos salen de la fuente de iconos de
Windows ("Segoe Fluent Icons" o "Segoe MDL2 Assets"), asi que no hace falta ninguna imagen.
"""
import math
import tkinter as tk
from collections import deque
from tkinter import font as tkfont
from tkinter import ttk


class Tema:
    """Colores y letras de toda la aplicacion."""

    FONDO = "#0d0e10"          # fondo de la ventana
    TARJETA = "#18191c"        # tarjetas
    CAMPO = "#222428"          # casillas, botones
    CAMPO_HOVER = "#2c2f34"
    BORDE = "#2a2c31"
    LINEA = "#26282c"          # grilla de graficos y separadores
    TEXTO = "#ecebe6"
    TEXTO_SUAVE = "#9a9da3"
    TENUE = "#3c3f45"          # puntos apagados
    ACENTO = "#ff5a36"         # naranja rojizo
    VERDE = "#4cc38a"
    AMBAR = "#f2b33d"
    ROJO = "#ff4d3d"

    # Nombres anteriores, para el resto del programa
    PANEL = TARJETA
    PANEL_SUAVE = TARJETA
    CABECERA_TABLA = TARJETA
    AZUL = ACENTO
    AZUL_OSCURO = ACENTO
    GRIS = TEXTO_SUAVE
    DESTACADO = CAMPO

    # Niveles: como los envia la estacion, como se muestran y su color
    NIVELES = ("BUENO", "MODERADO", "MALO", "MUY MALO")
    NOMBRES = ("BUENO", "NORMAL", "MALO", "RIESGOSO")
    COLOR_NIVEL = ("#4cc38a", "#f2d23d", "#ff8a3d", "#ff4d3d")      # verde, amarillo, naranja, rojo
    COLOR_NEUTRO = "#8c8f95"

    _mono = None

    @classmethod
    def mono(cls):
        """Fuente de ancho fijo: Cascadia Mono (Windows 11) o Consolas."""
        if cls._mono is None:
            familias = set(tkfont.families())
            cls._mono = next((f for f in ("Cascadia Mono", "JetBrains Mono", "Consolas", "Courier New")
                              if f in familias), "Courier")
        return cls._mono

    @classmethod
    def fuente(cls, tamano=10, negrita=False):
        return (cls.mono(), tamano, "bold" if negrita else "normal")

    @classmethod
    def indice(cls, estado):
        """0-3 a partir del numero, del nombre de la estacion ("MUY MALO") o del simple ("RIESGOSO")."""
        if isinstance(estado, int):
            return estado if 0 <= estado < 4 else None
        for lista in (cls.NIVELES, cls.NOMBRES):
            if estado in lista:
                return lista.index(estado)
        return None

    @classmethod
    def nombre(cls, estado):
        """Nombre simple para mostrar: MODERADO -> NORMAL, MUY MALO -> RIESGOSO."""
        indice = cls.indice(estado)
        return cls.NOMBRES[indice] if indice is not None else estado

    @classmethod
    def color_de(cls, estado):
        """Color de un nivel (numero o nombre), o el neutro si no es un nivel."""
        indice = cls.indice(estado)
        return cls.COLOR_NIVEL[indice] if indice is not None else cls.COLOR_NEUTRO

    @classmethod
    def aplicar_estilos(cls, raiz):
        """Estilo oscuro de los widgets ttk (tablas, listas, casillas, barras)."""
        estilo = ttk.Style(raiz)
        try:
            estilo.theme_use("clam")
        except tk.TclError:
            pass
        base = dict(background=cls.CAMPO, foreground=cls.TEXTO, fieldbackground=cls.CAMPO,
                    bordercolor=cls.BORDE, lightcolor=cls.CAMPO, darkcolor=cls.CAMPO,
                    insertcolor=cls.TEXTO, arrowcolor=cls.TEXTO_SUAVE)
        estilo.configure(".", font=cls.fuente(10), background=cls.TARJETA, foreground=cls.TEXTO)
        for nombre in ("TEntry", "TSpinbox", "TCombobox"):
            estilo.configure(nombre, padding=4, **base)
            estilo.map(nombre, fieldbackground=[("disabled", cls.TARJETA), ("readonly", cls.CAMPO)],
                       foreground=[("disabled", cls.TENUE)], selectbackground=[("readonly", cls.CAMPO)],
                       selectforeground=[("readonly", cls.TEXTO)], bordercolor=[("focus", cls.ACENTO)],
                       lightcolor=[("focus", cls.CAMPO)], background=[("active", cls.CAMPO_HOVER)])
        raiz.option_add("*TCombobox*Listbox.background", cls.CAMPO)
        raiz.option_add("*TCombobox*Listbox.foreground", cls.TEXTO)
        raiz.option_add("*TCombobox*Listbox.selectBackground", cls.ACENTO)
        raiz.option_add("*TCombobox*Listbox.font", cls.fuente(10))
        estilo.configure("Vertical.TScrollbar", background=cls.CAMPO, troughcolor=cls.TARJETA,
                         bordercolor=cls.TARJETA, lightcolor=cls.CAMPO, darkcolor=cls.CAMPO,
                         arrowcolor=cls.TEXTO_SUAVE, gripcount=0)
        estilo.map("Vertical.TScrollbar", background=[("active", cls.CAMPO_HOVER)])
        # Tablas minimalistas: sin rellenos ni rayas, encabezado en gris y aire entre filas.
        estilo.configure("Treeview", rowheight=28, font=cls.fuente(10), background=cls.TARJETA,
                         foreground=cls.TEXTO, fieldbackground=cls.TARJETA, bordercolor=cls.TARJETA,
                         borderwidth=0)
        estilo.configure("Treeview.Heading", font=cls.fuente(9), background=cls.TARJETA,
                         foreground=cls.TEXTO_SUAVE, relief="flat", borderwidth=0, padding=(6, 6))
        estilo.map("Treeview.Heading", background=[("active", cls.TARJETA)])
        estilo.map("Treeview", background=[("selected", cls.CAMPO_HOVER)], foreground=[("selected", cls.TEXTO)])

    @staticmethod
    def barra_oscura(ventana):
        """Barra de titulo oscura en Windows 10/11 (si no se puede, no pasa nada)."""
        try:
            import ctypes
            ventana.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(ventana.winfo_id())
            valor = ctypes.c_int(1)
            for atributo in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, atributo, ctypes.byref(valor), ctypes.sizeof(valor))
        except Exception:
            pass


# =====================================================================
# Letras de puntos
# =====================================================================
class MatrizPuntos:
    """Letras y numeros de 5x7 puntos, como un panel LED. Se dibujan en un tk.Canvas."""

    GLIFOS = {
        "0": ".###.|#...#|#..##|#.#.#|##..#|#...#|.###.", "1": "..#..|.##..|..#..|..#..|..#..|..#..|.###.",
        "2": ".###.|#...#|....#|...#.|..#..|.#...|#####", "3": "#####|...#.|..#..|...#.|....#|#...#|.###.",
        "4": "...#.|..##.|.#.#.|#..#.|#####|...#.|...#.", "5": "#####|#....|####.|....#|....#|#...#|.###.",
        "6": "..##.|.#...|#....|####.|#...#|#...#|.###.", "7": "#####|....#|...#.|..#..|.#...|.#...|.#...",
        "8": ".###.|#...#|#...#|.###.|#...#|#...#|.###.", "9": ".###.|#...#|#...#|.####|....#|...#.|.##..",
        "A": ".###.|#...#|#...#|#####|#...#|#...#|#...#", "B": "####.|#...#|#...#|####.|#...#|#...#|####.",
        "C": ".###.|#...#|#....|#....|#....|#...#|.###.", "D": "###..|#..#.|#...#|#...#|#...#|#..#.|###..",
        "E": "#####|#....|#....|####.|#....|#....|#####", "F": "#####|#....|#....|####.|#....|#....|#....",
        "G": ".###.|#...#|#....|#.###|#...#|#...#|.####", "H": "#...#|#...#|#...#|#####|#...#|#...#|#...#",
        "I": ".###.|..#..|..#..|..#..|..#..|..#..|.###.", "J": "..###|...#.|...#.|...#.|...#.|#..#.|.##..",
        "K": "#...#|#..#.|#.#..|##...|#.#..|#..#.|#...#", "L": "#....|#....|#....|#....|#....|#....|#####",
        "M": "#...#|##.##|#.#.#|#.#.#|#...#|#...#|#...#", "N": "#...#|#...#|##..#|#.#.#|#..##|#...#|#...#",
        "O": ".###.|#...#|#...#|#...#|#...#|#...#|.###.", "P": "####.|#...#|#...#|####.|#....|#....|#....",
        "Q": ".###.|#...#|#...#|#...#|#.#.#|#..#.|.##.#", "R": "####.|#...#|#...#|####.|#.#..|#..#.|#...#",
        "S": ".####|#....|#....|.###.|....#|....#|####.", "T": "#####|..#..|..#..|..#..|..#..|..#..|..#..",
        "U": "#...#|#...#|#...#|#...#|#...#|#...#|.###.", "V": "#...#|#...#|#...#|#...#|#...#|.#.#.|..#..",
        "W": "#...#|#...#|#...#|#.#.#|#.#.#|#.#.#|.#.#.", "X": "#...#|#...#|.#.#.|..#..|.#.#.|#...#|#...#",
        "Y": "#...#|#...#|.#.#.|..#..|..#..|..#..|..#..", "Z": "#####|....#|...#.|..#..|.#...|#....|#####",
        " ": "...|...|...|...|...|...|...", ".": "..|..|..|..|..|##|##", ":": "..|##|##|..|##|##|..",
        "-": ".....|.....|.....|#####|.....|.....|.....", "+": ".....|..#..|..#..|#####|..#..|..#..|.....",
        "%": "##...|##..#|...#.|..#..|.#...|#..##|...##", "/": ".....|....#|...#.|..#..|.#...|#....|.....",
        "°": ".#.|#.#|.#.|...|...|...|...",
    }
    SIN_ACENTO = str.maketrans("ÁÉÍÓÚÜÑ", "AEIOUUN")

    @classmethod
    def _glifo(cls, letra):
        filas = cls.GLIFOS.get(letra.upper().translate(cls.SIN_ACENTO), cls.GLIFOS[" "]).split("|")
        return filas

    @classmethod
    def medir(cls, texto, paso):
        """Ancho en pixeles del texto."""
        return sum((len(cls._glifo(c)[0]) + 1) * paso for c in texto) - paso if texto else 0

    @classmethod
    def dibujar(cls, lienzo, x, y, texto, paso=6, radio=2.2, color=Tema.TEXTO, etiqueta="puntos", ancla="nw"):
        """Dibuja el texto con su esquina (ancla "nw", "ne" o "n") en x, y. Devuelve el ancho."""
        ancho = cls.medir(texto, paso)
        if ancla == "ne":
            x -= ancho
        elif ancla == "n":
            x -= ancho / 2
        for letra in texto:
            filas = cls._glifo(letra)
            for f, fila in enumerate(filas):
                for c, marca in enumerate(fila):
                    if marca == "#":
                        cx, cy = x + c * paso + paso / 2, y + f * paso + paso / 2
                        lienzo.create_oval(cx - radio, cy - radio, cx + radio, cy + radio,
                                           fill=color, outline="", tags=etiqueta)
            x += (len(filas[0]) + 1) * paso
        return ancho


# =====================================================================
# Valores recomendados
# =====================================================================
class Referencias:
    """Lo que "se supone" que deberia medir el aula, para avisar cuando una cantidad es mala.

    RANGOS: clave -> (minimo, maximo, unidad, nombre). None = sin limite de ese lado.
    - CO2, humo y humo muy fino: el maximo de BUENO que usa la estacion (se actualiza con
      los limites que envia; por defecto 799 ppm y 12 µg/m³).
    - Polvo: 54 µg/m³ (BUENO del indice de la EPA).
    - Temperatura 20-26 °C y humedad 40-60 %: rangos de confort habituales para un aula.
    - Alumnos: el aforo del aula (30).
    """

    RANGOS = {
        "co2": (None, 799, "ppm", "CO2"),
        "pm25": (None, 12, "µg/m³", "HUMO"),
        "pm1": (None, 12, "µg/m³", "HUMO FINO"),
        "pm10": (None, 54, "µg/m³", "POLVO"),
        "temp": (20, 26, "°C", "TEMP"),
        "hum": (40, 60, "%", "HUMEDAD"),
        "dentro": (None, 30, "alumnos", "AFORO"),
    }

    # Nivel de cada medicion (BUENO, NORMAL, MALO; mas alla es RIESGOSO).
    # ESCALAS: hasta cuanto es cada nivel. BANDAS: entre que valores es cada nivel.
    ESCALAS = {
        "co2": (799, 1199, 1999),
        "pm25": (12, 35.4, 55.4),
        "pm1": (12, 35.4, 55.4),
        "pm10": (54, 154, 254),
        "dentro": (24, 30, 35),          # hasta 80 % del aforo, el aforo, un poco mas
    }
    BANDAS = {
        "temp": ((20, 26), (18, 28), (16, 30)),
        "hum": ((40, 60), (30, 70), (20, 80)),
    }

    @classmethod
    def actualizar_limites(cls, lim_co2=None, lim_pm25=None):
        """Usa los limites que tiene configurados la estacion."""
        if lim_co2:
            cls.RANGOS["co2"] = (None, lim_co2[0], "ppm", "CO2")
            cls.ESCALAS["co2"] = tuple(lim_co2)
        if lim_pm25:
            cls.RANGOS["pm25"] = (None, lim_pm25[0], "µg/m³", "HUMO")
            cls.RANGOS["pm1"] = (None, lim_pm25[0], "µg/m³", "HUMO FINO")
            cls.ESCALAS["pm25"] = cls.ESCALAS["pm1"] = tuple(lim_pm25)

    @classmethod
    def nivel(cls, clave, valor):
        """0 BUENO, 1 NORMAL, 2 MALO, 3 RIESGOSO (None si no hay valor)."""
        if valor is None:
            return None
        if clave in cls.ESCALAS:
            for indice, limite in enumerate(cls.ESCALAS[clave]):
                if valor <= limite:
                    return indice
            return 3
        if clave in cls.BANDAS:
            for indice, (minimo, maximo) in enumerate(cls.BANDAS[clave]):
                if minimo <= valor <= maximo:
                    return indice
            return 3
        return None

    @classmethod
    def color(cls, clave, valor, sin_dato=Tema.TEXTO):
        """Color del nivel de la lectura: verde, amarillo, naranja o rojo."""
        indice = cls.nivel(clave, valor)
        return sin_dato if indice is None else Tema.COLOR_NIVEL[indice]

    @classmethod
    def nombre_nivel(cls, clave, valor):
        indice = cls.nivel(clave, valor)
        return "--" if indice is None else Tema.NOMBRES[indice]

    @staticmethod
    def _numero(valor):
        return "{:g}".format(round(valor, 1))

    @classmethod
    def rango(cls, clave):
        """Texto del valor recomendado: "≤ 799" o "20-26"."""
        minimo, maximo, _, _ = cls.RANGOS[clave]
        if minimo is None:
            return "≤ " + cls._numero(maximo)
        return "{}-{}".format(cls._numero(minimo), cls._numero(maximo))

    @classmethod
    def desvio(cls, clave, valor):
        """Cuanto se pasa (positivo), cuanto le falta (negativo) o 0 si esta en lo recomendado."""
        if valor is None or clave not in cls.RANGOS:
            return None
        minimo, maximo, _, _ = cls.RANGOS[clave]
        if maximo is not None and valor > maximo:
            return valor - maximo
        if minimo is not None and valor < minimo:
            return valor - minimo
        return 0

    @classmethod
    def indicador(cls, clave, valor, corto=False):
        """(texto, color) para mostrar junto a la lectura. corto=True para espacios chicos."""
        desvio = cls.desvio(clave, valor)
        if desvio is None:
            return ("RECOM. " + cls.rango(clave), Tema.TEXTO_SUAVE)
        color = cls.color(clave, valor)
        nombre = cls.nombre_nivel(clave, valor)
        if desvio == 0:
            return (("✓ " if corto else nombre + " · ") + cls.rango(clave), color)
        marca = "▲" if desvio > 0 else "▼"
        if corto:
            return ("{} {:+g}".format(marca, round(desvio, 1)), color)
        return ("{} · {} {:+g} (RECOM. {})".format(nombre, marca, round(desvio, 1), cls.rango(clave)), color)

    @classmethod
    def resumen(cls, valores):
        """Que esta fuera de lo recomendado: (texto, color) para la tarjeta 01."""
        malos, peor = [], 0
        for clave in ("co2", "pm25", "pm10", "pm1", "temp", "hum", "dentro"):
            desvio = cls.desvio(clave, valores.get(clave))
            if desvio:
                _, _, unidad, nombre = cls.RANGOS[clave]
                malos.append("{} {:+g} {}".format(nombre, round(desvio, 1), unidad))
                peor = max(peor, cls.nivel(clave, valores.get(clave)) or 1)
        if not malos:
            return ("✓ TODO DENTRO DE LO RECOMENDADO", Tema.COLOR_NIVEL[0])
        return ("FUERA DE LO RECOMENDADO: " + " · ".join(malos), Tema.COLOR_NIVEL[peor])

    @classmethod
    def lineas(cls, claves):
        """Lineas de limite para un grafico: [(valor, texto, "max" o "min")], sin repetir valores."""
        lineas, vistos = [], set()
        for clave in claves:
            if clave not in cls.RANGOS:
                continue
            minimo, maximo, _, nombre = cls.RANGOS[clave]
            for valor, tipo, palabra in ((maximo, "max", "MÁX"), (minimo, "min", "MÍN")):
                if valor is not None and valor not in vistos:
                    vistos.add(valor)
                    texto = "{} {}".format(palabra, cls._numero(valor))
                    if len(claves) > 1:
                        texto = "{} {}".format(nombre, texto)
                    lineas.append((valor, texto, tipo))
        return lineas


# =====================================================================
# Iconos y botones
# =====================================================================
class Icono(tk.Label):
    """Un icono de la fuente de iconos de Windows, del color que se pida."""

    CODIGOS = {
        "actualizar": "E72C", "cerrar": "E711", "calendario": "E787", "reloj": "E823",
        "ajustes": "E713", "iniciar": "E768", "check": "E73E", "silencio": "E74F",
        "alerta": "E7BA", "personas": "E716", "lista": "E8FD", "barras": "E9F9",
        "area": "E9D2", "termometro": "E9CA", "nube": "E753", "gota": "EB42",
        "particulas": "F16A", "matraz": "F196", "tabla": "E80A", "tendencia": "EAFC",
        "entrar": "E72A", "salir": "E72B", "conectar": "E71B", "sigma": "E8EF",
        "carpeta": "E8B7", "info": "E946",
    }
    _familia = None

    @classmethod
    def familia(cls):
        if cls._familia is None:
            familias = set(tkfont.families())
            cls._familia = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in familias), "")
        return cls._familia

    @classmethod
    def caracter(cls, nombre):
        """El caracter del icono (vacio si la PC no tiene la fuente de iconos)."""
        return chr(int(cls.CODIGOS[nombre], 16)) if cls.familia() else ""

    def __init__(self, padre, nombre, color=Tema.TEXTO_SUAVE, tamano=14, fondo=None):
        super().__init__(padre, text=self.caracter(nombre), font=(self.familia() or "Segoe UI", tamano),
                         fg=color, bg=fondo or padre.cget("bg"))


class _Compuesto(tk.Frame):
    """Base de los widgets hechos con varias piezas que se usan como si fueran uno.

    Las clases hijas atienden "text" (y otras opciones propias) en _opcion();
    lo demas lo atiende tk.Frame normalmente.
    """

    PROPIAS = ("text",)

    def configure(self, cnf=None, **opciones):
        if cnf:
            opciones.update(cnf)
        for clave in [c for c in opciones if c in self.PROPIAS]:
            self._opcion(clave, opciones.pop(clave))
        if opciones:
            return super().configure(**opciones)
        return None

    config = configure

    def cget(self, clave):
        if clave in self.PROPIAS:
            return self._leer(clave)
        return super().cget(clave)

    def _opcion(self, clave, valor):
        raise NotImplementedError

    def _leer(self, clave):
        raise NotImplementedError

    def _al_hacer_clic(self, funcion, *widgets):
        for widget in (self,) + widgets:
            widget.bind("<Button-1>", lambda e: funcion())


class BotonIcono(_Compuesto):
    """Boton con icono y texto en mayusculas. Estilos: "normal", "primario" (naranja) y "peligro"."""

    PROPIAS = ("text", "state", "command")
    ESTILOS = {
        #            fondo         hover            borde        texto         icono
        "normal": (Tema.CAMPO, Tema.CAMPO_HOVER, Tema.BORDE, Tema.TEXTO, Tema.TEXTO_SUAVE),
        "primario": (Tema.ACENTO, "#ff7553", Tema.ACENTO, "#141414", "#141414"),
        "peligro": (Tema.CAMPO, Tema.CAMPO_HOVER, Tema.BORDE, Tema.TEXTO, Tema.ACENTO),
    }

    def __init__(self, padre, texto, icono=None, command=None, estilo="normal"):
        self._colores = self.ESTILOS[estilo]
        fondo, _, borde, color_texto, color_icono = self._colores
        super().__init__(padre, bg=fondo, highlightthickness=1, highlightbackground=borde, cursor="hand2")
        self._command = command
        self._estado = "normal"
        self._icono = Icono(self, icono, color_icono, 11, fondo) if icono else None
        if self._icono:
            self._icono.pack(side="left", padx=(10, 2), pady=5)
        self._texto = tk.Label(self, text=texto.upper(), bg=fondo, fg=color_texto, font=Tema.fuente(9, True))
        self._texto.pack(side="left", padx=(4 if icono else 12, 12), pady=5)
        piezas = [p for p in (self._icono, self._texto) if p]
        self._al_hacer_clic(self._clic, *piezas)
        for widget in [self] + piezas:
            widget.bind("<Enter>", lambda e: self._pintar(hover=True))
            widget.bind("<Leave>", lambda e: self._pintar(hover=False))

    def _clic(self):
        if self._estado != "disabled" and self._command:
            self._command()

    def _pintar(self, hover=False):
        fondo, fondo_hover, borde, color_texto, color_icono = self._colores
        if self._estado == "disabled":
            fondo, borde, color_texto, color_icono = Tema.TARJETA, Tema.LINEA, Tema.TENUE, Tema.TENUE
        elif hover:
            fondo = fondo_hover
        tk.Frame.configure(self, bg=fondo, highlightbackground=borde,
                           cursor="arrow" if self._estado == "disabled" else "hand2")
        self._texto.config(bg=fondo, fg=color_texto)
        if self._icono:
            self._icono.config(bg=fondo, fg=color_icono)

    def _opcion(self, clave, valor):
        if clave == "text":
            self._texto.config(text=str(valor).upper())
        elif clave == "state":
            self._estado = str(valor)
            self._pintar()
        elif clave == "command":
            self._command = valor

    def _leer(self, clave):
        if clave == "text":
            return self._texto.cget("text")
        if clave == "state":
            return self._estado
        return self._command


# =====================================================================
# Tarjetas
# =====================================================================
class Caja(tk.Canvas):
    """Tarjeta oscura de esquinas redondeadas. El contenido va en self.interior.

    ancho/alto fijos opcionales; si no, toma el tamano de lo que tenga adentro.
    """

    RADIO = 16
    MARGEN = 6           # el interior empieza un poco adentro para no tapar las esquinas

    def __init__(self, padre, ancho=None, alto=None, fondo=Tema.TARJETA):
        super().__init__(padre, bg=padre.cget("bg"), highlightthickness=0, bd=0,
                         width=ancho or 10, height=alto or 10)
        self._fondo = fondo
        self._fijo = (ancho, alto)
        self.interior = tk.Frame(self, bg=fondo)
        self._ventana = self.create_window(self.MARGEN, self.MARGEN, window=self.interior, anchor="nw")
        self.interior.bind("<Configure>", self._ajustar)
        self.bind("<Configure>", self._redibujar)
        self.after(300, self._vigilar)

    def _ajustar(self, _evento=None):
        ancho = self._fijo[0] or self.interior.winfo_reqwidth() + 2 * self.MARGEN
        alto = self._fijo[1] or self.interior.winfo_reqheight() + 2 * self.MARGEN
        if (int(self.cget("width")), int(self.cget("height"))) != (ancho, alto):
            self.config(width=ancho, height=alto)

    def _vigilar(self):
        """Si cambia lo de adentro (por ejemplo un aviso mas largo), la tarjeta se ajusta."""
        try:
            self._ajustar()
            self.after(400, self._vigilar)
        except tk.TclError:
            pass          # la ventana ya se cerro

    def _redibujar(self, evento):
        ancho, alto = evento.width, evento.height
        self.delete("fondo")
        r, x1, y1, x2, y2 = self.RADIO, 0.5, 0.5, ancho - 1.5, alto - 1.5
        puntos = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
                  x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        self.create_polygon(puntos, smooth=True, fill=self._fondo, outline=Tema.BORDE, tags="fondo")
        self.tag_lower("fondo")
        self.itemconfig(self._ventana, width=max(1, ancho - 2 * self.MARGEN),
                        height=max(1, alto - 2 * self.MARGEN))


class Panel(Caja):
    """Tarjeta con titulo numerado arriba ("01  CALIDAD DEL AIRE") y el contenido en self.cuerpo.

    A la derecha del titulo hay lugar para otros controles (self.cabecera_derecha).
    icono/barra se aceptan por compatibilidad; el estilo nuevo no los usa.
    """

    def __init__(self, padre, titulo, icono=None, barra=False, fondo=Tema.TARJETA, numero=None,
                 ancho=None, alto=None):
        super().__init__(padre, ancho, alto, fondo)
        self.cabecera = tk.Frame(self.interior, bg=fondo)
        self.cabecera.pack(fill="x", padx=14, pady=(10, 6))
        if numero is not None:
            tk.Label(self.cabecera, text="{:02d}".format(numero), bg=fondo, fg=Tema.TEXTO_SUAVE,
                     font=Tema.fuente(10)).pack(side="left", padx=(0, 10))
        tk.Label(self.cabecera, text=titulo.upper(), bg=fondo, fg=Tema.TEXTO,
                 font=Tema.fuente(10)).pack(side="left")
        self.cabecera_derecha = tk.Frame(self.cabecera, bg=fondo)
        self.cabecera_derecha.pack(side="right")
        self.cuerpo = tk.Frame(self.interior, bg=fondo)
        self.cuerpo.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def marca(self, texto, color=Tema.ACENTO):
        """Marca chica a la derecha del titulo, como "● EN VIVO"."""
        etiqueta = tk.Label(self.cabecera_derecha, text=texto, bg=self._fondo, fg=color, font=Tema.fuente(9))
        etiqueta.pack(side="right")
        return etiqueta


class Pestanas(tk.Frame):
    """Pestanas de texto: la elegida en blanco y subrayada en naranja."""

    def __init__(self, padre, fondo=Tema.TARJETA):
        super().__init__(padre, bg=fondo)
        self._fondo = fondo
        self.barra = tk.Frame(self, bg=fondo)
        self.barra.pack(fill="x", pady=(0, 8))
        self.contenido = tk.Frame(self, bg=fondo)
        self.contenido.pack(fill="both", expand=True)
        self._pestanas = []
        self.actual = 0

    def agregar(self, texto, icono=None):
        marco = tk.Frame(self.barra, bg=self._fondo, cursor="hand2")
        marco.pack(side="left", padx=(0, 18))
        etiqueta = tk.Label(marco, text=texto.upper(), bg=self._fondo, fg=Tema.TEXTO_SUAVE,
                            font=Tema.fuente(10), cursor="hand2")
        etiqueta.pack(pady=(0, 3))
        raya = tk.Frame(marco, bg=self._fondo, height=2)
        raya.pack(fill="x")
        pagina = tk.Frame(self.contenido, bg=self._fondo)
        indice = len(self._pestanas)
        for widget in (marco, etiqueta):
            widget.bind("<Button-1>", lambda e, i=indice: self.seleccionar(i))
        self._pestanas.append((marco, raya, etiqueta, pagina))
        if indice == 0:
            self.seleccionar(0)
        return pagina

    def fijar_tamano(self):
        """Fija el tamano al de la pestana mas grande, para que la ventana no salte al cambiar."""
        self.update_idletasks()
        paginas = [p for *_, p in self._pestanas]
        ancho = max(p.winfo_reqwidth() for p in paginas)
        alto = max(p.winfo_reqheight() for p in paginas)
        self.contenido.configure(width=ancho, height=alto)
        self.contenido.pack_propagate(False)

    def seleccionar(self, indice):
        self.actual = indice
        for i, (_marco, raya, etiqueta, pagina) in enumerate(self._pestanas):
            elegida = i == indice
            raya.config(bg=Tema.ACENTO if elegida else self._fondo)
            etiqueta.config(fg=Tema.TEXTO if elegida else Tema.TEXTO_SUAVE)
            if elegida:
                pagina.pack(fill="both", expand=True)
            else:
                pagina.pack_forget()


class Aviso(_Compuesto):
    """Linea de avisos dentro de la tarjeta del estado del aire.

    Cambia de color segun el texto: "ALERTA..." o "ALARMA..." en naranja, otro aviso en
    ambar y, sin texto, en gris con "Sin alertas". A la derecha caben otros controles (self.derecha).
    """

    ESTILOS = {
        #          marca  color marca   color texto
        "alerta": ("▲", Tema.ACENTO, Tema.TEXTO),
        "aviso": ("●", Tema.AMBAR, Tema.TEXTO),
        "vacio": ("●", Tema.VERDE, Tema.TEXTO_SUAVE),
    }

    def __init__(self, padre):
        fondo = padre.cget("bg")
        super().__init__(padre, bg=fondo)
        self._mensaje = ""
        self._fondo = fondo
        self._marca = tk.Label(self, bg=fondo, font=Tema.fuente(10))
        self._marca.pack(side="left", anchor="n", padx=(0, 8))
        textos = tk.Frame(self, bg=fondo)
        textos.pack(side="left", fill="x", expand=True)
        self._titulo = tk.Label(textos, bg=fondo, font=Tema.fuente(10, True), anchor="w", justify="left")
        self._titulo.pack(fill="x")
        # Alto fijo (titulo + 2 renglones) para que la tarjeta no cambie de tamano con cada aviso.
        self._resto = tk.Label(textos, bg=fondo, font=Tema.fuente(9), anchor="nw", justify="left",
                               wraplength=330, height=2)
        self._resto.pack(fill="x")
        self.derecha = tk.Frame(self, bg=fondo)
        self.derecha.pack(side="right", padx=(8, 0))
        self._opcion("text", "")

    def _opcion(self, clave, valor):
        self._mensaje = valor
        if valor.startswith(("ALERTA", "ALARMA")):
            estilo = "alerta"
        elif valor:
            estilo = "aviso"
        else:
            estilo = "vacio"
        marca, color_marca, color_texto = self.ESTILOS[estilo]
        if estilo == "vacio":
            titulo, resto = "SIN ALERTAS", ""
        elif ":" in valor[:8]:
            titulo, resto = valor.split(":", 1)[0].upper(), valor.split(":", 1)[1].strip()
        else:
            titulo, resto = "", valor
        self._marca.config(text=marca, fg=color_marca)
        self._titulo.config(text=titulo, fg=color_marca if estilo == "alerta" else color_texto)
        self._resto.config(text=resto, fg=Tema.TEXTO if estilo != "vacio" else Tema.TEXTO_SUAVE)

    def _leer(self, clave):
        return self._mensaje

    def repintar(self):
        """Se mantiene por compatibilidad (el fondo ya es el de la tarjeta)."""
        self._opcion("text", self._mensaje)


# =====================================================================
# Tarjetas de lecturas
# =====================================================================
class _Lectura:
    """Una lectura que se le pasa a una tarjeta (la tarjeta decide como mostrarla)."""

    def __init__(self, tarjeta, clave):
        self.tarjeta = tarjeta
        self.clave = clave
        self.valor = None

    def poner(self, valor, color=None, ideal=None, nivel=None):
        self.valor = valor
        self.tarjeta.poner(self.clave, valor, ideal, nivel)


class TarjetaLecturas(Panel):
    """Base de las tarjetas que muestran lecturas dibujadas en un lienzo.

    Cada lectura se obtiene con lectura(clave) y tiene poner(valor, color, ideal, nivel).
    """

    ANCHO, ALTO = 250, 150

    def __init__(self, padre, numero, titulo, claves):
        super().__init__(padre, titulo, numero=numero)
        self.lienzo = tk.Canvas(self.cuerpo, width=self.ANCHO, height=self.ALTO, bg=Tema.TARJETA,
                                highlightthickness=0, bd=0)
        self.lienzo.pack(fill="both", expand=True)
        self.pie = tk.Frame(self.cuerpo, bg=Tema.TARJETA)
        self.pie.pack(fill="x", pady=(6, 0))
        self.datos = {clave: {"valor": None, "ideal": None, "nivel": None} for clave in claves}
        self.lecturas = {clave: _Lectura(self, clave) for clave in claves}
        self.historia = {clave: deque(maxlen=60) for clave in claves}

    def lectura(self, clave):
        return self.lecturas[clave]

    def poner(self, clave, valor, ideal=None, nivel=None):
        anterior = self.datos[clave]["valor"]
        self.datos[clave] = {"valor": valor, "ideal": ideal, "nivel": nivel}
        if valor is not None and (valor != anterior or not self.historia[clave]):
            self.historia[clave].append(valor)
        if valor is None:
            self.historia[clave].clear()
        self.dibujar()

    def dibujar(self):
        raise NotImplementedError

    def numero_grande(self, x, y, texto, color=Tema.TEXTO, tamano=40, ancla="nw"):
        """Numero grande con letra de ancho fijo (se lee mejor que los puntos). Devuelve el ancho."""
        item = self.lienzo.create_text(x, y, anchor=ancla, text=texto, fill=color, font=Tema.fuente(tamano))
        x1, _, x2, _ = self.lienzo.bbox(item)
        return x2 - x1

    def etiqueta_pie(self, texto="", lado="left", color=Tema.TEXTO_SUAVE):
        etiqueta = tk.Label(self.pie, text=texto, bg=Tema.TARJETA, fg=color, font=Tema.fuente(9))
        etiqueta.pack(side=lado)
        return etiqueta

    @staticmethod
    def texto_numero(valor):
        return "--" if valor is None else "{:g}".format(round(valor, 1))

    @staticmethod
    def texto_ideal(valor, ideal):
        if ideal is None:
            return ""
        if valor is None:
            return "IDEAL {:g}".format(ideal)
        return "IDEAL {:g} ({:+g})".format(ideal, round(valor - ideal, 1))

    def color_nivel(self, nivel, normal=Tema.TEXTO):
        """Blanco si esta BUENO; el color del nivel si no."""
        return normal if nivel is None else Tema.COLOR_NIVEL[nivel]

    def barras_puntos(self, x, y_base, valores, ancho, alto, color_ultimo=Tema.ACENTO, paso=7):
        """Columnas de puntos (como un ecualizador) con los ultimos valores."""
        columnas = max(1, int(ancho // paso))
        valores = list(valores)[-columnas:]
        if not valores:
            for c in range(columnas):
                cx = x + c * paso + paso / 2
                self.lienzo.create_oval(cx - 1.5, y_base - 1.5, cx + 1.5, y_base + 1.5, fill=Tema.TENUE, outline="")
            return
        minimo, maximo = min(valores), max(valores)
        filas = int(alto // paso)
        for c, valor in enumerate(valores):
            nivel = 1 + int((valor - minimo) / (maximo - minimo) * (filas - 1)) if maximo > minimo else filas // 2
            cx = x + c * paso + paso / 2
            ultimo = c == len(valores) - 1
            for f in range(filas):
                cy = y_base - f * paso
                encendido = f < nivel
                color = (color_ultimo if ultimo else "#b9bbc0") if encendido else Tema.LINEA
                radio = 2.4 if encendido else 1.3
                self.lienzo.create_oval(cx - radio, cy - radio, cx + radio, cy + radio, fill=color, outline="")


class TarjetaCO2(TarjetaLecturas):
    """CO2: numero grande de puntos y un ecualizador con las ultimas lecturas."""

    def __init__(self, padre, numero):
        super().__init__(padre, numero, "CO2", ["co2"])
        self.marca("ppm", Tema.TEXTO_SUAVE)
        self._ideal = self.etiqueta_pie(lado="right")
        self.dibujar()

    def dibujar(self):
        dato = self.datos["co2"]
        self.lienzo.delete("all")
        nivel = Referencias.nivel("co2", dato["valor"])
        self.numero_grande(-3, -6, self.texto_numero(dato["valor"]), self.color_nivel(nivel))
        texto, color = Referencias.indicador("co2", dato["valor"])
        self.lienzo.create_text(0, 58, anchor="nw", text=texto, fill=color, font=Tema.fuente(9))
        self.barras_puntos(0, self.ALTO - 6, self.historia["co2"], self.ANCHO, 60,
                           color_ultimo=self.color_nivel(nivel, Tema.ACENTO))
        self._ideal.config(text=self.texto_ideal(dato["valor"], dato["ideal"]))


class TarjetaParticulas(TarjetaLecturas):
    """Polvo, humo y humo muy fino: anillo de puntos con el peor nivel y una lista con cada uno."""

    FILAS = (("pm10", "POLVO"), ("pm25", "HUMO"), ("pm1", "FINO"))
    ANCHO = 300

    def __init__(self, padre, numero):
        super().__init__(padre, numero, "Partículas", [c for c, _ in self.FILAS])
        self.marca("µg/m³", Tema.TEXTO_SUAVE)
        self._pie = self.etiqueta_pie()
        self.dibujar()

    def dibujar(self):
        lienzo = self.lienzo
        lienzo.delete("all")
        niveles = [Referencias.nivel(c, self.datos[c]["valor"]) for c, _ in self.FILAS]
        niveles = [n for n in niveles if n is not None]
        peor = max(niveles) if niveles else None
        cx, cy, radio, cantidad = 68, self.ALTO / 2, 62, 44
        encendidos = 0 if peor is None else round(cantidad * (peor + 1) / 4)
        for i in range(cantidad):
            angulo = -math.pi / 2 + 2 * math.pi * i / cantidad
            for anillo, r in enumerate((radio, radio - 9)):
                x, y = cx + r * math.cos(angulo), cy + r * math.sin(angulo)
                encendido = i < encendidos
                color = Tema.COLOR_NIVEL[peor] if encendido else (Tema.TEXTO_SUAVE if anillo == 0 else Tema.TENUE)
                rr = (2.2 if anillo == 0 else 1.6) if encendido else (1.4 if anillo == 0 else 1.1)
                lienzo.create_oval(x - rr, y - rr, x + rr, y + rr, fill=color, outline="")
        humo = self.datos["pm25"]["valor"]
        lienzo.create_text(cx, cy - 4, text=self.texto_numero(humo), fill=Tema.TEXTO, font=Tema.fuente(24))
        lienzo.create_text(cx, cy + 22, text="HUMO", fill=Tema.TEXTO_SUAVE, font=Tema.fuente(8))
        x = 150
        for i, (clave, nombre) in enumerate(self.FILAS):
            dato = self.datos[clave]
            y = 22 + i * 44
            nivel = Referencias.nivel(clave, dato["valor"])
            color = Tema.TENUE if nivel is None else Tema.COLOR_NIVEL[nivel]
            lienzo.create_oval(x, y + 3, x + 7, y + 10, fill=color, outline="")
            lienzo.create_text(x + 14, y, anchor="nw", text=nombre, fill=Tema.TEXTO, font=Tema.fuente(10))
            desvio = Referencias.desvio(clave, dato["valor"])
            lienzo.create_text(self.ANCHO - 2, y, anchor="ne", text=self.texto_numero(dato["valor"]),
                               fill=Referencias.color(clave, dato["valor"]), font=Tema.fuente(13))
            texto, color_ref = Referencias.indicador(clave, dato["valor"], corto=True)
            if desvio:
                texto = "{}  MÁX {}".format(texto, Referencias.rango(clave)[2:])
            lienzo.create_text(self.ANCHO - 2, y + 21, anchor="ne", text=texto, fill=color_ref, font=Tema.fuente(8))
            lienzo.create_text(x + 14, y + 19, anchor="nw", fill=color, font=Tema.fuente(9),
                               text="--" if nivel is None else Tema.NOMBRES[nivel])
        ideales = [self.texto_ideal(self.datos[c]["valor"], self.datos[c]["ideal"]) for c in ("pm25",)]
        self._pie.config(text=("HUMO " + ideales[0]) if ideales[0] else "")


class TarjetaAlumnos(TarjetaLecturas):
    """Alumnos en el aula (numero grande) y el aforo como una grilla de puntos."""

    CAPACIDAD = 30
    ANCHO = 250

    def __init__(self, padre, numero):
        super().__init__(padre, numero, "Alumnos en el aula", ["dentro", "salidas"])
        self._salieron = self.etiqueta_pie()
        self._puerta = self.etiqueta_pie(lado="right")
        self.dibujar()

    def poner_puerta(self, texto, ok=True):
        self._puerta.config(text=texto, fg=Tema.TEXTO_SUAVE if ok else Tema.ACENTO)

    def dibujar(self):
        lienzo = self.lienzo
        lienzo.delete("all")
        dentro = self.datos["dentro"]["valor"]
        nivel = Referencias.nivel("dentro", dentro)
        self.numero_grande(-3, -6, self.texto_numero(dentro), self.color_nivel(nivel))
        desvio = Referencias.desvio("dentro", dentro)
        if desvio:
            texto = "{} · ▲ {:g} SOBRE EL AFORO ({})".format(Tema.NOMBRES[nivel], desvio, self.CAPACIDAD)
        elif nivel is None:
            texto = "AFORO MÁXIMO {}".format(self.CAPACIDAD)
        else:
            texto = "{} · AFORO MÁXIMO {}".format(Tema.NOMBRES[nivel], self.CAPACIDAD)
        color = self.color_nivel(nivel, Tema.TEXTO_SUAVE)
        lienzo.create_text(0, 60, anchor="nw", text=texto, fill=color, font=Tema.fuente(9))
        # Grilla de aforo: 10 x 3 puntos
        x0, y0, paso = 0, 96, 13
        for i in range(self.CAPACIDAD):
            fila, columna = divmod(i, 10)
            x, y = x0 + columna * paso + 5, y0 + fila * paso + 5
            lleno = dentro is not None and i < dentro
            color = self.color_nivel(nivel) if lleno else Tema.TENUE
            r = 3.2 if lleno else 2
            lienzo.create_oval(x - r, y - r, x + r, y + r, fill=color, outline="")
        salidas = self.datos["salidas"]["valor"]
        self._salieron.config(text="SALIERON {}".format(self.texto_numero(salidas)))


class TarjetaAmbiente(TarjetaLecturas):
    """Temperatura y humedad, con una linea de puntos de la temperatura."""

    def __init__(self, padre, numero):
        super().__init__(padre, numero, "Ambiente", ["temp", "hum"])
        self._ideal = self.etiqueta_pie()
        self.dibujar()

    def dibujar(self):
        lienzo = self.lienzo
        lienzo.delete("all")
        for x, clave, unidad, nombre in ((0, "temp", "°C", "TEMP"), (138, "hum", "%", "HUMEDAD")):
            lienzo.create_text(x, 0, anchor="nw", text=nombre, fill=Tema.TEXTO_SUAVE, font=Tema.fuente(8))
            valor = self.datos[clave]["valor"]
            ancho = self.numero_grande(x - 2, 12, self.texto_numero(valor), Referencias.color(clave, valor),
                                       tamano=26)
            lienzo.create_text(x + ancho + 4, 50, anchor="sw", text=unidad, fill=Tema.TEXTO_SUAVE,
                               font=Tema.fuente(9))
            desvio = Referencias.desvio(clave, valor)
            color = Referencias.color(clave, valor, Tema.TEXTO_SUAVE)
            if desvio is None:
                texto = "RECOM. " + Referencias.rango(clave)
            elif desvio:
                texto = "{} {:+g}".format(Referencias.nombre_nivel(clave, valor), round(desvio, 1))
            else:
                texto = "{} · {}".format(Referencias.nombre_nivel(clave, valor), Referencias.rango(clave))
            lienzo.create_text(x, 58, anchor="nw", text=texto, fill=color, font=Tema.fuente(9))
        # Linea de puntos con la temperatura (como un monitor)
        valores = list(self.historia["temp"])[-46:]
        y_medio, alto = 118, 26
        if len(valores) > 1:
            minimo, maximo = min(valores), max(valores)
            rango = (maximo - minimo) or 1
            for i, valor in enumerate(valores):
                x = i * (self.ANCHO - 4) / 45 + 2
                y = y_medio + alto / 2 - (valor - minimo) / rango * alto
                ultimo = i == len(valores) - 1
                r = 2.6 if ultimo else 1.5
                lienzo.create_oval(x - r, y - r, x + r, y + r, outline="",
                                   fill=Tema.ACENTO if ultimo else Tema.TEXTO_SUAVE)
        else:
            for i in range(46):
                x = i * (self.ANCHO - 4) / 45 + 2
                lienzo.create_oval(x - 1.2, y_medio - 1.2, x + 1.2, y_medio + 1.2, fill=Tema.TENUE, outline="")
        ideal = self.texto_ideal(self.datos["temp"]["valor"], self.datos["temp"]["ideal"])
        self._ideal.config(text=("TEMP " + ideal) if ideal else "")


class EstadoAire(tk.Canvas):
    """La calificacion del aire en letras de puntos grandes ("MUY MALO"), con su color."""

    def __init__(self, padre, ancho=480, alto=64):
        super().__init__(padre, width=ancho, height=alto, bg=padre.cget("bg"), highlightthickness=0, bd=0)
        self._ancho = ancho
        self.texto = "--"
        self.color = Tema.COLOR_NEUTRO
        self.poner("--")

    def poner(self, texto, color=None):
        texto = Tema.nombre(texto)          # MODERADO -> NORMAL, MUY MALO -> RIESGOSO
        self.texto = texto
        self.color = color or Tema.color_de(texto)
        self.delete("all")
        paso = 8
        while MatrizPuntos.medir(texto, paso) > self._ancho and paso > 4:
            paso -= 1
        MatrizPuntos.dibujar(self, 0, 4, texto, paso=paso, radio=paso * 0.45, color=self.color)


class PasosIdeal(tk.Canvas):
    """Pasos del ambiente ideal: PRUEBA -> MEDICION -> LISTO, con el porcentaje.

    Se usa como una barra de progreso: barra["value"] = 0..100, y poner_estado(estado).
    """

    PASOS = ("PRUEBA", "MEDICIÓN", "LISTO")

    def __init__(self, padre, ancho=480, alto=56):
        super().__init__(padre, width=ancho, height=alto, bg=padre.cget("bg"), highlightthickness=0, bd=0)
        self._ancho = ancho
        self._valor = 0
        self.estado = "SIN_IDEAL"
        self._dibujar()

    def __setitem__(self, clave, valor):
        if clave == "value":
            self._valor = valor
            self._dibujar()
        else:
            super().__setitem__(clave, valor)

    def __getitem__(self, clave):
        return self._valor if clave == "value" else super().__getitem__(clave)

    def poner_estado(self, estado):
        self.estado = estado
        self._dibujar()

    def _dibujar(self):
        self.delete("all")
        hechos = {"SIN_IDEAL": 0, "FALLO": 0, "PROBANDO": 0, "MIDIENDO": 1, "LISTO": 3}.get(self.estado, 0)
        actual = {"PROBANDO": 0, "MIDIENDO": 1}.get(self.estado)
        xs = [32, 168, 304]
        y = 16
        for i in range(2):
            color = Tema.TEXTO_SUAVE if i < hechos else Tema.TENUE
            for x in range(xs[i] + 18, xs[i + 1] - 16, 8):
                self.create_oval(x - 1.3, y - 1.3, x + 1.3, y + 1.3, fill=color, outline="")
        for i, (x, nombre) in enumerate(zip(xs, self.PASOS)):
            if i < hechos:
                self.create_oval(x - 12, y - 12, x + 12, y + 12, fill=Tema.ACENTO, outline="")
                self.create_text(x, y, text="✓", fill="#141414", font=Tema.fuente(11, True))
            elif i == actual:
                self.create_oval(x - 12, y - 12, x + 12, y + 12, outline=Tema.ACENTO, width=2)
                self.create_oval(x - 4, y - 4, x + 4, y + 4, fill=Tema.ACENTO, outline="")
            else:
                color = Tema.ACENTO if self.estado == "FALLO" and i == 0 else Tema.TEXTO_SUAVE
                self.create_oval(x - 12, y - 12, x + 12, y + 12, outline=color, width=1.5)
            self.create_text(x, y + 22, text=nombre, anchor="n", fill=Tema.TEXTO_SUAVE, font=Tema.fuente(8))
        porcentaje = 100 if self.estado == "LISTO" else int(self._valor or 0)
        self.create_text(self._ancho - 2, y + 4, anchor="e", text="{}%".format(porcentaje),
                         fill=Tema.ACENTO if porcentaje else Tema.TEXTO_SUAVE, font=Tema.fuente(20))
