"""Estado de cada clip mientras se caza: en cola -> renderizando -> listo / falló.

Se deduce de las líneas que imprime el cazador (autoclip.py y envivo.py), igual que el resto de la app.
"""
import os
import re
import time

RE_COLA = re.compile(r"Clip (\d+) en cola de render")
RE_RENDER = re.compile(r"Renderizando clip (\d+)")
RE_LISTO = re.compile(r"CLIP GUARDADO: (.+\.mp4)\s*$")
RE_FALLO = re.compile(r"\(clip (\d+) fallo, lo salto: (.*?)\)?\s*$")   # el error puede seguir en otra línea
RE_NUMERO = re.compile(r"_(\d+)\.mp4$")
MAXIMO = 8


class ClipsVivos:
    def __init__(self, salida: str):
        self.salida = os.path.realpath(salida)
        self._clips = {}

    def _clip(self, n: int) -> dict:
        return self._clips.setdefault(n, {"n": n, "estado": "cola", "error": "", "carpeta": None,
                                          "nombre": None, "hora": time.time()})

    def leer(self, linea: str):
        """Actualiza con una línea del cazador. Devuelve ("listo"|"fallo", clip) para avisar, o None."""
        if m := RE_COLA.search(linea):
            self._clip(int(m[1]))["estado"] = "cola"
        elif m := RE_RENDER.search(linea):
            self._clip(int(m[1]))["estado"] = "renderizando"
        elif m := RE_FALLO.search(linea):
            c = self._clip(int(m[1]))
            c.update(estado="fallo", error=m[2].strip())
            return "fallo", c
        elif m := RE_LISTO.search(linea):
            ruta = os.path.realpath(m[1].strip())
            num = RE_NUMERO.search(ruta)
            c = self._clip(int(num[1]) if num else 10_000 + len(self._clips))   # VOD sin número: arriba
            c["estado"] = "listo"
            carpeta = os.path.dirname(ruta)
            if os.path.dirname(carpeta) == self.salida:      # solo rutas dentro de la galería
                c.update(carpeta=os.path.basename(carpeta), nombre=os.path.basename(ruta))
            return "listo", c
        return None

    def lista(self) -> list:
        return sorted(self._clips.values(), key=lambda c: (c["hora"], c["n"]), reverse=True)[:MAXIMO]

    def limpiar(self) -> None:
        self._clips.clear()
