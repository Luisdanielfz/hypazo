"""api_revision.py - Revisión del piloto de Hypazo (Clips → Revisar directo)."""
import re
import urllib.parse
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resumen import construir, guardar, hms, texto_exacto, texto_legible, validar
from revision import Revision, clips_de, emparejar
from sesion import Sesiones

router = APIRouter()
# Las pone app.py; se leen en cada llamada (los tests cambian la carpeta de app).
salida = lambda: "salida"          # noqa: E731
_ruta_clip = lambda carpeta, nombre: None   # noqa: E731


# ---------- Revisión del piloto de Hypazo (pestaña Revisar) ----------
# Solo guarda decisiones y resúmenes en salida/_revision y salida/_resumenes: nunca mueve ni borra clips.
RE_SESION = re.compile(r"^[0-9a-f]{8}$")
ACCIONES = ("etiqueta", "decidir", "deshacer_pareja", "rehacer_pareja", "escapado_añadir", "escapado_quitar")


class AccionRevision(BaseModel):
    accion: Literal[ACCIONES]
    clip: str | None = Field(None, max_length=200)
    valor: str | None = Field(None, max_length=20)
    t_s: int | None = Field(None, ge=0, le=7 * 24 * 3600)
    tipo: str | None = Field(None, max_length=20)
    i: int | None = Field(None, ge=0)


def _sesion(sid):
    """Datos de una sesión; 404 ante cualquier id raro (nada de rutas)."""
    if not RE_SESION.match(sid):
        raise HTTPException(404, "Esa sesión no existe.")
    try:
        return Sesiones(salida()).datos(sid)
    except (OSError, ValueError):
        raise HTTPException(404, "Esa sesión no existe.")


def _duracion(d):
    return hms(d["fin"] - d["inicio"]) if d.get("inicio") is not None and d.get("fin") is not None else None


@router.get("/api/revision/sesiones")
def revision_sesiones():
    return [{"id": d["id"], "canal": d["canal"], "plataforma": d["plataforma"],
             "duracion": _duracion(d), "n_clips": len(clips_de(salida(), d["id"]))}
            for d in Sesiones(salida()).lista()]


@router.get("/api/revision/sesion/{sid}")
def revision_sesion(sid: str):
    d = _sesion(sid)
    rev, clips = Revision(salida(), sid), clips_de(salida(), sid)
    estado = rev.estado()
    descartados = {c.id for c in clips if rev.decision(c.id, c.origen) == "descartar"}
    parejas = emparejar(clips, set(estado["deshechos"]), descartados)
    vistos = []
    for c in clips:
        _ruta_clip(c.carpeta, c.nombre + ".mp4")          # valida: solo clips de la galería
        vistos.append({"id": c.id, "url": f"/salida/{urllib.parse.quote(c.carpeta)}/{urllib.parse.quote(c.nombre)}.mp4",
                       "tiempo": hms(c.tiempo), "t": c.tiempo, "ventana": c.ventana, "origen": c.origen,
                       "decision": rev.decision(c.id, c.origen)})
    return {"sesion": {"canal": d["canal"], "plataforma": d["plataforma"], "inicio": d["estado_inicio"],
                       "duracion": _duracion(d),
                       "cortes": [{"en": hms(k["en"]), "dura_s": int(round(k["dura"]))} for k in d["cortes"]]},
            "clips": vistos, "parejas": {m: {"con": a, "solape": s} for m, (a, s) in parejas.items()},
            "estado": estado, "aviso": rev.aviso}


@router.post("/api/revision/sesion/{sid}")
def revision_cambiar(sid: str, a: AccionRevision):
    _sesion(sid)
    rev = Revision(salida(), sid)
    origenes = {c.id: c.origen for c in clips_de(salida(), sid)}
    if a.accion not in ("escapado_añadir", "escapado_quitar") and a.clip not in origenes:
        raise HTTPException(400, "Ese clip no es de esta sesión.")
    try:
        if a.accion == "etiqueta":
            rev.etiqueta(a.clip, a.valor)
        elif a.accion == "decidir":
            rev.decidir(a.clip, a.valor or "", origen=origenes[a.clip])
        elif a.accion == "deshacer_pareja":
            rev.deshacer_pareja(a.clip)
        elif a.accion == "rehacer_pareja":
            rev.rehacer_pareja(a.clip)
        elif a.accion == "escapado_añadir":
            rev.escapado_añadir(a.t_s if a.t_s is not None else -1, a.tipo or "")
        else:
            rev.escapado_quitar(a.i if a.i is not None else -1)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


def _resumen(sid):
    d = _sesion(sid)
    r = construir(d, clips_de(salida(), sid), Revision(salida(), sid).estado())
    validar(r)
    return r


@router.get("/api/revision/resumen/{sid}")
def revision_resumen(sid: str):
    r = _resumen(sid)
    return {"legible": texto_legible(r), "exacto": texto_exacto(r)}


@router.post("/api/revision/resumen/{sid}/guardar")
def revision_guardar(sid: str):
    """Solo se llama cuando el usuario confirma en la vista previa. No se envía a ningún sitio."""
    return {"guardado": guardar(_resumen(sid), salida())}
