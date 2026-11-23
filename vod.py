"""
vod.py - Saca los mejores momentos de un directo YA HECHO (VOD de Twitch).

1. Descarga la repetición del chat (cada mensaje con su segundo exacto).
2. Puntúa todo el directo con el mismo score del cazador en vivo (chat sobre lo normal +
   gente distinta) y elige los N mejores picos, separados entre sí.
3. Mide el audio solo alrededor de los candidatos (gritos/risas) y reordena.
4. Corta solo esos trozos del VOD (sin bajar el directo entero) y los renderiza
   (normal o split con chat), en salida/<fecha>_<canal>/vod_NN.mp4 + .json.

Uso: python vod.py https://www.twitch.tv/videos/123 --n 10 [--split] [--credito @x]
"""
import argparse
import sin_consola
sin_consola.activar()   # ffmpeg/yt-dlp sin ventanas de terminal
import collections
import concurrent.futures as cf
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

import audio
import comunidad
from autoclip import BASE_SEG, COOLDOWN, VENTANA, es_ruido, peso, puntuacion, resumen_chat

from comunidad import CLIENT_ID, GQL
HASH_COMENTARIOS = "b70a3591ff0f4e0313d126c6a1502d79a1c02baebb288227c582044aa76adf6a"
RE_VOD = re.compile(r"^https?://(?:www\.|m\.)?twitch\.tv/videos/(\d+)")
HILOS = 8
CANDIDATOS_POR_CLIP = 3     # se mide el audio de 3x candidatos y se quedan los N mejores


def _gql_comentarios(video_id, offset, intentos=3):
    body = json.dumps([{"operationName": "VideoCommentsByOffsetOrCursor",
                        "variables": {"videoID": video_id, "contentOffsetSeconds": int(offset)},
                        "extensions": {"persistedQuery": {"version": 1,
                                                          "sha256Hash": HASH_COMENTARIOS}}}]).encode()
    req = urllib.request.Request(GQL, body, {"Client-ID": CLIENT_ID,
                                             "Content-Type": "application/json"})
    for i in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                video = json.load(r)[0]["data"]["video"]
            return (video or {}).get("comments") or {"edges": []}
        except (OSError, ValueError, KeyError, TypeError):
            if i == intentos - 1:
                raise
            time.sleep(1 + i)


def _tramo_chat(video_id, ini, fin):
    """Recorre [ini, fin) saltando por segundo (Twitch no deja paginar con cursor sin
    sesión): cada petición trae ~50 mensajes desde ese segundo."""
    vistos, msgs, t = set(), [], ini
    while t < fin:
        edges = _gql_comentarios(video_id, t)["edges"]
        nuevos = 0
        for e in edges:
            n = e["node"]
            if n["id"] in vistos or not (ini <= n["contentOffsetSeconds"] < fin):
                continue
            vistos.add(n["id"])
            nuevos += 1
            texto = "".join(f.get("text") or "" for f in n["message"]["fragments"])
            usuario = (n.get("commenter") or {}).get("login") or "?"
            msgs.append((n["contentOffsetSeconds"], usuario, texto))
        ultimo = max((e["node"]["contentOffsetSeconds"] for e in edges), default=t)
        # Si la página no avanzó (chat saturado en 1 s o vacío) se salta 1 s.
        t = ultimo if nuevos and ultimo > t else t + (1 if edges else 10)
    return msgs


def descargar_chat(video_id, duracion, hilos=HILOS):
    trozo = max(60, duracion // (hilos * 4) + 1)
    tramos = [(i, min(i + trozo, duracion + 1)) for i in range(0, duracion + 1, trozo)]
    msgs, hechos = [], 0
    with cf.ThreadPoolExecutor(hilos) as ex:
        for parte in ex.map(lambda tr: _tramo_chat(video_id, *tr), tramos):
            msgs += parte
            hechos += 1
            print(f"   chat: {hechos}/{len(tramos)} tramos, {len(msgs)} mensajes", flush=True)
    return sorted(msgs)


def linea_de_tiempo(msgs, duracion, factor, unicos_min):
    """Por cada segundo: (puntaje de la ventana de 3 s, personas, base, score sin audio)."""
    por_seg = collections.defaultdict(list)
    for t, u, txt in msgs:
        cuerpo = txt.lower().encode()
        if not es_ruido(u.encode(), cuerpo):
            por_seg[int(t)].append((peso(cuerpo), u))
    v = int(VENTANA)
    puntajes, gente = [], []
    for s in range(duracion + 1):
        ventana = [x for k in range(s - v + 1, s + 1) for x in por_seg.get(k, ())]
        puntajes.append(sum(p for p, _ in ventana))
        gente.append(len({u for _, u in ventana}))
    linea = []
    for s in range(duracion + 1):
        previas = puntajes[max(0, s - BASE_SEG):s]
        base = max(1.0, statistics.median(previas)) if len(previas) >= 30 else max(1.0, puntajes[s])
        linea.append((puntajes[s], gente[s], base,
                      puntuacion(puntajes[s], base, gente[s], 0, factor, unicos_min, 0)))
    return linea


def mejores_picos(linea, n, separacion=COOLDOWN):
    """Los n segundos con mejor score (desempate: veces sobre lo normal), a 'separacion' s
    entre sí para no sacar dos clips del mismo momento."""
    orden = sorted(range(len(linea)), reverse=True,
                   key=lambda s: (linea[s][3], linea[s][0] / linea[s][2]))
    elegidos = []
    for s in orden:
        if len(elegidos) >= n or linea[s][3] <= 0:
            break
        if all(abs(s - e) >= separacion for e in elegidos):
            elegidos.append(s)
    return elegidos


def elegir(picos, linea, gritos, vistas, n, factor, unicos, audio_min):
    """Los n mejores picos: score del chat y del audio + bono por los clips que creó la gente.
    Devuelve (elegidos, score)."""
    def score(s):
        pt, gen, base, _ = linea[s]
        return min(99, puntuacion(pt, base, gen, gritos.get(s, 0.0), factor, unicos, audio_min)
                   + comunidad.bono(vistas.get(s, 0)))
    return sorted(picos, key=lambda s: (score(s), linea[s][0] / linea[s][2]), reverse=True)[:n], score


def _url_formato(vod_url, formato):
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-g", "-f", formato, vod_url],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(f"yt-dlp no pudo leer el VOD: {r.stderr.strip()[-300:]}")
    return r.stdout.strip().splitlines()[0]


def grito_en(audio_url, ini, fin, remate):
    """dB sobre lo normal del segundo más fuerte de [ini, fin] (baja solo ese audio)."""
    previo = 15     # algo de audio antes del clip para aprender el volumen normal
    desde = max(0, ini - previo)
    r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", str(desde),
                        "-i", audio_url, "-t", str(fin - desde), "-vn", "-ac", "1",
                        "-ar", str(audio.TASA), "-f", "s16le", "pipe:1"],
                       capture_output=True, timeout=180)
    vol = audio.Volumen()
    pcm = r.stdout
    for i in range(0, len(pcm) - audio.BYTES + 1, audio.BYTES):
        vol.agregar(desde + i / audio.BYTES * audio.TRAMO, audio.db(pcm[i:i + audio.BYTES]))
    return vol.pico(fin - ini, ahora=fin)


def _ventana_clip(pico, segundos, remate):
    fin = pico + remate
    return max(0, fin - segundos), fin


def renderizar(video_url, ini, fin, destino, credito, split, layout, chat):
    from clipeo import convertir, convertir_split, escribir_ass
    from envivo import tiene_video
    with tempfile.TemporaryDirectory() as tmp:
        ts = os.path.join(tmp, "trozo.ts")
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-ss", str(ini),
                        "-i", video_url, "-t", str(fin - ini), "-c", "copy", ts],
                       check=True, timeout=600)
        out = os.path.join(tmp, "render.mp4")
        if split and layout:
            # Ruta relativa (como el cazador): el filtro ass de ffmpeg se atraganta con "C:".
            assf = os.path.join(os.path.dirname(destino), "_vod_chat.ass")
            escribir_ass([(t - ini, f"{u}: {x}"[:46]) for t, u, x in chat], assf)
            try:
                convertir_split(ts, out, assf, credito, layout)
            finally:
                os.remove(assf)
        else:
            convertir(ts, out, credito)
        if not tiene_video(out):
            raise RuntimeError("el render salió sin vídeo")
        os.replace(out, destino)


def _siguiente(carpeta):
    nums = [int(m.group(1)) for f in os.listdir(carpeta) if (m := re.match(r"vod_(\d+)\.mp4$", f))]
    return max(nums, default=0) + 1


def _info(vod_url):
    r = subprocess.run([sys.executable, "-m", "yt_dlp", "-J", "--skip-download", vod_url],
                       capture_output=True, timeout=120, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError("No pude abrir ese VOD (¿borrado o solo para suscriptores?): "
                           + r.stderr.strip()[-300:])
    return json.loads(r.stdout)


def main():
    p = argparse.ArgumentParser(description="Mejores momentos de un directo ya hecho (VOD).")
    p.add_argument("url")
    p.add_argument("--n", type=int, default=10, help="Cuántos clips sacar")
    p.add_argument("--credito", default="")
    p.add_argument("--segundos", type=int, default=45)
    p.add_argument("--remate", type=float, default=7.0, help="Segundos tras el pico")
    p.add_argument("--factor", type=float, default=1.8)
    p.add_argument("--unicos", type=int, default=10)
    p.add_argument("--audio", type=float, default=12.0, help="0 = no medir gritos")
    p.add_argument("--split", action="store_true")
    a = p.parse_args()

    m = RE_VOD.match(a.url)
    if not m:
        sys.exit("De momento solo VODs de Twitch: https://www.twitch.tv/videos/NUMERO")
    video_id = m.group(1)
    info = _info(a.url)
    canal = (info.get("uploader_id") or "twitch").lower()
    duracion = int(info.get("duration") or 0)
    titulo = re.sub(r"\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", "", info.get("title") or "")
    fecha = time.strftime("%Y-%m-%d", time.localtime(info.get("timestamp") or time.time()))
    print(f"VOD de {canal}: «{titulo}» ({duracion // 3600}h{duracion % 3600 // 60:02d}m)")

    print("1/4 Descargando la repetición del chat...")
    msgs = descargar_chat(video_id, duracion)
    if len(msgs) < 50:
        sys.exit("Este VOD casi no tiene chat guardado: no puedo saber cuáles son los mejores momentos.")

    print(f"2/4 Puntuando el directo entero ({len(msgs)} mensajes)...")
    linea = linea_de_tiempo(msgs, duracion, a.factor, a.unicos)
    n_cand = a.n * (CANDIDATOS_POR_CLIP if a.audio > 0 else 1)
    picos = mejores_picos(linea, n_cand)
    clips_com = comunidad.clips_del_vod(canal, video_id)
    vistas = collections.Counter()
    for s, v in comunidad.repartir(picos, clips_com, COOLDOWN, max_nuevos=a.n).items():
        vistas[min(s, duracion)] += v
    if clips_com:
        print(f"   La gente creó {len(clips_com)} clips de este VOD (de los más vistos): cuentan para elegir.")
    picos = sorted(set(picos) | set(vistas))
    if not picos:
        sys.exit("No encontré ningún pico de chat en este VOD.")

    gritos = {s: 0.0 for s in picos}
    if a.audio > 0:
        print(f"3/4 Midiendo gritos y risas en {len(picos)} candidatos...")
        audio_url = _url_formato(a.url, "Audio_Only/bestaudio/worst")
        def medir(s):
            ini, fin = _ventana_clip(s, a.segundos, a.remate)
            try:
                return s, grito_en(audio_url, ini, fin, a.remate)
            except (subprocess.SubprocessError, OSError):
                return s, 0.0
        with cf.ThreadPoolExecutor(4) as ex:
            gritos.update(ex.map(medir, picos))
    else:
        print("3/4 Audio desactivado: solo chat.")

    elegidos, score = elegir(picos, linea, gritos, vistas, a.n, a.factor, a.unicos, a.audio)

    from clipeo import LAYOUTS
    layout = LAYOUTS.get(canal) if a.split else None
    if a.split and not layout:
        print(f"   Sin recorte split para {canal}: los clips salen en formato normal "
              "(calíbralo en Ajustes con Auto y vuelve a lanzarlo).")
    from clipeo import SALIDA
    carpeta = os.path.join(SALIDA, f"{fecha}_{canal}")
    os.makedirs(carpeta, exist_ok=True)
    print(f"4/4 Cortando {len(elegidos)} clips del VOD en {carpeta}...")
    video_url = _url_formato(a.url, "best[height<=1080]/best")
    indice = _siguiente(carpeta)
    for puesto, s in enumerate(sorted(elegidos), 1):
        ini, fin = _ventana_clip(s, a.segundos, a.remate)
        chat = [x for x in msgs if ini <= x[0] <= fin]
        destino = os.path.join(carpeta, f"vod_{indice:02d}.mp4")
        minuto = f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
        print(f"   [{puesto}/{len(elegidos)}] momento {minuto}, score {score(s)}, "
              f"grito +{gritos[s]:.0f} dB"
              + (f", {vistas[s]} vistas en clips de la gente" if vistas.get(s) else "") + " ...", flush=True)
        try:
            renderizar(video_url, ini, fin, destino, a.credito, a.split, layout, chat)
        except (subprocess.SubprocessError, OSError, RuntimeError) as e:
            print(f"   (ese clip falló, lo salto: {e})")
            continue
        pt, gen, base, _ = linea[s]
        meta = {"puntaje": pt, "personas": gen, "normal": round(base), "hora": minuto,
                "top_chat": resumen_chat([f"{u}: {x}" for _, u, x in chat]),
                "motivo": "vod", "grito_db": round(gritos[s], 1), "directo": titulo,
                "canal": canal, "plataforma": "twitch", "score": score(s),
                "vod": a.url, "momento": s, "comunidad_vistas": vistas.get(s, 0), "remate": a.remate}
        with open(destino[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        print(f"   CLIP GUARDADO: {os.path.abspath(destino)}", flush=True)
        indice += 1
    print("Listo. Los clips están en la galería.")


if __name__ == "__main__":
    main()
