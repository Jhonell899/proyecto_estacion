import json
import select
import sys


class EnlacePC:
    """Enlace con el software de control de la PC por el cable USB.

    Hacia la PC se envian lineas de texto con un prefijo y un JSON:
        DATOS {...}   lecturas y ajustes actuales
        RESP {...}    respuesta a un comando: {"ok": true/false, "msg": "..."}
    Desde la PC llegan comandos, uno por linea, en JSON:
        {"cmd": "limites", "co2": [a, b, c], "pm25": [a, b, c]}
        {"cmd": "intervalos", "lectura": ms, "pantalla": ms}
        {"cmd": "pms", "dormir": true/false}
    """

    MAX_LINEA = 300

    def __init__(self):
        self._buffer = ""
        # poll permite revisar si llego algo sin detener el programa.
        self._poll = select.poll()
        self._poll.register(sys.stdin, select.POLLIN)

    def _enviar(self, tipo, contenido):
        print(tipo + " " + json.dumps(contenido))

    def enviar_datos(self, datos):
        self._enviar("DATOS", datos)

    def responder(self, ok, mensaje):
        self._enviar("RESP", {"ok": ok, "msg": mensaje})

    def recibir(self):
        """Devuelve la lista de comandos completos (diccionarios) que llegaron."""
        comandos = []
        while self._poll.poll(0):
            caracter = sys.stdin.read(1)
            if not caracter:
                break
            if caracter in "\r\n":
                linea = self._buffer.strip()
                self._buffer = ""
                if not linea:
                    continue
                try:
                    comando = json.loads(linea)
                except ValueError:
                    self.responder(False, "Comando no entendido")
                    continue
                if isinstance(comando, dict):
                    comandos.append(comando)
            elif len(self._buffer) < self.MAX_LINEA:
                self._buffer += caracter
            else:
                self._buffer = ""  # linea demasiado larga: se descarta
        return comandos
