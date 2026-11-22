"""Que ningún proceso hijo (ffmpeg, yt-dlp, el cazador...) abra una ventana de terminal en Windows.

Hypazo corre sin consola (ventana nativa con pythonw.exe): sin esto, cada subprocess abre su propia
consola negra, p. ej. al pulsar "Clip ya". Se activa una vez al arrancar cada proceso de entrada.
"""
import subprocess
import sys

_Popen_init_original = subprocess.Popen.__init__
_activo = False


def con_flags(kwargs: dict) -> dict:
    """Los kwargs de Popen con CREATE_NO_WINDOW añadido (respetando los flags que ya traigan)."""
    return {**kwargs, "creationflags": kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW}


def activar() -> None:
    global _activo
    if sys.platform != "win32" or _activo:
        return
    # Se llama a través del módulo para que las pruebas puedan espiar _Popen_init_original.
    subprocess.Popen.__init__ = lambda self, *a, **kw: sys.modules[__name__]._Popen_init_original(
        self, *a, **con_flags(kw))
    _activo = True
