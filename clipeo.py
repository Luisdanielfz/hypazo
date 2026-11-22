"""
clipeo.py - Convierte un clip de Twitch/YouTube en un video vertical listo para TikTok.
100% gratis, sin marca de agua. Fondo difuminado + clip centrado + credito al streamer.

Uso:
    python clipeo.py "URL_DEL_CLIP" --credito "@auronplay"
    python clipeo.py --test            (auto-prueba sin descargar nada)

Los subtitulos: actívalos GRATIS al subir en la propia app de TikTok (auto-captions).
"""
import argparse
import subprocess
import sys
import os
import tempfile

SALIDA = os.environ.get("CLIPEO_SALIDA") or "salida"   # el instalador la pone en Vídeos\Hypazo
# Fuente para el credito en pantalla. En el filtro de FFmpeg el ':' de la unidad va escapado.
FONT = "'C\\:/Windows/Fonts/arialbd.ttf'"


def _esc_texto(t):
    # Escapa caracteres especiales de drawtext.
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def filtro_vertical(credito):
    cap = (
        f"drawtext=fontfile={FONT}:text='{_esc_texto(credito)}'"
        ":fontcolor=white:fontsize=46:box=1:boxcolor=black@0.5:boxborderw=14"
        ":x=(w-text_w)/2:y=h-220"
    ) if credito else "null"
    return (
        # fps=30 primero y fondo difuminado a 270x480 (luego escalado): misma imagen, 2,5x más rápido.
        "[0:v]fps=30,split=2[bg][fg];"
        "[bg]scale=270:480:force_original_aspect_ratio=increase,"
        "crop=270:480,boxblur=6,scale=1080:1920[bgb];"
        "[fg]scale=1080:-2[fgs];"
        "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,format=yuv420p[ov];"
        f"[ov]{cap}[out]"
    )


CANDIDATOS_HW = ("h264_nvenc", "h264_qsv", "h264_amf")   # NVIDIA, Intel QuickSync, AMD
_codificador = None


def elegir_codificador(ejecutar=subprocess.run):
    """El primer codificador por hardware que de verdad funciona en este PC, o libx264."""
    for c in CANDIDATOS_HW:
        r = ejecutar(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                      "color=c=black:s=256x256:d=0.2", "-c:v", c, "-f", "null", "-"], capture_output=True)
        if r.returncode == 0:
            return c
    return "libx264"


def args_video():
    """Codificador para los clips (se averigua una vez por proceso)."""
    global _codificador
    if _codificador is None:
        _codificador = elegir_codificador()
    extra = ["-preset", "veryfast"] if _codificador == "libx264" else []
    return ["-c:v", _codificador, *extra, "-b:v", "4000k"]


def convertir(entrada, salida, credito):
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-err_detect", "ignore_err",
        "-fflags", "+discardcorrupt", "-max_error_rate", "1.0", "-i", entrada,
        "-filter_complex", filtro_vertical(credito),
        "-map", "[out]", "-map", "0:a?",
        "-r", "30", *args_video(),
        "-c:a", "aac", "-b:a", "128k", salida,
    ]
    subprocess.run(cmd, check=True)


# Recortes "cara/avatar" y "gameplay" por streamer, en formato  w:h:x:y  sobre
# el frame 1920x1080. Reajustar si el streamer mueve su camara o cambia de escena.
_LAYOUTS_CALIBRADOS = {
    "auronplay": {"face": "300:300:60:430", "game": "1060:1080:430:0"},
    "rubius":    {"face": "415:300:5:490",  "game": "1060:1080:520:0"},
}
# La app (app.py) edita layouts.json; si no existe, valen los calibrados.
LAYOUTS_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "layouts.json")
try:
    import json
    with open(LAYOUTS_JSON, encoding="utf-8") as _f:
        LAYOUTS = json.load(_f)
except (FileNotFoundError, ValueError):
    LAYOUTS = dict(_LAYOUTS_CALIBRADOS)


def guardar_layout(canal, layout):
    """Añade/actualiza el recorte de un streamer en layouts.json (escritura atómica)."""
    import json
    try:
        with open(LAYOUTS_JSON, encoding="utf-8-sig") as f:
            todos = json.load(f)
    except (FileNotFoundError, ValueError):
        todos = dict(LAYOUTS)
    todos[canal.lower()] = {"face": layout["face"], "game": layout["game"]}
    tmp = LAYOUTS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(todos, f, indent=2)
    os.replace(tmp, LAYOUTS_JSON)
    LAYOUTS[canal.lower()] = todos[canal.lower()]


def cadenas_split(lay):
    """Recorte + escalado de la cara (arriba, 1080x820) y del gameplay (abajo, 1080x1100).
    Lo usan el render y la vista previa de Ajustes: asi la previa es exacta."""
    top = (f"crop={lay['face']},scale=1080:820:force_original_aspect_ratio=increase,"
           "crop=1080:820,setsar=1")
    bot = (f"crop={lay['game']},scale=1080:1100:force_original_aspect_ratio=increase,"
           "crop=1080:1100,setsar=1")
    return top, bot


def ruta_filtro(ruta):
    """Ruta para usar dentro de un filtro de ffmpeg: con los clips en Vídeos/Hypazo la ruta es absoluta
    (C:/...) y los ':' sin escapar rompen el filtro. Entre comillas y con ':' escapados, como FONT."""
    return "'" + ruta.replace("\\", "/").replace(":", "\\:") + "'"


def convertir_split(entrada, salida, chatfile="", credito="", layout=None):
    """Formato split vertical: streamer arriba, gameplay abajo, banda de chat
    semi-transparente (pequena) encima del gameplay. Los recortes salen del
    LAYOUT del streamer; reajustar si mueve la camara o cambia de escena."""
    lay = layout or LAYOUTS["auronplay"]
    # El chat llega como archivo .ass (animado, transparente, a un lado).
    chat_f = f",ass={ruta_filtro(chatfile)}" if chatfile and os.path.exists(chatfile) else ""
    cap = (
        f",drawtext=fontfile={FONT}:text='{_esc_texto(credito)}':fontcolor=white"
        ":fontsize=40:box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y=h-96"
    ) if credito else ""
    top, bot = cadenas_split(lay)
    fc = (
        "[0:v]fps=30,split=2[v1][v2];"          # 30 fps antes de recortar: menos trabajo
        f"[v1]{top}[top];"
        f"[v2]{bot}[bot];"
        f"[top][bot]vstack=inputs=2,format=yuv420p{chat_f}{cap}[out]"
    )
    cmd = [
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-err_detect", "ignore_err",
        "-fflags", "+discardcorrupt", "-max_error_rate", "1.0", "-i", entrada,
        "-filter_complex", fc,
        "-map", "[out]", "-map", "0:a?",
        "-r", "30", *args_video(),
        "-c:a", "aac", "-b:a", "128k", salida,
    ]
    subprocess.run(cmd, check=True)


_ASS_CABECERA = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: chat,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H78000000,0,0,0,0,100,100,0,0,3,5,0,3,10,24,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_t(seg):
    seg = max(0.0, seg)
    h = int(seg // 3600)
    m = int((seg % 3600) // 60)
    s = seg % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _san(texto):
    return texto.replace("{", "(").replace("}", ")").replace("\\", "/").strip()[:26]


def escribir_ass(mensajes, path, gap=0.7, nlineas=4, maximo=80):
    """Chat REAL en un recuadro pequeno (abajo-derecha) que se actualiza como
    chat en vivo: muestra las ultimas 'nlineas' y va cambiando con el tiempo.
    mensajes = lista de (t_segundos, 'usuario: texto')."""
    limpios = []
    ult = -999.0
    for t, texto in sorted(mensajes, key=lambda m: m[0]):
        if t - ult < gap:          # no amontonar: salta mensajes muy seguidos
            continue
        texto = _san(texto)
        if not texto:
            continue
        ult = t
        limpios.append((t, texto))
        if len(limpios) >= maximo:
            break
    filas = []
    for i, (t, _tx) in enumerate(limpios):
        fin = limpios[i + 1][0] if i + 1 < len(limpios) else t + 4.0
        bloque = limpios[max(0, i - nlineas + 1): i + 1]
        texto = r"\N".join(x[1] for x in bloque)
        filas.append(f"Dialogue: 0,{_ass_t(t)},{_ass_t(fin)},chat,,0,0,0,,{texto}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_ASS_CABECERA + "\n".join(filas) + "\n")


def descargar(url, destino):
    subprocess.run(
        [sys.executable, "-m", "yt_dlp", "-f", "mp4/best",
         "-o", destino, url],
        check=True,
    )


def dimensiones(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", path],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def test():
    # Genera un clip 16:9 sintetico y verifica que la salida queda 1080x1920.
    tmp = tempfile.mkdtemp()
    entrada = os.path.join(tmp, "in.mp4")
    salida = os.path.join(tmp, "out.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", entrada],
        check=True,
    )
    convertir(entrada, salida, "@auronplay")
    dims = dimensiones(salida)
    assert dims == "1080x1920", f"Esperaba 1080x1920, obtuve {dims}"
    print(f"OK - auto-prueba pasada, salida {dims} con credito.")


def procesar(url, credito, indice):
    raw = os.path.join(SALIDA, f"_raw_{indice}.mp4")
    final = os.path.join(SALIDA, f"clip_{indice:02d}_tiktok.mp4")
    print(f"[{indice}] Descargando {url} ...")
    descargar(url, raw)
    print(f"[{indice}] Convirtiendo a vertical...")
    convertir(raw, final, credito)
    os.remove(raw)
    print(f"[{indice}] Listo: {os.path.abspath(final)}")


def main():
    p = argparse.ArgumentParser(description="Clips de Twitch/YouTube -> vertical TikTok, gratis.")
    p.add_argument("url", nargs="*", help="Una o varias URLs de clips")
    p.add_argument("--credito", default="", help="Texto de credito, ej: @auronplay")
    p.add_argument("--lote", help="Archivo .txt con una URL por linea")
    p.add_argument("--test", action="store_true", help="Auto-prueba sin descargar")
    a = p.parse_args()

    if a.test:
        test()
        return

    urls = list(a.url)
    if a.lote:
        with open(a.lote, encoding="utf-8") as f:
            urls += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    if not urls:
        p.error("Pasa una o varias URLs, o --lote archivo.txt (o usa --test).")

    os.makedirs(SALIDA, exist_ok=True)
    fallos = []
    for i, url in enumerate(urls, 1):
        try:
            procesar(url, a.credito, i)
        except Exception as e:  # una URL mala no tumba el lote
            print(f"[{i}] ERROR con {url}: {e}")
            fallos.append(url)

    ok = len(urls) - len(fallos)
    print(f"\nHechos {ok}/{len(urls)} en '{SALIDA}'." + (f" Fallaron: {fallos}" if fallos else ""))


if __name__ == "__main__":
    main()
