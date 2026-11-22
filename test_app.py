"""Autoprueba de la logica nueva. Uso:  python test_app.py"""
import os
import tempfile

from fastapi import HTTPException

from autoclip import resumen_chat, siguiente_indice
from app import ruta_clip

# Resumen del chat: los mas repetidos primero, ignora vacios.
top = resumen_chat(["a: KEKW", "b: KEKW", "c: hola", "d: KEKW", "e: "])
assert top[0] == ("KEKW", 3) and ("hola", 1) in top, top

# Re-arrancar el mismo dia sigue la numeracion (no pisa envivo_01).
d = tempfile.mkdtemp()
assert siguiente_indice(d) == 1
for f in ("envivo_01.mp4", "envivo_07.mp4", "envivo_03_corte.mp4", "chat_09.ass"):
    open(os.path.join(d, f), "w").close()
assert siguiente_indice(d) == 8, siguiente_indice(d)

# Rutas de clip: nada fuera de salida/, ni papelera, ni no-mp4.
for carpeta, nombre in [("..", "x.mp4"), ("a/../..", "x.mp4"), ("_papelera", "x.mp4"),
                        ("ok", "..\\..\\app.py"), ("ok", "app.py"), ("", "x.mp4")]:
    try:
        ruta_clip(carpeta, nombre)
        raise AssertionError(f"debio rechazar {carpeta}/{nombre}")
    except HTTPException as e:
        assert e.status_code in (400, 404), e.status_code

# Chat de Kick (sin red): el historial al conectar no cuenta y no repite mensajes.
import kick

respuestas = [
    {"id": 1},                                                     # info_canal
    {"data": {"messages": [{"id": "a", "sender": {"username": "x"}, "content": "Hola"}]}},
    {"data": {"messages": [{"id": "a", "sender": {"username": "x"}, "content": "Hola"},
                           {"id": "b", "sender": {"username": "y"},
                            "content": "[emote:39286:KEKW] jaja"}]}},
]
kick._get = lambda url: respuestas.pop(0)
kick.INTERVALO = 0
chat = kick.Chat("prueba")
assert chat.leer() == [(b"y", b"kekw jaja")], "solo el nuevo, emote limpio, minusculas"
assert chat.intervalo == kick.INTERVALO, "chat tranquilo: consulta normal"
kick._get = lambda url: {"data": {"messages": [
    {"id": f"m{i}", "sender": {"username": f"u{i}"}, "content": "x"} for i in range(25)]}}
chat.ultima = 0
assert len(chat.leer()) == 25 and chat.intervalo == kick.INTERVALO_RAPIDO, "lleno: acelera"

# Produccion: grupos cortos, corte por pausa, palabra activa en amarillo, texto seguro.
import produccion

g = produccion.agrupar([(0, .2, "a"), (.3, .5, "b"), (.6, .8, "c"), (.9, 1, "d"),
                        (3, 3.2, "e")])
assert [len(x) for x in g] == [3, 1, 1], g          # max 3, y la pausa de 2s corta
assert produccion.limpiar("hola {\\pos(1,1)}  x") == "hola (/pos(1,1)) x"
ass = os.path.join(d, "t.ass")
produccion.escribir_ass([(0, .4, "hola"), (.5, .9, "mundo")], "Titulo", 5.0, ass, marca={})
txt = open(ass, encoding="utf-8").read()
assert "titulo,,0,0,0,,TITULO" in txt and "{\\c&H0000FFFF&}HOLA" in txt, txt
assert ",marca," not in txt.split("[Events]")[1], "sin marca configurada no hay marca de agua"
# Enfasis + marca + estilo minimal (sin mayusculas ni resaltado), y sin emojis.
produccion.escribir_ass([(0, .4, "dios"), (.5, .9, "jajaja")], "", 5.0, ass, "minimal",
                        {"handle": "@cuenta", "outro": "Sigueme"})
txt = open(ass, encoding="utf-8").read()
assert produccion.ENFASIS_COLOR + "&\\fscx112\\fscy112}dios" in txt, txt     # 'dios' resaltado
assert "😱" not in txt and "Segoe UI Emoji" not in txt                        # sin emojis
assert ",marca,,0,0,0,,@cuenta" in txt and "0:00:02.50,0:00:05.00,outro" in txt
assert "Style: sub,Arial,60," in txt and "DIOS" not in txt

# PARA SUBIR: nombre legible, sin caracteres prohibidos en Windows, y re-producir
# encuentra la version anterior del MISMO clip (no la de envivo_04_corte).
dest = tempfile.mkdtemp()
src = os.path.join(d, "2026-11-20_rubius", "envivo_04.mp4")
nuevo, viejos = produccion.ruta_para_subir(src, 'Rubius: ¿qué "pasa"?', dest)
assert os.path.basename(nuevo) == "2026-11-20 rubius envivo_04 - RUBIUS ¿QUÉ PASA.mp4", nuevo
assert viejos == []
for f in ("2026-11-20 rubius envivo_04 - TITULO VIEJO.mp4", "2026-11-20 rubius envivo_04.mp4",
          "2026-11-20 rubius envivo_04_corte - OTRO.mp4", "2026-11-20 rubius envivo_041.mp4"):
    open(os.path.join(dest, f), "w").close()
_, viejos = produccion.ruta_para_subir(src, "", dest)
assert sorted(os.path.basename(v) for v in viejos) == [
    "2026-11-20 rubius envivo_04 - TITULO VIEJO.mp4", "2026-11-20 rubius envivo_04.mp4"], viejos

# Audio: dB de PCM, base que se adapta, y grito de 1s detectado (golpe suelto no).
import array as _array
import audio
from autoclip import puntuacion


def _pcm(amplitud, n=audio.BYTES // 2):
    return _array.array("h", [amplitud if i % 2 else -amplitud for i in range(n)]).tobytes()


assert audio.db(b"") == audio.SILENCIO and audio.db(_pcm(0)) == audio.SILENCIO
assert abs(audio.db(_pcm(32767))) < 0.1                        # maximo = 0 dB
assert abs(audio.db(_pcm(3277)) - -20) < 0.2                   # 10x menos = -20 dB
v = audio.Volumen()
t = 0.0
for _ in range(60 * audio.POR_SEGUNDO):                        # 60 s de voz normal
    v.agregar(t, audio.db(_pcm(1000))); t += audio.TRAMO
assert abs(v.base - audio.db(_pcm(1000))) < 0.5, v.base
v.agregar(t, audio.db(_pcm(30000))); t += audio.TRAMO          # golpe de 0.25 s
assert v.pico(3, t) < 12, "un golpe suelto no es un grito"
for _ in range(audio.POR_SEGUNDO * 2):                         # grito de 2 s (+30 dB)
    v.agregar(t, audio.db(_pcm(30000))); t += audio.TRAMO
assert v.pico(3, t) > 25, v.pico(3, t)
assert v.base < audio.db(_pcm(1000)) + 1, "el grito no debe subir la base"
# Caso real que fallo: 30 s de corte de audio no deben hundir la base (luego todo
# pareceria un grito de +30 dB).
for _ in range(30 * audio.POR_SEGUNDO):
    v.agregar(t, audio.SILENCIO); t += audio.TRAMO
assert abs(v.base - audio.db(_pcm(1000))) < 0.5, v.base
for _ in range(2 * audio.POR_SEGUNDO):                         # voz normal tras el corte
    v.agregar(t, audio.db(_pcm(1000))); t += audio.TRAMO
assert v.pico(3, t) < 3, "voz normal no es grito"

# Base del chat: sigue al chat cuando se anima de verdad; un pico corto no la mueve.
import collections as _col
from autoclip import linea_base, MIN_MUESTRAS
m = _col.deque(maxlen=120)
assert linea_base(m, 20.0) == 20.0                              # sin datos: la inicial
m.extend([150] * 100)                                           # chat grande sostenido
assert linea_base(m, 20.0) == 150, "debe subir con el chat (antes se quedaba en 21)"
m.extend([600] * 15)                                            # pico de 15 s
assert linea_base(m, 20.0) == 150, "un pico corto no mueve la base"
assert linea_base(_col.deque([0] * MIN_MUESTRAS), 20.0) == 1.0  # nunca 0

# Score 0-99: acotado, y sube con cada senal.
assert puntuacion(0, 20, 0, 0, 1.8, 10, 12) == 0
assert puntuacion(10**6, 1, 999, 999, 1.8, 10, 12) == 99
assert puntuacion(10**6, 1, 999, 0, 1.8, 10, 0) == 99           # sin audio tambien llega a 99
assert puntuacion(40, 20, 10, 20, 1.8, 10, 12) > puntuacion(40, 20, 10, 0, 1.8, 10, 12)

# Render sin video (directo corrupto): se detecta para no guardar un clip solo de audio.
import subprocess
from envivo import tiene_video
solo_audio, con_video = os.path.join(d, "a.mp4"), os.path.join(d, "v.mp4")
subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                "sine=duration=1", solo_audio], check=True)
subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                "testsrc=size=64x64:duration=1", con_video], check=True)
assert not tiene_video(solo_audio) and tiene_video(con_video)

# Calibración: anuncio de Twitch (liso) vs directo real (con detalle); la cara quieta
# (webcam) gana a las que saltan (personajes del juego); sin caras -> "sin cámara".
import cv2
import numpy as np
import calibrar
liso = cv2.merge([np.tile(np.linspace(0, 255, 640, dtype=np.uint8), (360, 1))] * 3)
assert calibrar.es_anuncio(liso)
detalle = np.random.default_rng(1).integers(0, 255, (360, 640, 3)).astype(np.uint8)
assert not calibrar.es_anuncio(detalle)
por_frame = [[(100, 100, 50, 50, .9), (500, 300, 80, 80, .95)],
             [(102, 101, 50, 50, .9), (900, 100, 80, 80, .95)],
             [(101, 99, 50, 50, .9)]]
assert calibrar._cara_estable(por_frame)[0] in (100, 101, 102), "debe ganar la webcam quieta"
try:
    calibrar.calibrar_frames([np.zeros((360, 640, 3), np.uint8)])
    raise AssertionError("sin caras debe decir que no hay cámara")
except calibrar.SinCamara:
    pass

# --- vod: un estallido de chat a los 500 s y otro más flojo a los 900 s; ruido de fondo
import vod
fondo = [(t, f"u{t % 7}", "hola") for t in range(0, 1200, 2)]
grande = [(500 + i / 10, f"g{i}", "KEKW") for i in range(80)]
flojo = [(900 + i / 10, f"f{i}", "jaja") for i in range(30)]
linea = vod.linea_de_tiempo(sorted(fondo + grande + flojo), 1200, 1.8, 10)
picos = vod.mejores_picos(linea, 3)
assert 497 <= picos[0] <= 509 and any(897 <= p <= 909 for p in picos), picos
assert all(abs(a - b) >= vod.COOLDOWN for a in picos for b in picos if a != b), picos
assert vod._ventana_clip(500, 45, 7) == (462, 507)
assert vod.RE_VOD.match("https://www.twitch.tv/videos/2936129297").group(1) == "2936129297"

print("OK - autoprueba pasada.")
