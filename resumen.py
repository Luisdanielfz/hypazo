"""Resumen del piloto de Hypazo: una lista CERRADA de datos, sin vídeo, rutas, fechas, canal ni chat.

Se guarda solo cuando el usuario lo confirma, en salida/_resumenes/resumen-piloto-N.json.
"""
import json
import os
import re

from revision import ETIQUETAS, emparejar

FORMATO = 1
_PROHIBIDO = re.compile(r":\\|/|\\|\.mp4|\d{4}-\d{2}-\d{2}")
_HMS = re.compile(r"^(≈ )?\d{2,}:\d{2}:\d{2}$")


def hms(s: float | None) -> str:
    if s is None:
        return "desconocido"
    s = max(0, int(round(s)))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def construir(sesion: dict, clips: list, estado: dict) -> dict:
    decisiones = estado.get("decisiones", {})
    decision = lambda c: decisiones.get(c.id, "pendiente" if c.origen == "forzado" else "conservar")
    descartados = {c.id for c in clips if decision(c) == "descartar"}
    deshechos = set(estado.get("deshechos", []))
    parejas = emparejar(clips, deshechos, descartados)
    por_id = {c.id: c for c in clips}

    def pareja(c):
        if c.origen == "automatico":
            return None
        if c.id in parejas:
            return {"con": hms(por_id[parejas[c.id][0]].tiempo), "regla": "automatica"}
        if c.id in deshechos:
            return {"regla": "corregida"}
        return "se_escapo" if c.origen == "manual" else None

    estado_txt = {"conservar": "conservado", "aprobar": "aprobado", "pendiente": "pendiente"}
    inicio, fin = sesion.get("inicio"), sesion.get("fin")
    autos = [c for c in clips if c.origen == "automatico"]
    return {
        "formato": FORMATO,
        "plataforma": sesion["plataforma"],
        "sesion": {"duracion": hms(fin - inicio) if inicio is not None and fin is not None else None,
                   "inicio": sesion["estado_inicio"],
                   "cortes": [{"en": hms(k["en"]), "dura_s": int(round(k["dura"]))}
                              for k in sesion.get("cortes", [])]},
        "clips": [{"tiempo": hms(c.tiempo), "origen": c.origen,
                   "etiqueta": estado.get("etiquetas", {}).get(c.id),
                   "estado": estado_txt[decision(c)], "pareja": pareja(c)}
                  for c in clips if c.id not in descartados],
        "escapados_recordados": [{"tiempo": "≈ " + hms(e["t_s"]), "tipo": e["tipo"]}
                                 for e in estado.get("escapados", [])],
        "automaticos": {"conservados": sum(c.id not in descartados for c in autos),
                        "descartados": sum(c.id in descartados for c in autos)},
    }


def _claves(d, permitidas, donde):
    if not isinstance(d, dict) or set(d) != set(permitidas):
        raise ValueError(f"Claves no permitidas en {donde}")


def _uno_de(v, opciones, donde):
    if v not in opciones:
        raise ValueError(f"Valor no permitido en {donde}: {v!r}")


def _tiempo(v, donde, aprox=False):
    if v == "desconocido" and not aprox:
        return
    if not isinstance(v, str) or not _HMS.match(v) or v.startswith("≈") != aprox:
        raise ValueError(f"Tiempo no válido en {donde}: {v!r}")


def validar(r: dict) -> None:
    """Lanza ValueError si el resumen tiene algo fuera de la lista cerrada."""
    if _PROHIBIDO.search(json.dumps(r, ensure_ascii=False)):
        raise ValueError("El resumen contiene algo parecido a una ruta, un archivo o una fecha.")
    _claves(r, ("formato", "plataforma", "sesion", "clips", "escapados_recordados", "automaticos"), "resumen")
    _uno_de(r["formato"], (FORMATO,), "formato")
    _uno_de(r["plataforma"], ("twitch", "kick"), "plataforma")
    s = r["sesion"]
    _claves(s, ("duracion", "inicio", "cortes"), "sesion")
    if s["duracion"] is not None:
        _tiempo(s["duracion"], "duracion")
    _uno_de(s["inicio"], ("completo", "parcial", "desconocido"), "inicio")
    for k in s["cortes"]:
        _claves(k, ("en", "dura_s"), "corte")
        _tiempo(k["en"], "corte")
        if not isinstance(k["dura_s"], int):
            raise ValueError("dura_s no es un entero")
    for c in r["clips"]:
        _claves(c, ("tiempo", "origen", "etiqueta", "estado", "pareja"), "clip")
        _tiempo(c["tiempo"], "clip")
        _uno_de(c["origen"], ("automatico", "manual", "forzado"), "origen")
        _uno_de(c["etiqueta"], (None, *ETIQUETAS), "etiqueta")
        _uno_de(c["estado"], ("conservado", "aprobado", "pendiente"), "estado")
        p = c["pareja"]
        if isinstance(p, dict):
            if p.get("regla") == "automatica":
                _claves(p, ("con", "regla"), "pareja")
                _tiempo(p["con"], "pareja")
            else:
                _claves(p, ("regla",), "pareja")
                _uno_de(p["regla"], ("corregida",), "pareja")
        else:
            _uno_de(p, (None, "se_escapo"), "pareja")
    for e in r["escapados_recordados"]:
        _claves(e, ("tiempo", "tipo"), "escapado")
        _tiempo(e["tiempo"], "escapado", aprox=True)
        _uno_de(e["tipo"], ETIQUETAS, "escapado")
    a = r["automaticos"]
    _claves(a, ("conservados", "descartados"), "automaticos")
    if not all(isinstance(v, int) and v >= 0 for v in a.values()):
        raise ValueError("Recuento de automáticos no válido")


def texto_exacto(r: dict) -> str:
    return json.dumps(r, ensure_ascii=False, indent=2)


def texto_legible(r: dict) -> str:
    s = r["sesion"]
    cortes = "".join(f" ({k['en']}, {k['dura_s'] // 60} min)" for k in s["cortes"])
    n = len(s["cortes"])
    lineas = [f"{r['plataforma']} · inicio {s['inicio']} · dura {s['duracion'] or 'desconocido'} · "
              f"{n} {'corte' if n == 1 else 'cortes'}{cortes}", "clips:"]
    for c in r["clips"]:
        p = c["pareja"]
        extra = (" · se escapó" if p == "se_escapo" else f" · emparejado con {p['con']}" if isinstance(p, dict)
                 and "con" in p else " · separado a mano" if isinstance(p, dict) else "")
        extra += "" if c["estado"] == "conservado" else f" · {c['estado']}"
        lineas.append(f"  {c['tiempo']}  {c['origen']:<10} {c['etiqueta'] or '—':<7}{extra}")
    lineas.append("se escaparon (recordados):")
    lineas += [f"  {e['tiempo']}  {e['tipo']}" for e in r["escapados_recordados"]] or ["  ninguno"]
    a = r["automaticos"]
    pl = lambda k, palabra: f"{k} {palabra}{'' if k == 1 else 's'}"
    lineas.append(f"automáticos: {pl(a['conservados'], 'conservado')} · {pl(a['descartados'], 'descartado')}"
                  "   (solo números)")
    return "\n".join(lineas)


def guardar(r: dict, salida: str) -> str:
    """Valida y guarda en salida/_resumenes/resumen-piloto-N.json. Devuelve solo el nombre."""
    validar(r)
    carpeta = os.path.join(salida, "_resumenes")
    os.makedirs(carpeta, exist_ok=True)
    n = 1
    while os.path.exists(os.path.join(carpeta, f"resumen-piloto-{n}.json")):
        n += 1
    nombre = f"resumen-piloto-{n}.json"
    with open(os.path.join(carpeta, nombre), "x", encoding="utf-8", newline="") as f:
        f.write(texto_exacto(r))
    return nombre
