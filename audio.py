"""
audio.py - Volumen del directo en vivo, para detectar gritos, risas y explosiones.

Lee audio PCM (mono, 8 kHz, s16le) del mismo ffmpeg que graba el buffer y guarda el
nivel en dB cada 0.25 s. Aprende solo cual es el volumen "normal" del stream.
"""
import array
import collections
import math
import statistics
import threading
import time

TASA = 8000
TRAMO = 0.25                       # segundos por medicion
BYTES = int(TASA * TRAMO) * 2      # s16 = 2 bytes por muestra
POR_SEGUNDO = int(1 / TRAMO)
SILENCIO = -90.0
CORTE = -80.0                      # por debajo = corte de audio, no cuenta para la base
VENTANA_BASE = 60                  # segundos de historia para el volumen normal


def db(pcm):
    """Nivel RMS en dBFS de un trozo de audio s16le (0 = maximo, -90 = silencio)."""
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    if not a:
        return SILENCIO
    rms = math.sqrt(sum(x * x for x in a) / len(a))
    return max(SILENCIO, 20 * math.log10(rms / 32768)) if rms > 0 else SILENCIO


class Volumen:
    def __init__(self):
        self.niveles = collections.deque(maxlen=120 * POR_SEGUNDO)   # (t, dB), 2 min
        self.base = None          # volumen normal del stream (dB), se adapta solo
        self._ult_base = 0.0

    def leer_de(self, stream):
        """Lee el PCM en un hilo. Hay que vaciar el pipe siempre: si no, ffmpeg se
        bloquea y deja de grabar el buffer."""
        threading.Thread(target=self._bucle, args=(stream,), daemon=True).start()

    def _bucle(self, stream):
        while True:
            pcm = stream.read(BYTES)
            if not pcm:
                return
            self.agregar(time.time(), db(pcm))

    def agregar(self, t, nivel):
        self.niveles.append((t, nivel))
        if t - self._ult_base < 1.0:
            return
        # Base = mediana del ultimo minuto: un grito o una pausa cortos no la mueven.
        # (La version con media movil + freno solo hacia arriba se hundia sola en
        # silencios y luego cualquier voz parecia un grito de +30 dB.)
        utiles = [d for d in self._ultimos(VENTANA_BASE, t) if d > CORTE]
        if len(utiles) >= POR_SEGUNDO * 3:
            self.base = statistics.median(utiles)
        self._ult_base = t

    def _ultimos(self, segundos, ahora):
        return [d for t, d in self.niveles if ahora - t <= segundos]

    @staticmethod
    def _media(v):
        return sum(v) / len(v) if v else SILENCIO

    def pico(self, segundos, ahora=None):
        """Cuantos dB sobre lo normal llego el segundo mas fuerte del tramo.
        Usa medias de 1 s: un golpe suelto de 0.25 s no cuenta como grito."""
        ahora = time.time() if ahora is None else ahora
        v = self._ultimos(segundos, ahora)
        if self.base is None or len(v) < POR_SEGUNDO:
            return 0.0
        medias = [self._media(v[i:i + POR_SEGUNDO]) for i in range(len(v) - POR_SEGUNDO + 1)]
        return max(0.0, max(medias) - self.base)
