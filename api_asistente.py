"""Endpoints de preferencias (primer uso, favoritos), proveedores de IA y el chat del Asistente.

Todo se guarda en la configuración local de Hypazo (<home>/config): nada sale del PC salvo los
mensajes que el usuario manda a la IA que él mismo configuró.
"""
import json
import os
import re
import threading
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, ValidationError

import agente
import hypazo
import ia

router = APIRouter()
_lock = threading.Lock()
RE_CANAL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{1,24}$")
MAX_FAVORITOS = 20
MAX_CONVERSACIONES = 50
MAX_MENSAJES = 200
SISTEMA = ("Eres el asistente de Hypazo, una app de Windows que caza clips de directos de Twitch y Kick "
           "(atajos: F9 = clip ya, F8 = pausar la caza). Ayudas a clippers y streamers con títulos, "
           "hashtags, ideas de clips, horarios de subida y dudas de la app. Responde en español, claro y breve, "
           "con Markdown sencillo cuando ayude.")


def _cfg() -> dict:
    return hypazo.config()


def _guardar(cambio) -> dict:
    with _lock:
        nuevo = cambio(_cfg())
        hypazo.guardar_config(nuevo)
        return nuevo


def _vista(cfg: dict) -> dict:
    # La carpeta que usa de verdad el servidor (hypazo start la fija en CLIPEO_SALIDA).
    salida = os.environ.get("CLIPEO_SALIDA") or cfg["salida"]
    return {"bienvenida_vista": bool(cfg.get("bienvenida_vista")), "salida": salida,
            "favoritos": cfg.get("favoritos", []), "centinela": bool(cfg.get("centinela")), "ia": ia.publico(cfg.get("ia", {})), "catalogo": ia.catalogo()}


@router.get("/api/preferencias")
def preferencias():
    return _vista(_cfg())


class Favorito(BaseModel):
    canal: str = Field(max_length=25)
    plataforma: Literal["twitch", "kick"] = "twitch"


class Preferencias(BaseModel):
    bienvenida_vista: bool | None = None
    favoritos: list[Favorito] | None = Field(None, max_length=MAX_FAVORITOS)
    centinela: bool | None = None


@router.post("/api/preferencias")
def cambiar_preferencias(p: Preferencias):
    cambios = {}
    if p.bienvenida_vista is not None:
        cambios["bienvenida_vista"] = p.bienvenida_vista
    if p.centinela is not None:
        cambios["centinela"] = p.centinela
    if p.favoritos is not None:
        if any(not RE_CANAL.match(f.canal) for f in p.favoritos):
            raise HTTPException(400, "Nombre de canal inválido en favoritos.")
        unicos = {(f.canal.lower(), f.plataforma): None for f in p.favoritos}
        cambios["favoritos"] = [{"canal": c, "plataforma": pl} for c, pl in unicos]
    return _vista(_guardar(lambda c: {**c, **cambios}))


class Proveedor(BaseModel):
    id: str = Field(max_length=30)
    clave: str = Field("", max_length=300)
    borrar_clave: bool = False
    modelo: str | None = Field(None, max_length=120)
    activo: bool | None = None
    url: str | None = Field(None, max_length=300)


@router.post("/api/ia/proveedor")
def cambiar_proveedor(p: Proveedor):
    cambios = {k: v for k, v in p.model_dump().items() if k != "id" and v is not None}
    try:
        cfg = _guardar(lambda c: {**c, "ia": ia.actualizar(c.get("ia", {}), p.id, cambios)})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _vista(cfg)


class Orden(BaseModel):
    orden: list[str] = Field(max_length=30)


@router.post("/api/ia/orden")
def cambiar_orden(o: Orden):
    return _vista(_guardar(lambda c: {**c, "ia": ia.con_orden(c.get("ia", {}), o.orden)}))


@router.get("/api/ia/modelos")
def modelos(proveedor: str):
    try:
        return {"modelos": ia.modelos(_cfg().get("ia", {}), proveedor)}
    except ia.ErrorIA as e:
        raise HTTPException(400, str(e))


class Probar(BaseModel):
    proveedor: str = Field(max_length=30)


@router.post("/api/ia/probar")
def probar(p: Probar):
    lista = [d for d in ia.disponibles(_cfg().get("ia", {}), p.proveedor) if d["id"] == p.proveedor]
    if not lista:
        raise HTTPException(400, "Ese proveedor no está listo: pon su clave y actívalo.")
    solo = {"orden": [p.proveedor], "proveedores": {p.proveedor: _cfg().get("ia", {}).get("proveedores", {}).get(p.proveedor, {})}}
    try:
        r = ia.chat(solo, [{"role": "user", "content": "Responde solo: OK"}], proveedor=p.proveedor)
    except ia.ErrorIA as e:
        raise HTTPException(502, str(e))
    return {"ok": True, "modelo": r["modelo"], "respuesta": r["texto"][:80]}


class Mensaje(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=12000)
    ctx: str | None = Field(None, max_length=4000)    # lo que consultó la IA (clips…), para los siguientes mensajes


def _para_ia(m: Mensaje) -> dict:
    return {"role": m.role, "content": m.content + (f"\n\n{m.ctx}" if m.ctx else "")}


class Chat(BaseModel):
    mensajes: list[Mensaje] = Field(min_length=1, max_length=MAX_MENSAJES)
    proveedor: str | None = Field(None, max_length=30)      # None = automático
    modelo: str | None = Field(None, max_length=120)


@router.post("/api/ia/chat")
def chat(c: Chat):
    mensajes = [{"role": "system", "content": SISTEMA}] + [_para_ia(m) for m in c.mensajes[-40:]]
    try:
        prov, modelo, trozos = ia.abrir_stream(_cfg().get("ia", {}), mensajes, c.proveedor or None, c.modelo or None)
    except ia.ErrorIA as e:
        raise HTTPException(502, str(e))

    def flujo():
        try:
            yield from trozos
        except Exception as e:            # corte a mitad: que se vea en el chat, no un hilo colgado
            yield f"\n\n[Se cortó la respuesta: {str(e)[:120]}]"
    nombre = ia.PROVEEDORES.get(prov, {}).get("nombre", prov)
    return StreamingResponse(flujo(), media_type="text/plain; charset=utf-8",
                             headers={"X-Proveedor": nombre.encode("ascii", "ignore").decode(),
                                      "X-Modelo": modelo.encode("ascii", "ignore").decode(),
                                      "Cache-Control": "no-store"})


def _ruta_chats() -> str:
    return os.path.join(hypazo.casa(), "config", "chats.json")


@router.get("/api/ia/conversaciones")
def conversaciones():
    try:
        with open(_ruta_chats(), encoding="utf-8") as f:
            return {"conversaciones": json.load(f)}
    except (OSError, ValueError):
        return {"conversaciones": []}


class Conversacion(BaseModel):
    id: str = Field(pattern=r"^[0-9a-f]{8,32}$")
    titulo: str = Field(max_length=80)
    mensajes: list[Mensaje] = Field(max_length=MAX_MENSAJES)
    hora: float = 0


class Conversaciones(BaseModel):
    conversaciones: list[Conversacion] = Field(max_length=MAX_CONVERSACIONES)


@router.put("/api/ia/conversaciones")
def guardar_conversaciones(c: Conversaciones):
    ruta = _ruta_chats()
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    tmp = ruta + ".tmp"
    with _lock:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([x.model_dump(exclude_none=True) for x in c.conversaciones], f, ensure_ascii=False)
        os.replace(tmp, ruta)
    return {"ok": True}


def _app():
    import app                       # ya cargado: es quien incluye este router
    return app


def _estado_cazador(_a):
    s = _app().status()
    minutos = round((time.time() - s["inicio"]) / 60) if s["corriendo"] and s["inicio"] else 0
    return {"corriendo": s["corriendo"], "canal": s["canal"] if s["corriendo"] else "", "pausado": s["pausado"],
            "minutos": minutos, "clips_en_marcha": s["vivos"]}


LECTURAS = {
    "buscar_clips": lambda a: agente.buscar(_app().clips(), **{k: a[k] for k in
                                            ("texto", "canal", "dias", "orden", "limite") if k in a}),
    "estado_cazador": _estado_cazador,
    "resumen": lambda a: agente.resumen(_app().clips(), a.get("dias") or 7),
}


def _producir(a):
    m = _app()
    return m.clip_producir(m.Produccion(carpeta=str(a.get("carpeta", "")), nombre=str(a.get("nombre", "")),
                                        titulo=str(a.get("titulo") or "")[:80],
                                        estilo=a.get("estilo") if a.get("estilo") in ("amarillo", "caja", "minimal")
                                        else "amarillo", ajustar=True))


# Solo tras pulsar Confirmar en el chat. Cada una pasa por el endpoint de siempre (y su validación).
ACCIONES = {
    "empezar_caza": lambda a: _app().start(_app().Arranque(
        canal=str(a.get("canal", "")), plataforma="kick" if a.get("plataforma") == "kick" else "twitch")),
    "parar_caza": lambda a: _app().stop(),
    "producir_clip": _producir,
    "generar_textos": lambda a: _app().clip_textos(_app().Textos(carpeta=str(a.get("carpeta", "")),
                                                                  nombre=str(a.get("nombre", "")))),
    "marcar_clip": lambda a: _marcar(a),
    "marcar_subido": lambda a: _app().clip_mover(_app().Mover(carpeta="PARA SUBIR", nombre=str(a.get("nombre", "")),
                                                              destino="SUBIDOS")),
    "analizar_vod": lambda a: _app().vod(_app().Vod(url=str(a.get("url", ""))[:200], n=a.get("n") or 10)),
    "clip_ya": lambda a: _app().clip_ya(),
    "pausar_caza": lambda a: _app().pausa(),
    "reanudar_caza": lambda a: _app().reanudar(),
}


def _marcar(a):
    m = _app()
    if a.get("estado", "") not in m.ESTADOS:
        raise HTTPException(400, "Estado de clip inválido: bueno, descartado o vacío.")
    return m.clip_estado(m.Estado(carpeta=str(a.get("carpeta", "")), nombre=str(a.get("nombre", "")),
                                  estado=a.get("estado", "")))


def validar_propuesta(nombre: str, a: dict) -> str | None:
    """Error si la acción no se va a poder hacer (clip que no existe, enlace malo); None si vale.
    Así la IA corrige su propuesta antes de que llegue al usuario."""
    m = _app()
    try:
        if nombre in ("producir_clip", "generar_textos", "marcar_clip"):
            m.ruta_clip(str(a.get("carpeta", "")), str(a.get("nombre", "")))
        elif nombre == "marcar_subido":
            m.ruta_clip(m.PARA_SUBIR, str(a.get("nombre", "")))
        elif nombre == "analizar_vod" and not m.RE_VOD.match(str(a.get("url", "")).strip()):
            return "Ese enlace no es un VOD de Twitch (https://www.twitch.tv/videos/NUMERO)."
        elif nombre in ("clip_ya", "pausar_caza", "reanudar_caza", "parar_caza") and not m._corriendo():
            return "El cazador no está en marcha: no hay nada que parar, pausar o recortar."
        elif nombre in ("empezar_caza", "analizar_vod") and m._corriendo():
            return "Ya hay una caza o un VOD en marcha: párala primero (parar_caza)."
    except HTTPException as e:
        return f"{e.detail} ({a.get('carpeta', m.PARA_SUBIR if nombre == 'marcar_subido' else '')}/{a.get('nombre', '')})"
    return None


@router.post("/api/ia/agente")
def agente_responder(c: Chat):
    try:
        r = agente.responder(_cfg().get("ia", {}), [_para_ia(m) for m in c.mensajes[-40:]], LECTURAS, ACCIONES,
                             c.proveedor or None, c.modelo or None, validar=validar_propuesta)
    except ia.ErrorIA as e:
        raise HTTPException(502, str(e))
    return {**r, "proveedor": ia.PROVEEDORES.get(r["proveedor"], {}).get("nombre", r["proveedor"])}


class Accion(BaseModel):
    herramienta: Literal["empezar_caza", "parar_caza", "producir_clip", "generar_textos", "marcar_clip",
                         "marcar_subido", "analizar_vod", "clip_ya", "pausar_caza", "reanudar_caza"]
    args: dict = Field(default_factory=dict)


@router.post("/api/ia/accion")
def accion(a: Accion):
    try:
        res = ACCIONES[a.herramienta](a.args)
    except ValidationError as e:
        raise HTTPException(400, "Datos no válidos: " + str(e.errors()[0].get("msg", ""))[:120])
    return {"ok": True, "resumen": agente.resumen_accion(a.herramienta, a.args), "resultado": res}
