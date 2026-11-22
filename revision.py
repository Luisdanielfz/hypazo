"""Revisión del piloto de Hypazo: etiquetas, descartes, emparejamiento y momentos que se escaparon.

Solo guarda decisiones en salida/_revision/<sesion>.json: nunca mueve ni borra clips.
"""
import json
import os
import shutil
from dataclasses import dataclass

from sesion import escribir_json

ETIQUETAS = ("callado", "frase", "jugada", "risa", "otro")
DECISIONES = {"automatico": ("conservar", "descartar"), "manual": ("conservar", "descartar"),
              "forzado": ("aprobar", "descartar", "pendiente")}
AVISO_ROTO = "El estado de revisión estaba dañado; se guardó una copia .roto y empieza vacío."


@dataclass(frozen=True)
class Clip:
    id: str                      # "<carpeta>/<nombre sin .mp4>"
    carpeta: str                 # solo para la URL del vídeo: nunca va al resumen
    nombre: str
    origen: str                  # automatico | manual | forzado
    tiempo: float | None
    ventana: tuple[float, float] | None


def clips_de(salida: str, sesion: str) -> list[Clip]:
    """Clips de una sesión en las carpetas visibles de la galería, con su .mp4 presente."""
    clips = []
    for carpeta in sorted(os.listdir(salida)):
        ruta = os.path.join(salida, carpeta)
        if carpeta.startswith(("_", ".")) or not os.path.isdir(ruta):
            continue
        for f in sorted(os.listdir(ruta)):
            if not f.endswith(".json") or not os.path.isfile(os.path.join(ruta, f[:-5] + ".mp4")):
                continue
            try:
                with open(os.path.join(ruta, f), encoding="utf-8") as fh:
                    m = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(m, dict) or m.get("sesion") != sesion:
                continue
            # Se empareja por el reloj del cazador (siempre existe); el tiempo del directo puede faltar.
            v = m.get("ventana_reloj") or m.get("ventana_directo")
            clips.append(Clip(f"{carpeta}/{f[:-5]}", carpeta, f[:-5], m.get("origen", "automatico"),
                              m.get("tiempo_directo"), tuple(v) if v else None))
    return sorted(clips, key=lambda c: (c.tiempo is None, c.tiempo or 0))


def emparejar(clips: list[Clip], deshechos: set[str], descartados: set[str]) -> dict[str, tuple[str, float]]:
    """manual/forzado -> (automático que más se solapa, segundos de solape). Cada automático, una vez."""
    autos = [c for c in clips if c.origen == "automatico" and c.ventana and c.id not in descartados]
    usados, parejas = set(), {}
    for m in clips:
        if m.origen == "automatico" or not m.ventana or m.id in deshechos or m.id in descartados:
            continue
        mejor, maximo = None, 0.0
        for a in autos:
            solape = min(m.ventana[1], a.ventana[1]) - max(m.ventana[0], a.ventana[0])
            if a.id not in usados and solape > maximo:
                mejor, maximo = a, solape
        if mejor:
            parejas[m.id] = (mejor.id, round(maximo, 1))
            usados.add(mejor.id)
    return parejas


def _validar_estado(e) -> None:
    """La forma exacta del estado; cualquier otra cosa se trata como archivo dañado."""
    if set(e) != {"etiquetas", "decisiones", "deshechos", "escapados"}:
        raise ValueError("claves inesperadas")
    if not isinstance(e["etiquetas"], dict) or not all(v in ETIQUETAS for v in e["etiquetas"].values()):
        raise ValueError("etiquetas")
    validas = {v for vs in DECISIONES.values() for v in vs}
    if not isinstance(e["decisiones"], dict) or not all(v in validas for v in e["decisiones"].values()):
        raise ValueError("decisiones")
    if not isinstance(e["deshechos"], list) or not all(isinstance(x, str) for x in e["deshechos"]):
        raise ValueError("deshechos")
    if not isinstance(e["escapados"], list) or not all(
            isinstance(x, dict) and set(x) == {"t_s", "tipo"} and isinstance(x["t_s"], int)
            and x["t_s"] >= 0 and x["tipo"] in ETIQUETAS for x in e["escapados"]):
        raise ValueError("escapados")


class Revision:
    def __init__(self, salida: str, sesion: str):
        carpeta = os.path.join(salida, "_revision")
        os.makedirs(carpeta, exist_ok=True)
        self.ruta = os.path.join(carpeta, f"{sesion}.json")
        self.aviso = None
        self._e = self._cargar()

    def _vacio(self) -> dict:
        return {"etiquetas": {}, "decisiones": {}, "deshechos": [], "escapados": []}

    def _cargar(self) -> dict:
        if not os.path.exists(self.ruta):
            return self._vacio()
        try:
            with open(self.ruta, encoding="utf-8") as f:
                e = json.load(f)
            e = {**self._vacio(), **(e if isinstance(e, dict) else {"x": None})}
            _validar_estado(e)
            return e
        except (OSError, ValueError):
            shutil.copyfile(self.ruta, self.ruta + ".roto")   # se conserva para mirarlo a mano
            self.aviso = AVISO_ROTO
            return self._vacio()

    def _guardar(self) -> None:
        escribir_json(self.ruta, self._e)

    def estado(self) -> dict:
        return json.loads(json.dumps(self._e))           # copia: nadie modifica el estado por fuera

    def etiqueta(self, clip_id: str, valor: str | None) -> None:
        if valor is None:
            self._e["etiquetas"].pop(clip_id, None)
        elif valor in ETIQUETAS:
            self._e["etiquetas"][clip_id] = valor
        else:
            raise ValueError(f"Etiqueta no válida: {valor}")
        self._guardar()

    def decision(self, clip_id: str, origen: str) -> str:
        return self._e["decisiones"].get(clip_id, "pendiente" if origen == "forzado" else "conservar")

    def decidir(self, clip_id: str, valor: str, origen: str) -> None:
        if valor not in DECISIONES.get(origen, ()):
            raise ValueError(f"Decisión no válida para un clip {origen}: {valor}")
        self._e["decisiones"][clip_id] = valor
        self._guardar()

    def deshacer_pareja(self, clip_id: str) -> None:
        if clip_id not in self._e["deshechos"]:
            self._e["deshechos"].append(clip_id)
            self._guardar()

    def rehacer_pareja(self, clip_id: str) -> None:
        self._e["deshechos"] = [x for x in self._e["deshechos"] if x != clip_id]
        self._guardar()

    def escapado_añadir(self, t_s: int, tipo: str) -> None:
        if not isinstance(t_s, int) or t_s < 0 or tipo not in ETIQUETAS:
            raise ValueError("Momento no válido: tiempo en segundos y un tipo de la lista.")
        self._e["escapados"].append({"t_s": t_s, "tipo": tipo})
        self._guardar()

    def escapado_quitar(self, i: int) -> None:
        if not 0 <= i < len(self._e["escapados"]):
            raise ValueError("Ese momento no existe.")
        del self._e["escapados"][i]
        self._guardar()
