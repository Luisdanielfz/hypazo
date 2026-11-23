"""api_recortes.py - Recortes del formato split (Ajustes → Recortes): frame del directo, auto-calibrar y layouts.json."""
import glob
import json
import os
import re
import subprocess
import tempfile
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()
RE_CANAL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{1,24}$")   # Kick admite '-'
RE_RECORTE = re.compile(r"^\d{1,4}:\d{1,4}:\d{1,4}:\d{1,4}$")
# Las pone app.py; se leen en cada llamada (los tests cambian las rutas de app).
buffer_dir = lambda: "buffer"          # noqa: E731
layouts_json = lambda: "layouts.json"  # noqa: E731


def _leer_layouts():
    try:
        with open(layouts_json(), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        from clipeo import LAYOUTS
        return LAYOUTS


def validar_layouts(datos):
    """Devuelve el dict limpio o lanza ValueError con el motivo."""
    if not isinstance(datos, dict):
        raise ValueError("Formato invalido.")
    limpio = {}
    for nombre, lay in datos.items():
        if not RE_CANAL.match(str(nombre)):
            raise ValueError(f"Nombre de streamer invalido: {nombre!r}")
        if not isinstance(lay, dict):
            raise ValueError(f"{nombre}: formato invalido.")
        marco = str(lay.get("frame") or "1920x1080")
        m = re.fullmatch(r"(\d{3,4})x(\d{3,4})", marco)
        if not m:
            raise ValueError(f"{nombre}: tamaño de frame inválido ({marco}).")
        fw, fh = int(m[1]), int(m[2])
        for k in ("face", "game"):
            if not RE_RECORTE.match(str(lay.get(k, ""))):
                raise ValueError(f"{nombre}.{k} debe ser w:h:x:y (ej 300:300:60:430)")
            w, h, x, y = map(int, str(lay[k]).split(":"))
            parte = "la cara" if k == "face" else "el juego"
            if w < 16 or h < 16:
                raise ValueError(f"{nombre}: el recorte de {parte} es demasiado pequeño.")
            if x + w > fw or y + h > fh:     # ffmpeg fallaría en cada clip
                raise ValueError(f"{nombre}: el recorte de {parte} se sale del frame ({fw}x{fh}).")
        limpio[nombre.lower()] = {"face": lay["face"], "game": lay["game"]}
        if lay.get("frame"):
            limpio[nombre.lower()]["frame"] = marco
        if lay.get("manual"):          # ajustado a mano: la calibración automática no lo pisa
            limpio[nombre.lower()]["manual"] = True
    return limpio



_frames = {}            # (plataforma, canal) -> (hora, png): reusar el frame al ajustar numeros
FRAME_TTL = 60


def _frame_en_vivo(canal, plataforma):
    """PNG de un frame reciente del directo. Si el cazador graba ese canal, sale de su
    buffer (sin tocar la red); si no, se pide un frame al directo."""
    clave = (plataforma, canal)
    hora, png = _frames.get(clave, (0.0, ""))
    if png and time.time() - hora < FRAME_TTL and os.path.exists(png):
        return png
    png = os.path.join(tempfile.gettempdir(), f"clipeo_frame_{plataforma}_{canal}.png")
    segs = sorted(glob.glob(os.path.join(buffer_dir(), f"{plataforma}_{canal}", "seg*.ts")),
                  key=os.path.getmtime)
    if len(segs) >= 2 and time.time() - os.path.getmtime(segs[-2]) < 60:
        fuente = segs[-2]                     # el ultimo puede estar a medio escribir
    else:
        from envivo import resolver_url
        fuente = resolver_url(canal, plataforma)   # RuntimeError si no esta en vivo
    r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", fuente,
                        "-frames:v", "1", png], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not os.path.exists(png):
        raise RuntimeError("No pude sacar un frame del directo: " + r.stderr.strip()[-200:])
    import cv2
    import calibrar
    if calibrar.es_anuncio(cv2.imread(png)):
        # Twitch puso su pantalla de anuncios: mirar hasta un minuto y quedarse con un frame real.
        cv2.imwrite(png, calibrar.frames_de(canal, plataforma, n=1)[-1])
    _frames[clave] = (time.time(), png)
    return png


class AutoCal(BaseModel):
    canal: str
    plataforma: Literal["twitch", "kick"] = "twitch"


@router.post("/api/auto-calibrar")
def auto_calibrar(a: AutoCal):
    """Detecta la cámara del streamer y propone el recorte split. NO lo guarda: la app
    lo enseña en la vista previa y el usuario confirma con «Guardar recortes»."""
    import cv2
    import calibrar
    if not RE_CANAL.match(a.canal):
        raise HTTPException(400, "Nombre de canal invalido.")
    canal = a.canal.lower()
    try:
        frames = calibrar.frames_de(canal, a.plataforma)
        r = calibrar.calibrar_frames(frames)
    except calibrar.SinCamara as e:
        raise HTTPException(422, str(e))
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        raise HTTPException(404, f"{canal}: {e}")
    # la previa reutiliza este frame real (sin esperar otra vez a los anuncios)
    png = os.path.join(tempfile.gettempdir(), f"clipeo_frame_{a.plataforma}_{canal}.png")
    cv2.imwrite(png, frames[-1])
    _frames[(a.plataforma, canal)] = (time.time(), png)
    return r


def _frame_guardado(canal, plataforma):
    """El último frame que se sacó de ese directo (para ajustar el recorte aunque ya no esté en vivo)."""
    png = os.path.join(tempfile.gettempdir(), f"clipeo_frame_{plataforma}_{canal}.png")
    return png if os.path.exists(png) else None


@router.get("/api/frame")
def frame(canal: str, plataforma: Literal["twitch", "kick"] = "twitch", fresco: bool = False):
    """Frame del directo para el editor visual de recortes. Si no está en vivo, el último guardado
    (cabecera X-Viejo = segundos que tiene). X-Ancho/X-Alto = tamaño real del frame."""
    from PIL import Image
    if not RE_CANAL.match(canal):
        raise HTTPException(400, "Nombre de canal invalido.")
    canal, cab = canal.lower(), {"Cache-Control": "no-store"}
    if fresco:
        _frames.pop((plataforma, canal), None)
    sin_frame = HTTPException(404, f"{canal} no está en vivo y no tengo ningún frame suyo guardado. "
                                   "Prueba cuando esté en directo.")
    try:
        png = _frame_en_vivo(canal, plataforma)
    except Exception:             # offline, anuncios, ffmpeg o cv2: se prueba con el último guardado
        png = _frame_guardado(canal, plataforma)
        if not png:
            raise sin_frame
        cab["X-Viejo"] = str(int(max(0, time.time() - os.path.getmtime(png))))
    try:
        with Image.open(png) as im:
            im.verify()
        with Image.open(png) as im:
            cab["X-Ancho"], cab["X-Alto"] = map(str, im.size)
    except Exception:             # frame a medio escribir
        raise sin_frame
    return FileResponse(png, media_type="image/png", headers=cab)


@router.get("/api/layouts")
def get_layouts():
    return _leer_layouts()


@router.put("/api/layouts")
def put_layouts(datos: dict):
    try:
        limpio = validar_layouts(datos)
    except ValueError as e:
        raise HTTPException(400, str(e))
    from clipeo import escribir_json
    try:
        escribir_json(layouts_json(), limpio)    # atómica y con reintentos (el cazador puede estar leyéndolo)
    except OSError as e:
        raise HTTPException(503, f"No pude guardar los recortes (el archivo está ocupado): {e}")
    return {"ok": True, "nota": "Se aplica al siguiente clip, tambien si el cazador esta en marcha."}
