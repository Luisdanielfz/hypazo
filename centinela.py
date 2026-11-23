"""centinela.py - Modo centinela: vigila los favoritos y arranca el cazador solo cuando uno entra en directo.

Cada minuto (solo si está activado y no hay ya una caza en marcha) mira qué favoritos están en directo y arranca
el primero de la lista. Si paras a mano a uno que sigue en directo, no lo vuelve a arrancar hasta que termine.
Cuando el directo acaba, el cazador se para solo y el centinela vuelve a vigilar.
"""
import threading
import time

import comunidad

CADA_S = 60
REINTENTO_S = 300    # si una caza que arrancó se para enseguida, ese canal espera 5 min (no relanzar cada minuto)


def en_directo(favoritos, pedir=comunidad.gql, info_kick=None):
    """(en directo, comprobados): sets de (canal, plataforma). Twitch: una sola consulta para todos.
    Un canal que no se pudo comprobar (sin red, Kick bloqueando) no está en «comprobados»."""
    vivos, vistos = set(), set()
    twitch = [c for c, p in favoritos if p == "twitch"]
    if twitch:
        variables = {f"c{i}": c for i, c in enumerate(twitch)}
        q = ("query(" + ",".join(f"$c{i}:String!" for i in range(len(twitch))) + "){"
             + " ".join(f"u{i}:user(login:$c{i}){{stream{{id}}}}" for i in range(len(twitch))) + "}")
        try:
            datos = pedir(q, variables) or {}
            for i, c in enumerate(twitch):
                if f"u{i}" in datos:                       # null = el canal no existe: comprobado, no en directo
                    vistos.add((c, "twitch"))
                    if (datos[f"u{i}"] or {}).get("stream"):
                        vivos.add((c, "twitch"))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError):
            pass
    if info_kick is None:
        import kick
        info_kick = kick.info_canal
    for c in (c for c, p in favoritos if p == "kick"):
        try:
            vivo = (info_kick(c) or {}).get("livestream")
            vistos.add((c, "kick"))
            if vivo:
                vivos.add((c, "kick"))
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, AttributeError):
            pass
    return vivos, vistos


class Centinela:
    def __init__(self, corriendo, arrancar, ajustes, consultar=en_directo):
        """ajustes() -> (activo, [(canal, plataforma)] en orden de prioridad)."""
        self.corriendo, self.arrancar, self.ajustes, self.consultar = corriendo, arrancar, ajustes, consultar
        self.saltar = set()        # parados a mano mientras seguían en directo
        self.ultimo = {}           # (canal, plataforma) -> hora en que lo arranqué
        self.texto = ""            # lo que pasó en la última vuelta
        self._lock = threading.Lock()

    def estado(self):
        """Texto para la app: lo de la última vuelta, o qué pasa ahora si aún no ha dado ninguna."""
        if not self.ajustes()[0]:
            return "Apagado."
        if self.corriendo():
            return "Hay una caza en marcha: vuelvo a vigilar cuando termine."
        return self.texto if self.texto and self.texto != "Apagado." else "Activado: lo miro en menos de un minuto."

    def parado_a_mano(self, canal, plataforma):
        with self._lock:
            self.saltar.add((canal, plataforma))

    def vuelta(self):
        activo, favs = self.ajustes()
        favs = [tuple(f) for f in favs]
        if not activo:
            self.texto = "Apagado."
            return
        if not favs:
            self.texto = "Guarda algún favorito para que pueda vigilarlo."
            return
        if self.corriendo():
            return
        vivos, vistos = self.consultar(favs)
        if self.corriendo():                         # lo arrancaste a mano mientras miraba
            return
        ahora, hora = time.time(), time.strftime("%H:%M")
        with self._lock:
            self.saltar -= vistos - vivos             # perdonado solo si de verdad terminó su directo
            listos = [f for f in favs if f in vivos and f not in self.saltar]
            fav = next((f for f in listos if ahora - self.ultimo.get(f, -REINTENTO_S) >= REINTENTO_S), None)
        if fav is None:
            parados = [c for c, p in favs if (c, p) in vivos and (c, p) in self.saltar]
            sin_ver = [c for c, p in favs if (c, p) not in vistos]
            if listos:
                f = listos[0]
                texto = (f"{f[0]} se paró al poco de empezar: lo reintento a las "
                         f"{time.strftime('%H:%M', time.localtime(self.ultimo[f] + REINTENTO_S))}.")
            elif parados:
                texto = f"{', '.join(parados)} en directo, pero lo paraste tú: no lo vuelvo a arrancar hasta que termine."
            else:
                texto = f"Vigilando {len(favs)} favoritos: ninguno en directo."
            self.texto = texto[:-1] + (f"; no pude mirar {', '.join(sin_ver)}" if sin_ver else "") + f" ({hora})."
            return
        self.ultimo[fav] = ahora
        try:
            self.arrancar(fav)
            self.texto = f"{fav[0]} entró en directo: cazando desde las {hora}."
        except Exception as e:                      # que un fallo no pare la vigilancia
            self.texto = f"No pude arrancar a {fav[0]}: {e}"

    def vigilar(self, cada=CADA_S):
        def bucle():
            while True:
                try:
                    self.vuelta()
                except Exception as e:
                    self.texto = f"Error vigilando: {e}"
                time.sleep(cada)
        threading.Thread(target=bucle, daemon=True, name="centinela").start()
