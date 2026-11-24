"""
produccion.py - Deja un clip listo para TikTok: titulo gancho arriba + subtitulos
quemados palabra a palabra + marca de la cuenta. Un solo pase de FFmpeg.

Transcribe en LOCAL con faster-whisper (gratis, el audio no sale del PC).
La primera vez descarga el modelo (~460 MB).

Estilos de subtitulo:  amarillo (palabra que suena en amarillo) | caja (sobre caja
negra, palabra en rojo) | minimal (pequeño, sin resaltar).  Palabras fuertes
("no", "dios", "brutal"...) salen en naranja.

Marca (marca.json, editable desde la app):  {"handle": "@tucuenta", "outro": "Sigueme para mas"}
  handle -> marca de agua arriba a la derecha;  outro -> cartel los ultimos 2.5 s.

Uso:
    python produccion.py salida/2026-11-20_rubius/envivo_02.mp4 --titulo "RUBIUS FLIPA"
    python produccion.py clip.mp4 --estilo caja --sin-subs --titulo "..."
Sale en  salida/PARA SUBIR/  con nombre legible, p.ej.
    "2026-11-20 rubius envivo_04 - RUBIUS FLIPA.mp4"
(re-producir el mismo clip reemplaza su version anterior, no duplica).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading

import clipeo
import cortes
import efectos
import voz

MODELO = "small"        # base = mas rapido / peor; small va bien en español en CPU
PALABRAS_POR_GRUPO = 3
PAUSA_CORTE = 0.6       # silencio (s) que fuerza grupo nuevo
OUTRO_SEG = 2.5
CONTEXTO_SEG = 3.0      # el rótulo de contexto, al empezar el cuerpo del clip
MARCA_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "marca.json")
_modelo = None

# Colores ASS en &HAABBGGRR (BGR + alfa, 00 = opaco).
_ESTILO_BASE = "Style: {n},{font},{size},{prim},&H000000FF,{out},{back},{bold},0,0,0,100,100,0,0,{borde},{outline},{shadow},{align},{ml},{mr},{mv},1"
ESTILOS = {
    "amarillo": dict(sub=dict(font="Arial", size=80, prim="&H00FFFFFF", out="&H00000000",
                              back="&H64000000", bold=1, borde=1, outline=7, shadow=3),
                     activo="&H0000FFFF", mayus=True),
    "caja": dict(sub=dict(font="Arial", size=74, prim="&H00FFFFFF", out="&H00000000",
                          back="&H00000000", bold=1, borde=3, outline=12, shadow=0),
                 activo="&H004B4BFF", mayus=True),
    "minimal": dict(sub=dict(font="Arial", size=60, prim="&H00FFFFFF", out="&H00000000",
                             back="&H80000000", bold=0, borde=1, outline=3, shadow=2),
                    activo="", mayus=False),
}
ENFASIS_COLOR = "&H00008CFF"   # naranja
ENFASIS = {"no", "noo", "nooo", "dios", "joder", "hostia", "ostia", "madre", "increible",
           "increíble", "brutal", "loco", "gol", "golazo", "vamos", "wtf", "omg", "qué",
           "mierda", "flipa", "flipo", "tremendo", "imposible", "muerto", "nunca"}

_CABECERA = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: titulo,Arial,68,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,3,16,0,8,70,70,120,1
{sub}
Style: marca,Arial,38,&H60FFFFFF,&H000000FF,&H80000000,&H00000000,1,0,0,0,100,100,0,0,1,2,0,9,40,40,40,1
Style: contexto,Arial,50,&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,3,14,0,2,90,90,760,1
Style: outro,Arial,76,&H00FFFFFF,&H000000FF,&H00FF4691,&H00000000,1,0,0,0,100,100,0,0,3,22,0,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _t(seg):
    seg = max(0.0, seg)
    return f"{int(seg // 3600)}:{int(seg % 3600 // 60):02d}:{seg % 60:05.2f}"


def limpiar(texto):
    """Texto seguro para ASS: sin llaves/barras (son comandos) ni saltos."""
    return " ".join(texto.replace("{", "(").replace("}", ")").replace("\\", "/").split())


def _clave(palabra):
    return re.sub(r"[^\wáéíóúñü]", "", palabra.lower())


def agrupar(palabras):
    """palabras=[(ini, fin, texto)] -> grupos cortos para leer de un vistazo."""
    grupos, actual = [], []
    for p in palabras:
        if actual and (len(actual) >= PALABRAS_POR_GRUPO or p[0] - actual[-1][1] > PAUSA_CORTE):
            grupos.append(actual)
            actual = []
        actual.append(p)
    if actual:
        grupos.append(actual)
    return grupos


def _palabra(w, activa, est):
    """Una palabra del grupo con su color: activa > enfasis > normal."""
    if activa and est["activo"]:
        return "{\\c" + est["activo"] + "&}" + w + "{\\c&HFFFFFF&}"
    if _clave(w) in ENFASIS:
        return "{\\c" + ENFASIS_COLOR + "&\\fscx112\\fscy112}" + w + "{\\c&HFFFFFF&\\fscx100\\fscy100}"
    return w


def escribir_ass(palabras, titulo, duracion, path, estilo="amarillo", marca=None, contexto=None):
    """contexto = (ini, fin, texto): rótulo que sitúa la escena, debajo del título."""
    est = ESTILOS.get(estilo, ESTILOS["amarillo"])
    marca = marca or {}
    sub = _ESTILO_BASE.format(n="sub", align=2, ml=60, mr=60, mv=560, **est["sub"])
    filas = []
    if titulo:
        filas.append(f"Dialogue: 1,{_t(0)},{_t(duracion)},titulo,,0,0,0,,{limpiar(titulo).upper()}")
    if contexto and limpiar(contexto[2]):
        ini_c, fin_c, texto_c = contexto
        filas.append(f"Dialogue: 1,{_t(ini_c)},{_t(fin_c)},contexto,,0,0,0,,{{\\fad(200,300)}}{limpiar(texto_c)}")
    handle, outro = limpiar(marca.get("handle", "")), limpiar(marca.get("outro", ""))
    if handle:
        filas.append(f"Dialogue: 2,{_t(0)},{_t(duracion)},marca,,0,0,0,,{handle}")
    if outro:
        ini = max(0.0, duracion - OUTRO_SEG)
        filas.append(f"Dialogue: 3,{_t(ini)},{_t(duracion)},outro,,0,0,0,,"
                     "{\\fad(250,0)}" + outro + (r"\N" + handle if handle else ""))
    textos = [(i, f, limpiar(t)) for i, f, t in palabras if limpiar(t)]
    grupos = agrupar([(i, f, t.upper() if est["mayus"] else t) for i, f, t in textos])
    for g, grupo in enumerate(grupos):
        fin_grupo = grupo[-1][1] + 0.3
        if g + 1 < len(grupos):
            fin_grupo = min(fin_grupo, grupos[g + 1][0][0])
        for k, (ini, _fin, _tx) in enumerate(grupo):
            hasta = grupo[k + 1][0] if k + 1 < len(grupo) else fin_grupo
            texto = " ".join(_palabra(w, j == k, est) for j, (_a, _b, w) in enumerate(grupo))
            filas.append(f"Dialogue: 0,{_t(ini)},{_t(hasta)},sub,,0,0,0,,{texto}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_CABECERA.format(sub=sub) + "\n".join(filas) + "\n")


def cargar_marca():
    try:
        with open(MARCA_JSON, encoding="utf-8-sig") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"handle": "", "outro": ""}


def _duracion(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", path], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _audio(path):
    """Audio mono a 16 kHz en float32. Decodificado con nuestro FFmpeg: el lector interno (PyAV) choca de versión."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-f", "f32le",
                          "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def transcribir(path):
    """[(ini, fin, palabra)] del audio del clip, en español."""
    global _modelo
    from faster_whisper import WhisperModel
    if _modelo is None:   # se carga una vez y se reutiliza (tarda ~10s)
        _modelo = WhisperModel(MODELO, device="cpu", compute_type="int8")
    audio = _audio(path)
    if not len(audio):
        return []
    segs, _info = _modelo.transcribe(audio, language="es", word_timestamps=True, vad_filter=True)
    return [(w.start, w.end, w.word.strip()) for s in segs for w in s.words]


def ruta_para_subir(src, titulo, carpeta_destino):
    """Nombre legible en PARA SUBIR + versiones anteriores de este mismo clip.
    salida/2026-11-20_rubius/envivo_04.mp4 + "Rubius flipa" ->
        "2026-11-20 rubius envivo_04 - RUBIUS FLIPA.mp4"
    Devuelve (ruta_nueva, [rutas_viejas]) para que re-producir reemplace, no duplique."""
    origen = os.path.basename(os.path.dirname(src)).replace("_", " ", 1)
    clave = f"{origen} {os.path.basename(src)[:-4]}"
    t = re.sub(r'[\\/:*?"<>|]', "", limpiar(titulo)).strip().upper()[:60]  # prohibido en Windows
    nuevo = os.path.join(carpeta_destino, clave + (f" - {t}" if t else "") + ".mp4")
    viejos = [os.path.join(carpeta_destino, f) for f in os.listdir(carpeta_destino)
              if f == clave + ".mp4" or (f.startswith(clave + " - ") and f.endswith(".mp4"))]
    return nuevo, viejos


def pct_ffmpeg(linea: str, duracion: float):
    """% hecho a partir de una línea de `ffmpeg -progress` (out_time_us / out_time_ms, ambas en µs)."""
    clave, _, valor = linea.strip().partition("=")
    if clave not in ("out_time_us", "out_time_ms") or not duracion:
        return None
    try:
        return max(0, min(99, int(int(valor) / 1e6 / duracion * 100)))
    except ValueError:
        return None


def _ffmpeg_con_progreso(cmd, cwd, duracion, aviso):
    """Como subprocess.run(check=True) pero contando el avance; mismo CalledProcessError si falla."""
    proc = subprocess.Popen(cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:], cwd=cwd, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    err = []
    hilo = threading.Thread(target=lambda: err.extend(proc.stderr), daemon=True)   # que stderr no tape la tubería
    hilo.start()
    try:
        for linea in proc.stdout:
            pct = pct_ffmpeg(linea, duracion)
            if pct is not None:
                aviso("Montando el vídeo", pct)
    except BaseException:          # si falla el aviso, que ffmpeg no se quede vivo bloqueando la carpeta temporal
        proc.kill()
        proc.wait()
        raise
    proc.wait()
    hilo.join(5)
    if proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr="".join(err))


def _tiene_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _tamano(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True, check=True)
    ancho, alto = r.stdout.strip().splitlines()[0].split(",")[:2]
    return int(ancho), int(alto)


def _fuentes(origen, filtro, etiqueta, n, partir):
    """Aplica `filtro` a la entrada y la reparte en n copias (una etiqueta de filtro solo se usa una vez)."""
    if not filtro:
        return [], [origen] * n
    trozos = [f"{origen}{filtro}[{etiqueta}]"]
    if n == 1:
        return trozos, [f"[{etiqueta}]"]
    salidas = [f"[{etiqueta}{k}]" for k in range(n)]
    trozos.append(f"[{etiqueta}]{partir}={n}{''.join(salidas)}")
    return trozos, salidas


def _filtro_montaje(partes, audio, video_pre="", golpe=""):
    """filter_complex: efectos sobre el clip entero, luego pega los tramos [(desde, hasta)] y quema los
    subtítulos -> [v] y [a]."""
    n, trozos, entradas = len(partes), [], ""
    t_v, fv = _fuentes("[0:v]", f"setpts=PTS-STARTPTS,{video_pre}" if video_pre else "", "vz", n, "split")
    trozos += t_v
    fa = ["[0:a]"] * n
    if audio and golpe:
        trozos.append(f"{golpe}[g]")
        t_a, fa = _fuentes("[0:a]", "asetpts=PTS-STARTPTS[a0];[a0][g]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=disabled",
                           "az", n, "asplit")
        trozos += t_a
    for k, (a, b) in enumerate(partes):
        trozos.append(f"{fv[k]}trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{k}]")
        entradas += f"[v{k}]"
        if audio:
            trozos.append(f"{fa[k]}atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{k}]")
            entradas += f"[a{k}]"
    salida = "[m][a]" if audio else "[m]"
    trozos.append(f"{entradas}concat=n={len(partes)}:v=1:a={int(audio)}{salida}")
    trozos.append("[m]ass=prod.ass[v]")
    return ";".join(trozos)


def producir(src, titulo="", subtitulos=True, estilo="amarillo", marca=None, out=None, aviso=None,
             ajustar=False, cold_open=False, remate=7.0, zoom=False, golpe=False, contexto="",
             solo_streamer=False, perfil=None):
    """Crea el clip para TikTok en `out` (por defecto <src>_tiktok.mp4).
    ajustar: empezar en una frase (cortes.inicio); cold_open: abrir con el momento. El pico del chat está
    `remate` segundos antes del final (None = no se sabe: ni corte, ni cold open, ni zoom, ni golpe).
    zoom/golpe: efectos.py en el momento; contexto: rótulo que sitúa la escena al empezar el cuerpo.
    solo_streamer: quita las frases de otras voces (voz.py) con el perfil de voz guardado (o None).
    aviso(paso, pct=None), si se da, recibe en qué paso va.
    Devuelve (ruta, n_palabras, {"inicio": s, "cold_open": bool, "zoom": bool, "golpe": bool, "perfil": huella|None})."""
    aviso = aviso or (lambda paso, pct=None: None)
    out = out or src[:-4] + "_tiktok.mp4"
    if remate is None:
        ajustar = cold_open = zoom = golpe = False
    if subtitulos or ajustar:
        aviso("Transcribiendo lo que se dice")
    if subtitulos:
        palabras = transcribir(src)
    elif ajustar:
        try:                    # solo para el corte: si Whisper falla, el clip sale entero como antes
            palabras = transcribir(src)
        except Exception:
            palabras = []
    else:
        palabras = []
    nuevo_perfil = None
    if solo_streamer and palabras:
        aviso("Separando la voz del streamer")
        try:                    # si algo falla (sin modelo, sin red), subtítulos con todas las voces, como antes
            palabras, nuevo_perfil = voz.filtrar(palabras, _audio(src), perfil=perfil)
        except Exception:
            nuevo_perfil = None
    tmpdir = tempfile.mkdtemp(prefix="clipeo_")
    try:
        aviso("Poniendo título y subtítulos")
        ass = os.path.join(tmpdir, "prod.ass")
        duracion = _duracion(src)
        pico = max(0.0, duracion - (remate or 0.0))
        ini = cortes.inicio(palabras, pico) if ajustar else 0.0
        partes = cortes.tramos(duracion, pico, ini, cold_open)
        total = sum(b - a for a, b in partes)
        cuerpo = partes[-1][1] - partes[-1][0]
        rotulo = (total - cuerpo, min(total, total - cuerpo + CONTEXTO_SEG), contexto) if contexto.strip() else None
        escribir_ass(cortes.recolocar(palabras, partes) if subtitulos else [], titulo, total, ass, estilo,
                     cargar_marca() if marca is None else marca, contexto=rotulo)
        tmp_mp4 = os.path.join(tmpdir, "prod.mp4")
        aviso("Montando el vídeo", 0)
        audio = _tiene_audio(src)
        zoom, golpe = zoom and efectos.cabe(pico), golpe and audio and efectos.cabe(pico)
        if partes == [(0.0, duracion)] and not zoom and not golpe:
            montaje = ["-vf", "ass=prod.ass"]
        else:
            video_pre = efectos.zoom(pico, *_tamano(src)) if zoom else ""
            filtro = _filtro_montaje(partes, audio, video_pre, efectos.golpe(pico) if golpe else "")
            montaje = ["-filter_complex", filtro, "-map", "[v]"] + (["-map", "[a]"] if audio else [])
        # cwd=tmpdir y nombre relativo: evita escapar 'C:' dentro del filtro ass=
        clipeo.con_respaldo(lambda video: _ffmpeg_con_progreso(
            ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", os.path.abspath(src),
             *montaje, "-r", "30", *video, "-c:a", "aac", "-b:a", "128k", "prod.mp4"],
            tmpdir, total, aviso), "5000k")
        if os.path.exists(out):     # re-producir: en Windows move no pisa un archivo
            os.remove(out)
        shutil.move(tmp_mp4, out)   # aparece entero o no aparece
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out, len(palabras) if subtitulos else 0, {"inicio": float(round(ini, 2)), "cold_open": cold_open,
                                                     "zoom": zoom, "golpe": golpe, "perfil": nuevo_perfil}


def main():
    p = argparse.ArgumentParser(description="Titulo gancho + subtitulos quemados para TikTok.")
    p.add_argument("clip")
    p.add_argument("--titulo", default="")
    p.add_argument("--estilo", choices=list(ESTILOS), default="amarillo")
    p.add_argument("--sin-subs", action="store_true")
    a = p.parse_args()
    from clipeo import SALIDA
    destino = os.path.join(os.path.dirname(os.path.abspath(__file__)), SALIDA, "PARA SUBIR")
    os.makedirs(destino, exist_ok=True)
    out, viejos = ruta_para_subir(os.path.abspath(a.clip), a.titulo, destino)
    out, n, _info = producir(a.clip, a.titulo, not a.sin_subs, a.estilo, out=out)
    for v in viejos:
        if os.path.abspath(v) != os.path.abspath(out):
            os.remove(v)
    print(f"Listo ({n} palabras subtituladas): {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
