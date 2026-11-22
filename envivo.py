"""
envivo.py - Caza clips del LIVE en tiempo real con buffer rodante.

Graba la senal PUBLICA del directo en segmentos. Cuando veas algo caliente,
pulsas ENTER y te guarda los ultimos ~45s ya en vertical con credito.
Escribe 'q' + ENTER para salir.

Uso:
    python envivo.py auronplay --credito "@auronplay"
    python envivo.py auronplay --segundos 45 --credito "@auronplay"

Solo usa la senal publica (como verla en el navegador). Da siempre el credito
al streamer al subir, y baja cualquier clip si su equipo lo pide.
"""
import argparse
import glob
import os
import re
import subprocess
import sys
import time

from clipeo import convertir, SALIDA

BUF = "buffer"
SEG = 5           # duracion de cada segmento (s)
WRAP = 24         # nº de segmentos en el buffer rodante (24*5 = 120s)


def resolver_url(canal, plataforma="twitch"):
    web = f"https://kick.com/{canal}" if plataforma == "kick" else f"https://www.twitch.tv/{canal}"
    r = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "-g", web],
        capture_output=True, text=True,
    )
    url = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    if not url.startswith("http"):
        raise RuntimeError(f"No esta en vivo o no se pudo resolver: {r.stderr.strip()[:200]}")
    return url


def titulo_directo(canal, plataforma="twitch"):
    """Titulo del directo (de ahi sale el juego para los hashtags). En Twitch yt-dlp lo da
    en 'description' ('title' es "Canal (live) fecha"); en Kick viene en 'title' + fecha."""
    web = f"https://kick.com/{canal}" if plataforma == "kick" else f"https://www.twitch.tv/{canal}"
    campo = "%(title)s" if plataforma == "kick" else "%(description)s"
    try:
        r = subprocess.run([sys.executable, "-m", "yt_dlp", "--print", campo, web],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=40)
    except subprocess.TimeoutExpired:
        return ""
    linea = r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""
    linea = re.sub(r"\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", "", linea)   # fecha que añade yt-dlp
    return "" if linea in ("NA", "None") else linea[:200]


def inicio_directo(canal, plataforma="twitch", ejecutar=subprocess.run):
    """Hora de inicio del directo (epoch) según la plataforma, o None si no se sabe.
    Nunca se inventa: sin dato, los tiempos del piloto quedan como 'desconocido'."""
    web = f"https://kick.com/{canal}" if plataforma == "kick" else f"https://www.twitch.tv/{canal}"
    try:
        r = ejecutar([sys.executable, "-m", "yt_dlp", "--print", "%(timestamp)s", web],
                     capture_output=True, text=True, encoding="utf-8", errors="replace",
                     timeout=40)
    except (subprocess.TimeoutExpired, OSError):
        return None
    linea = (r.stdout or "").strip().splitlines()
    try:
        return float(linea[0]) if linea else None
    except ValueError:
        return None


def iniciar_captura(url, audio=False):
    """audio=True: el mismo ffmpeg saca tambien el audio (PCM mono 8 kHz) por stdout,
    para medir volumen sin descargar el directo dos veces. Hay que leer proc.stdout."""
    os.makedirs(BUF, exist_ok=True)
    for f in glob.glob(os.path.join(BUF, "seg*.ts")):
        os.remove(f)
    cmd = [
        # -nostdin: el stdin del cazador es el canal del "clip ya"; si ffmpeg lo lee,
        # la 'c' de "clip" le abre su prompt de comandos y se cuelga.
        "ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", url,
        "-c", "copy", "-f", "segment", "-segment_time", str(SEG),
        "-segment_wrap", str(WRAP), "-reset_timestamps", "1",
        os.path.join(BUF, "seg%03d.ts"),
    ]
    if audio:
        cmd += ["-map", "0:a:0", "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1"]
        return subprocess.Popen(cmd, stdout=subprocess.PIPE)
    return subprocess.Popen(cmd)


def _concatenar(segundos):
    """Une los segmentos mas recientes del buffer y devuelve el .ts, o None."""
    segs = sorted(glob.glob(os.path.join(BUF, "seg*.ts")), key=os.path.getmtime)
    if len(segs) < 2:
        print("   Aun no hay suficiente buffer, espera unos segundos.")
        return None
    n = max(1, round(segundos / SEG))
    elegidos = segs[:-1][-n:]  # descarta el ultimo (en escritura)
    # Dentro del BUF de cada canal: dos cazadores a la vez no se pisan los temporales.
    lista = os.path.join(BUF, "concat.txt")
    with open(lista, "w", encoding="utf-8") as f:
        for s in elegidos:
            f.write(f"file '{os.path.abspath(s)}'\n")
    unido = os.path.join(BUF, "unido.ts")
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "concat",
                    "-safe", "0", "-i", lista, "-c", "copy", unido], check=True)
    return unido


def recortar(credito, segundos, indice, carpeta=SALIDA):
    unido = _concatenar(segundos)
    if not unido:
        return
    _render(lambda tmp: convertir(unido, tmp, credito), carpeta, indice)


def tiene_video(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_type", "-of", "csv=p=0", path], capture_output=True, text=True)
    return "video" in r.stdout


def es_anuncio_clip(path):
    """¿El clip es la pantalla de anuncio? Mira un frame del centro del clip."""
    import cv2
    from calibrar import es_anuncio
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        medio = float(r.stdout.strip()) / 2
    except ValueError:
        return False
    png = path + ".medio.png"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", f"{medio:.2f}",
                    "-i", path, "-frames:v", "1", png], capture_output=True)
    img = cv2.imread(png)
    if os.path.exists(png):
        os.remove(png)
    return img is not None and es_anuncio(img)


def _render(hacer, carpeta, indice):
    """Renderiza en el buffer y mueve a salida/ solo al terminar: la galeria nunca
    ve un mp4 a medias, y parar el cazador a mitad no deja un clip corrupto."""
    os.makedirs(carpeta, exist_ok=True)
    final = os.path.join(carpeta, f"envivo_{indice:02d}.mp4")
    tmp = os.path.join(BUF, "render.mp4")
    hacer(tmp)
    # El render tolera errores (un frame malo no debe tirar el clip), pero si el directo
    # trae el video roto entero (corte, anuncio) sale un mp4 SOLO con audio: no guardarlo.
    if not tiene_video(tmp):
        os.remove(tmp)
        raise RuntimeError("el render salio sin video (directo corrupto o anuncio); no lo guardo")
    # Sin cuenta, Twitch tapa el directo con "Commercial break in progress" en las pausas
    # de anuncios: un clip de esa pantalla no sirve.
    if es_anuncio_clip(tmp):
        os.remove(tmp)
        raise RuntimeError("el clip cayo en una pausa de anuncios de Twitch; no lo guardo")
    os.replace(tmp, final)
    print(f"   CLIP GUARDADO: {os.path.abspath(final)}")


def recortar_split(credito, segundos, indice, chatfile="", layout=None, carpeta=SALIDA):
    from clipeo import convertir_split
    unido = _concatenar(segundos)
    if not unido:
        return
    _render(lambda tmp: convertir_split(unido, tmp, chatfile, credito, layout), carpeta, indice)


def main():
    p = argparse.ArgumentParser(description="Caza clips del live en tiempo real.")
    p.add_argument("canal", help="Nombre del canal de Twitch, ej: auronplay")
    p.add_argument("--credito", default="", help="Credito en pantalla, ej: @auronplay")
    p.add_argument("--segundos", type=int, default=45, help="Duracion hacia atras del clip")
    a = p.parse_args()

    print(f"Resolviendo el live de {a.canal}...")
    url = resolver_url(a.canal)
    print("Grabando el directo. Llenando buffer...")
    proc = iniciar_captura(url)
    time.sleep(SEG * 2 + 2)  # deja que se forme algo de buffer

    indice = 1
    try:
        while True:
            cmd = input("\n>> ENTER = guardar clip caliente | q + ENTER = salir: ").strip().lower()
            if cmd == "q":
                break
            if proc.poll() is not None:
                print("La captura se detuvo (el live pudo terminar). Saliendo.")
                break
            print("Cortando los ultimos segundos...")
            recortar(a.credito, a.segundos, indice)
            indice += 1
    finally:
        proc.terminate()
        print("Grabacion detenida.")


if __name__ == "__main__":
    main()
