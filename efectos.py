"""efectos.py - Edición dinámica al producir: zoom con sacudida en el momento y golpe de sonido.

Todo con filtros de ffmpeg (sin sonidos ni imágenes de terceros). Los tiempos son los del clip original:
el montaje (cortes.py) recorta después, así que el efecto sale igual en el cold open y en el cuerpo.
"""
ZOOM = 0.2          # +20 % en el momento
ANTES = 0.8         # el momento suele estar justo antes del pico del chat
DESPUES = 0.9
SUBIDA, BAJADA = 0.15, 0.35     # segundos en acercarse y en volver
SACUDIDA = 8        # píxeles de temblor, solo mientras dura el zoom
ANCLA_Y = 0.35      # algo por encima del centro: en split, la reacción (la cámara) está arriba
GOLPE = "aevalsrc=exprs='0.6*sin(2*PI*55*t)*exp(-6*t)+0.2*(random(0)*2-1)*exp(-40*t)':d=0.8:s=48000"


def _envolvente(pico):
    """0 fuera del momento, 1 durante el zoom (con subida y bajada suaves)."""
    a, b = pico - ANTES, pico + DESPUES
    return f"clip((t-{a:.3f})/{SUBIDA},0,1)*clip(({b:.3f}-t)/{BAJADA},0,1)"


def zoom(pico, ancho, alto):
    """Cadena de filtros de vídeo (sin etiquetas): acerca la imagen en el momento y la hace temblar."""
    e = _envolvente(pico)
    z = f"(1+{ZOOM}*{e})"
    ancho, alto = ancho // 2 * 2, alto // 2 * 2      # scale da tamaños pares: el recorte, también
    return (f"scale=w='trunc({ancho}*{z}/2)*2':h='trunc({alto}*{z}/2)*2':eval=frame,"
            f"crop={ancho}:{alto}:x='(in_w-{ancho})/2+{SACUDIDA}*{e}*sin(t*55)'"
            f":y='(in_h-{alto})*{ANCLA_Y}+{SACUDIDA}*{e}*cos(t*47)'")


def cabe(pico):
    """¿Hay sitio antes del pico para acercarse suave? Si el pico está casi al principio, sin efectos."""
    return pico >= ANTES


def golpe(pico):
    """Fuente de audio (sin etiquetas): un «boom» grave que suena cuando empieza el zoom."""
    ms = int(max(0.0, pico - ANTES) * 1000)
    return f"{GOLPE},adelay={ms}|{ms}"
