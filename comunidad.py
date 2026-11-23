"""comunidad.py - Los clips que crea la gente en Twitch: en qué segundo del VOD están y cuántas vistas tienen.

Los espectadores ya marcan los mejores momentos creando clips. Sin cuenta, Twitch da los 100 clips más vistos
del canal por periodo (día, semana, mes), cada uno con su VOD y su segundo: con eso, en el análisis de un VOD,
los momentos que la gente más ha clipeado suben en la lista.
"""
import json
import math
import urllib.request

GQL = "https://gql.twitch.tv/gql"
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"     # el del reproductor web (público)
PERIODOS = ("LAST_DAY", "LAST_WEEK", "LAST_MONTH")
Q_CLIPS = ("query($l:String!,$p:ClipsPeriod){user(login:$l){clips(first:100, criteria:{period:$p}){edges{node{"
           "slug viewCount videoOffsetSeconds durationSeconds video{id}}}}}}")
MARGEN_FIN = 5      # la gente pulsa «clip» justo después: el momento está unos segundos antes del final
BONO_MAX = 35       # puntos de score como mucho por clips de la comunidad


def gql(query, variables, timeout=20):
    req = urllib.request.Request(GQL, json.dumps({"query": query, "variables": variables}).encode(),
                                 {"Client-ID": CLIENT_ID, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        d = json.load(r)
    if d.get("errors"):
        raise RuntimeError(d["errors"][0].get("message", "error de Twitch"))
    return d.get("data") or {}


def clips_del_vod(canal, video_id, pedir=gql):
    """[(segundo_del_momento, vistas)] de los clips de ese VOD, de más a menos vistas.
    shortcut: sin cuenta solo llegan los 100 más vistos por periodo; con la API oficial (con cuenta) saldrían todos."""
    vistos = {}
    for periodo in PERIODOS:
        try:
            datos = pedir(Q_CLIPS, {"l": canal, "p": periodo})
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):   # sin red o Twitch cambió algo: solo chat
            continue
        for e in ((((datos or {}).get("user") or {}).get("clips") or {}).get("edges") or []):
            n = e.get("node") or {}
            if (n.get("video") or {}).get("id") != str(video_id) or n.get("videoOffsetSeconds") is None:
                continue
            momento = max(0, n["videoOffsetSeconds"] + (n.get("durationSeconds") or 30) - MARGEN_FIN)
            vistos[n["slug"]] = (momento, n.get("viewCount") or 0)
    return sorted(vistos.values(), key=lambda x: -x[1])


def bono(vistas):
    """Puntos extra de score: 0 sin vistas, ~10 con 10, ~29 con 750, como mucho BONO_MAX."""
    return min(BONO_MAX, round(10 * math.log10(1 + vistas)))


def repartir(picos, clips, separacion, max_nuevos):
    """{segundo: vistas}. Un clip cerca (< separacion) de un pico del chat suma sus vistas a ese pico; si no,
    abre un candidato nuevo (como mucho max_nuevos, los más vistos primero) o se suma a uno ya abierto."""
    extra, nuevos = {}, 0
    for s, v in sorted(clips, key=lambda x: -x[1]):
        destino = next((p for p in [*picos, *extra] if abs(p - s) < separacion), None)
        if destino is None:
            if nuevos >= max_nuevos:
                continue
            destino, nuevos = s, nuevos + 1
        extra[destino] = extra.get(destino, 0) + v
    return extra
