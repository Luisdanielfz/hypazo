"""aprendizaje.py - Aprende de lo que guardas y lo que descartas: probabilidad de que te quedes un clip.

Cada clip cazado guarda sus señales en su .json (chat sobre lo normal, gente, grito, clips de la gente) y tú
decides: «bueno» = 1; «descartado» o mandado a la papelera = 0. Con bastantes decisiones de un streamer
(MIN_TOTAL, y MIN_POR_CLASE de cada tipo) se ajusta una regresión logística para él; si aún no hay, vale la
aprendida con todos los streamers juntos. Un modelo solo se usa si, probado con clips que no vio, acierta
más que «decir siempre lo más común» (validación cruzada).
"""
import json
import math
import os
import threading
import time

import numpy as np

MIN_TOTAL = 30
MIN_POR_CLASE = 8
MEJORA = 0.05          # tiene que acertar al menos 5 puntos más que sin aprender
TODOS = "*"
NOMBRES = ("el chat sobre lo normal", "la gente que escribe", "los gritos", "los clips de la gente")
PAPELERA = "_papelera"
HISTORIAL = "_aprendizaje.jsonl"   # decisiones de clips ya borrados para siempre (al vaciar la papelera)


def senales(meta):
    """Las señales del clip, o None si el clip no las tiene."""
    try:
        return (math.log(max(1.0, float(meta["puntaje"])) / max(1.0, float(meta["normal"]))),
                math.log1p(max(0.0, float(meta.get("personas") or 0))),
                float(meta.get("grito_db") or 0.0) / 10,
                math.log1p(max(0.0, float(meta.get("comunidad_vistas") or 0))))
    except (KeyError, TypeError, ValueError):
        return None


def _etiqueta(meta, en_papelera):
    if meta.get("producido") or meta.get("de") or meta.get("motivo") in ("manual", "forzado"):
        return None            # copias (producidos, cortes) y clips pedidos a mano: no dicen nada del detector
    if meta.get("estado") == "descartado":
        return 0
    if meta.get("estado") == "bueno":
        return 1               # también en la papelera: Limpieza manda ahí los originales ya subidos
    return 0 if en_papelera else None     # borrado sin decidir = no lo querías


def _de_carpeta(salida, carpeta):
    out = []
    for raiz, _dirs, archivos in os.walk(carpeta):
        en_papelera = os.path.relpath(raiz, salida).split(os.sep)[0] == PAPELERA
        for f in archivos:
            if not f.endswith(".json") or not os.path.exists(os.path.join(raiz, f[:-5] + ".mp4")):
                continue
            try:
                with open(os.path.join(raiz, f), encoding="utf-8-sig") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            y, x = _etiqueta(meta, en_papelera), senales(meta)
            if y is not None and x is not None:
                clave = os.path.relpath(os.path.join(raiz, f), salida).replace(os.sep, "/")
                out.append((clave, str(meta.get("canal") or "?").lower(), x, y))
    return out


def _historial(salida):
    """{clave: (canal, señales, 0/1)}. La clave es la ruta del .json en la papelera (única: lleva la hora)."""
    out = {}
    try:
        with open(os.path.join(salida, HISTORIAL), encoding="utf-8") as f:
            for n, linea in enumerate(f):
                try:
                    datos = json.loads(linea)
                    clave, (canal, x, y) = (datos[0], datos[1:]) if len(datos) == 4 else (f"#{n}", datos)
                    out[str(clave)] = (str(canal), tuple(float(v) for v in x), int(y))
                except (ValueError, TypeError):
                    continue          # una línea rota no tira el resto
    except FileNotFoundError:
        pass
    return out


def muestras(salida):
    """[(canal, señales, 0/1)] de todos los clips decididos: carpeta de salida, papelera e historial
    (lo ya archivado que siga en la papelera cuenta una sola vez)."""
    hist = _historial(salida)
    return [(c, x, y) for clave, c, x, y in _de_carpeta(salida, salida) if clave not in hist] + list(hist.values())


def archivar_papelera(salida):
    """Antes de vaciar la papelera: guarda en el historial sus decisiones aún no guardadas. Devuelve cuántas.
    Si no puede escribir, lanza OSError (y la papelera no debe vaciarse)."""
    hist = _historial(salida)
    nuevas = [m for m in _de_carpeta(salida, os.path.join(salida, PAPELERA)) if m[0] not in hist]
    if nuevas:
        with open(os.path.join(salida, HISTORIAL), "a", encoding="utf-8") as f:
            f.writelines(json.dumps([clave, c, list(x), y]) + "\n" for clave, c, x, y in nuevas)
    return len(nuevas)


def entrenar(X, y, pasos=600, lr=0.3, l2=0.01):
    X, y = np.asarray(X, float), np.asarray(y, float)
    media, escala = X.mean(0), X.std(0)
    escala[escala == 0] = 1.0
    Z = (X - media) / escala
    w, b = np.zeros(Z.shape[1]), 0.0
    for _ in range(pasos):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        w -= lr * (Z.T @ (p - y) / len(y) + l2 * w)
        b -= lr * float(np.mean(p - y))
    return {"media": media.tolist(), "escala": escala.tolist(), "pesos": w.tolist(), "sesgo": b}


def _p(modelo, x):
    z = (np.asarray(x, float) - modelo["media"]) / modelo["escala"]
    return float(1 / (1 + np.exp(-(z @ np.asarray(modelo["pesos"]) + modelo["sesgo"]))))


def _acierto(X, y, k=5):
    """Validación cruzada: % de clips (que el modelo no vio) en los que acierta."""
    orden = np.random.default_rng(0).permutation(len(y))
    bien = 0
    for f in range(k):
        prueba = orden[f::k]
        entreno = np.setdiff1d(orden, prueba)
        m = entrenar([X[i] for i in entreno], [y[i] for i in entreno])
        bien += sum((_p(m, X[i]) >= 0.5) == bool(y[i]) for i in prueba)
    return bien / len(y)


def _uno(datos):
    X, y = [x for x, _ in datos], [y for _, y in datos]
    buenos = sum(y)
    info = {"n": len(y), "buenos": buenos, "malos": len(y) - buenos,
            "falta": max(MIN_TOTAL - len(y), MIN_POR_CLASE - min(buenos, len(y) - buenos), 0), "activo": False}
    if info["falta"]:
        return info
    modelo = entrenar(X, y)
    acierto, base = _acierto(X, y), max(buenos, len(y) - buenos) / len(y)
    fuerte = int(np.argmax(np.abs(modelo["pesos"])))
    return {**info, "modelo": modelo, "acierto": round(acierto, 3), "base": round(base, 3),
            "activo": acierto >= base + MEJORA, "senal": NOMBRES[fuerte]}


def modelos(muestras_):
    """{canal: info} y TODOS (con todos los streamers). info: n, buenos, malos, falta, activo, acierto, base, senal."""
    por = {}
    for canal, x, y in muestras_:
        por.setdefault(canal, []).append((x, y))
    out = {c: _uno(d) for c, d in por.items()}
    out[TODOS] = _uno([(x, y) for _c, x, y in muestras_])
    return out


def prob(mods, meta):
    """0-100: probabilidad de que te quedes este clip, o None si aún no hay nada aprendido para él."""
    x = senales(meta)
    if x is None:
        return None
    propio = mods.get(str(meta.get("canal") or "").lower())
    if propio and not propio["falta"] and not propio["activo"]:
        return None          # con datos suyos que no predicen nada, lo general (de otros) tampoco vale
    for m in (propio, mods.get(TODOS)):
        if m and m["activo"]:
            return min(99, max(1, round(100 * _p(m["modelo"], x))))     # nunca «seguro» del todo
    return None


class Aprendizaje:
    """Para la app: reentrena solo si cambió alguna decisión, y como mucho cada `cada` segundos mira la carpeta."""

    def __init__(self, salida, cada=30):
        self.salida, self.cada = salida, cada
        self._mods, self._firma, self._visto = {}, None, -1e9
        self._lock = threading.Lock()

    def resumen(self):
        with self._lock:
            if time.time() - self._visto >= self.cada:
                self._visto = time.time()
                m = muestras(self.salida())
                firma = hash(tuple(sorted(m)))
                if firma != self._firma:
                    self._mods, self._firma = modelos(m), firma
            return self._mods

    def prob(self, meta):
        return prob(self.resumen(), meta)
