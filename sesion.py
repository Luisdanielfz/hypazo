"""Sesiones de directo del piloto de Hypazo: una caza sobre un canal, con sus cortes.

Se guardan en salida/_sesiones/<id>.json (carpeta con '_': la galería no la muestra).
"""
import json
import os
import secrets

CORTE_NUEVA_S = 600     # volver a cazar el mismo canal antes de esto = misma sesión con un corte
UMBRAL_TARDE_S = 60     # cazar más tarde que esto desde el inicio del directo = inicio parcial


def escribir_json(ruta: str, datos) -> None:
    """Escritura atómica: un cierre a medias nunca deja un JSON roto."""
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False)
    os.replace(tmp, ruta)


class Sesiones:
    def __init__(self, carpeta: str, nuevo_id=lambda: secrets.token_hex(4)):
        self.dir = os.path.join(carpeta, "_sesiones")
        self.nuevo_id = nuevo_id
        os.makedirs(self.dir, exist_ok=True)

    def _ruta(self, sid: str) -> str:
        return os.path.join(self.dir, f"{sid}.json")

    def _guardar(self, d: dict) -> None:
        escribir_json(self._ruta(d["id"]), d)

    def datos(self, sid: str) -> dict:
        with open(self._ruta(sid), encoding="utf-8") as f:
            return json.load(f)

    def lista(self) -> list[dict]:
        sesiones = []
        for nombre in os.listdir(self.dir):
            if nombre.endswith(".json"):
                try:
                    sesiones.append(self.datos(nombre[:-5]))
                except (OSError, ValueError):
                    continue
        return sorted(sesiones, key=lambda d: d.get("abierta", 0), reverse=True)

    def abrir(self, canal: str, plataforma: str, inicio: float | None, ahora: float) -> str:
        canal = canal.lower()
        for d in self.lista():
            if (d["canal"], d["plataforma"]) == (canal, plataforma) and d.get("fin") is not None \
                    and 0 <= ahora - d["fin"] < CORTE_NUEVA_S:
                en = d["fin"] - d["inicio"] if d.get("inicio") is not None else None
                d["cortes"].append({"en": en, "dura": ahora - d["fin"]})
                d["fin"] = ahora
                self._guardar(d)
                return d["id"]
        if inicio is None:
            estado = "desconocido"
        else:
            estado = "parcial" if ahora - inicio > UMBRAL_TARDE_S else "completo"
        d = {"id": self.nuevo_id(), "canal": canal, "plataforma": plataforma, "inicio": inicio,
             "estado_inicio": estado, "cortes": [], "abierta": ahora, "fin": ahora}
        self._guardar(d)
        return d["id"]

    def tiempo(self, sid: str, ahora: float) -> float | None:
        inicio = self.datos(sid).get("inicio")
        return None if inicio is None else ahora - inicio

    def tocar(self, sid: str, ahora: float) -> None:
        d = self.datos(sid)
        d["fin"] = ahora
        self._guardar(d)

    cerrar = tocar   # la app para el cazador con taskkill: cerrar y tocar guardan lo mismo
