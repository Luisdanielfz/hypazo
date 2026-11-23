"""cortes.py - Dónde empieza un clip y cómo se monta (corte por frases y «cold open»).

Con los tiempos por palabra de Whisper:
- **inicio()**: en vez de los 45 s fijos, el clip empieza al principio de una frase, entre 12 y 40 s antes del
  pico. Prefiere la frase más cercana al pico que llega tras una pausa clara (ahí suele empezar la historia);
  si no hay pausas claras, la que queda a unos 20 s. Sin voz o sin frases en ese rango: no se corta nada.
- **tramos()**: con cold open, el vídeo abre con ~2,5 s del pico y luego vuelve al contexto.
- **recolocar()**: mueve los subtítulos al vídeo montado.
"""
FRASE_PAUSA = 0.7        # un hueco así entre palabras = frase nueva
PAUSA = 1.2              # un hueco así antes de una frase = buen sitio para empezar el clip
CONTEXTO = (12, 40)      # segundos antes del pico donde puede empezar el clip
OBJETIVO = 20            # si no hay pausas claras: la frase más cercana a 20 s antes del pico
MARGEN = 0.15            # empezar un pelín antes de la primera palabra (no comerse la sílaba)
CO_ANTES, CO_DESPUES = 2.0, 0.5    # cold open: el momento suele estar justo antes del pico del chat


def frases(palabras):
    """[(inicio, pausa_antes)] de cada frase. palabras = [(ini, fin, texto)] en orden."""
    out, fin_prev, texto_prev = [], None, ""
    for ini, fin, texto in palabras:
        if fin_prev is None:
            out.append((ini, ini))
        elif ini - fin_prev >= FRASE_PAUSA or texto_prev.rstrip().endswith((".", "?", "!", "…")):
            out.append((ini, ini - fin_prev))
        fin_prev, texto_prev = fin, texto
    return out


def inicio(palabras, pico):
    """Segundo del clip donde empezar (0.0 = no cortar)."""
    cands = [(t, pausa) for t, pausa in frases(palabras) if CONTEXTO[0] <= pico - t <= CONTEXTO[1]]
    if not cands:
        return 0.0
    con_pausa = [t for t, pausa in cands if pausa >= PAUSA]
    t = max(con_pausa) if con_pausa else min(cands, key=lambda c: abs(pico - c[0] - OBJETIVO))[0]
    return max(0.0, t - MARGEN)


def tramos(duracion, pico, ini=0.0, cold_open=False):
    """[(desde, hasta)] del clip original, en el orden en que se montan."""
    cuerpo = [(ini, duracion)]
    if not cold_open:
        return cuerpo
    return [(max(0.0, pico - CO_ANTES), min(duracion, pico + CO_DESPUES))] + cuerpo


def recolocar(palabras, partes):
    """Palabras con sus tiempos en el vídeo montado (una palabra cortada por el borde de un tramo no sale)."""
    out, desfase = [], 0.0
    for a, b in partes:
        out += [(i - a + desfase, f - a + desfase, t) for i, f, t in palabras if a <= i and f <= b + 0.08]   # Whisper a veces se pasa unos ms del final
        desfase += b - a
    return out
