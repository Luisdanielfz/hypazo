"""Actividad del chat en vivo para la gráfica de Cazar.

El cazador escribe cada 2 s una línea "[medida] puntaje normal umbral"; aquí se guardan las
últimas (no van al registro visible) y la hora de cada clip cazado, para marcarlo en la gráfica.
"""
import collections
import re
import threading

RE_CLIP = re.compile(r"Clip \d+ en cola de render")


class SerieChat:
    MAXIMO = 300          # 10 minutos a una medida cada 2 s

    def __init__(self):
        self._lock = threading.Lock()
        self._puntos = collections.deque(maxlen=self.MAXIMO)
        self._marcas = collections.deque(maxlen=50)

    def leer(self, linea: str, ahora: float) -> bool:
        """True si la línea es una medida (no debe ir al registro)."""
        t = linea.strip()
        if t.startswith("[medida]"):
            try:
                p, b, u = t.split()[1:4]
                punto = [round(ahora, 1), int(p), float(b), float(u)]
            except ValueError:
                return True
            with self._lock:
                self._puntos.append(punto)
            return True
        if RE_CLIP.search(t):
            with self._lock:
                self._marcas.append(round(ahora, 1))
        return False

    def datos(self) -> dict:
        with self._lock:
            return {"puntos": [list(p) for p in self._puntos], "marcas": list(self._marcas)}

    def limpiar(self) -> None:
        with self._lock:
            self._puntos.clear()
            self._marcas.clear()
