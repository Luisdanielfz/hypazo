"""
autoclip.py - Caza momentos epicos del LIVE de forma AUTOMATICA.

Graba la senal publica del directo y vigila el chat publico (lectura anonima).
Mide la REACCION del chat (no solo risa): volumen de mensajes + palabras de hype
y pedidos de clip con peso extra, y exige que reaccionen muchas personas distintas
(no un solo spammer). Cuando explota, guarda con los ~45s previos + un post-roll
para que entre el remate. No tienes que pulsar nada. Ctrl+C para parar.

Uso:
    python autoclip.py auronplay --credito "@auronplay"
    python autoclip.py auronplay --piso 40 --factor 1.8 --unicos 10 --postroll 7
    python autoclip.py westcol --plataforma kick --piso 30 --unicos 8

  --piso    : puntaje en 3s minimo para considerar pico
  --factor  : cuantas veces la actividad normal
  --unicos  : personas distintas minimas en la ventana (anti-spammer)
  --postroll: segundos a esperar tras el pico para captar el remate/risa
  --audio   : dB sobre el volumen normal que cuenta como grito/risa (0 = sin audio)

Mientras corre: ENTER = clip manual YA (la app lo hace con su boton "Clip ya").

Prueba del chat (sin grabar):  python autoclip.py auronplay --test 15

Solo usa senales publicas. Da el credito al streamer al subir y baja lo que pidan.
"""
import argparse
import collections
import json
import os
import queue
import random
import re
import socket
import statistics
import sys
import threading
import time

import audio
import sin_consola
sin_consola.activar()   # ffmpeg/yt-dlp sin ventanas de terminal
import envivo
from cola_render import Renderizador
from credito import credito_final
from clipeo import SALIDA
from sesion import Sesiones
from envivo import resolver_url, iniciar_captura, instantanea, quitar_anuncios, recortar, recortar_split, titulo_directo, SEG

VENTANA = 3.0        # segundos de la ventana que mide el pico
COOLDOWN = 90        # no sacar otro clip hasta pasados N segundos
BASE_SEG = 120       # historia (s) para la actividad normal del chat
MIN_MUESTRAS = 30    # calentamiento: sin disparos automaticos hasta 30 s de chat
SCORE_MIN_AUDIO = 50 # en la prueba real, los clips por audio con score <45 eran relleno

# Mensajes que contienen estas palabras cuentan DOBLE (hype / pedido de clip).
CLAVES = [b"clip", b"pog", b"vamos", b"omg", b"wtf", b"kekw", b"omegalul",
          b"lmao", b"jajaj", b"increible", b"no way", b"letsgo", b"loco",
          b"crack", b"golazo", b"brutal"]


def conectar_chat(canal, intentos=3):
    # Sin tiempo limite, un servidor de chat que no contesta colgaba el cazador para siempre
    # (sin un solo mensaje). 15 s por intento y, si no, un error claro.
    for n in range(1, intentos + 1):
        try:
            s = socket.create_connection(("irc.chat.twitch.tv", 6667), timeout=15)
            break
        except OSError as e:
            print(f"   (el chat de Twitch no contesta, intento {n}/{intentos}: {e})")
            if n == intentos:
                raise RuntimeError("No pude conectar con el chat de Twitch; prueba de nuevo en un rato.")
            time.sleep(3)
    s.send(f"NICK justinfan{random.randint(10000, 99999)}\r\n".encode())
    s.send(f"JOIN #{canal.lower()}\r\n".encode())
    s.settimeout(0.4)
    return s


def leer_eventos(s, buffer_ref):
    """Devuelve lista de (peso, usuario) de los mensajes recien llegados."""
    eventos = []
    try:
        data = s.recv(8192)
    except (socket.timeout, OSError):
        return eventos
    if not data:
        return eventos
    buffer_ref[0] += data
    trozos = buffer_ref[0].split(b"\r\n")
    buffer_ref[0] = trozos[-1]
    for ln in trozos[:-1]:
        if ln.startswith(b"PING"):
            s.send(b"PONG :tmi.twitch.tv\r\n")
        elif b"PRIVMSG #" in ln:
            try:
                user = ln[1:ln.index(b"!")]
                cuerpo = ln.split(b"PRIVMSG #", 1)[1].split(b" :", 1)[1].lower()
            except (ValueError, IndexError):
                user, cuerpo = b"", b""
            eventos.append((peso(cuerpo), user, cuerpo))
    return eventos


def peso(cuerpo):
    return 2 if any(k in cuerpo for k in CLAVES) else 1


def abrir_chat(plataforma, canal):
    """Devuelve (conexion, leer) con leer(buf) -> [(peso, usuario, texto)]."""
    if plataforma == "kick":
        import kick
        chat = kick.Chat(canal)
        return chat, lambda _buf: [(peso(t), u, t) for u, t in chat.leer()]
    s = conectar_chat(canal)
    return s, lambda buf: leer_eventos(s, buf)


def resumen_chat(lineas, n=5):
    """Los mensajes mas repetidos de la ventana: [(texto, veces)]."""
    textos = (ln.split(": ", 1)[-1].strip() for ln in lineas)
    return collections.Counter(t for t in textos if t).most_common(n)


def siguiente_indice(carpeta):
    """Siguiente numero libre, para que re-arrancar el mismo dia no pise clips."""
    nums = [int(m.group(1)) for f in os.listdir(carpeta)
            if (m := re.match(r"envivo_(\d+)\.mp4$", f))]
    return max(nums, default=0) + 1


CAL_CADA = 15        # s entre intentos de calibración automática del split
CAL_SIN_CAMARA = 3   # veces seguidas "sin cámara" antes de rendirse (una pausa no basta)


def auto_layout(canal, plataforma, guardar):
    """Calibra el split con la grabación del propio cazador (sin otra conexión al directo).
    Devuelve (layout | None = reintentar | False = no hay cámara, mensaje)."""
    import calibrar
    try:
        r = calibrar.calibrar(canal, plataforma, buffer_dir=envivo.BUF, solo_buffer=True)
    except calibrar.SinCamara as e:
        return False, f"   [calibracion] {e}"
    except RuntimeError:
        return None, ""          # anuncios o aún sin grabación: se reintenta luego
    guardar(canal, r)
    extra = f" Ojo: {r['aviso']}" if r["aviso"] else ""
    return ({"face": r["face"], "game": r["game"]},
            f"   [calibracion] Recorte split calibrado solo: cara {r['face']}, juego {r['game']}."
            f"{extra} Puedes revisarlo en Ajustes.")


def vigilar_camara(canal, plataforma, layout, guardar):
    """Tras un clip split: ¿sigue la cara dentro del recorte? Si no, recalibra."""
    import calibrar
    try:
        img = calibrar.frames_de(canal, plataforma, n=1, buffer_dir=envivo.BUF, solo_buffer=True)[-1]
    except RuntimeError:
        return layout, ""
    if calibrar.es_anuncio(img) or calibrar.cara_dentro(img, layout["face"]):
        return layout, ""
    nuevo, _msg = auto_layout(canal, plataforma, guardar)
    if nuevo:
        return nuevo, (f"   [calibracion] La cámara se movió: recorte recalibrado solo "
                       f"(cara {nuevo['face']}). Revísalo en Ajustes.")
    return layout, ("   [aviso] No veo la cara dentro del recorte de la cámara: puede que el "
                    "streamer la haya movido o esté en otra escena. Revísalo en Ajustes.")


def linea_base(muestras, actual):
    """Actividad normal del chat = mediana de las muestras (1/s, ultimos BASE_SEG s).
    Un pico corto no la mueve, y si el chat se anima de verdad la base sube con el.
    (Antes: media movil que solo se actualizaba fuera de picos -> en la prueba real
    se quedo en 21 con el chat de Kick en ~150 y saco un clip cada 90 s.)"""
    if len(muestras) < MIN_MUESTRAS:
        return actual
    return max(1.0, statistics.median(muestras))


def puntuacion(puntaje, base, unicos, grito, factor, unicos_min, audio_min):
    """0-99: cuanto destaca el momento. Chat sobre lo normal + gente distinta + grito.
    Cada senal satura al doble de su umbral (asi un spam enorme no lo llena solo)."""
    chat = min(puntaje / max(base, 1.0) / (2 * factor), 1.0)
    gente = min(unicos / (2 * max(unicos_min, 1)), 1.0)
    if audio_min <= 0:                      # sin audio: reparte entre chat y gente
        return round(99 * (0.6 * chat + 0.4 * gente))
    voz = min(grito / (2 * audio_min), 1.0)
    return round(99 * (0.45 * chat + 0.25 * gente + 0.30 * voz))


def interpretar(linea, pausado):
    """Una orden de stdin -> (motivo del clip o None, pausado). 'clip' o ENTER = clip manual
    (forzado si la caza automática está en pausa); 'pausa' / 'reanudar' paran o vuelven a cazar."""
    orden = linea.strip().lower()
    if orden in ("", "clip"):
        return ("forzado" if pausado else "manual"), pausado
    if orden == "pausa":
        return None, True
    if orden == "reanudar":
        return None, False
    return None, pausado


def escuchar_teclado(pedidos):
    """Cada linea en stdin (ENTER en consola, o la app) es una orden: ver interpretar()."""
    def bucle():
        for linea in sys.stdin:
            pedidos.put(linea)
    threading.Thread(target=bucle, daemon=True).start()


HUECO_S = 2.0           # bucle parado mas que esto: el chat que llegue ya es atrasado
AVALANCHA = 120         # mensajes en una sola lectura: imposible en 0,4 s, es chat acumulado


def es_atraso(ahora, ultima_vuelta, n_eventos):
    """Chat que no hay que contar para disparar: lo leido tras un parón del bucle o en avalancha.
    Sin esto, el chat acumulado (minutos) se marcaba con la hora de lectura y parecia un pico."""
    return ahora - ultima_vuelta > HUECO_S or n_eventos >= AVALANCHA


AL_DIA_MIN = 15         # una lectura con menos mensajes que esto (o 3x lo normal) = ya al dia
ATRASO_MAX_S = 10       # por si acaso: nunca mas de 10 s sin contar el chat


class Atraso:
    """Tras un paron del bucle, el chat acumulado entra en VARIAS lecturas (~100 mensajes cada una):
    no se cuenta para disparar hasta ponerse al dia (una lectura de tamano normal)."""

    def __init__(self):
        self.ultima = None
        self.desde = None               # None = al dia

    def contar(self, ahora, n_eventos, esperado=0.0):
        """True si los mensajes de esta lectura cuentan para el chat. esperado: mensajes normales por lectura."""
        if self.ultima is not None and es_atraso(ahora, self.ultima, n_eventos):
            self.desde = self.desde or ahora
        elif self.desde is not None and (n_eventos < max(AL_DIA_MIN, 3 * esperado)
                                         or ahora - self.desde > ATRASO_MAX_S):
            self.desde = None
        self.ultima = ahora
        return self.desde is None


LATIDO_S = 30   # cada cuánto se apunta en la sesión que el cazador sigue vivo


def latido(sesiones, sesion, ahora, ultimo):
    """Guarda 'fin' en la sesión cada 30 s: la app para el cazador con taskkill y sin esto
    un rearranque tras un rato sin clips abriría una sesión nueva en vez de marcar un corte."""
    if ahora - ultimo < LATIDO_S:
        return ultimo
    sesiones.tocar(sesion, ahora)
    return ahora


def meta_piloto(motivo, sesion, tiempo, segundos, reloj=None):
    """Campos del piloto de Hypazo en el .json del clip: sesión, origen y tiempo en el directo."""
    t = None if tiempo is None else round(tiempo, 1)
    origen = motivo if motivo in ("manual", "forzado") else "automatico"
    meta = {"sesion": sesion, "origen": origen, "tiempo_directo": t,
            "ventana_directo": None if t is None else [round(t - segundos, 1), t]}
    if reloj is not None:     # para emparejar aunque la plataforma no dé la hora de inicio
        meta["ventana_reloj"] = [round(reloj - segundos, 1), round(reloj, 1)]
    if origen == "forzado":
        meta["revisar"] = True        # pendiente de revisión: nunca se trata como un clip normal
    return meta


def _trabajo_clip(a, indice, trozo, split, assf, layout, carpeta, meta, sesiones, sesion, cambios_layout):
    """El render de un clip, para el hilo de render: corta, guarda su .json y borra el trozo."""
    def trabajo():
        try:
            print(f"   Renderizando clip {indice}...")     # la app lo enseña en la tarjeta del clip
            quitar_anuncios(trozo)                      # fuera la pantalla de anuncios de Twitch
            if split:
                recortar_split(a.credito, a.segundos, indice, assf, layout, carpeta, unido=trozo)
            else:
                recortar(a.credito, a.segundos, indice, carpeta, unido=trozo)
            m = dict(meta)
            guardar_meta(carpeta, indice, m.pop("puntaje"), m.pop("unicos"), m.pop("base"), m.pop("lineas"), **m)
            sesiones.tocar(sesion, time.time())
            if split:                                   # ¿se movio la camara? recalibra solo
                from clipeo import guardar_layout
                nuevo, mensaje = vigilar_camara(a.canal, a.plataforma, layout, guardar_layout)
                if nuevo is not layout:
                    cambios_layout.put(nuevo)
                if mensaje:
                    print(mensaje)
        finally:
            if os.path.exists(trozo):
                os.remove(trozo)
    return trabajo


def guardar_meta(carpeta, indice, puntaje, unicos, base, lineas, **extra):
    """Deja envivo_NN.json junto al clip: por que se cazo (lo lee la app)."""
    mp4 = os.path.join(carpeta, f"envivo_{indice:02d}.mp4")
    if not os.path.exists(mp4):
        return
    meta = {"puntaje": puntaje, "personas": unicos, "normal": round(base),
            "hora": time.strftime("%H:%M:%S"), "top_chat": resumen_chat(lineas), **extra}
    try:
        with open(mp4[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
    except OSError as e:
        print(f"   (no pude guardar datos del clip {indice}: {e})")


def test_chat(canal, segundos, plataforma="twitch"):
    s, leer = abrir_chat(plataforma, canal)
    buf = [b""]
    msgs = collections.deque()
    fin = time.time() + segundos
    pico = 0
    ultimo_print = 0.0
    while time.time() < fin:
        now = time.time()
        for p, user, _ in leer(buf):
            msgs.append((now, p, user))
        while msgs and now - msgs[0][0] > VENTANA:
            msgs.popleft()
        puntaje = sum(p for _, p, _ in msgs)
        unicos = len({u for _, _, u in msgs})
        pico = max(pico, puntaje)
        if now - ultimo_print >= 0.5:   # sin limite inundaba la salida (64MB en 12s)
            print(f"  puntaje: {puntaje:3d}  personas: {unicos:3d}   (pico: {pico})", end="\r")
            ultimo_print = now
    s.close()
    print(f"\nOK - chat de {canal} conectado. Pico de puntaje en {segundos}s: {pico}.")
    print("  Pon --piso cerca del nivel normal y sube con --factor.")


def main():
    p = argparse.ArgumentParser(description="Caza momentos epicos del live automaticamente.")
    p.add_argument("canal")
    p.add_argument("--credito", default="")
    p.add_argument("--segundos", type=int, default=45, help="Duracion hacia atras del clip")
    p.add_argument("--piso", type=int, default=40, help="Puntaje/3s minimo para pico")
    p.add_argument("--factor", type=float, default=1.8, help="Veces sobre la actividad normal")
    p.add_argument("--unicos", type=int, default=10, help="Personas distintas minimas (anti-spam)")
    p.add_argument("--postroll", type=float, default=7.0,
                   help="Segundos de espera tras el pico para que la risa entre al clip")
    p.add_argument("--split", action="store_true",
                   help="Formato split: Auron arriba, chat real en medio, gameplay abajo")
    p.add_argument("--plataforma", choices=("twitch", "kick"), default="twitch")
    p.add_argument("--audio", type=float, default=12.0,
                   help="dB sobre el volumen normal = grito/risa (0 desactiva el audio)")
    p.add_argument("--test", type=int, help="Solo prueba el chat N segundos, sin grabar")
    a = p.parse_args()
    a.credito = credito_final(a.credito, a.canal, a.plataforma)   # todo clip lleva crédito

    if a.test:
        test_chat(a.canal, a.test, a.plataforma)
        return

    from clipeo import LAYOUTS, escribir_ass, guardar_layout
    if a.split:
        # Cargar OpenCV YA, antes de que exista el hilo que lee stdin (el "clip ya" de la app):
        # importarlo después, con ese hilo bloqueado leyendo la tubería, colgaba el cazador.
        import calibrar  # noqa: F401
    layout = LAYOUTS.get(a.canal.lower())
    if a.split and layout is None:
        # Antes usaba el recorte de Auron (casi siempre mal encuadrado en otro streamer).
        print(f"Sin recorte split para '{a.canal}': lo calibro solo en cuanto pasen los "
              "anuncios (hasta entonces, los clips salen en formato normal).")
    ultima_cal, sin_camara = 0.0, 0

    # Carpeta organizada por fecha y streamer: salida/2026-11-20_auronplay/
    # Twitch mantiene el nombre de siempre; Kick lleva prefijo para no mezclar canales.
    pref = "kick_" if a.plataforma == "kick" else ""
    carpeta = os.path.join(SALIDA, f"{time.strftime('%Y-%m-%d')}_{pref}{a.canal.lower()}")
    os.makedirs(carpeta, exist_ok=True)
    print(f"Guardando en: {carpeta}")
    # Buffer propio por canal: dos cazadores a la vez no se borran los segmentos.
    envivo.BUF = os.path.join("buffer", f"{a.plataforma}_{a.canal.lower()}")

    print(f"Resolviendo el live de {a.canal} ({a.plataforma})...")
    url = resolver_url(a.canal, a.plataforma)
    directo = titulo_directo(a.canal, a.plataforma)   # para los hashtags (el juego)
    inicio = envivo.inicio_directo(a.canal, a.plataforma)
    if inicio is None:
        print("No sé a qué hora empezó el directo: los tiempos del resumen saldrán como desconocidos.")
    sesiones = Sesiones(SALIDA)            # misma raíz que las carpetas de clips
    sesion = sesiones.abrir(a.canal, a.plataforma, inicio, time.time())
    ultimo_latido = time.time()
    if directo:
        print(f"Directo: {directo}")
    if a.plataforma == "twitch":
        print("AVISO: Twitch suele poner anuncios al empezar a ver un canal sin cuenta; "
              "los clips del primer minuto o dos pueden caer en ellos.")
    print("Grabando el directo y vigilando chat" + (" y audio" if a.audio > 0 else "")
          + ". ENTER = clip manual. Ctrl+C para parar.")
    proc = iniciar_captura(url, audio=a.audio > 0)
    vol = audio.Volumen()
    if a.audio > 0:
        vol.leer_de(proc.stdout)
    pedidos = queue.Queue()
    pausado = False
    escuchar_teclado(pedidos)
    s, leer = abrir_chat(a.plataforma, a.canal)
    buf = [b""]

    msgs = collections.deque()
    lineas = collections.deque(maxlen=400)   # (timestamp, linea) del chat real
    base = 20.0           # actividad normal: mediana de los ultimos 2 min (ver linea_base)
    muestras = collections.deque(maxlen=BASE_SEG)
    ultimo_clip = 0.0
    ultima_muestra = time.time()
    ultimo_reporte = time.time()
    max_chat = max_gente = 0
    max_ratio = max_grito = 0.0
    indice = siguiente_indice(carpeta)
    render = Renderizador()                     # los clips se renderizan en segundo plano
    cambios_layout = queue.Queue()              # recalibraciones hechas por el hilo de render
    atraso = Atraso()
    try:
        while proc.poll() is None:
            now = time.time()
            eventos = leer(buf)
            # ~0,4 s por lectura (timeout del socket): mensajes normales por lectura segun la base.
            cuenta = atraso.contar(now, len(eventos), esperado=base * 0.4 / VENTANA)
            if not cuenta:
                msgs.clear()                    # el chat atrasado no dispara nada
            for p, user, texto in eventos:
                if cuenta:
                    msgs.append((now, p, user))
                linea = user.decode(errors="ignore") + ": " + texto.decode(errors="ignore")
                lineas.append((now, linea[:46]))
            while not cambios_layout.empty():
                layout = cambios_layout.get_nowait()
            while msgs and now - msgs[0][0] > VENTANA:
                msgs.popleft()
            puntaje = sum(p for _, p, _ in msgs)
            unicos = len({u for _, _, u in msgs})

            # Adapta la linea base (solo fuera de un pico, para no auto-enmascararse).
            if now - ultima_muestra >= 1.0:
                muestras.append(puntaje)
                base = linea_base(muestras, base)
                ultima_muestra = now

            grito = vol.pico(VENTANA) if a.audio > 0 else 0.0
            # Lo mas alto de los ultimos 30s: dice lo cerca que estuvo de disparar.
            max_chat = max(max_chat, puntaje)
            max_ratio = max(max_ratio, puntaje / max(base, 1.0))
            max_gente = max(max_gente, unicos)
            max_grito = max(max_grito, grito)
            if now - ultimo_reporte >= 30:   # para afinar umbrales mirando el registro
                voz = (f" | audio normal {vol.base:.0f} dB, grito max +{max_grito:.0f} dB"
                       f" (dispara a +{a.audio:.0f})") if vol.base is not None else ""
                print(f"   [estado] chat normal ~{base:.0f}/3s, max {max_chat} "
                      f"(x{max_ratio:.1f}, dispara a {a.piso} y x{a.factor}), "
                      f"max {max_gente} personas (pide {a.unicos}){voz}")
                ultimo_reporte = now
                max_chat = max_gente = 0
                max_ratio = max_grito = 0.0

            if a.split and layout is None and now - ultima_cal >= CAL_CADA:
                ultima_cal = now
                nuevo, mensaje = auto_layout(a.canal, a.plataforma, guardar_layout)
                if nuevo:
                    layout = nuevo
                elif nuevo is False:
                    sin_camara += 1
                    if sin_camara >= CAL_SIN_CAMARA:
                        a.split = False
                        mensaje += " Sigo en formato normal."
                    else:
                        mensaje = ""
                if mensaje:
                    print(mensaje)

            calentando = len(muestras) < MIN_MUESTRAS   # aun no sabe que es "normal"
            pico_chat = (not calentando and puntaje >= a.piso and puntaje >= base * a.factor
                         and unicos >= a.unicos)
            # Grito fuerte Y gente reaccionando Y score decente: en la prueba real, gritos
            # con el chat muerto eran relleno y ademas gastaban el cooldown de un pico mejor.
            pico_audio = (not calentando and a.audio > 0 and grito >= a.audio
                          and puntaje >= base and unicos >= max(3, a.unicos // 2)
                          and puntuacion(puntaje, base, unicos, grito, a.factor, a.unicos,
                                         a.audio) >= SCORE_MIN_AUDIO)
            ultimo_latido = latido(sesiones, sesion, now, ultimo_latido)
            pedido = None
            while not pedidos.empty():
                antes = pausado
                m, pausado = interpretar(pedidos.get_nowait(), pausado)
                pedido = m or pedido
                if pausado != antes:
                    print("\nCaza automática EN PAUSA: Clip ya = clip forzado." if pausado
                          else "\nCaza automática reanudada.")
            if pausado:
                pico_chat = pico_audio = False
            manual = pedido is not None
            forzado = pedido == "forzado"
            motivo = pedido or ("chat" if pico_chat else "audio" if pico_audio else None)
            if motivo and (manual or now - ultimo_clip > COOLDOWN):
                score = puntuacion(puntaje, base, unicos, grito, a.factor, a.unicos, a.audio)
                if forzado:
                    print("\nClip FORZADO (caza en pausa).")
                print(f"\nPICO ({motivo})! puntaje {puntaje} / {unicos} personas "
                      f"(normal ~{base:.0f}), grito +{grito:.0f} dB, score {score}. "
                      f"Esperando {a.postroll:.0f}s para el remate...")
                # Sigue leyendo el chat durante el post-roll (que no se congele).
                fin_post = time.time() + a.postroll
                while time.time() < fin_post:
                    t2 = time.time()
                    for _p, _u, _tx in leer(buf):
                        ln = _u.decode(errors="ignore") + ": " + _tx.decode(errors="ignore")
                        lineas.append((t2, ln[:46]))
                    time.sleep(0.2)
                try:
                    ini = time.time() - a.segundos
                    t_fin = time.time()            # fin del clip: lo que cuenta en el directo
                    ventana = [(ts - ini, ln) for ts, ln in lineas if ts >= ini]
                    # Guarda YA el trozo del buffer: el render va a la cola y el cazador sigue.
                    trozo = instantanea(a.segundos, os.path.join(envivo.BUF, f"clip_{indice:02d}.ts"))
                    if not trozo:
                        raise RuntimeError("aun no hay buffer suficiente")
                    split = bool(a.split and layout and not forzado)   # sin recorte o forzado: normal
                    assf = os.path.join(carpeta, f"chat_{indice:02d}.ass") if split else ""
                    if split:
                        escribir_ass(ventana, assf)
                    # El grito puede llegar antes que el chat: el maximo de todo el clip.
                    grito_clip = vol.pico(a.segundos) if a.audio > 0 else 0.0
                    meta = dict(puntaje=puntaje, unicos=unicos, base=base, lineas=[ln for _, ln in ventana],
                                motivo=motivo, grito_db=round(grito_clip, 1), directo=directo,
                                canal=a.canal.lower(), plataforma=a.plataforma,
                                **meta_piloto(motivo, sesion, sesiones.tiempo(sesion, t_fin),
                                              a.segundos, reloj=t_fin),
                                score=max(score, puntuacion(puntaje, base, unicos, grito_clip,
                                                            a.factor, a.unicos, a.audio)))
                    render.encargar(str(indice), _trabajo_clip(
                        a, indice, trozo, split, assf, layout, carpeta, meta, sesiones, sesion, cambios_layout))
                    print(f"   Clip {indice} en cola de render ({render.pendientes()} pendientes). Sigo cazando.")
                    indice += 1
                except Exception as e:  # un clip malo no debe tumbar el cazador
                    print(f"   (clip {indice} fallo, lo salto: {e})")
                if not forzado:                 # el forzado no gasta el enfriamiento
                    ultimo_clip = now
    except KeyboardInterrupt:
        print("\nParando...")
    finally:
        if render.pendientes():
            print(f"   Quedan {render.pendientes()} clips por renderizar: espero hasta 3 min...")
            render.esperar(180)
        sesiones.cerrar(sesion, time.time())
        proc.terminate()
        s.close()
        print(f"Detenido. Clips en la carpeta '{os.path.abspath(SALIDA)}'.")


if __name__ == "__main__":
    main()
