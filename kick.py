"""
kick.py - Chat publico de Kick, lectura anonima (sin cuenta, solo leer).

Consulta cada ~1s la API publica de mensajes recientes del canal (la misma que
usa kick.com al abrir un directo) y devuelve solo los mensajes nuevos.
"""
import json
import re
import time
import urllib.request

INTERVALO = 1.0   # segundos entre consultas con el chat tranquilo
INTERVALO_RAPIDO = 0.4   # si la ultima respuesta vino casi llena (la API da 25 como mucho)
CASI_LLENA = 18
RE_EMOTE = re.compile(r"\[emote:\d+:([^\]]*)\]")   # [emote:123:KEKW] -> KEKW


def _get(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json",
        "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def info_canal(canal):
    return _get(f"https://kick.com/api/v2/channels/{canal}")


class Chat:
    """Misma idea que el socket IRC de Twitch: leer() -> mensajes nuevos."""

    def __init__(self, canal):
        self.cid = info_canal(canal)["id"]
        self.vistos = set()
        self.ultima = 0.0
        self.fallos = 0
        self.intervalo = INTERVALO
        self.leer()          # lo que ya estaba en pantalla no cuenta como reaccion
        self.ultima = 0.0

    def leer(self):
        """[(usuario_bytes, texto_bytes_minusculas)] de lo llegado desde la ultima vez.
        shortcut: la API da los ultimos 25; si llega casi llena consulta cada 0.4s
        (hasta ~60 msg/s). Pasar al websocket oficial si aun se queda corto."""
        espera = self.ultima + self.intervalo - time.time()
        if espera > 0:
            time.sleep(min(espera, 0.2))   # no girar en vacio
            return []
        self.ultima = time.time()
        try:
            datos = _get(f"https://kick.com/api/v2/channels/{self.cid}/messages"
                         f"?t={int(self.ultima * 1000)}")   # ?t= evita la cache
            msgs = datos.get("data", {}).get("messages", [])
            self.fallos = 0
        except (OSError, ValueError) as e:
            self.fallos += 1
            if self.fallos in (1, 10, 100):   # avisa sin inundar el registro
                print(f"   (chat de Kick no responde: {e})")
            return []
        nuevos = []
        for m in sorted(msgs, key=lambda m: m.get("created_at", "")):
            mid = m.get("id")
            if mid in self.vistos:
                continue
            self.vistos.add(mid)
            try:
                texto = RE_EMOTE.sub(r"\1", m["content"])
                nuevos.append((m["sender"]["username"].encode(), texto.lower().encode()))
            except (KeyError, TypeError, AttributeError):
                continue
        if len(self.vistos) > 5000:          # memoria acotada en lives largos
            self.vistos = {m.get("id") for m in msgs}
        self.intervalo = INTERVALO_RAPIDO if len(nuevos) >= CASI_LLENA else INTERVALO
        return nuevos

    def close(self):
        pass
