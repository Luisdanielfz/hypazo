"""
calibrar.py - Calibra solo el formato split de un streamer: dónde está su cámara
(recorte de cara, arriba) y qué trozo de juego va abajo.

1. Saca varios frames (del buffer del cazador si está grabando ese canal; si no, del directo).
2. YuNet (OpenCV, en local) encuentra la cara.
3. Desde la cara busca los bordes reales de la cámara (saltos de brillo); un lado sin
   borde que llega al filo de la pantalla se pega al filo (cámara en una esquina).
4. Mediana entre frames: una alerta o transición en un frame no lo engaña.
5. Sin bordes claros: encuadre alrededor de la cara con margen.

Uso:  python calibrar.py rubius [--plataforma kick]     (imprime el layout, no guarda)
"""
import glob
import os
import statistics
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(AQUI, "assets", "models", "face_detection_yunet_2023mar.onnx")
ANCHO_DET = 960          # se detecta sobre el frame reducido (rápido) y se reescala
SCORE_MIN = 0.75   # con 0.6 colaban relojes y caras de pósters/dibujos (prueba real: thegrefg)
ASPECTO_TOP = 1080 / 820  # forma de la franja de arriba del split
MARGEN = 3                # px hacia dentro: que no entre ni el borde de la cámara
_det = None


UMBRAL_ANUNCIO = 3.0     # % de bordes: el "Commercial break" de Twitch da ~1.6; un directo real, >4.5
MSG_ANUNCIOS = ("Twitch está poniendo anuncios (pasa al conectar sin cuenta, o en una pausa del "
                "directo). Prueba en un minuto, o arranca el cazador y calibra desde su grabación.")


class SinCamara(Exception):
    """No hay cámara usable: el split no tiene sentido para este directo."""


def es_anuncio(img):
    """¿Es la pantalla lisa de anuncio de Twitch? (degradado sin detalle + una línea de texto)."""
    g = cv2.cvtColor(cv2.resize(img, (480, 270)), cv2.COLOR_BGR2GRAY)
    return 100 * (cv2.Canny(g, 60, 160) > 0).mean() < UMBRAL_ANUNCIO


# ---------------------------------------------------------------- frames
def _leer_png(path):
    img = cv2.imread(path)
    if img is None:
        raise RuntimeError(f"no pude leer el frame {path}")
    return img


def frames_de(canal, plataforma="twitch", n=4, buffer_dir=None, viejo_ok=False, solo_buffer=False):
    """n frames BGR del directo. Del buffer del cazador si es reciente (o si viejo_ok);
    si no, del directo (salvo solo_buffer: el cazador no abre una segunda conexión)."""
    buffer_dir = buffer_dir or os.path.join(AQUI, "buffer", f"{plataforma}_{canal}")
    segs = sorted(glob.glob(os.path.join(buffer_dir, "seg*.ts")), key=os.path.getmtime)[:-1]
    segs = [s for s in segs if os.path.getsize(s) > 0]
    tmp = tempfile.mkdtemp(prefix="clipeo_cal_")
    reciente = segs and (viejo_ok or time.time() - os.path.getmtime(segs[-1]) < 60)
    if solo_buffer and not (len(segs) >= n and reciente):
        raise RuntimeError("aún no hay grabación suficiente para calibrar")
    if len(segs) >= n and reciente:
        rutas = []
        for i, seg in enumerate(segs[-n:]):          # segmentos de 5 s: frames separados
            out = os.path.join(tmp, f"f{i}.png")
            subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", seg,
                            "-frames:v", "1", out], capture_output=True, timeout=60)
            if os.path.exists(out):
                rutas.append(out)
    else:
        # Al conectar sin cuenta Twitch pone anuncios: mirar 60 s y quedarse con lo real.
        from envivo import resolver_url
        url = resolver_url(canal, plataforma)        # RuntimeError si no está en vivo
        subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", url, "-t", "60",
                        "-vf", "fps=1/5", "-frames:v", "12", os.path.join(tmp, "f%02d.png")],
                       capture_output=True, timeout=150)
        rutas = sorted(glob.glob(os.path.join(tmp, "f*.png")))
    if not rutas:
        raise RuntimeError("no pude sacar frames del directo")
    reales = [img for img in (_leer_png(r) for r in rutas) if not es_anuncio(img)]
    if not reales:
        raise RuntimeError(MSG_ANUNCIOS)
    return reales[-n:]


# ---------------------------------------------------------------- cara
def caras(img):
    """[(x, y, w, h, score)] en píxeles del frame original, mejor primero."""
    global _det
    alto, ancho = img.shape[:2]
    k = ANCHO_DET / ancho if ancho > ANCHO_DET else 1.0
    peq = cv2.resize(img, (round(ancho * k), round(alto * k))) if k != 1 else img
    if _det is None:
        _det = cv2.FaceDetectorYN.create(MODELO, "", (peq.shape[1], peq.shape[0]), SCORE_MIN)
    _det.setInputSize((peq.shape[1], peq.shape[0]))
    _ok, res = _det.detect(peq)
    if res is None:
        return []
    out = [(r[0] / k, r[1] / k, r[2] / k, r[3] / k, float(r[-1])) for r in res if r[-1] >= SCORE_MIN]
    return sorted(out, key=lambda c: c[2] * c[3] * c[4], reverse=True)


# ---------------------------------------------------------------- bordes
SALTO_PX = 22       # diferencia de gris entre píxeles vecinos que cuenta como "borde"
COBERTURA = 0.55    # parte de la franja que el borde debe cruzar para ser el marco de la cámara


def _borde(g, desde, hasta, paso, banda, vertical):
    """Línea (columna si vertical, fila si no) entre desde→hasta donde un salto de brillo
    cruza la mayor parte de la franja `banda` (rango del otro eje). El marco de una cámara
    es una línea recta que la cruza entera; el borde de un póster o de un objeto, solo un
    trozo. None si ninguna línea llega a COBERTURA."""
    b0, b1 = banda
    if b1 - b0 < 8:
        return None
    mejor, mejor_cob = None, COBERTURA
    for i in range(desde, hasta, paso):
        j = i - paso
        if not (0 <= i < (g.shape[1] if vertical else g.shape[0]) and 0 <= j < (g.shape[1] if vertical else g.shape[0])):
            continue
        a, b = (g[b0:b1, i], g[b0:b1, j]) if vertical else (g[i, b0:b1], g[j, b0:b1])
        cob = float((np.abs(a - b) > SALTO_PX).mean())
        if cob > mejor_cob + 0.05:           # claramente mejor (si empatan, gana la más cercana)
            mejor, mejor_cob = i, cob
    return mejor


def recuadro(img, cara):
    """(x0, y0, x1, y1, por_bordes) de la cámara que contiene la cara."""
    alto, ancho = img.shape[:2]
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    fx, fy, fw, fh = (int(v) for v in cara[:4])
    # franjas que cruzan la cámara: a la altura de la cara (para bordes verticales) y a su
    # anchura (para los horizontales); la cámara siempre es más grande que la cara
    filas_cara = (max(0, fy), min(alto, fy + fh))
    cols_cara = (max(0, fx), min(ancho, fx + fw))
    alcance_x, alcance_y = int(fw * 4), int(fh * 4)
    lados = {
        "x0": (_borde(g, fx, max(-1, fx - alcance_x), -1, filas_cara, True), 0, fx - alcance_x <= 0),
        "x1": (_borde(g, fx + fw, min(ancho, fx + fw + alcance_x), 1, filas_cara, True), ancho, fx + fw + alcance_x >= ancho),
        "y0": (_borde(g, fy, max(-1, fy - alcance_y), -1, cols_cara, False), 0, fy - alcance_y <= 0),
        "y1": (_borde(g, fy + fh, min(alto, fy + fh + alcance_y), 1, cols_cara, False), alto, fy + fh + alcance_y >= alto),
    }
    bordes, encontrados = {}, 0
    for lado, (pos, filo, llega) in lados.items():
        if pos is not None:
            # hacia la izquierda/arriba el salto está entre pos y pos+1: la cámara empieza en pos+1;
            # hacia la derecha/abajo está entre pos-1 y pos: la cámara acaba en pos (exclusivo)
            bordes[lado] = pos + 1 if lado in ("x0", "y0") else pos
            encontrados += 1
        elif llega:
            bordes[lado] = filo                  # la cámara toca el filo de la pantalla
    if len(bordes) == 4 and encontrados >= 2:
        return bordes["x0"], bordes["y0"], bordes["x1"], bordes["y1"], True
    # sin bordes claros: encuadre alrededor de la cara con la forma de la franja de arriba
    h = fh * 2.6
    w = h * ASPECTO_TOP
    cx, cy = fx + fw / 2, fy + fh * 0.62
    x0, y0 = max(0, cx - w / 2), max(0, cy - h / 2)
    return int(x0), int(y0), int(min(ancho, x0 + w)), int(min(alto, y0 + h)), False


# ---------------------------------------------------------------- todo junto
def _par(v):
    return int(v) // 2 * 2       # ffmpeg crop con dimensiones pares es más seguro


def _cara_estable(por_frame):
    """La webcam está quieta; las caras del juego se mueven. Elige, de todas las caras,
    la que reaparece en el mismo sitio en más frames (desempate: tamaño x confianza)."""
    todas = [c for cs in por_frame for c in cs]
    if not todas:
        return None

    def cerca(a, b):
        return (abs((a[0] + a[2] / 2) - (b[0] + b[2] / 2)) < a[2] * .5
                and abs((a[1] + a[3] / 2) - (b[1] + b[3] / 2)) < a[3] * .5)

    def apoyo(c):
        return sum(any(cerca(c, o) for o in cs) for cs in por_frame)
    return max(todas, key=lambda c: (apoyo(c), c[2] * c[3] * c[4]))


def calibrar_frames(frames):
    """Layout {'face': 'w:h:x:y', 'game': 'w:h:x:y'} + cómo se obtuvo."""
    alto, ancho = frames[0].shape[:2]
    por_frame = [caras(img) for img in frames]
    ref = _cara_estable(por_frame)
    cajas, por_bordes = [], 0
    for img, cs in zip(frames, por_frame):
        # en cada frame, la cara más próxima a la estable (si la hay)
        cs = [c for c in cs if abs(c[0] - ref[0]) < ref[2] and abs(c[1] - ref[1]) < ref[3]] if ref else []
        if not cs:
            continue
        x0, y0, x1, y1, ok = recuadro(img, cs[0])
        cajas.append((x0, y0, x1, y1))
        por_bordes += ok
    if not cajas:
        raise SinCamara("No veo ninguna cara en el directo: sin cámara el formato split no tiene "
                        "sentido. Usa el formato normal (o calibra a mano en Ajustes).")
    x0, y0, x1, y1 = (statistics.median(c[i] for c in cajas) for i in range(4))
    x0, y0 = x0 + MARGEN, y0 + MARGEN
    x1, y1 = x1 - MARGEN, y1 - MARGEN
    w, h = _par(x1 - x0), _par(y1 - y0)
    if w * h > 0.6 * ancho * alto:
        raise SinCamara("La cámara ocupa casi toda la pantalla: este directo no tiene un juego "
                        "aparte para poner abajo. Usa el formato normal.")
    if w < 40 or h < 40:
        raise SinCamara("La cámara detectada es demasiado pequeña; calibra a mano en Ajustes.")
    # gameplay: franja de la forma habitual (1060 de 1920) sin pisar la cámara
    gw = min(ancho, _par(ancho * 1060 / 1920))
    if x1 <= ancho / 2:                           # cámara a la izquierda
        gx = x1 + 8
    elif x0 >= ancho / 2:                         # cámara a la derecha
        gx = x0 - 8 - gw
    else:
        gx = (ancho - gw) / 2
    gx = _par(max(0, min(ancho - gw, gx)))
    metodo = "bordes" if por_bordes * 2 >= len(cajas) else "cara"
    return {
        "face": f"{w}:{h}:{_par(x0)}:{_par(y0)}",
        "game": f"{gw}:{_par(alto)}:{gx}:0",
        "metodo": metodo,
        "frames": len(frames), "con_cara": len(cajas),
        # sin recuadro de cámara (IRL / cámara a pantalla completa) el split suele quedar raro
        "aviso": "" if metodo == "bordes" else (
            "No encuentro el recuadro de la cámara: parece un directo con la cámara a pantalla "
            "completa (IRL). Recorté alrededor de la cara, pero el formato normal suele quedar mejor."),
    }


def cara_dentro(img, face):
    """¿Sigue la cara dentro del recorte? (para avisar si el streamer movió la cámara)."""
    w, h, x, y = (int(v) for v in face.split(":"))
    for cx, cy, cw, ch, _s in caras(img):
        mx, my = cx + cw / 2, cy + ch / 2
        if x <= mx <= x + w and y <= my <= y + h:
            return True
    return False


def calibrar(canal, plataforma="twitch", **kw):
    return calibrar_frames(frames_de(canal, plataforma, **kw))


if __name__ == "__main__":
    plat = sys.argv[sys.argv.index("--plataforma") + 1] if "--plataforma" in sys.argv else "twitch"
    print(calibrar(sys.argv[1], plat))
