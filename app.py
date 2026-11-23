"""
app.py - UI local para el clipeo. Envuelve autoclip.py (no lo reescribe).

Uso:   python app.py      -> abre http://127.0.0.1:8765
"""
import collections
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

import clipeo
from clips_vivos import ClipsVivos
import progreso
from serie_chat import SerieChat
from credito import credito_final
import sin_consola
sin_consola.activar()   # ffmpeg/yt-dlp sin ventanas de terminal

AQUI = os.path.dirname(os.path.abspath(__file__))
# Sobrescribibles solo para probar la limpieza con datos falsos sin tocar los clips reales.
SALIDA = os.environ.get("CLIPEO_SALIDA") or os.path.join(AQUI, "salida")
BUFFER = os.environ.get("CLIPEO_BUFFER") or os.path.join(AQUI, "buffer")
LAYOUTS_JSON = os.path.join(AQUI, "layouts.json")
PUERTO = 8765


os.makedirs(SALIDA, exist_ok=True)
app = FastAPI(title="Clipeo")
# Solo peticiones a este PC: una web que se haga pasar por 127.0.0.1 (DNS rebinding) recibe 400.
from fastapi.middleware.trustedhost import TrustedHostMiddleware
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
app.mount("/salida", StaticFiles(directory=SALIDA), name="salida")
# Fuentes y recursos de la interfaz, servidos desde el proyecto (sin depender de internet).
os.makedirs(os.path.join(AQUI, "assets"), exist_ok=True)
app.mount("/assets", StaticFiles(directory=os.path.join(AQUI, "assets")), name="assets")
from api_asistente import router as _router_asistente   # preferencias, proveedores de IA y chat
app.include_router(_router_asistente)
import api_recortes                                      # Ajustes → Recortes
from api_recortes import RE_CANAL, validar_layouts       # noqa: F401  (validar_layouts: la usan los tests)
api_recortes.buffer_dir = lambda: BUFFER
api_recortes.layouts_json = lambda: LAYOUTS_JSON
app.include_router(api_recortes.router)
import api_revision                                      # Clips → Revisar directo
api_revision.salida = lambda: SALIDA
api_revision._ruta_clip = lambda carpeta, nombre: ruta_clip(carpeta, nombre)
app.include_router(api_revision.router)

# Estado del cazador: uno a la vez.
_lock = threading.Lock()
_estado = {"proc": None, "canal": "", "inicio": 0.0, "pausado": False}
_log = collections.deque(maxlen=300)
_vivos = ClipsVivos(SALIDA)
_serie = SerieChat()


def avisador(titulo, texto):
    """Aviso de Windows. Lo sustituye la bandeja del sistema al abrir la app nativa (hypazo.py)."""


def _avisar_clip(evento):
    if not evento:
        return
    tipo, c = evento
    try:
        if tipo == "listo":
            avisador("Clip listo", f"Clip {c['n']} de {_estado['canal']} guardado.")
        else:
            avisador("Clip descartado", f"Clip {c['n']}: {c['error']}"[:200])
    except Exception:          # un aviso que falla no debe parar la lectura del cazador
        pass


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
        if _serie.leer(linea, time.time()):      # medida para la gráfica: no ensucia el registro
            continue
        _log.append(linea.rstrip("\r\n"))
        _avisar_clip(_vivos.leer(linea))
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
        _vivos.limpiar()
        _serie.limpiar()
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
        _vivos.limpiar()
        _serie.limpiar()
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
            "inicio": _estado["inicio"], "log": list(_log)[-120:], "vivos": _vivos.lista(),
            "serie": _serie.datos()}


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
    try:
        clipeo.con_respaldo(lambda video: subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{c.ini:.2f}", "-to", f"{c.fin:.2f}",
             "-i", src, "-r", "30", *video, "-c:a", "aac", "-b:a", "128k", out],
            capture_output=True, text=True, check=True))
    except subprocess.CalledProcessError as e:
        if os.path.exists(out):
            os.remove(out)
        raise HTTPException(500, "FFmpeg fallo: " + (e.stderr or "").strip()[-300:])
    meta = {k: v for k, v in _meta(src).items() if k != "estado"}
    _guardar_meta(out, {**meta, "estado": "bueno", "de": c.nombre,
                        "corte": [round(c.ini, 2), round(c.fin, 2)]})
    return {"ok": True, "nombre": os.path.basename(out)}


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
    clave = f"{p.carpeta}/{p.nombre}"
    try:
        out, n = producir(src, p.titulo, p.subtitulos, p.estilo, out=destino, aviso=progreso.avisador(clave))
    except subprocess.CalledProcessError as e:
        raise HTTPException(500, "FFmpeg fallo: " + (e.stderr or "")[-300:])
    finally:
        progreso.quitar(clave)
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


REDES = ("tiktok", "shorts", "reels")
_lock_redes = threading.Lock()


class Red(ClipRef):
    red: Literal["tiktok", "shorts", "reels"]
    hecho: bool


@app.post("/api/clip/redes")
def clip_redes(r: Red):
    """Marca en qué redes está subido un clip de PARA SUBIR; con las tres, pasa solo a SUBIDOS."""
    if r.carpeta != PARA_SUBIR:
        raise HTTPException(400, "Solo los clips de PARA SUBIR llevan la lista de redes.")
    with _lock_redes:          # tres clics seguidos: leer-cambiar-guardar uno detrás de otro
        mp4 = ruta_clip(r.carpeta, r.nombre)
        meta = _meta(mp4)
        hechas = set(meta.get("subido_en") or []) & set(REDES)
        hechas = hechas | {r.red} if r.hecho else hechas - {r.red}
        _guardar_meta(mp4, {**meta, "subido_en": sorted(hechas)})
        movido = hechas == set(REDES)
        if movido:
            clip_mover(Mover(carpeta=PARA_SUBIR, nombre=r.nombre, destino=SUBIDOS))
    return {"subido_en": sorted(hechas), "movido": movido}


class Carpeta(BaseModel):
    carpeta: str


@app.post("/api/abrir-carpeta")
def abrir_carpeta(c: Carpeta):
    """Abre la carpeta en el Explorador de Windows (para arrastrar el clip a TikTok)."""
    os.startfile(ruta_carpeta(c.carpeta))   # app local: abre en el PC del usuario
    return {"ok": True}


@app.post("/api/abrir-salida")
def abrir_salida():
    """La carpeta donde se guardan todos los clips (asistente de primer uso)."""
    os.startfile(SALIDA)
    return {"ok": True}


class Textos(ClipRef):
    transcribir: bool = True


def _transcripcion(mp4, meta):
    """Lo que se dice en el clip (Whisper local, se guarda en su .json). Vacío si el PC está ocupado."""
    if meta.get("transcripcion") is not None:
        return meta["transcripcion"]
    from produccion import transcribir
    if not _lock_prod.acquire(timeout=2):
        return ""
    try:
        texto = " ".join(w for _i, _f, w in transcribir(mp4))[:3000]
    except (subprocess.CalledProcessError, OSError, RuntimeError):
        return ""
    finally:
        _lock_prod.release()
    _guardar_meta(mp4, {**_meta(mp4), "transcripcion": texto})
    return texto


PASOS_TEXTOS = ("Transcribiendo lo que se dice", "Pidiendo títulos a la IA", "Preparando textos")


@app.post("/api/clip/textos")
def clip_textos(t: Textos):
    """Títulos, hashtags y textos para TikTok / Shorts / Reels (con IA si hay proveedor)."""
    import hypazo
    import ia
    import textos_clip
    mp4 = ruta_clip(t.carpeta, t.nombre)
    meta = _meta(mp4)
    if not meta.get("canal"):                  # clips viejos: el canal sale de la carpeta
        m = re.match(r"^\d{4}-\d{2}-\d{2}_(kick_)?(.+)$", meta.get("origen") or t.carpeta)
        if m:
            meta = {**meta, "canal": m[2], "plataforma": "kick" if m[1] else "twitch"}
    cfg_ia = hypazo.config().get("ia", {})
    hay_ia = bool(ia.disponibles(cfg_ia))
    clave = f"{t.carpeta}/{t.nombre}"
    try:
        if hay_ia and t.transcribir:
            progreso.poner(clave, "Transcribiendo lo que se dice")
        texto = _transcripcion(mp4, meta) if (hay_ia and t.transcribir) else ""
        progreso.poner(clave, "Pidiendo títulos a la IA" if hay_ia else "Preparando textos")
        res = textos_clip.generar(meta, cfg_ia, texto) if hay_ia else textos_clip.basico(meta)
    finally:
        if progreso.lista().get(clave, {}).get("paso") in PASOS_TEXTOS:   # no borrar el de una producción
            progreso.quitar(clave)
    _guardar_meta(mp4, {**_meta(mp4), "textos": res})
    return res


@app.get("/api/progreso")
def ver_progreso():
    """Tareas largas en curso (producir, textos) y en qué paso van."""
    return progreso.lista()


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(AQUI, "app.html"), encoding="utf-8") as f:
        html = f.read()
    # ?v=<fecha del archivo>: tras actualizar, la ventana no se queda con el CSS/JS viejo en caché
    return re.sub(r'(/assets/[\w.-]+\.(?:css|js))"',
                  lambda m: f'{m[1]}?v={int(os.path.getmtime(os.path.join(AQUI, m[1][1:])))}"', html)


abrir_mini = None    # la pone hypazo.py al abrir la ventana de escritorio


@app.post("/api/mini")
def mini():
    """Mini ventana siempre encima mientras se caza (solo en la app de escritorio)."""
    if abrir_mini is None:
        raise HTTPException(409, "La mini ventana solo está en la app de escritorio.")
    abrir_mini()
    return {"ok": True}


@app.get("/mini", response_class=HTMLResponse)
def pagina_mini():
    with open(os.path.join(AQUI, "mini.html"), encoding="utf-8") as f:
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
