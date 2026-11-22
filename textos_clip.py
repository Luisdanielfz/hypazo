"""Títulos, hashtags y textos listos para TikTok, YouTube Shorts e Instagram Reels.

Con IA (ia.py) si hay algún proveedor configurado; si no, o si falla, unos textos básicos.
A la IA solo se le manda texto: canal, título del directo, chat y lo que se dice en el clip.
"""
import json
import re
import unicodedata

import ia
from credito import credito_final

MAX_TITULO = 90
REDES_TAGS = {"twitch": "#twitchclips", "kick": "#kickclips"}

PROMPT = ("Eres editor de clips virales en español para TikTok, YouTube Shorts y Reels. "
          "Con los datos del clip, propone 3 títulos gancho distintos (máx. 60 caracteres, sin comillas, "
          "sin inventar hechos que no estén en los datos) y 6 hashtags relevantes. "
          'Responde SOLO con JSON: {"titulos": ["...", "...", "..."], "hashtags": ["#...", ...]}')


def _tag(texto: str) -> str:
    t = unicodedata.normalize("NFD", str(texto)).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9ñ]", "", t)
    return "#" + t if len(t) > 1 else ""


def _unicos(tags) -> list:
    out = []
    for t in tags:
        h = _tag(t)
        if h and h not in out:
            out.append(h)
    return out


def _canal(meta):
    return meta.get("canal") or "", meta.get("plataforma") or "twitch"


def redes(titulos: list, hashtags: list, meta: dict) -> dict:
    """Las plantillas por red, siempre con el crédito al canal."""
    canal, plat = _canal(meta)
    credito = "🎥 " + credito_final("", canal, plat) if canal else ""
    t = titulos[0] if titulos else ""
    tags = hashtags or []
    shorts = (t[:100 - len(" #shorts")].rstrip() + " #shorts").strip()
    return {
        "tiktok": "\n".join(x for x in (t, credito, " ".join(tags[:6] + ["#fyp"])) if x),
        "shorts": {"titulo": shorts, "descripcion": "\n".join(x for x in (credito, " ".join(tags[:3])) if x)},
        "reels": "\n".join(x for x in (t, credito, " ".join(tags[:5])) if x),
    }


def basico(meta: dict) -> dict:
    canal, plat = _canal(meta)
    nombre = canal.upper() or "EL STREAMER"
    chat = [t for t, _n in (meta.get("top_chat") or [])][:1]
    titulos = [f"{nombre} NO SE LO ESPERABA", f"EL MOMENTO MÁS LOCO DE {nombre}",
               f"EL CHAT EXPLOTÓ: {chat[0].upper()}"[:MAX_TITULO] if chat else f"{nombre} EN DIRECTO"]
    tags = _unicos([canal, "clips", REDES_TAGS.get(plat, "#twitchclips"), "parati"])
    return {"fuente": "basico", "titulos": titulos, "hashtags": tags, "redes": redes(titulos, tags, meta)}


def contexto(meta: dict, transcripcion: str = "") -> str:
    canal, plat = _canal(meta)
    chat = ", ".join(f"{t} (x{n})" for t, n in (meta.get("top_chat") or [])[:8])
    partes = [f"Canal: {canal} ({plat})", f"Título del directo: {meta.get('directo') or 'desconocido'}",
              f"Por qué se cazó: {meta.get('motivo') or 'desconocido'}", f"Lo más repetido en el chat: {chat or 'nada'}"]
    if transcripcion:
        partes.append("Lo que se dice en el clip: " + transcripcion[:1500])
    return "\n".join(partes)


def _json(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        raise ValueError("sin JSON")
    return json.loads(m.group(0))


def generar(meta: dict, cfg_ia: dict, transcripcion: str = "") -> dict:
    try:
        r = ia.chat(cfg_ia, [{"role": "system", "content": PROMPT},
                             {"role": "user", "content": contexto(meta, transcripcion)}], json_modo=True)
        datos = _json(r["texto"])
        titulos = [" ".join(str(t).split())[:MAX_TITULO] for t in datos.get("titulos", []) if str(t).strip()][:3]
        tags = _unicos(datos.get("hashtags", []))[:8]
        if not titulos:
            raise ValueError("sin títulos")
        base = basico(meta)
        tags = tags or base["hashtags"]
        return {"fuente": "ia", "proveedor": r["proveedor"], "modelo": r["modelo"], "titulos": titulos,
                "hashtags": tags, "redes": redes(titulos, tags, meta)}
    except ia.ErrorIA as e:
        return {**basico(meta), "aviso": str(e)}
    except (ValueError, TypeError, AttributeError):
        return {**basico(meta), "aviso": "La IA no devolvió un formato válido; textos básicos."}
