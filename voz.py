"""voz.py - Subtítulos solo con la voz del streamer (no la de los personajes del juego).

Cada frase que transcribe Whisper recibe una «huella de voz» (256 números) con un modelo pequeño de
reconocimiento de hablante: WeSpeaker ResNet34 entrenado con VoxCeleb (CC-BY-4.0, ~26 MB, se baja la primera
vez y se comprueba su SHA-256). Sin perfil guardado de ese streamer no se filtra nada: solo se aprende su voz
de un clip en el que casi todo lo dice una sola voz (él hablando). Con perfil, se quitan las frases claramente
de otra voz y el perfil se afina clip a clip. Si el modelo no está o algo falla, los subtítulos salen como siempre.
"""
import hashlib
import json
import os

import numpy as np

import cortes

REPO = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
ARCHIVO = "voxceleb_resnet34_LM.onnx"
REVISION = "f0c48c298fd835726c27956a5d617bad7115627e"
SHA256 = "7bb2f06e9df17cdf1ef14ee8a15ab08ed28e8d0ef5054ee135741560df2ec068"
SR = 16000
UMBRAL = 0.30        # por debajo, otra voz (con margen: un grito del streamer con ruido sigue pasando)
MIN_FRASE = 0.6      # segundos: menos no da una huella fiable (la frase sigue a su vecina)
MEZCLA = 0.2         # cuánto cambia el perfil guardado con cada clip
SOLO_UNA_VOZ = 0.9   # para aprender la voz sin perfil: esa parte del habla tiene que ser de una sola voz
MIN_HABLA = 3.0      # ...y al menos 2 frases y estos segundos de habla (una frase suelta podría ser del juego)
REINTENTO_S = 600    # sin modelo (p. ej. sin internet): no reintentar la descarga en cada clip
DIM = 256
_modelo = None
_fallo = 0.0


def _banco_mel(n_fft=512, n_mels=80, fmin=20.0, fmax=8000.0):
    mel = lambda f: 1127.0 * np.log(1 + f / 700.0)       # noqa: E731
    m = np.linspace(mel(fmin), mel(fmax), n_mels + 2)
    fm = mel(np.arange(n_fft // 2 + 1) * SR / n_fft)
    banco = np.zeros((n_mels, len(fm)), np.float32)
    for i in range(n_mels):
        izq, cen, der = m[i], m[i + 1], m[i + 2]
        banco[i] = np.clip(np.minimum((fm - izq) / (cen - izq), (der - fm) / (der - cen)), 0, None)
    return banco


_BANCO = _banco_mel()


def fbank(x):
    """80 bandas log-mel cada 10 ms (ventanas de 25 ms, sin salirse del audio) con la media restada:
    lo que espera el modelo (estilo Kaldi)."""
    x = np.asarray(x, np.float64) * 32768.0
    lon, paso = 400, 160
    if len(x) < lon:
        return np.zeros((0, 80), np.float32)
    marcos = np.lib.stride_tricks.sliding_window_view(x, lon)[::paso]
    marcos = marcos - marcos.mean(1, keepdims=True)
    marcos = np.concatenate([marcos[:, :1] * 0.03, marcos[:, 1:] - 0.97 * marcos[:, :-1]], 1) * np.hamming(lon)
    f = np.log(np.maximum((np.abs(np.fft.rfft(marcos, 512)) ** 2) @ _BANCO.T, 1.1920929e-07)).astype(np.float32)
    return f - f.mean(0)


def _cargar():
    """La sesión ONNX del modelo (lo baja la primera vez), o None si no se puede."""
    global _modelo
    if _modelo is None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        ruta = hf_hub_download(REPO, ARCHIVO, revision=REVISION)
        with open(ruta, "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != SHA256:
                raise RuntimeError("El modelo de voz descargado no es el esperado.")
        _modelo = ort.InferenceSession(ruta, providers=["CPUExecutionProvider"])
    return _modelo


def huella_modelo():
    """Función huella(audio, ini, fin) -> vector unitario, o None si el modelo no está disponible."""
    global _fallo
    import time
    if _modelo is None and time.time() - _fallo < REINTENTO_S:
        return None
    try:
        modelo = _cargar()
    except Exception:            # sin internet, sin onnxruntime, descarga rota: subtítulos como siempre
        _fallo = time.time()
        return None

    def huella(audio, a, b):
        f = fbank(audio[int(a * SR):int(b * SR)])
        e = modelo.run(None, {"feats": f[None]})[0][0]
        return e / (np.linalg.norm(e) or 1.0)
    return huella


def _frases(palabras):
    """Índices de palabras agrupados por frase (pausa >= cortes.FRASE_PAUSA)."""
    grupos = []
    for i, (ini, _fin, _t) in enumerate(palabras):
        if grupos and ini - palabras[grupos[-1][-1]][1] < cortes.FRASE_PAUSA:
            grupos[-1].append(i)
        else:
            grupos.append([i])
    return grupos


def filtrar(palabras, audio, perfil=None, huella="modelo"):
    """(palabras solo del streamer, perfil nuevo o None). Sin modelo, con una sola voz o si todo parece de otra
    voz (perfil viejo que ya no vale), devuelve las palabras tal cual."""
    if huella == "modelo":
        huella = huella_modelo()
    grupos = _frases(palabras)
    if huella is None or not grupos:
        return palabras, None
    span = [(palabras[g[0]][0], palabras[g[-1]][1]) for g in grupos]
    hs = [huella(audio, a, b) if b - a >= MIN_FRASE else None for a, b in span]
    con = [k for k, h in enumerate(hs) if h is not None]
    if not con:
        return palabras, None
    M = np.array([hs[k] for k in con])
    peso = np.array([span[k][1] - span[k][0] for k in con])
    ref = np.asarray(perfil, np.float32) if perfil is not None else M[int(np.argmax((M @ M.T) @ peso))]
    voto = {k: float(M[j] @ ref) >= UMBRAL for j, k in enumerate(con)}
    if not any(voto.values()):
        return palabras, None
    if perfil is None:
        # Sin perfil no se sabe quién es el streamer (el juego puede hablar más): no se filtra, y solo se aprende
        # su voz si casi todo lo dice una sola voz.
        una = sum(p for k, p in zip(con, peso) if voto[k]) / peso.sum()
        if una < SOLO_UNA_VOZ or len(con) < 2 or peso.sum() < MIN_HABLA:
            return palabras, None
    for k in range(len(grupos)):       # las frases cortas, con su vecina con huella más cercana en el tiempo
        if k not in voto:
            vecina = min(con, key=lambda j: min(abs(span[j][0] - span[k][1]), abs(span[k][0] - span[j][1])))
            voto[k] = voto[vecina]
    quedan = [palabras[i] for k, g in enumerate(grupos) if voto[k] for i in g]
    buenos = [j for j, k in enumerate(con) if voto[k]]
    nuevo = (M[buenos] * peso[buenos, None]).sum(0)
    return quedan, nuevo / (np.linalg.norm(nuevo) or 1.0)


def _leer(ruta):
    """{canal: vector} válidos del archivo (lo roto o de otro tamaño se ignora)."""
    try:
        with open(ruta, encoding="utf-8") as f:
            todos = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(todos, dict):
        return {}
    return {c: v for c, v in todos.items() if isinstance(v, list) and len(v) == DIM
            and all(isinstance(x, (int, float)) for x in v)}


def perfil_de(ruta, canal):
    v = _leer(ruta).get(canal)
    return None if v is None else np.asarray(v, np.float32)


def guardar_perfil(ruta, canal, huella):
    """Mezcla la huella de este clip con el perfil guardado (un clip raro no lo estropea)."""
    todos = _leer(ruta)
    viejo = todos.get(canal)
    nuevo = np.asarray(huella, np.float64)
    if viejo is not None:
        nuevo = (1 - MEZCLA) * np.asarray(viejo, np.float64) + MEZCLA * nuevo
    todos[canal] = (nuevo / (np.linalg.norm(nuevo) or 1.0)).round(5).tolist()
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(todos, f)
    os.replace(tmp, ruta)
