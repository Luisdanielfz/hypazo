"""
app.py - UI local para el clipeo. Envuelve autoclip.py (no lo reescribe).

Uso:   python app.py      -> abre http://127.0.0.1:8765
"""
import collections
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import webbrowser

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from typing import Literal

from pydantic import BaseModel, Field

from credito import credito_final
import sin_consola
sin_consola.activar()   # ffmpeg/yt-dlp sin ventanas de terminal
from resumen import construir, guardar, hms, texto_exacto, texto_legible, validar
from revision import Revision, clips_de, emparejar
from sesion import Sesiones

AQUI = os.path.dirname(os.path.abspath(__file__))
# Sobrescribibles solo para probar la limpieza con datos falsos sin tocar los clips reales.
SALIDA = os.environ.get("CLIPEO_SALIDA") or os.path.join(AQUI, "salida")
BUFFER = os.environ.get("CLIPEO_BUFFER") or os.path.join(AQUI, "buffer")
LAYOUTS_JSON = os.path.join(AQUI, "layouts.json")
PUERTO = 8765

RE_CANAL = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{1,24}$")   # Kick admite '-'
RE_RECORTE = re.compile(r"^\d{1,4}:\d{1,4}:\d{1,4}:\d{1,4}$")

os.makedirs(SALIDA, exist_ok=True)
app = FastAPI(title="Clipeo")
app.mount("/salida", StaticFiles(directory=SALIDA), name="salida")
# Fuentes y recursos de la interfaz, servidos desde el proyecto (sin depender de internet).
os.makedirs(os.path.join(AQUI, "assets"), exist_ok=True)
app.mount("/assets", StaticFiles(directory=os.path.join(AQUI, "assets")), name="assets")

# Estado del cazador: uno a la vez.
_lock = threading.Lock()
_estado = {"proc": None, "canal": "", "inicio": 0.0, "pausado": False}
_log = collections.deque(maxlen=300)


class Arranque(BaseModel):
    canal: str
    plataforma: Literal["twitch", "kick"] = "twitch"
    credito: str = Field("", max_length=40)
    piso: int = Field(40, ge=1, le=10000)
    factor: float = Field(1.8, ge=1.0, le=10.0)
    unicos: int = Field(10, ge=1, le=500)
    postroll: float = Field(7.0, ge=0, le=60)
    audio: float = Field(12.0, ge=0, le=40)
    split: bool = False


def _leer_salida(proc):
    for linea in proc.stdout:
        _log.append(linea.rstrip("\r\n"))
    _log.append(f"[proceso terminado, codigo {proc.wait()}]")


def _corriendo():
    p = _estado["proc"]
    return p is not None and p.poll() is None


@app.post("/api/start")
def start(a: Arranque):
    if not RE_CANAL.match(a.canal):
        raise HTTPException(400, "Nombre de canal invalido (solo letras, numeros y _).")
    with _lock:
        if _corriendo():
            raise HTTPException(409, "El cazador ya esta corriendo. Paralo primero.")
        cmd = [sys.executable, "-u", "autoclip.py", a.canal.lower(),
               "--plataforma", a.plataforma, "--piso", str(a.piso), "--factor", str(a.factor),
               "--unicos", str(a.unicos), "--postroll", str(a.postroll),
               "--audio", str(a.audio)]
        cmd += ["--credito", credito_final(a.credito, a.canal, a.plataforma)]   # siempre con crédito
        if a.split:
            cmd.append("--split")
        _log.clear()
        _log.append("$ " + " ".join(cmd[2:]))
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        # stdin=PIPE: por ahi le llega el "clip ya" (autoclip lo lee como un ENTER).
        proc = subprocess.Popen(cmd, cwd=AQUI, env=env, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        _estado.update(proc=proc, canal=f"{a.canal.lower()} ({a.plataforma})", inicio=time.time(),
                       pausado=False)
        _activar_atajos()
        threading.Thread(target=_leer_salida, args=(proc,), daemon=True).start()
    return {"ok": True}


RE_VOD = re.compile(r"^https?://(?:www\.|m\.)?twitch\.tv/videos/\d+(?:\?.*)?$")


class Vod(BaseModel):
    url: str = Field(..., max_length=200)
    n: int = Field(10, ge=1, le=30)
    credito: str = Field("", max_length=40)
    factor: float = Field(1.8, ge=1.0, le=10.0)
    unicos: int = Field(10, ge=1, le=500)
    remate: float = Field(7.0, ge=0, le=60)
    audio: float = Field(12.0, ge=0, le=40)
    split: bool = False


@app.post("/api/vod")
def vod(v: Vod):
    """Mejores momentos de un directo ya hecho: corre vod.py en el mismo hueco que el
    cazador (uno a la vez), así el registro, el estado y Parar sirven igual."""
    url = v.url.strip()
    if not RE_VOD.match(url):
        raise HTTPException(400, "Pega el enlace de un VOD de Twitch: https://www.twitch.tv/videos/NUMERO")
    with _lock:
        if _corriendo():
            raise HTTPException(409, "Ya hay algo corriendo (cazador o VOD). Paralo primero.")
        cmd = [sys.executable, "-u", "vod.py", url.split("?")[0], "--n", str(v.n),
               "--factor", str(v.factor), "--unicos", str(v.unicos),
               "--remate", str(v.remate), "--audio", str(v.audio)]
        if v.credito:
            cmd += ["--credito", v.credito]
        if v.split:
            cmd.append("--split")
        _log.clear()
        _log.append("$ " + " ".join(cmd[2:]))
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(cmd, cwd=AQUI, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        _estado.update(proc=proc, canal="VOD " + url.rsplit("/", 1)[-1].split("?")[0],
                       inicio=time.time())
        threading.Thread(target=_leer_salida, args=(proc,), daemon=True).start()
    return {"ok": True}


@app.post("/api/stop")
def stop():
    with _lock:
        p = _estado["proc"]
        if not _corriendo():
            return {"ok": True, "msg": "No estaba corriendo."}
        # /T mata tambien el ffmpeg hijo; terminate() a secas lo dejaria huerfano.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)],
                       capture_output=True)
        _log.append("[parado desde la app]")
        _quitar_atajos()
    return {"ok": True}


def _orden(texto, aviso):
    """Manda una orden al cazador por su stdin (ver autoclip.interpretar)."""
    with _lock:
        if not _corriendo():
            raise HTTPException(409, "El cazador no esta corriendo.")
        try:
            _estado["proc"].stdin.write(texto + "\n")
            _estado["proc"].stdin.flush()
        except OSError as e:
            raise HTTPException(500, f"No pude avisar al cazador: {e}")
        _log.append(aviso)


@app.post("/api/pausa")
def pausa():
    """Pausa la caza automática (p. ej. en "vuelvo enseguida"). Clip ya pasa a ser forzado."""
    _orden("pausa", "[caza automatica en pausa desde la app]")
    _estado["pausado"] = True
    return {"ok": True, "pausado": True}


@app.post("/api/reanudar")
def reanudar():
    _orden("reanudar", "[caza automatica reanudada desde la app]")
    _estado["pausado"] = False
    return {"ok": True, "pausado": False}


# Atajos globales (funcionan con el juego en primer plano): F9 = Clip ya, F8 = pausar/reanudar.
_atajos = []


def _seguro(f):
    def envoltura():
        try:
            f()
        except HTTPException:
            pass                       # cazador parado: el atajo no hace nada
    return envoltura


def _alternar_pausa():
    (reanudar if _estado["pausado"] else pausa)()


def _activar_atajos():
    _quitar_atajos()
    try:
        import keyboard
        _atajos.append(keyboard.add_hotkey("f9", _seguro(clip_ya)))
        _atajos.append(keyboard.add_hotkey("f8", _seguro(_alternar_pausa)))
    except Exception as e:             # sin permisos o sin la librería: la app sigue sin atajos
        _log.append(f"[sin atajos de teclado F9/F8: {e}]")


def _quitar_atajos():
    try:
        import keyboard
        for h in _atajos:
            keyboard.remove_hotkey(h)
    except Exception:
        pass
    _atajos.clear()


# ---------- Actualizaciones (Ajustes → Actualizaciones) ----------
@app.get("/api/version")
def version():
    import hypazo
    actual, ultima = hypazo.version_actual(), hypazo.ultima_version()
    return {"actual": actual, "ultima": ultima, "hay_nueva": hypazo.hay_nueva(actual, ultima),
            "instalado": hypazo.instalado()}


def _lanzar_update():
    """`hypazo update` en otro proceso (git fetch + checkout de la última versión + dependencias)."""
    import hypazo
    python = os.path.join(os.path.dirname(sys.executable), "python.exe") if sys.platform == "win32" else sys.executable
    r = subprocess.run([python, os.path.join(AQUI, "hypazo.py"), "update"], cwd=AQUI, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, HYPAZO_HOME=hypazo.casa(), PYTHONIOENCODING="utf-8"))
    return r.returncode, (r.stdout + r.stderr)[-1500:]


@app.post("/api/actualizar")
def actualizar():
    import hypazo
    if not hypazo.instalado():
        raise HTTPException(409, "Solo se puede actualizar la app instalada (no la carpeta de desarrollo).")
    if _corriendo():
        raise HTTPException(409, "Para el cazador antes de actualizar.")
    codigo, salida = _lanzar_update()
    if codigo != 0:
        raise HTTPException(500, f"No se pudo actualizar: {salida[-600:]}")
    return {"ok": True, "version": hypazo.version_actual(),
            "mensaje": "Actualizado. Cierra Hypazo y vuelve a abrirlo para usar la versión nueva."}


@app.post("/api/clip-ya")
def clip_ya():
    """Clip manual ahora mismo (salta el cooldown)."""
    with _lock:
        if not _corriendo():
            raise HTTPException(409, "El cazador no esta corriendo.")
        try:
            _estado["proc"].stdin.write("clip\n")
            _estado["proc"].stdin.flush()
        except OSError as e:
            raise HTTPException(500, f"No pude avisar al cazador: {e}")
        _log.append("[clip manual pedido desde la app]")
    return {"ok": True}


@app.get("/api/status")
def status():
    return {"corriendo": _corriendo(), "canal": _estado["canal"], "pausado": _estado["pausado"],
            "inicio": _estado["inicio"], "log": list(_log)[-120:]}


PAPELERA = "_papelera"   # carpetas con '_' no salen en la galeria
ESTADOS = ("", "bueno", "descartado")
# Flujo de los clips terminados: producir -> PARA SUBIR -> (ya lo subi) -> SUBIDOS.
PARA_SUBIR, SUBIDOS = "PARA SUBIR", "SUBIDOS"
for _c in (PARA_SUBIR, SUBIDOS):
    os.makedirs(os.path.join(SALIDA, _c), exist_ok=True)


def _meta(mp4):
    try:
        # utf-8-sig: un json con BOM (p.ej. editado en Windows) no debe leerse como vacio,
        # o el siguiente guardado borraria los datos de reaccion.
        with open(mp4[:-4] + ".json", encoding="utf-8-sig") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _guardar_meta(mp4, meta):
    tmp = mp4[:-4] + ".json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    os.replace(tmp, mp4[:-4] + ".json")


def _validar_parte(parte):
    """Un nombre de carpeta/archivo de la galeria: sin rutas, ni ocultos, ni papelera."""
    if not parte or "/" in parte or "\\" in parte or parte.startswith(".") \
            or parte.startswith("_"):
        raise HTTPException(400, "Ruta de clip invalida.")


def ruta_carpeta(carpeta):
    """Ruta real de una carpeta de la galeria (hija directa de salida/)."""
    _validar_parte(carpeta)
    ruta = os.path.realpath(os.path.join(SALIDA, carpeta))
    if os.path.dirname(ruta) != os.path.realpath(SALIDA) or not os.path.isdir(ruta):
        raise HTTPException(404, "Esa carpeta no existe.")
    return ruta


def ruta_clip(carpeta, nombre):
    """Ruta real de un clip de la galeria; rechaza cualquier cosa fuera de salida/."""
    for parte in (carpeta, nombre):
        _validar_parte(parte)
    if not nombre.lower().endswith(".mp4"):
        raise HTTPException(400, "Solo clips .mp4.")
    ruta = os.path.realpath(os.path.join(SALIDA, carpeta, nombre))
    if os.path.dirname(os.path.dirname(ruta)) != os.path.realpath(SALIDA):
        raise HTTPException(400, "Ruta de clip invalida.")
    if not os.path.isfile(ruta):
        raise HTTPException(404, "Ese clip ya no existe.")
    return ruta


@app.get("/api/clips")
def clips():
    grupos = []
    # PARA SUBIR arriba, SUBIDOS al final; en medio las carpetas con fecha (la mas nueva
    # primero, por el nombre: la hora de modificacion cambia al mover archivos) y luego
    # las que no tienen fecha (p.ej. 'Borrador').
    def orden(c):
        return (c == PARA_SUBIR, c != SUBIDOS, bool(re.match(r"\d{4}-\d{2}-\d{2}_", c)), c)
    for carpeta in sorted(os.listdir(SALIDA), key=orden, reverse=True):
        ruta = os.path.join(SALIDA, carpeta)
        if carpeta.startswith("_") or not os.path.isdir(ruta):
            continue
        mp4 = sorted((f for f in os.listdir(ruta) if f.lower().endswith(".mp4")),
                     key=lambda f: os.path.getmtime(os.path.join(ruta, f)), reverse=True)
        if mp4:
            grupos.append({"carpeta": carpeta, "clips": [
                {"nombre": f, "url": "/salida/" + urllib.parse.quote(f"{carpeta}/{f}"),
                 "mb": round(os.path.getsize(os.path.join(ruta, f)) / 1e6, 1),
                 # v= cambia si el clip cambia: el navegador puede cachear la miniatura para siempre
                 "thumb": "/api/miniatura?" + urllib.parse.urlencode(
                     {"carpeta": carpeta, "nombre": f,
                      "v": int(os.path.getmtime(os.path.join(ruta, f)))}),
                 **_meta(os.path.join(ruta, f))}
                for f in mp4]})
    return grupos


THUMBS = os.path.join(tempfile.gettempdir(), "clipeo_thumbs")   # cache fuera de salida/
_lock_thumb = threading.Lock()   # una a la vez: 70 ffmpeg en paralelo ahogarian al cazador


@app.get("/api/miniatura")
def miniatura(carpeta: str, nombre: str):
    """Portada del clip (un frame del segundo 2), cacheada por ruta + fecha + tamaño."""
    import hashlib
    mp4 = ruta_clip(carpeta, nombre)
    st = os.stat(mp4)
    clave = hashlib.sha1(f"{mp4}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()
    jpg = os.path.join(THUMBS, clave + ".jpg")
    if not os.path.exists(jpg):
        os.makedirs(THUMBS, exist_ok=True)
        with _lock_thumb:
            tmp = jpg[:-4] + ".tmp.jpg"
            for ss in ("2", "0"):          # clip de menos de 2 s: el primer frame
                if os.path.exists(jpg):
                    break
                subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", ss,
                                "-i", mp4, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "5",
                                tmp], capture_output=True, timeout=60)
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    os.replace(tmp, jpg)
        if not os.path.exists(jpg):
            raise HTTPException(500, "No pude sacar la miniatura de ese clip.")
    return FileResponse(jpg, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=31536000, immutable"})


class ClipRef(BaseModel):
    carpeta: str
    nombre: str


class Estado(ClipRef):
    estado: str


class Corte(ClipRef):
    ini: float = Field(ge=0)
    fin: float = Field(gt=0)


@app.post("/api/clip/estado")
def clip_estado(e: Estado):
    if e.estado not in ESTADOS:
        raise HTTPException(400, "Estado invalido.")
    mp4 = ruta_clip(e.carpeta, e.nombre)
    _guardar_meta(mp4, {**_meta(mp4), "estado": e.estado})
    return {"ok": True}


@app.post("/api/clip/borrar")
def clip_borrar(c: ClipRef):
    """No borra: mueve a salida/_papelera/<carpeta>/ (recuperable a mano)."""
    _a_papelera(ruta_clip(c.carpeta, c.nombre), c.carpeta)
    return {"ok": True}


def _acompanantes(mp4):
    """El clip + su json + su chat_NN.ass (formato split), los que existan."""
    m = re.match(r"envivo_(\d+)\.mp4$", os.path.basename(mp4))
    extra = [os.path.join(os.path.dirname(mp4), f"chat_{m.group(1)}.ass")] if m else []
    return [f for f in [mp4, mp4[:-4] + ".json", *extra] if os.path.exists(f)]


def _a_papelera(mp4, carpeta):
    destino = os.path.join(SALIDA, PAPELERA, carpeta)
    os.makedirs(destino, exist_ok=True)
    sello = time.strftime("%Y%m%d%H%M%S_")
    for src in _acompanantes(mp4):
        os.replace(src, os.path.join(destino, sello + os.path.basename(src)))


# ---------------------------------------------------------------- limpieza
BUFFER_EN_USO = 120   # s: un buffer escrito hace menos es de un cazador activo, no se toca


def _peso(rutas):
    return round(sum(os.path.getsize(f) for f in rutas if os.path.isfile(f)) / 1e6, 1)


def _clips_crudos():
    """(carpeta, ruta_mp4, meta) de los clips cazados (no PARA SUBIR/SUBIDOS/papelera)."""
    for carpeta in os.listdir(SALIDA):
        ruta = os.path.join(SALIDA, carpeta)
        if carpeta.startswith("_") or carpeta in (PARA_SUBIR, SUBIDOS) or not os.path.isdir(ruta):
            continue
        for f in os.listdir(ruta):
            if f.lower().endswith(".mp4"):
                mp4 = os.path.join(ruta, f)
                yield carpeta, mp4, _meta(mp4)


def _candidatos():
    """Que se limpiaria en cada categoria: {categoria: [(carpeta, mp4 o ruta)]}."""
    subidos_dir = os.path.join(SALIDA, SUBIDOS)
    subidos = [(SUBIDOS, os.path.join(subidos_dir, f)) for f in os.listdir(subidos_dir)
               if f.lower().endswith(".mp4")] if os.path.isdir(subidos_dir) else []
    # Originales cuyo clip producido ya se subio (el producido guarda de donde salio).
    origen_subido = {(_meta(m).get("origen"), _meta(m).get("de")) for _c, m in subidos}
    crudos = list(_clips_crudos())
    papelera = [(PAPELERA, os.path.join(r, f)) for r, _d, fs in os.walk(os.path.join(SALIDA, PAPELERA))
                for f in fs]
    buffers = []
    if os.path.isdir(BUFFER):
        for d in os.listdir(BUFFER):
            ruta = os.path.join(BUFFER, d)
            if not os.path.isdir(ruta):
                continue
            archivos = [os.path.join(ruta, f) for f in os.listdir(ruta)]
            ultimo = max((os.path.getmtime(f) for f in archivos), default=0)
            if time.time() - ultimo > BUFFER_EN_USO:     # no es de un cazador activo
                buffers.append((d, ruta))
    return {
        "descartados": [(c, m) for c, m, meta in crudos if meta.get("estado") == "descartado"],
        "originales_subidos": [(c, m) for c, m, _meta_ in crudos
                               if (c, os.path.basename(m)) in origen_subido],
        "subidos": subidos,
        "buffers": buffers,
        "papelera": papelera,
    }


def _archivos(categoria, items):
    if categoria == "buffers":
        return [os.path.join(r, f) for _d, r in items for f in os.listdir(r)]
    if categoria == "papelera":
        return [r for _c, r in items]
    return [f for _c, m in items for f in _acompanantes(m)]


@app.get("/api/limpieza")
def limpieza_resumen():
    cand = _candidatos()
    return {cat: {"n": len(items), "mb": _peso(_archivos(cat, items))}
            for cat, items in cand.items()}


class Limpiar(BaseModel):
    categoria: Literal["descartados", "originales_subidos", "subidos", "buffers", "papelera"]


@app.post("/api/limpieza")
def limpieza_hacer(l: Limpiar):
    """descartados/originales/subidos -> papelera (recuperable); buffers -> se borran
    (se regeneran al cazar); papelera -> borrado definitivo (la UI pide confirmacion)."""
    items = _candidatos()[l.categoria]
    mb = _peso(_archivos(l.categoria, items))
    if l.categoria == "buffers":
        for _d, ruta in items:
            shutil.rmtree(ruta, ignore_errors=True)
    elif l.categoria == "papelera":
        shutil.rmtree(os.path.join(SALIDA, PAPELERA), ignore_errors=True)
    else:
        for carpeta, mp4 in items:
            _a_papelera(mp4, carpeta)
    return {"ok": True, "n": len(items), "mb": mb}


@app.post("/api/clip/cortar")
def clip_cortar(c: Corte):
    """Exporta solo [ini, fin] del clip como clip nuevo (el original queda)."""
    if c.fin - c.ini < 1:
        raise HTTPException(400, "El corte debe durar al menos 1 segundo.")
    src = ruta_clip(c.carpeta, c.nombre)
    base = src[:-4]
    n = 1
    while os.path.exists(out := f"{base}_corte{'' if n == 1 else n}.mp4"):
        n += 1
    # Re-codifica (no -c copy): copiar cortaria en el keyframe y perderias el gancho.
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{c.ini:.2f}", "-to", f"{c.fin:.2f}",
         "-i", src, "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-b:v", "4000k",
         "-c:a", "aac", "-b:a", "128k", out],
        capture_output=True, text=True)
    if r.returncode != 0:
        if os.path.exists(out):
            os.remove(out)
        raise HTTPException(500, "FFmpeg fallo: " + r.stderr.strip()[-300:])
    meta = {k: v for k, v in _meta(src).items() if k != "estado"}
    _guardar_meta(out, {**meta, "estado": "bueno", "de": c.nombre,
                        "corte": [round(c.ini, 2), round(c.fin, 2)]})
    return {"ok": True, "nombre": os.path.basename(out)}


def _leer_layouts():
    try:
        with open(LAYOUTS_JSON, encoding="utf-8") as f:
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
        for k in ("face", "game"):
            if not RE_RECORTE.match(str(lay.get(k, ""))):
                raise ValueError(f"{nombre}.{k} debe ser w:h:x:y (ej 300:300:60:430)")
        limpio[nombre.lower()] = {"face": lay["face"], "game": lay["game"]}
    return limpio


class Produccion(ClipRef):
    titulo: str = Field("", max_length=80)
    subtitulos: bool = True
    estilo: Literal["amarillo", "caja", "minimal"] = "amarillo"


class Marca(BaseModel):
    handle: str = Field("", max_length=30)
    outro: str = Field("", max_length=60)


@app.get("/api/marca")
def get_marca():
    from produccion import cargar_marca
    return cargar_marca()


@app.put("/api/marca")
def put_marca(m: Marca):
    from produccion import MARCA_JSON
    tmp = MARCA_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"handle": m.handle.strip(), "outro": m.outro.strip()}, f, ensure_ascii=False)
    os.replace(tmp, MARCA_JSON)
    return {"ok": True}


_lock_prod = threading.Lock()   # un render+whisper a la vez: el PC no da para dos


@app.post("/api/clip/producir")
def clip_producir(p: Produccion):
    """Titulo gancho + subtitulos quemados -> salida/PARA SUBIR/<nombre legible>.mp4
    (lo hace produccion.py). Re-producir el mismo clip reemplaza su version anterior."""
    from produccion import producir, ruta_para_subir
    if p.carpeta in (PARA_SUBIR, SUBIDOS):
        raise HTTPException(400, "Este clip ya esta producido. Produce desde el clip original.")
    src = ruta_clip(p.carpeta, p.nombre)
    destino, viejos = ruta_para_subir(src, p.titulo, os.path.join(SALIDA, PARA_SUBIR))
    if not _lock_prod.acquire(blocking=False):
        raise HTTPException(409, "Ya hay un clip produciendose. Espera a que termine.")
    try:
        out, n = producir(src, p.titulo, p.subtitulos, p.estilo, out=destino)
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, "FFmpeg fallo: " + (e.stderr or "")[-300:])
    finally:
        _lock_prod.release()
    for v in viejos:    # solo tras exito: si falla, la version anterior sigue ahi
        if os.path.abspath(v) != os.path.abspath(out):
            for f in (v, v[:-4] + ".json"):
                if os.path.exists(f):
                    os.remove(f)
    meta = {k: v for k, v in _meta(src).items() if k != "estado"}
    _guardar_meta(out, {**meta, "estado": "bueno", "producido": True, "titulo": p.titulo,
                        "estilo": p.estilo, "de": p.nombre, "origen": p.carpeta})
    return {"ok": True, "nombre": os.path.basename(out), "carpeta": PARA_SUBIR, "palabras": n}


class Mover(ClipRef):
    destino: Literal["PARA SUBIR", "SUBIDOS"]


@app.post("/api/clip/mover")
def clip_mover(m: Mover):
    """Ya lo subi (PARA SUBIR -> SUBIDOS) o deshacerlo (SUBIDOS -> PARA SUBIR)."""
    if m.carpeta not in (PARA_SUBIR, SUBIDOS) or m.carpeta == m.destino:
        raise HTTPException(400, "Solo se mueven clips producidos entre PARA SUBIR y SUBIDOS.")
    src = ruta_clip(m.carpeta, m.nombre)
    dst = os.path.join(SALIDA, m.destino, m.nombre)
    if os.path.exists(dst):
        raise HTTPException(409, f"Ya hay un clip con ese nombre en {m.destino}.")
    os.replace(src, dst)
    if os.path.exists(src[:-4] + ".json"):
        os.replace(src[:-4] + ".json", dst[:-4] + ".json")
    return {"ok": True}


class Carpeta(BaseModel):
    carpeta: str


@app.post("/api/abrir-carpeta")
def abrir_carpeta(c: Carpeta):
    """Abre la carpeta en el Explorador de Windows (para arrastrar el clip a TikTok)."""
    os.startfile(ruta_carpeta(c.carpeta))   # app local: abre en el PC del usuario
    return {"ok": True}


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
    segs = sorted(glob.glob(os.path.join(BUFFER, f"{plataforma}_{canal}", "seg*.ts")),
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


@app.post("/api/auto-calibrar")
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


@app.get("/api/preview-recorte")
def preview_recorte(canal: str, face: str, game: str,
                    plataforma: Literal["twitch", "kick"] = "twitch", fresco: bool = False):
    """Frame real con los recortes dibujados (rojo = cara, verde = gameplay) y, al lado,
    como queda el clip split. Para calibrar sin cazar a ciegas."""
    from PIL import Image
    from clipeo import cadenas_split
    if not RE_CANAL.match(canal):
        raise HTTPException(400, "Nombre de canal invalido.")
    for nombre, rec in (("cara", face), ("gameplay", game)):
        if not RE_RECORTE.match(rec):
            raise HTTPException(400, f"El recorte de {nombre} debe ser ancho:alto:x:y.")
    canal = canal.lower()
    if fresco:
        _frames.pop((plataforma, canal), None)
    try:
        png = _frame_en_vivo(canal, plataforma)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        raise HTTPException(404, f"{canal} no esta en vivo o no responde. ({e})")
    with Image.open(png) as im:
        ancho, alto = im.size
    cajas = []
    for nombre, rec, color in (("cara", face, "red"), ("gameplay", game, "lime")):
        w, h, x, y = map(int, rec.split(":"))
        if w < 16 or h < 16 or x + w > ancho or y + h > alto:
            raise HTTPException(400, f"El recorte de {nombre} ({rec}) se sale del frame "
                                     f"({ancho}x{alto}).")
        cajas.append(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={color}:t=6")
    top, bot = cadenas_split({"face": face, "game": game})
    fc = (f"[0:v]split=3[a][b][c];[a]{','.join(cajas)},scale=-2:720[full];"
          f"[b]{top}[top];[c]{bot}[bot];[top][bot]vstack,scale=-2:720[split];"
          "[full][split]hstack")
    out = png[:-4] + "_preview.jpg"
    r = subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", png,
                        "-filter_complex", fc, "-frames:v", "1", "-q:v", "3", out],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise HTTPException(500, "FFmpeg fallo: " + r.stderr.strip()[-300:])
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/layouts")
def get_layouts():
    return _leer_layouts()


@app.put("/api/layouts")
def put_layouts(datos: dict):
    try:
        limpio = validar_layouts(datos)
    except ValueError as e:
        raise HTTPException(400, str(e))
    tmp = LAYOUTS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(limpio, f, indent=2)
    os.replace(tmp, LAYOUTS_JSON)  # escritura atomica: no deja el json a medias
    return {"ok": True, "nota": "Se aplica al proximo arranque del cazador."}


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
        return Sesiones(SALIDA).datos(sid)
    except (OSError, ValueError):
        raise HTTPException(404, "Esa sesión no existe.")


def _duracion(d):
    return hms(d["fin"] - d["inicio"]) if d.get("inicio") is not None and d.get("fin") is not None else None


@app.get("/api/revision/sesiones")
def revision_sesiones():
    return [{"id": d["id"], "canal": d["canal"], "plataforma": d["plataforma"],
             "duracion": _duracion(d), "n_clips": len(clips_de(SALIDA, d["id"]))}
            for d in Sesiones(SALIDA).lista()]


@app.get("/api/revision/sesion/{sid}")
def revision_sesion(sid: str):
    d = _sesion(sid)
    rev, clips = Revision(SALIDA, sid), clips_de(SALIDA, sid)
    estado = rev.estado()
    descartados = {c.id for c in clips if rev.decision(c.id, c.origen) == "descartar"}
    parejas = emparejar(clips, set(estado["deshechos"]), descartados)
    vistos = []
    for c in clips:
        ruta_clip(c.carpeta, c.nombre + ".mp4")          # valida: solo clips de la galería
        vistos.append({"id": c.id, "url": f"/salida/{urllib.parse.quote(c.carpeta)}/{urllib.parse.quote(c.nombre)}.mp4",
                       "tiempo": hms(c.tiempo), "t": c.tiempo, "ventana": c.ventana, "origen": c.origen,
                       "decision": rev.decision(c.id, c.origen)})
    return {"sesion": {"canal": d["canal"], "plataforma": d["plataforma"], "inicio": d["estado_inicio"],
                       "duracion": _duracion(d),
                       "cortes": [{"en": hms(k["en"]), "dura_s": int(round(k["dura"]))} for k in d["cortes"]]},
            "clips": vistos, "parejas": {m: {"con": a, "solape": s} for m, (a, s) in parejas.items()},
            "estado": estado, "aviso": rev.aviso}


@app.post("/api/revision/sesion/{sid}")
def revision_cambiar(sid: str, a: AccionRevision):
    _sesion(sid)
    rev = Revision(SALIDA, sid)
    origenes = {c.id: c.origen for c in clips_de(SALIDA, sid)}
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
    r = construir(d, clips_de(SALIDA, sid), Revision(SALIDA, sid).estado())
    validar(r)
    return r


@app.get("/api/revision/resumen/{sid}")
def revision_resumen(sid: str):
    r = _resumen(sid)
    return {"legible": texto_legible(r), "exacto": texto_exacto(r)}


@app.post("/api/revision/resumen/{sid}/guardar")
def revision_guardar(sid: str):
    """Solo se llama cuando el usuario confirma en la vista previa. No se envía a ningún sitio."""
    return {"guardado": guardar(_resumen(sid), SALIDA)}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(AQUI, "app.html"), encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import socket
    import uvicorn
    URL = f"http://127.0.0.1:{PUERTO}"
    # Si ya esta abierta (doble clic otra vez), solo abre la pagina en vez de fallar.
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", PUERTO)) == 0:
            webbrowser.open(URL)
            sys.exit(0)
    threading.Timer(1.5, webbrowser.open, args=(URL,)).start()
    print(f"Clipeo abierto en {URL}  (cierra esta ventana para apagarlo)")
    uvicorn.run(app, host="127.0.0.1", port=PUERTO, log_level="warning")
