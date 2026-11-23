"""Tareas largas en curso (producir, sacar textos): en qué paso van, para que la ventana lo enseñe.

Clave = "carpeta/nombre" del clip. La ventana pregunta con GET /api/progreso mientras espera.
"""
import threading

_lock = threading.Lock()
_tareas = {}


def poner(clave: str, paso: str, pct: int | None = None) -> None:
    with _lock:
        _tareas[clave] = {"paso": paso, "pct": pct}


def quitar(clave: str) -> None:
    with _lock:
        _tareas.pop(clave, None)


def lista() -> dict:
    with _lock:
        return {k: dict(v) for k, v in _tareas.items()}


def limpiar() -> None:
    with _lock:
        _tareas.clear()


def avisador(clave: str):
    """Función aviso(paso, pct=None) para pasar a produccion.producir."""
    return lambda paso, pct=None: poner(clave, paso, pct)
