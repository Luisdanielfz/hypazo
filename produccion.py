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

MODELO = "small"        # base = mas rapido / peor; small va bien en español en CPU
PALABRAS_POR_GRUPO = 3
PAUSA_CORTE = 0.6       # silencio (s) que fuerza grupo nuevo
OUTRO_SEG = 2.5
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


def escribir_ass(palabras, titulo, duracion, path, estilo="amarillo", marca=None):
    est = ESTILOS.get(estilo, ESTILOS["amarillo"])
    marca = marca or {}
    sub = _ESTILO_BASE.format(n="sub", align=2, ml=60, mr=60, mv=560, **est["sub"])
    filas = []
    if titulo:
        filas.append(f"Dialogue: 1,{_t(0)},{_t(duracion)},titulo,,0,0,0,,{limpiar(titulo).upper()}")
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


def transcribir(path):
    """[(ini, fin, palabra)] del audio del clip, en español."""
    global _modelo
    import numpy as np
    from faster_whisper import WhisperModel
    if _modelo is None:   # se carga una vez y se reutiliza (tarda ~10s)
        _modelo = WhisperModel(MODELO, device="cpu", compute_type="int8")
    # Audio decodificado con nuestro FFmpeg: el lector interno (PyAV) choca de version.
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-f", "f32le",
                          "-ac", "1", "-ar", "16000", "-"], capture_output=True, check=True).stdout
    if not raw:
        return []
    segs, _info = _modelo.transcribe(np.frombuffer(raw, np.float32), language="es",
                                     word_timestamps=True, vad_filter=True)
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


def producir(src, titulo="", subtitulos=True, estilo="amarillo", marca=None, out=None, aviso=None):
    """Crea el clip para TikTok en `out` (por defecto <src>_tiktok.mp4).
    aviso(paso, pct=None), si se da, recibe en qué paso va. Devuelve (ruta, n_palabras)."""
    aviso = aviso or (lambda paso, pct=None: None)
    out = out or src[:-4] + "_tiktok.mp4"
    if subtitulos:
        aviso("Transcribiendo lo que se dice")
    palabras = transcribir(src) if subtitulos else []
    tmpdir = tempfile.mkdtemp(prefix="clipeo_")
    try:
        aviso("Poniendo título y subtítulos")
        ass = os.path.join(tmpdir, "prod.ass")
        duracion = _duracion(src)
        escribir_ass(palabras, titulo, duracion, ass, estilo,
                     cargar_marca() if marca is None else marca)
        tmp_mp4 = os.path.join(tmpdir, "prod.mp4")
        aviso("Montando el vídeo", 0)
        # cwd=tmpdir y nombre relativo: evita escapar 'C:' dentro del filtro ass=
        _ffmpeg_con_progreso(["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                              "-i", os.path.abspath(src), "-vf", "ass=prod.ass", "-r", "30",
                              "-c:v", "libx264", "-preset", "veryfast", "-b:v", "5000k",
                              "-c:a", "aac", "-b:a", "128k", "prod.mp4"], tmpdir, duracion, aviso)
        if os.path.exists(out):     # re-producir: en Windows move no pisa un archivo
            os.remove(out)
        shutil.move(tmp_mp4, out)   # aparece entero o no aparece
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return out, len(palabras)


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
    out, n = producir(a.clip, a.titulo, not a.sin_subs, a.estilo, out=out)
    for v in viejos:
        if os.path.abspath(v) != os.path.abspath(out):
            os.remove(v)
    print(f"Listo ({n} palabras subtituladas): {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
