"""Software de control de la estacion de calidad del aire (se ejecuta en la PC).

Recibe los datos del ESP32 por el cable USB, los muestra en una ventana,
avisa con una alarma cuando el aire es MALO o MUY MALO, permite cambiar
los ajustes de la estacion y medir (o borrar) el ambiente ideal.

Uso:   python control_estacion.py
Requiere pyserial para conectarse al ESP32:   pip install pyserial
(El puerto "Simulador" funciona sin ESP32 y sin pyserial.)
"""
import json
import os
import queue
import random
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from componentes import (Aviso, BotonIcono, EstadoAire, MatrizPuntos, Panel, PasosIdeal, Referencias,
                         TarjetaAlumnos,
                         TarjetaAmbiente, TarjetaCO2, TarjetaParticulas, Tema)
from estadisticas import Estadistica, PanelEstadistica, RegistroDatos


# =====================================================================
# Enlaces: como llegan los datos a la PC
# =====================================================================
class Enlace:
    """Clase base de la conexion con la estacion.

    Lo recibido se deja en self.cola como tuplas (tipo, contenido), con tipo
    "DATOS", "RESP", "TEXTO" o "ERROR". Cada clase hija define como conectar,
    desconectar y enviar.
    """

    def __init__(self):
        self.cola = queue.Queue()
        self.conectado = False

    def conectar(self, puerto):
        raise NotImplementedError

    def desconectar(self):
        raise NotImplementedError

    def enviar(self, comando):
        raise NotImplementedError

    def _recibir_linea(self, linea):
        """Clasifica una linea de texto llegada desde la estacion."""
        for tipo in ("DATOS", "RESP"):
            if linea.startswith(tipo + " "):
                try:
                    self.cola.put((tipo, json.loads(linea[len(tipo) + 1:])))
                except ValueError:
                    pass  # linea cortada o con ruido: se ignora
                return
        if linea:
            self.cola.put(("TEXTO", linea))


class EnlaceSerial(Enlace):
    """Conexion real con el ESP32 por el puerto serie del cable USB."""

    BAUDIOS = 115200

    def __init__(self):
        super().__init__()
        self._serie = None
        self._hilo = None

    @staticmethod
    def puertos():
        """Lista los puertos serie disponibles (vacia si falta pyserial)."""
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        return [puerto.device for puerto in list_ports.comports()]

    def conectar(self, puerto):
        try:
            import serial
        except ImportError:
            raise OSError("Falta pyserial. Instalalo con:  pip install pyserial")
        try:
            serie = serial.Serial()
            serie.port = puerto
            serie.baudrate = self.BAUDIOS
            serie.timeout = 0.2
            # DTR/RTS apagados: en el ESP32 DevKit pueden dejar la placa en reinicio.
            serie.dtr = False
            serie.rts = False
            serie.open()
            self._serie = serie
        except serial.SerialException as error:
            raise OSError("No se pudo abrir {} (cierra Thonny si esta abierto): {}".format(puerto, error))
        self.conectado = True
        self._hilo = threading.Thread(target=self._leer, daemon=True)
        self._hilo.start()

    def _leer(self):
        while self.conectado:
            try:
                linea = self._serie.readline()
            except Exception as error:
                if self.conectado:
                    self.conectado = False
                    self.cola.put(("ERROR", "Se perdio la conexion: {}".format(error)))
                break
            if linea:
                self._recibir_linea(linea.decode("utf-8", "replace").strip())

    def enviar(self, comando):
        self._serie.write((json.dumps(comando) + "\n").encode("utf-8"))

    def desconectar(self):
        self.conectado = False
        if self._hilo:
            self._hilo.join(timeout=1)
        if self._serie:
            self._serie.close()


class EnlaceSimulado(Enlace):
    """Estacion de mentira para probar el programa sin el ESP32.

    Imita al ESP32: envia lecturas cada cierto tiempo y obedece los mismos comandos.
    Para no esperar una hora, en el simulador 1 minuto de medicion dura 1 segundo.
    """

    NIVELES = ("BUENO", "MODERADO", "MALO", "MUY MALO")
    VARIABLES = ("co2", "temp", "hum", "pm1", "pm25", "pm10")
    PRUEBA_S = 2
    LIMITES_PM10 = (54, 154, 254)
    CAPACIDAD = 30

    def __init__(self):
        super().__init__()
        self._hilo = None
        self._co2 = 650.0
        self._pm25 = 8.0
        self._polvo = 0.0
        self._dormido = False
        self._lim_co2 = [799, 1199, 1999]
        self._lim_pm25 = [12, 35.4, 55.4]
        self._t_lectura = 1000
        self._t_pantalla = 2000
        # Ambiente ideal simulado
        self._ideal_estado = "SIN_IDEAL"
        self._ideal_mensaje = "Aun no se midio el ambiente ideal"
        self._ideal_valores = None
        self._ideal_prueba = {}
        self._ideal_inicio = 0
        self._ideal_minutos = 60
        self._ideal_muestras = []
        # Puerta simulada
        self._dentro = 0
        self._entradas = 0
        self._salidas = 0
        self._umbral_cm = 70

    def _midiendo_ideal(self):
        return self._ideal_estado in ("PROBANDO", "MIDIENDO")

    def _resumen_ideal(self):
        progreso, restante_s = 0, 0
        if self._ideal_estado == "MIDIENDO":
            transcurrido = time.time() - self._ideal_inicio
            progreso = min(100, int(transcurrido * 100 / self._ideal_minutos))
            restante_s = int(max(0, self._ideal_minutos - transcurrido) * 60)
        return {
            "estado": self._ideal_estado, "mensaje": self._ideal_mensaje,
            "progreso": progreso, "restante_s": restante_s, "minutos": self._ideal_minutos,
            "prueba": self._ideal_prueba, "valores": self._ideal_valores,
        }

    def _avanzar_ideal(self, lecturas):
        transcurrido = time.time() - self._ideal_inicio
        if self._ideal_estado == "PROBANDO" and transcurrido >= self.PRUEBA_S:
            self._ideal_prueba = {"SCD40": True, "PMS5003": not self._dormido, "DHT11": True, "OLED": True}
            self._ideal_estado = "MIDIENDO"
            self._ideal_inicio = time.time()
            self._ideal_mensaje = "Prueba superada, midiendo el ambiente"
        elif self._ideal_estado == "MIDIENDO":
            self._ideal_muestras.append(lecturas)
            if transcurrido >= self._ideal_minutos:
                self._ideal_valores = {
                    v: round(sum(m[v] for m in self._ideal_muestras) / len(self._ideal_muestras), 1)
                    for v in self.VARIABLES
                }
                self._ideal_estado = "LISTO"
                self._ideal_mensaje = "Ambiente ideal guardado ({} min)".format(self._ideal_minutos)

    @staticmethod
    def _nivel(valor, limites):
        if valor is None:
            return None
        for nivel, limite in enumerate(limites):
            if valor <= limite:
                return nivel
        return len(limites)

    def _alerta(self, n_pm1, n_pm25, n_pm10):
        finas = [n for n in (n_pm1, n_pm25) if n is not None]
        humo = bool(finas) and max(finas) >= 2
        polvo = n_pm10 is not None and n_pm10 >= 2
        if humo and polvo:
            return "HUMO_POLVO"
        return "HUMO" if humo else "POLVO" if polvo else None

    def _estado(self):
        co2 = round(self._co2)
        pm25 = None if self._dormido else round(self._pm25)
        pm1 = None if pm25 is None else max(0, pm25 - 3)
        pm10 = None if pm25 is None else round(pm25 + 6 + self._polvo)
        n_co2 = self._nivel(co2, self._lim_co2)
        n_pm25 = self._nivel(pm25, self._lim_pm25)
        n_pm1 = self._nivel(pm1, self._lim_pm25)
        n_pm10 = self._nivel(pm10, self.LIMITES_PM10)
        niveles = [n for n in (n_co2, n_pm25, n_pm10) if n is not None]
        return {
            "co2": co2, "temp": round(22 + 0.12 * self._dentro, 1), "hum": round(45 + 0.5 * self._dentro),
            "pm1": pm1, "pm25": pm25, "pm10": pm10,
            "n_pm1": n_pm1, "n_pm10": n_pm10, "alerta_pm": self._alerta(n_pm1, n_pm25, n_pm10),
            "estado": self.NIVELES[max(niveles)], "n_co2": n_co2, "n_pm25": n_pm25,
            "calentando": False, "pms_dormido": self._dormido,
            "lim_co2": self._lim_co2, "lim_pm25": self._lim_pm25,
            "t_lectura": self._t_lectura, "t_pantalla": self._t_pantalla,
            "ideal": self._resumen_ideal(),
            "personas": {
                "dentro": self._dentro, "entradas": self._entradas, "salidas": self._salidas,
                "umbral_cm": self._umbral_cm, "exterior_ok": True, "interior_ok": True,
            },
        }

    def _mover_personas(self):
        """A veces entra o sale alguien; con mas gente dentro, el CO2 sube mas rapido."""
        if self._dentro < self.CAPACIDAD and random.random() < 0.25:
            self._entradas += 1
            self._dentro += 1
            self.cola.put(("TEXTO", "Entro un alumno. En el aula: {}".format(self._dentro)))
        elif self._dentro and random.random() < 0.2:
            self._salidas += 1
            self._dentro -= 1
            self.cola.put(("TEXTO", "Salio un alumno. En el aula: {}".format(self._dentro)))
        self._co2 += self._dentro * 2

    def _generar(self):
        self.cola.put(("TEXTO", "Simulador listo. Midiendo calidad del aire..."))
        while self.conectado:
            # El aula se va cargando de CO2 y a veces se abre una ventana.
            self._co2 += random.uniform(5, 45)
            if self._co2 > 2300:
                self._co2 = 600
            self._pm25 = max(2, self._pm25 + random.uniform(-3, 4))
            if self._pm25 > 70:
                self._pm25 = 6
            # De vez en cuando alguien levanta polvo (barre, sacude la tiza...).
            self._polvo *= 0.85
            if random.random() < 0.04:
                self._polvo = 200
            self._mover_personas()
            if self._midiendo_ideal() and not self._dormido:
                datos = self._estado()
                self._avanzar_ideal({v: datos[v] for v in self.VARIABLES})
            self.cola.put(("DATOS", self._estado()))
            time.sleep(self._t_pantalla / 1000)

    def conectar(self, puerto):
        self.conectado = True
        self._hilo = threading.Thread(target=self._generar, daemon=True)
        self._hilo.start()

    def enviar(self, comando):
        nombre = comando.get("cmd")
        if nombre == "limites":
            self._lim_co2, self._lim_pm25 = comando["co2"], comando["pm25"]
            mensaje = "Limites actualizados"
        elif nombre == "intervalos":
            self._t_lectura, self._t_pantalla = comando["lectura"], comando["pantalla"]
            mensaje = "Intervalos actualizados"
        elif nombre == "personas" and comando.get("accion") == "umbral":
            self._umbral_cm = int(comando["cm"])
            mensaje = "Umbral de la puerta: {} cm".format(self._umbral_cm)
        elif nombre == "personas":
            self._dentro = self._entradas = self._salidas = 0
            mensaje = "Conteo de alumnos en cero"
        elif nombre == "ideal" and comando.get("accion") == "iniciar":
            if self._midiendo_ideal():
                self.cola.put(("RESP", {"ok": False, "msg": "Ya se esta midiendo; resetea para cancelar"}))
                return
            self._dormido = False
            self._ideal_minutos = int(comando.get("minutos", 60))
            self._ideal_muestras = []
            self._ideal_prueba = {}
            self._ideal_inicio = time.time()
            self._ideal_estado = "PROBANDO"
            self._ideal_mensaje = "Prueba de funcionamiento en curso"
            mensaje = "Prueba de funcionamiento iniciada; luego medira {} min".format(self._ideal_minutos)
        elif nombre == "ideal":
            self._ideal_estado = "SIN_IDEAL"
            self._ideal_valores = None
            self._ideal_prueba = {}
            self._ideal_mensaje = "Ambiente ideal borrado"
            mensaje = "Ambiente ideal borrado"
        else:
            if comando.get("dormir") and self._midiendo_ideal():
                self.cola.put(("RESP", {"ok": False, "msg": "No se puede dormir el sensor de polvo y humo mientras se mide el ambiente ideal"}))
                return
            self._dormido = bool(comando.get("dormir"))
            mensaje = "Sensor de polvo y humo dormido" if self._dormido else "Sensor de polvo y humo despierto"
        self.cola.put(("RESP", {"ok": True, "msg": mensaje}))
        self.cola.put(("DATOS", self._estado()))

    def desconectar(self):
        self.conectado = False


# =====================================================================
# Alarma
# =====================================================================
class Alarma:
    """Decide cuando avisar: se activa con MALO o MUY MALO y puede silenciarse.

    Si el aire mejora y luego vuelve a empeorar, la alarma suena de nuevo.
    """

    ESTADOS_DE_ALARMA = ("MALO", "MUY MALO")
    REPETIR_SONIDO_S = 4

    def __init__(self):
        self.activa = False
        self.silenciada = False
        self.con_sonido = True
        self._ultimo_sonido = 0

    def evaluar(self, estado):
        """Recibe la calificacion del aire. Devuelve True si hay alarma."""
        hay_alarma = estado in self.ESTADOS_DE_ALARMA
        if hay_alarma and not self.activa:
            self.silenciada = False
        self.activa = hay_alarma
        return hay_alarma

    def silenciar(self):
        self.silenciada = True

    def apagar(self):
        self.activa = False
        self.silenciada = False

    def debe_sonar(self):
        if not (self.activa and self.con_sonido and not self.silenciada):
            return False
        ahora = time.time()
        if ahora - self._ultimo_sonido < self.REPETIR_SONIDO_S:
            return False
        self._ultimo_sonido = ahora
        return True

    @staticmethod
    def sonar(ventana):
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONHAND)
        except Exception:
            ventana.bell()


# =====================================================================
# Ventana
# =====================================================================
class VentanaControl(tk.Tk):
    """Ventana principal del software de control."""

    TITULO = "Sistema de Monitoreo de la Calidad del Aire y Aforo del Aula"
    SIMULADOR = "Simulador"
    COLORES = {n: c for n, c in zip(Tema.NIVELES, Tema.COLOR_NIVEL)}
    COLOR_NEUTRO = Tema.COLOR_NEUTRO
    COLORES_NIVEL = ("#2e7d32", "#b28704", "#ef6c00", "#c62828")   # texto de los numeros
    SIN_DATOS_S = 10
    LUGAR_POR_DEFECTO = "Laboratorio A"
    MINUTOS_REGISTRO = 5          # grabar un promedio cada 5 minutos
    CARPETA_REGISTROS = Path(__file__).resolve().parent / "registros"
    DIAS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")
    REFRESCO_ESTADISTICA_S = 60
    # Nombres simples de cada dispositivo en la prueba de funcionamiento.
    NOMBRES_PRUEBA = {"SCD40": "CO2", "PMS5003": "Polvo y humo", "DHT11": "Temp/hum",
                      "OLED": "Pantalla", "PUERTA": "Puerta"}
    # Alertas de particulas que envia la estacion: (que pasa, que hacer)
    ALERTAS_PM = {
        "HUMO": ("humo o contaminacion en el aire",
                 "Si viene de afuera, cierra las ventanas."),
        "POLVO": ("mucho polvo en el aire",
                  "Ventila el aula y evita levantar polvo."),
        "HUMO_POLVO": ("humo y polvo en el aire",
                       "Revisa de donde vienen antes de abrir las ventanas."),
    }
    def __init__(self):
        super().__init__()
        self.title(self.TITULO)
        self.configure(bg=Tema.FONDO)
        self.resizable(False, False)
        Tema.aplicar_estilos(self)
        self._poner_icono_ventana()
        Tema.barra_oscura(self)

        self.enlace = None
        self.alarma = Alarma()
        self._ajustes_cargados = False
        self._pms_dormido = False
        self._ultimo_dato = 0
        self._ultima_estadistica = 0
        self._controles = []
        self._ideal_anterior = None
        self._ideal_midiendo = False
        self._hay_ideal = False
        self.registro_datos = RegistroDatos(self.CARPETA_REGISTROS, self.LUGAR_POR_DEFECTO, self.MINUTOS_REGISTRO)

        self._crear_conexion()
        grilla = tk.Frame(self, bg=Tema.FONDO)
        grilla.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        # Fila de arriba: 01 estado, 02 CO2, 03 particulas, 04 alumnos, 05 ambiente
        self._crear_estado(grilla).grid(row=0, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        self._crear_lecturas(grilla)
        # Abajo: a la izquierda ideal, mensajes y ajustes; a la derecha el historial
        izquierda = tk.Frame(grilla, bg=Tema.FONDO)
        izquierda.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self._crear_ideal(izquierda)
        self._crear_registro(izquierda)
        self._crear_ajustes(izquierda)
        self._crear_mas_ajustes()
        self._crear_estadisticas(grilla)

        self.actualizar_puertos()
        self._habilitar_ajustes(False)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        self.panel_estadistica.actualizar()
        self.after(200, self._revisar)

    # ---------- Construccion de la ventana ----------
    def _poner_icono_ventana(self):
        """Icono de la barra de titulo: un anillo de puntos naranja, dibujado punto por punto."""
        imagen = tk.PhotoImage(width=32, height=32)
        for y in range(32):
            fila = []
            for x in range(32):
                d = ((x - 15.5) ** 2 + (y - 15.5) ** 2) ** 0.5
                fila.append("#ff5a36" if 9 <= d <= 14 or d <= 4 else "#18191c")
            imagen.put("{" + " ".join(fila) + "}", to=(0, y))
        self._imagen_icono = imagen
        self.iconphoto(True, imagen)

    def _crear_conexion(self):
        """Encabezado: titulo de puntos, estado de la conexion, puerto y fecha/hora."""
        marco = tk.Frame(self, bg=Tema.FONDO)
        marco.pack(fill="x", padx=20, pady=(14, 12))
        titulo = tk.Frame(marco, bg=Tema.FONDO)
        titulo.pack(side="left")
        lienzo = tk.Canvas(titulo, width=420, height=26, bg=Tema.FONDO, highlightthickness=0, bd=0)
        lienzo.pack(anchor="w")
        MatrizPuntos.dibujar(lienzo, 0, 1, "CALIDAD DEL AIRE", paso=3.4, radio=1.25, color=Tema.TEXTO)
        linea = tk.Frame(titulo, bg=Tema.FONDO)
        linea.pack(anchor="w", pady=(4, 0))
        tk.Label(linea, text="MONITOREO Y AFORO DEL AULA", bg=Tema.FONDO, fg=Tema.TEXTO_SUAVE,
                 font=Tema.fuente(9)).pack(side="left", padx=(0, 16))
        self._punto = tk.Label(linea, text="●", bg=Tema.FONDO, fg=Tema.GRIS, font=Tema.fuente(9))
        self._punto.pack(side="left", padx=(0, 6))
        self._conexion = tk.Label(linea, text="Desconectado", bg=Tema.FONDO, fg=Tema.TEXTO_SUAVE,
                                  font=Tema.fuente(9))
        self._conexion.pack(side="left")

        leyenda = tk.Frame(marco, bg=Tema.FONDO)
        leyenda.pack(side="left", padx=(48, 0))
        fila = tk.Frame(leyenda, bg=Tema.FONDO)
        fila.pack(anchor="w", pady=(2, 0))
        for nombre, color in zip(Tema.NOMBRES, Tema.COLOR_NIVEL):
            tk.Label(fila, text="●", bg=Tema.FONDO, fg=color, font=Tema.fuente(12)).pack(side="left")
            tk.Label(fila, text=nombre, bg=Tema.FONDO, fg=Tema.TEXTO, font=Tema.fuente(9)).pack(
                side="left", padx=(2, 12))

        reloj = tk.Frame(marco, bg=Tema.FONDO)
        reloj.pack(side="right")
        self._hora = tk.Label(reloj, text="", bg=Tema.FONDO, fg=Tema.TEXTO, font=Tema.fuente(20))
        self._hora.pack(anchor="e")
        self._reloj = tk.Label(reloj, text="", bg=Tema.FONDO, fg=Tema.TEXTO_SUAVE, font=Tema.fuente(9))
        self._reloj.pack(anchor="e")

        controles = tk.Frame(marco, bg=Tema.FONDO)
        controles.pack(side="right", padx=(0, 32))
        tk.Label(controles, text="PUERTO", bg=Tema.FONDO, fg=Tema.TEXTO_SUAVE,
                 font=Tema.fuente(9)).pack(side="left", padx=(0, 8))
        self._puerto = ttk.Combobox(controles, width=12, state="readonly", font=Tema.fuente(10))
        self._puerto.pack(side="left", padx=(0, 8))
        BotonIcono(controles, "Actualizar", "actualizar", self.actualizar_puertos).pack(side="left", padx=4)
        self._boton_conectar = BotonIcono(controles, "Conectar", "conectar", self.alternar_conexion, "primario")
        self._boton_conectar.pack(side="left", padx=4)

    def _crear_estado(self, padre):
        """01: la calificacion del aire en grande, el aviso y la alarma."""
        panel = Panel(padre, "Calidad del aire", numero=1)
        self._marca_vivo = panel.marca("")
        self._estado = EstadoAire(panel.cuerpo, ancho=400, alto=66)
        self._estado.pack(anchor="w", pady=(6, 2))
        # Que mediciones estan fuera de lo recomendado (y por cuanto)
        self._fuera = tk.Label(panel.cuerpo, text="LA PEOR ENTRE CO2, HUMO Y POLVO", bg=Tema.TARJETA,
                               fg=Tema.TEXTO_SUAVE, font=Tema.fuente(9), anchor="w", justify="left",
                               wraplength=400, height=2)
        self._fuera.pack(fill="x", pady=(0, 6))
        self._aviso = Aviso(panel.cuerpo)
        self._aviso.pack(fill="x")
        abajo = tk.Frame(panel.cuerpo, bg=Tema.TARJETA)
        abajo.pack(fill="x", side="bottom", pady=(10, 0))
        self._con_sonido = tk.BooleanVar(value=True)
        tk.Checkbutton(abajo, text="SONIDO", variable=self._con_sonido, command=self._cambiar_sonido,
                       font=Tema.fuente(9), bd=0, highlightthickness=0, bg=Tema.TARJETA, fg=Tema.TEXTO_SUAVE,
                       activebackground=Tema.TARJETA, activeforeground=Tema.TEXTO,
                       selectcolor=Tema.CAMPO).pack(side="left")
        self._boton_silenciar = BotonIcono(abajo, "Silenciar alarma", "silencio", self.silenciar)
        self._boton_silenciar.pack(side="right")
        self._boton_silenciar.config(state="disabled")
        return panel

    def _crear_lecturas(self, padre):
        """02 CO2, 03 particulas, 04 alumnos y 05 ambiente. Cada lectura queda en self._tarjetas."""
        co2 = TarjetaCO2(padre, 2)
        particulas = TarjetaParticulas(padre, 3)
        self._tarjeta_alumnos = TarjetaAlumnos(padre, 4)
        ambiente = TarjetaAmbiente(padre, 5)
        for columna, tarjeta in enumerate((co2, particulas, self._tarjeta_alumnos, ambiente), start=1):
            tarjeta.grid(row=0, column=columna, sticky="nsew", padx=(0, 0 if columna == 4 else 12), pady=(0, 12))
        self._tarjetas = {"co2": co2.lectura("co2"), "temp": ambiente.lectura("temp"),
                          "hum": ambiente.lectura("hum"), "pm10": particulas.lectura("pm10"),
                          "pm25": particulas.lectura("pm25"), "pm1": particulas.lectura("pm1"),
                          "dentro": self._tarjeta_alumnos.lectura("dentro"),
                          "salidas": self._tarjeta_alumnos.lectura("salidas")}

    def _crear_registro(self, padre):
        panel = Panel(padre, "Mensajes", numero=7)
        panel.pack(fill="both", expand=True, pady=(12, 0))
        self._registro = tk.Text(panel.cuerpo, height=4, width=50, state="disabled", wrap="word",
                                 font=Tema.fuente(9), bd=0, bg=Tema.TARJETA, fg=Tema.TEXTO_SUAVE,
                                 insertbackground=Tema.TEXTO, selectbackground=Tema.CAMPO_HOVER,
                                 highlightthickness=0)
        barra = ttk.Scrollbar(panel.cuerpo, orient="vertical", command=self._registro.yview)
        self._registro.configure(yscrollcommand=barra.set)
        self._registro.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")

    def _etiqueta(self, padre, texto, negrita=False, **opciones):
        fondo = padre.cget("bg")
        return tk.Label(padre, text=texto, bg=fondo, fg=opciones.pop("fg", Tema.TEXTO),
                        font=Tema.fuente(opciones.pop("tamano", 10), negrita), **opciones)

    def _crear_ideal(self, padre):
        """06: prueba de funcionamiento + medicion del ambiente ideal, en tres pasos."""
        panel = Panel(padre, "Ambiente ideal", numero=6)
        panel.pack(fill="x")
        cuerpo = panel.cuerpo
        self._ideal_barra = PasosIdeal(cuerpo, ancho=400, alto=50)
        self._ideal_barra.pack(anchor="w", pady=(4, 4))
        self._ideal_texto = self._etiqueta(cuerpo, "Sin conexion", tamano=9, anchor="w", justify="left",
                                           wraplength=400)
        self._ideal_texto.pack(fill="x")
        self._ideal_prueba = self._etiqueta(cuerpo, "", fg=Tema.TEXTO_SUAVE, tamano=8, anchor="w")
        self._ideal_prueba.pack(fill="x", pady=(2, 8))
        fila = tk.Frame(cuerpo, bg=cuerpo.cget("bg"))
        fila.pack(fill="x")
        self._etiqueta(fila, "MIN", fg=Tema.TEXTO_SUAVE, tamano=9).pack(side="left")
        self._ideal_minutos = ttk.Spinbox(fila, from_=1, to=240, width=4, justify="center", font=Tema.fuente(10))
        self._ideal_minutos.set(60)
        self._ideal_minutos.pack(side="left", padx=(6, 10))
        self._controles.append(self._ideal_minutos)
        self._boton_ideal = self._boton(fila, "Iniciar", self.iniciar_ideal, "iniciar", "primario")
        self._boton_ideal.pack(side="left")
        self._boton_reset = self._boton(fila, "Resetear", self.resetear_ideal, "actualizar")
        self._boton_reset.pack(side="right")

    def _crear_ajustes(self, padre):
        """08: limites de la calificacion y el boton "Mas ajustes"."""
        panel = Panel(padre, "Límites", numero=8)
        panel.pack(fill="x", pady=(12, 0))
        tabla = tk.Frame(panel.cuerpo, bg=panel.cuerpo.cget("bg"))
        tabla.pack(fill="x", pady=(2, 0))
        for columna, texto in enumerate(("", "BUENO ≤", "NORMAL ≤", "MALO ≤")):
            tk.Label(tabla, text=texto, bg=Tema.TARJETA,
                     fg=Tema.COLOR_NIVEL[columna - 1] if columna else Tema.TEXTO_SUAVE, font=Tema.fuente(8),
                     anchor="w" if columna == 0 else "center").grid(row=0, column=columna, sticky="ew")
        self._lim_co2 = self._fila_entradas(tabla, 1, "CO2 ppm", 3)
        self._lim_pm25 = self._fila_entradas(tabla, 2, "HUMO µg/m³", 3)
        botones = tk.Frame(panel.cuerpo, bg=panel.cuerpo.cget("bg"))
        botones.pack(fill="x", pady=(8, 0))
        self._boton(botones, "Aplicar", self.aplicar_limites, "check").pack(side="left")
        BotonIcono(botones, "Más ajustes", "ajustes", self.mostrar_mas_ajustes).pack(side="right")

    def _crear_mas_ajustes(self):
        """Ventana "Mas ajustes": intervalos, sensor de polvo y humo, puerta y registro.

        Se crea al inicio y queda oculta; el boton "Mas ajustes" la muestra."""
        ventana = tk.Toplevel(self, bg=Tema.FONDO)
        ventana.title("Más ajustes de la estación")
        ventana.resizable(False, False)
        ventana.withdraw()
        ventana.protocol("WM_DELETE_WINDOW", ventana.withdraw)
        self._ventana_ajustes = ventana
        marco = tk.Frame(ventana, bg=Tema.FONDO)
        marco.pack(padx=14, pady=14)

        lecturas = Panel(marco, "Cada cuánto mide", numero=1)
        lecturas.pack(fill="x", pady=(0, 10))
        tabla = tk.Frame(lecturas.cuerpo, bg=lecturas.cuerpo.cget("bg"))
        tabla.pack(fill="x")
        self._etiqueta(tabla, "LEER SENSORES", fg=Tema.TEXTO_SUAVE, tamano=8).grid(row=0, column=1)
        self._etiqueta(tabla, "PANTALLA", fg=Tema.TEXTO_SUAVE, tamano=8).grid(row=0, column=2)
        self._intervalos = self._fila_entradas(tabla, 1, "CADA (ms)", 2)
        self._boton(tabla, "Aplicar", self.aplicar_intervalos, "check").grid(row=1, column=3, padx=8)

        sensor = Panel(marco, "Sensor de polvo y humo (PMS5003)", numero=2)
        sensor.pack(fill="x", pady=(0, 10))
        self._etiqueta(sensor.cuerpo, "Dormirlo alarga la vida del láser y del ventilador.",
                       fg=Tema.TEXTO_SUAVE, tamano=9).pack(anchor="w")
        self._boton_pms = self._boton(sensor.cuerpo, "Dormir", self.alternar_pms)
        self._boton_pms.pack(anchor="w", pady=(6, 0))

        puerta = Panel(marco, "Puerta (conteo de alumnos)", numero=3)
        puerta.pack(fill="x", pady=(0, 10))
        self._puerta = self._etiqueta(puerta.cuerpo, "", tamano=9, anchor="w")
        self._puerta.pack(fill="x")
        tabla = tk.Frame(puerta.cuerpo, bg=puerta.cuerpo.cget("bg"))
        tabla.pack(fill="x", pady=(6, 0))
        self._umbral = self._fila_entradas(tabla, 0, "UMBRAL cm", 1)[0]
        self._boton(tabla, "Aplicar", self.aplicar_umbral, "check").grid(row=0, column=2, padx=8)
        self._boton(tabla, "Reiniciar conteo", self.reiniciar_conteo, "actualizar").grid(row=0, column=3)

        registro = Panel(marco, "Registro (historial)", numero=4)
        registro.pack(fill="x")
        fila = tk.Frame(registro.cuerpo, bg=registro.cuerpo.cget("bg"))
        fila.pack(fill="x")
        self._etiqueta(fila, "LUGAR", fg=Tema.TEXTO_SUAVE, tamano=9).pack(side="left")
        self._lugar = ttk.Entry(fila, width=22, font=Tema.fuente(10))
        self._lugar.insert(0, self.LUGAR_POR_DEFECTO)
        self._lugar.pack(side="left", padx=8)
        self._lugar.bind("<FocusOut>", lambda e: self._cambiar_lugar())
        self._lugar.bind("<Return>", lambda e: self._cambiar_lugar())
        self._grabar = tk.BooleanVar(value=True)
        tk.Checkbutton(fila, text="GRABAR CADA", variable=self._grabar, command=self._cambiar_grabacion,
                       bg=Tema.TARJETA, fg=Tema.TEXTO_SUAVE, activebackground=Tema.TARJETA,
                       activeforeground=Tema.TEXTO, selectcolor=Tema.CAMPO, font=Tema.fuente(9),
                       bd=0, highlightthickness=0).pack(side="left", padx=(8, 4))
        self._minutos = ttk.Spinbox(fila, from_=1, to=60, width=4, justify="center",
                                    command=self._cambiar_minutos, font=Tema.fuente(10))
        self._minutos.set(self.MINUTOS_REGISTRO)
        self._minutos.bind("<FocusOut>", lambda e: self._cambiar_minutos())
        self._minutos.pack(side="left")
        self._etiqueta(fila, "MIN", fg=Tema.TEXTO_SUAVE, tamano=9).pack(side="left", padx=(6, 0))
        self._estado_registro = self._etiqueta(registro.cuerpo, "", fg=Tema.TEXTO_SUAVE, tamano=8, anchor="w")
        self._estado_registro.pack(fill="x", pady=(6, 0))
        botones = tk.Frame(registro.cuerpo, bg=registro.cuerpo.cget("bg"))
        botones.pack(fill="x", pady=(6, 0))
        BotonIcono(botones, "Exportar a Excel", "tabla", self.exportar_excel).pack(side="left")
        BotonIcono(botones, "Abrir carpeta", "carpeta", self.abrir_registros).pack(side="left", padx=8)
        self._mostrar_registro()

    def mostrar_mas_ajustes(self):
        self._ventana_ajustes.deiconify()
        self._ventana_ajustes.lift()
        Tema.barra_oscura(self._ventana_ajustes)

    def _crear_estadisticas(self, padre):
        """09: historial con graficos y tabla."""
        self.panel_estadistica = PanelEstadistica(padre, self.CARPETA_REGISTROS,
                                                  lambda: self.registro_datos.lugar, self.exportar_excel)
        self.panel_estadistica.grid(row=1, column=1, columnspan=4, sticky="nsew")

    def _fila_entradas(self, marco, fila, texto, cantidad):
        fondo = marco.cget("bg")
        tk.Label(marco, text=texto, bg=fondo, fg=Tema.TEXTO_SUAVE, font=Tema.fuente(9),
                 anchor="w", padx=0).grid(row=fila, column=0, sticky="w", pady=4, padx=(0, 10))
        entradas = []
        for columna in range(1, cantidad + 1):
            entrada = ttk.Entry(marco, width=8, justify="center", font=Tema.fuente(10))
            entrada.grid(row=fila, column=columna, padx=4, pady=4)
            entradas.append(entrada)
            self._controles.append(entrada)
        return entradas

    def _boton(self, marco, texto, accion, icono=None, estilo="normal"):
        boton = BotonIcono(marco, texto, icono, accion, estilo)
        self._controles.append(boton)
        return boton

    # ---------- Utilidades ----------
    def registrar(self, texto):
        self._registro.config(state="normal")
        self._registro.insert("end", time.strftime("%H:%M:%S  ") + texto + "\n")
        self._registro.see("end")
        self._registro.config(state="disabled")

    def _habilitar_ajustes(self, habilitar):
        for control in self._controles:
            control.config(state="normal" if habilitar else "disabled")

    @staticmethod
    def _poner_entradas(entradas, valores):
        for entrada, valor in zip(entradas, valores):
            entrada.delete(0, "end")
            entrada.insert(0, "{:g}".format(valor))

    @staticmethod
    def _leer_entradas(entradas, nombre):
        try:
            return [float(entrada.get().replace(",", ".")) for entrada in entradas]
        except ValueError:
            raise ValueError("Revisa {}: solo se aceptan numeros".format(nombre))

    # ---------- Conexion ----------
    def actualizar_puertos(self):
        puertos = EnlaceSerial.puertos() + [self.SIMULADOR]
        self._puerto.config(values=puertos)
        if self._puerto.get() not in puertos:
            self._puerto.set(puertos[0])

    def alternar_conexion(self):
        if self.enlace:
            self.desconectar()
        else:
            self.conectar(self._puerto.get())

    def conectar(self, puerto):
        enlace = EnlaceSimulado() if puerto == self.SIMULADOR else EnlaceSerial()
        try:
            enlace.conectar(puerto)
        except OSError as error:
            self.registrar(str(error))
            return
        self.enlace = enlace
        self._ajustes_cargados = False
        self._cambiar_lugar()
        self._ultimo_dato = time.time()
        self._boton_conectar.config(text="Desconectar")
        self._conexion.config(text="Conectado a " + puerto)
        self._punto.config(fg=Tema.VERDE)
        self._marca_vivo.config(text="● EN VIVO")
        self.panel_estadistica.actualizar()
        self.registrar("Conectado a " + puerto)

    def desconectar(self):
        if not self.enlace:
            return
        self.enlace.desconectar()
        self.enlace = None
        self.registro_datos.cerrar()
        self._mostrar_registro()
        self.alarma.apagar()
        self._boton_conectar.config(text="Conectar")
        self._conexion.config(text="Desconectado")
        self._punto.config(fg=Tema.GRIS)
        self._marca_vivo.config(text="")
        self._estado.poner("--")
        self._fuera.config(text="LA PEOR ENTRE CO2, HUMO Y POLVO", fg=Tema.TEXTO_SUAVE)
        self._aviso.config(text="")
        self._boton_silenciar.config(state="disabled")
        for tarjeta in self._tarjetas.values():
            tarjeta.poner(None)
        self._puerta.config(text="")
        self._ideal_texto.config(text="Sin conexion")
        self._ideal_barra["value"] = 0
        self._ideal_prueba.config(text="")
        self._ideal_anterior = None
        self._ideal_midiendo = False
        self._hay_ideal = False
        self._habilitar_ajustes(False)
        self.registrar("Desconectado")

    def cerrar(self):
        self.desconectar()
        self.destroy()

    # ---------- Recepcion ----------
    def _revisar(self):
        """Se ejecuta 5 veces por segundo: atiende lo recibido y la alarma."""
        if self.enlace:
            try:
                while True:
                    tipo, contenido = self.enlace.cola.get_nowait()
                    self._atender(tipo, contenido)
                    if not self.enlace:
                        break
            except queue.Empty:
                pass

        if self.enlace and time.time() - self._ultimo_dato > self.SIN_DATOS_S:
            self._estado.poner("SIN DATOS", self.COLOR_NEUTRO)
            self._aviso.config(text="La estacion no envia datos. Revisa el cable y que main.py este corriendo.")
            self.alarma.apagar()
            self._boton_silenciar.config(state="disabled")

        if self.alarma.debe_sonar():
            self.alarma.sonar(self)
        self._mostrar_reloj()
        if time.time() - self._ultima_estadistica > self.REFRESCO_ESTADISTICA_S:
            self._ultima_estadistica = time.time()
            self.panel_estadistica.actualizar()
        self.after(200, self._revisar)

    def _atender(self, tipo, contenido):
        if tipo == "DATOS":
            self._mostrar_datos(contenido)
        elif tipo == "RESP":
            self.registrar(("OK: " if contenido.get("ok") else "ERROR: ") + str(contenido.get("msg")))
        elif tipo == "TEXTO":
            # La linea de lecturas que el ESP32 repite para Thonny no se muestra.
            if " | " not in contenido:
                self.registrar(contenido)
        elif tipo == "ERROR":
            self.registrar(contenido)
            self.desconectar()

    def _mostrar_datos(self, datos):
        self._ultimo_dato = time.time()
        filas_antes = self.registro_datos.filas_hoy
        self.registro_datos.agregar(datos)
        self.panel_estadistica.agregar_lectura(datos)
        if self.registro_datos.filas_hoy != filas_antes:
            self._mostrar_registro()
            self.panel_estadistica.actualizar()
        niveles = {"co2": datos.get("n_co2"), "pm25": datos.get("n_pm25"),
                   "pm1": datos.get("n_pm1"), "pm10": datos.get("n_pm10")}
        ideal = datos.get("ideal") or {}
        valores_ideales = ideal.get("valores") or {}
        personas = datos.get("personas") or {}
        valores = dict(datos)
        valores.update(personas)
        Referencias.actualizar_limites(datos.get("lim_co2"), datos.get("lim_pm25"))
        texto, color = Referencias.resumen(valores)
        self._fuera.config(text=texto, fg=color)
        for clave, tarjeta in self._tarjetas.items():
            nivel = niveles.get(clave)
            # Polimorfismo: cada tipo de tarjeta decide como mostrar el dato.
            tarjeta.poner(valores.get(clave), None if nivel is None else self.COLORES_NIVEL[nivel],
                          valores_ideales.get(clave), nivel)
        if personas:
            self._mostrar_puerta(personas)

        estado = datos.get("estado", "--")
        self._estado.poner(estado, self.COLORES.get(estado, self.COLOR_NEUTRO))

        if self.alarma.evaluar(estado):
            alerta = self.ALERTAS_PM.get(datos.get("alerta_pm"))
            if self.alarma.silenciada:
                self._aviso.config(text="Alarma silenciada. " + (alerta[1] if alerta else "Ventila el aula."))
            elif alerta:
                self._aviso.config(text="ALERTA: {}. {}".format(*alerta))
            else:
                self._aviso.config(text="ALARMA: aire {}. Ventila el aula.".format(Tema.nombre(estado)))
            self._boton_silenciar.config(state="disabled" if self.alarma.silenciada else "normal")
        else:
            if datos.get("pms_dormido"):
                self._aviso.config(text="Sensor de polvo y humo dormido: la calificacion usa solo el CO2.")
            elif datos.get("calentando"):
                self._aviso.config(text="El sensor de polvo y humo se esta calentando (30 s).")
            else:
                self._aviso.config(text="")
            self._boton_silenciar.config(state="disabled")

        self._pms_dormido = bool(datos.get("pms_dormido"))
        if not self._ajustes_cargados:
            self._habilitar_ajustes(True)
            self._cargar_ajustes(datos)
        self._boton_pms.config(text="Despertar" if self._pms_dormido else "Dormir")
        if ideal:
            self._mostrar_ideal(ideal)

    def _mostrar_puerta(self, personas):
        """Estado de los dos HC-SR04 de la puerta."""
        exterior = "OK" if personas.get("exterior_ok") else "NO RESPONDE"
        interior = "OK" if personas.get("interior_ok") else "NO RESPONDE"
        self._puerta.config(text="sensor exterior {}   sensor interior {}".format(exterior, interior),
                            fg=Tema.TEXTO if exterior == interior == "OK" else Tema.ROJO)
        ok = exterior == interior == "OK"
        self._tarjeta_alumnos.poner_puerta("PUERTA OK" if ok else "PUERTA: REVISAR", ok)

    def _mostrar_ideal(self, ideal):
        """Actualiza el panel del ambiente ideal y anota en Mensajes cada cambio de etapa."""
        estado = ideal.get("estado")
        mensaje = ideal.get("mensaje", "")
        if estado != self._ideal_anterior:
            if self._ideal_anterior is not None:
                self.registrar("Ambiente ideal: " + mensaje)
            self._ideal_anterior = estado

        if estado == "PROBANDO":
            texto = "Prueba de funcionamiento: comprobando que los sensores respondan..."
        elif estado == "MIDIENDO":
            texto = "Midiendo: {}%, faltan {} min. No ventiles ni cambies el ambiente.".format(
                ideal.get("progreso", 0), (ideal.get("restante_s", 0) + 59) // 60)
        elif estado == "LISTO":
            texto = mensaje
        elif estado == "FALLO":
            texto = mensaje + ". Revisa las conexiones y vuelve a iniciar."
        else:
            texto = "Sin ambiente ideal. Deja el aula en su estado normal y pulsa Iniciar."
        self._ideal_texto.config(text=texto)
        self._ideal_barra.poner_estado(estado)
        self._ideal_barra["value"] = 100 if estado == "LISTO" else ideal.get("progreso", 0)

        prueba = ideal.get("prueba") or {}
        self._ideal_prueba.config(text="Prueba:   " + "   ".join(
            "{} {}".format(self.NOMBRES_PRUEBA.get(nombre, nombre), "OK" if responde else "NO RESPONDE")
            for nombre, responde in prueba.items()) if prueba else "")

        self._ideal_midiendo = estado in ("PROBANDO", "MIDIENDO")
        self._hay_ideal = bool(ideal.get("valores"))
        bloqueado = "disabled" if self._ideal_midiendo else "normal"
        self._boton_ideal.config(state=bloqueado)
        self._ideal_minutos.config(state=bloqueado)
        self._boton_pms.config(state=bloqueado)
        self._boton_reset.config(text="Cancelar" if self._ideal_midiendo else "Resetear")

    def _cargar_ajustes(self, datos):
        """Copia a las casillas los ajustes que tiene la estacion."""
        try:
            self._poner_entradas(self._lim_co2, datos["lim_co2"])
            self._poner_entradas(self._lim_pm25, datos["lim_pm25"])
            self._poner_entradas(self._intervalos, [datos["t_lectura"], datos["t_pantalla"]])
            if datos.get("personas"):
                self._poner_entradas([self._umbral], [datos["personas"]["umbral_cm"]])
            self._ajustes_cargados = True
        except (KeyError, TypeError, ValueError):
            pass

    # ---------- Acciones ----------
    def _enviar(self, comando):
        if not self.enlace:
            return
        try:
            self.enlace.enviar(comando)
        except Exception as error:
            self.registrar("No se pudo enviar: {}".format(error))

    def aplicar_limites(self):
        try:
            co2 = self._leer_entradas(self._lim_co2, "los limites de CO2")
            pm25 = self._leer_entradas(self._lim_pm25, "los limites de humo")
            for nombre, valores in (("CO2", co2), ("humo", pm25)):
                if not 0 < valores[0] < valores[1] < valores[2]:
                    raise ValueError("Los limites de {} deben ir de menor a mayor".format(nombre))
        except ValueError as error:
            self.registrar("ERROR: {}".format(error))
            return
        self._enviar({"cmd": "limites", "co2": co2, "pm25": pm25})

    def aplicar_intervalos(self):
        try:
            lectura, pantalla = self._leer_entradas(self._intervalos, "los intervalos")
            if not 500 <= lectura <= 60000:
                raise ValueError("Leer sensores: entre 500 y 60000 ms")
            if not 1000 <= pantalla <= 60000:
                raise ValueError("Actualizar pantalla: entre 1000 y 60000 ms")
        except ValueError as error:
            self.registrar("ERROR: {}".format(error))
            return
        self._enviar({"cmd": "intervalos", "lectura": int(lectura), "pantalla": int(pantalla)})

    # ---------- Registro y estadisticas ----------
    def _mostrar_reloj(self):
        ahora = datetime.now()
        self._reloj.config(text="{} {}".format(self.DIAS[ahora.weekday()][:3].upper(), ahora.strftime("%d/%m/%Y")))
        self._hora.config(text=ahora.strftime("%H:%M:%S"))

    def _cambiar_lugar(self):
        lugar = self._lugar.get().strip() or self.LUGAR_POR_DEFECTO
        # Los datos del simulador se marcan para no mezclarlos con los reales.
        if self.enlace and isinstance(self.enlace, EnlaceSimulado):
            lugar += " (simulado)"
        if lugar != self.registro_datos.lugar:
            self.registro_datos.guardar()
            self.registro_datos.lugar = lugar
        self._mostrar_registro()

    def _cambiar_grabacion(self):
        if not self._grabar.get():
            self.registro_datos.cerrar()
        self.registro_datos.activo = self._grabar.get()
        self._mostrar_registro()

    def _cambiar_minutos(self):
        try:
            minutos = int(self._minutos.get())
            if not 1 <= minutos <= 60:
                raise ValueError
        except ValueError:
            self._minutos.set(self.registro_datos.minutos)
            return
        if minutos != self.registro_datos.minutos:
            self.registro_datos.cerrar()
            self.registro_datos.minutos = minutos

    def _mostrar_registro(self):
        if not self._grabar.get():
            texto = "Grabacion pausada"
        else:
            texto = "{} registros hoy en {}  ({})".format(
                self.registro_datos.filas_hoy, "registros/" + self.registro_datos.archivo_actual().name,
                self.registro_datos.lugar)
        self._estado_registro.config(text=texto)

    def exportar_excel(self, archivo=None, abrir=True):
        """Guarda en un .xlsx todos los dias grabados del lugar actual y lo abre en Excel."""
        try:
            from exportar_excel import ExportadorExcel
        except ImportError:
            self.registrar("Exportar a Excel es opcional y necesita openpyxl: pip install openpyxl")
            return None
        self.registro_datos.guardar()          # que entre tambien el ultimo intervalo
        lugar = self.registro_datos.lugar
        filas = Estadistica(Estadistica.leer_carpeta(self.CARPETA_REGISTROS)).filtrar(lugar=lugar).filas
        if not filas:
            self.registrar("No hay registros de {} para exportar todavia.".format(lugar))
            return None
        if archivo is None:
            archivo = filedialog.asksaveasfilename(
                parent=self, title="Exportar a Excel", defaultextension=".xlsx",
                filetypes=[("Libro de Excel", "*.xlsx")], initialdir=str(self.CARPETA_REGISTROS),
                initialfile="Calidad del aire - {} - {}.xlsx".format(lugar, datetime.now().strftime("%Y-%m-%d")))
            if not archivo:
                return None
        try:
            ExportadorExcel(filas, lugar).guardar(archivo)
        except PermissionError:
            self.registrar("ERROR: no se pudo guardar. Si el archivo esta abierto en Excel, cierralo y vuelve a exportar.")
            return None
        self.registrar("Exportado a Excel: {} registros en {}".format(len(filas), Path(archivo).name))
        if abrir:
            try:
                os.startfile(archivo)
            except (AttributeError, OSError):
                pass
        return archivo

    def abrir_registros(self):
        self.CARPETA_REGISTROS.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(self.CARPETA_REGISTROS)
        except (AttributeError, OSError):
            self.registrar("Los registros estan en: {}".format(self.CARPETA_REGISTROS))

    def alternar_pms(self):
        self._enviar({"cmd": "pms", "dormir": not self._pms_dormido})

    def aplicar_umbral(self):
        try:
            umbral = self._leer_entradas([self._umbral], "el umbral de la puerta")[0]
            if not 10 <= umbral <= 190:
                raise ValueError("El umbral de la puerta debe ser de 10 a 190 cm")
        except ValueError as error:
            self.registrar("ERROR: {}".format(error))
            return
        self._enviar({"cmd": "personas", "accion": "umbral", "cm": int(umbral)})

    def reiniciar_conteo(self):
        if messagebox.askyesno("Conteo de alumnos",
                               "¿Poner en cero los alumnos en el aula y los que salieron?"):
            self._enviar({"cmd": "personas", "accion": "resetear"})

    def iniciar_ideal(self):
        try:
            minutos = int(self._ideal_minutos.get())
            if not 1 <= minutos <= 240:
                raise ValueError
        except ValueError:
            self.registrar("ERROR: la duracion debe ser un numero de 1 a 240 minutos")
            return
        if self._hay_ideal and not messagebox.askyesno(
                "Ambiente ideal",
                "Ya hay un ambiente ideal guardado.\n"
                "Se reemplazara cuando termine la nueva medicion. ¿Continuar?"):
            return
        self._enviar({"cmd": "ideal", "accion": "iniciar", "minutos": minutos})

    def resetear_ideal(self):
        if self._ideal_midiendo:
            pregunta = ("¿Cancelar la medicion en curso?\n"
                        "Tambien se borrara el ambiente ideal guardado, si habia uno.")
        else:
            pregunta = "¿Borrar el ambiente ideal guardado?\nNo se puede deshacer."
        if messagebox.askyesno("Ambiente ideal", pregunta):
            self._enviar({"cmd": "ideal", "accion": "resetear"})

    def silenciar(self):
        self.alarma.silenciar()
        self._boton_silenciar.config(state="disabled")
        self._aviso.config(text="Alarma silenciada. Ventila el aula.")

    def _cambiar_sonido(self):
        self.alarma.con_sonido = self._con_sonido.get()


if __name__ == "__main__":
    VentanaControl().mainloop()
