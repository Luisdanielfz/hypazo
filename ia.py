"""IA con muchos proveedores gratuitos (todos hablan la API de chat de OpenAI).

Cada proveedor tiene su clave en la configuración local (<home>/config/config.json, nunca en git).
Si el elegido falla (límite gratuito, clave mala, caído) se prueba el siguiente del orden: así el
plan gratis de uno no deja al usuario sin IA.
"""
import json
import re
import time

import httpx

PROVEEDORES = {
    "groq": {"nombre": "Groq", "url": "https://api.groq.com/openai/v1", "modelo": "openai/gpt-oss-120b",
             "web": "https://console.groq.com/keys", "nota": "Gratis, muy rápido"},
    "gemini": {"nombre": "Google Gemini", "url": "https://generativelanguage.googleapis.com/v1beta/openai",
               "modelo": "gemini-flash-lite-latest", "web": "https://aistudio.google.com/apikey",
               "nota": "Gratis con límite diario"},
    "openrouter": {"nombre": "OpenRouter", "url": "https://openrouter.ai/api/v1",
                   "modelo": "meta-llama/llama-3.3-70b-instruct:free", "web": "https://openrouter.ai/keys",
                   "nota": "Muchos modelos; los que acaban en :free son gratis"},
    "cerebras": {"nombre": "Cerebras", "url": "https://api.cerebras.ai/v1", "modelo": "llama3.1-8b",
                 "web": "https://cloud.cerebras.ai", "nota": "Gratis, muy rápido"},
    "mistral": {"nombre": "Mistral", "url": "https://api.mistral.ai/v1", "modelo": "mistral-small-latest",
                "web": "https://console.mistral.ai/api-keys", "nota": "Plan gratuito de pruebas"},
    "github": {"nombre": "GitHub Models", "url": "https://models.github.ai/inference",
               "modelo": "openai/gpt-4.1-mini", "web": "https://github.com/settings/tokens",
               "nota": "Gratis con cuenta de GitHub (token)"},
    "cohere": {"nombre": "Cohere", "url": "https://api.cohere.ai/compatibility/v1", "modelo": "command-a-03-2025",
               "web": "https://dashboard.cohere.com/api-keys", "nota": "Clave de prueba gratuita"},
    "sambanova": {"nombre": "SambaNova", "url": "https://api.sambanova.ai/v1",
                  "modelo": "Meta-Llama-3.3-70B-Instruct", "web": "https://cloud.sambanova.ai/apis",
                  "nota": "Gratis con límite"},
    "nvidia": {"nombre": "NVIDIA NIM", "url": "https://integrate.api.nvidia.com/v1",
               "modelo": "meta/llama-3.3-70b-instruct", "web": "https://build.nvidia.com",
               "nota": "Créditos gratis"},
    "ollama": {"nombre": "Ollama (en este PC)", "url": "http://127.0.0.1:11434/v1", "modelo": "llama3.2",
               "web": "https://ollama.com/download", "nota": "Sin clave ni internet; usa tu PC", "sin_clave": True},
    "personalizado": {"nombre": "Otro (compatible con OpenAI)", "url": "", "modelo": "",
                      "web": "", "nota": "Pon la URL base, p. ej. https://…/v1"},
}
TIEMPO_S = 45
RE_URL = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?(/[^\s]*)?$")   # host simple: nada de [ ni espacios
VACIO = {"clave": "", "modelo": "", "activo": True}


class ErrorIA(Exception):
    pass


_cliente = None


def _compartido() -> httpx.Client:
    global _cliente
    if _cliente is None:
        _cliente = httpx.Client(timeout=httpx.Timeout(TIEMPO_S, read=120))
    return _cliente


def catalogo() -> list:
    return [{"id": k, **{c: v for c, v in p.items()}} for k, p in PROVEEDORES.items()]


def _prov(cfg: dict, pid: str) -> dict:
    return {**VACIO, **(cfg or {}).get("proveedores", {}).get(pid, {})}


def publico(cfg: dict) -> dict:
    """La configuración para la ventana: sin las claves, solo si están puestas."""
    out = {}
    listos = {d["id"] for d in disponibles(cfg)}
    for pid in PROVEEDORES:
        p = _prov(cfg, pid)
        out[pid] = {"configurada": bool(p["clave"]), "modelo": p["modelo"], "activo": p["activo"],
                    "url": p.get("url", ""), "listo": pid in listos}
    return {"orden": orden(cfg), "proveedores": out}


def actualizar(cfg: dict, pid: str, cambios: dict) -> dict:
    """Copia nueva de cfg con los cambios de un proveedor. Clave vacía = conservar la que había."""
    if pid not in PROVEEDORES:
        raise ValueError("Proveedor desconocido.")
    p = _prov(cfg, pid)
    if cambios.get("clave"):
        p["clave"] = str(cambios["clave"]).strip()[:300]
    if cambios.get("borrar_clave"):
        p["clave"] = ""
    if "modelo" in cambios:
        p["modelo"] = str(cambios["modelo"] or "").strip()[:120]
    if "activo" in cambios:
        p["activo"] = bool(cambios["activo"])
    if pid == "personalizado" and "url" in cambios:
        url = str(cambios["url"] or "").strip().rstrip("/")
        if url and not RE_URL.match(url):
            raise ValueError("La URL debe empezar por http:// o https://")
        p["url"] = url
    provs = {**(cfg or {}).get("proveedores", {}), pid: p}
    nuevo_orden = [x for x in (cfg or {}).get("orden", []) if x in PROVEEDORES]
    if pid not in nuevo_orden:
        nuevo_orden.append(pid)
    return {**(cfg or {}), "proveedores": provs, "orden": nuevo_orden}


def con_orden(cfg: dict, nuevo: list) -> dict:
    return {**(cfg or {}), "orden": [x for x in dict.fromkeys(nuevo) if x in PROVEEDORES]}


def orden(cfg: dict) -> list:
    dado = [x for x in (cfg or {}).get("orden", []) if x in PROVEEDORES]
    return dado + [x for x in PROVEEDORES if x not in dado]


def _base(pid: str, p: dict) -> str:
    return (p.get("url") if pid == "personalizado" else PROVEEDORES[pid]["url"]) or ""


def disponibles(cfg: dict, primero: str | None = None) -> list:
    """Proveedores listos para usar (activos y con clave, o que no la necesitan), en orden."""
    ids = orden(cfg)
    if primero in ids:
        ids = [primero] + [x for x in ids if x != primero]
    out = []
    for pid in ids:
        p = _prov(cfg, pid)
        listo = p["clave"] or (PROVEEDORES[pid].get("sin_clave") and pid in (cfg or {}).get("proveedores", {}))
        if p["activo"] and listo and _base(pid, p):
            out.append({"id": pid, "url": _base(pid, p), "clave": p["clave"],
                        "modelo": p["modelo"] or PROVEEDORES[pid]["modelo"]})
    return out


def _cabeceras(d: dict) -> dict:
    h = {"Content-Type": "application/json", "User-Agent": "hypazo"}
    if d["clave"]:
        h["Authorization"] = "Bearer " + d["clave"]
    return h


_reemplazos = {}   # (proveedor, modelo caducado) -> modelo que sí existe, mientras dure la app
_descanso = {}     # proveedor -> hora hasta la que no se usa (se pasó del límite gratuito)
DESCANSO_S, DESCANSO_MAX_S = 60, 300
SATURADO = (429, 503)          # límite gratuito o proveedor saturado: que descanse
NO_CHAT = ("whisper", "guard", "safeguard", "tts", "embed", "orpheus", "audio", "image", "vision", "rerank",
           "moderation", "transcribe", "live", "computer-use", "robotics", "lyria", "genie", "banana",
           "deep-research", "aqa")
PREFERIDOS = ("gpt-oss-120b", "llama-3.3-70b", "flash-latest", "-latest", "flash", "70b", "qwen", "mistral-small", "llama", "gpt")
RE_CADUCADO = re.compile(r"model_not_found|does not exist|not found|no such model|unknown model|decommissioned|"
                         r"not supported|invalid model|no longer available|deprecated|retired", re.I)


def _candidatos(cfg, proveedor, modelo):
    lista = disponibles(cfg, proveedor)
    if not lista:
        raise ErrorIA("No hay ningún proveedor de IA listo. Añade una clave gratuita en Ajustes → Proveedores de IA.")
    if modelo and proveedor and lista[0]["id"] == proveedor:
        lista[0] = {**lista[0], "modelo": modelo}
    lista = [{**d, "modelo": _reemplazos.get((d["id"], d["modelo"]), d["modelo"])} for d in lista]
    ahora = time.time()
    libres = [d for d in lista if _descanso.get(d["id"], 0) <= ahora]
    # los que descansan, al final: si fallan todos los demás, mejor intentarlo que no contestar
    return libres + [d for d in lista if d not in libres]


def _descansar(d, r):
    try:
        espera = float(r.headers.get("retry-after") or DESCANSO_S)
    except ValueError:
        espera = DESCANSO_S
    _descanso[d["id"]] = time.time() + min(DESCANSO_MAX_S, max(DESCANSO_S, espera))


def elegir_modelo(lista: list) -> str | None:
    """De los modelos de un proveedor, uno de chat (nada de voz, imagen o filtros), el mejor conocido primero."""
    chat_ = [m for m in lista if not any(x in m.lower() for x in NO_CHAT)]
    for pref in PREFERIDOS:
        for m in chat_:
            if pref in m.lower():
                return m
    return chat_[0] if chat_ else None


def _sustituto(d, cliente):
    try:
        return elegir_modelo([m for m in _listar(d, cliente) if m != d["modelo"]])
    except ErrorIA:
        return None


def _corto(texto, clave: str = "") -> str:
    t = " ".join(str(texto).split())
    if clave:
        t = t.replace(clave, "***")          # hay proveedores que repiten la clave en el error 401
    return t[:160]


def chat(cfg: dict, mensajes: list, proveedor: str | None = None, modelo: str | None = None,
         cliente: httpx.Client | None = None, json_modo: bool = False, herramientas: list | None = None) -> dict:
    """Respuesta completa. Prueba los proveedores en orden hasta que uno conteste.
    Con herramientas, 'llamadas' trae las que pidió la IA (formato tool_calls de OpenAI)."""
    cliente = cliente or _compartido()
    errores = []
    for d in _candidatos(cfg, proveedor, modelo):
        cuerpo = {"model": d["modelo"], "messages": mensajes}
        if json_modo:
            cuerpo["response_format"] = {"type": "json_object"}
        if herramientas:
            cuerpo["tools"] = herramientas
        try:
            r = cliente.post(d["url"] + "/chat/completions", headers=_cabeceras(d), json=cuerpo)
            if r.status_code in (400, 404) and RE_CADUCADO.search(r.text) and "model" in r.text.lower():
                nuevo = _sustituto(d, cliente)          # el modelo por defecto ya no existe: otro de su lista
                if nuevo:
                    _reemplazos[(d["id"], d["modelo"])] = nuevo
                    d, cuerpo = {**d, "modelo": nuevo}, {**cuerpo, "model": nuevo}
                    r = cliente.post(d["url"] + "/chat/completions", headers=_cabeceras(d), json=cuerpo)
            if r.status_code in SATURADO:
                _descansar(d, r)
            if r.status_code != 200:
                errores.append(f"{d['id']}: {r.status_code} {_corto(r.text, d['clave'])}")
                continue
            msg = r.json()["choices"][0]["message"]
            return {"texto": msg.get("content") or "", "proveedor": d["id"], "modelo": d["modelo"],
                    "llamadas": msg.get("tool_calls") or []}
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            errores.append(f"{d['id']}: {_corto(e, d['clave'])}")
    raise ErrorIA("Ningún proveedor respondió. " + " | ".join(errores))


def _trozos(respuesta: httpx.Response):
    try:
        for linea in respuesta.iter_lines():
            if not linea.startswith("data:"):
                continue
            dato = linea[5:].strip()
            if dato == "[DONE]":
                break
            try:
                trozo = json.loads(dato)["choices"][0].get("delta", {}).get("content")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):   # p. ej. "delta": null
                continue
            if trozo:
                yield trozo
    finally:
        respuesta.close()


def abrir_stream(cfg: dict, mensajes: list, proveedor: str | None = None, modelo: str | None = None,
                 cliente: httpx.Client | None = None):
    """(proveedor, modelo, generador de trozos). El cambio de proveedor solo ocurre antes del primer trozo."""
    cliente = cliente or _compartido()
    errores = []
    for d in _candidatos(cfg, proveedor, modelo):
        try:
            req = cliente.build_request("POST", d["url"] + "/chat/completions", headers=_cabeceras(d),
                                        json={"model": d["modelo"], "messages": mensajes, "stream": True})
            r = cliente.send(req, stream=True)
            if r.status_code != 200:
                r.read()
                if r.status_code in SATURADO:
                    _descansar(d, r)
                errores.append(f"{d['id']}: {r.status_code} {_corto(r.text, d['clave'])}")
                r.close()
                continue
            return d["id"], d["modelo"], _trozos(r)
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            errores.append(f"{d['id']}: {_corto(e, d['clave'])}")
    raise ErrorIA("Ningún proveedor respondió. " + " | ".join(errores))


def modelos(cfg: dict, pid: str, cliente: httpx.Client | None = None) -> list:
    """Modelos que ofrece el proveedor con esa clave (GET /models)."""
    lista = [d for d in disponibles(cfg, pid) if d["id"] == pid]
    if not lista:
        raise ErrorIA("Pon primero la clave de ese proveedor.")
    return _listar(lista[0], cliente or _compartido())


def _listar(d: dict, cliente: httpx.Client) -> list:
    try:
        r = cliente.get(d["url"] + "/models", headers=_cabeceras(d))
        r.raise_for_status()
        datos = r.json().get("data", [])
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, AttributeError) as e:
        raise ErrorIA(f"No pude leer los modelos: {_corto(e, d['clave'])}")
    return sorted({str(m.get("id", "")).removeprefix("models/") for m in datos if isinstance(m, dict) and m.get("id")})
