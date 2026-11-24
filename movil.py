"""Conectar el móvil: la app de Android habla con este PC por wifi o por Tailscale.

- Apagado por defecto. El servidor de siempre (127.0.0.1:8765, la ventana de escritorio) no cambia.
- Encendido: un segundo servidor HTTPS en el puerto 8766, solo en las IPs de wifi y de Tailscale
  (nunca 0.0.0.0), con un certificado propio cuya huella va en el QR (el móvil solo acepta ese).
- Allí todo pide un token por móvil (se guarda solo su hash; se puede revocar) y las cosas que
  solo tienen sentido delante del PC (abrir carpetas, mini ventana, actualizar) dan 403.
"""
import asyncio
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

import hypazo

PUERTO = 8766
CADUCA_S = 300                 # el código del QR vale 5 minutos y una sola vez
MAX_FALLOS = 5                 # códigos mal tecleados seguidos: se anulan todos (fuerza bruta)
MAX_MOVILES = 10
LETRAS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"     # sin 0/O ni 1/I/L: se teclea sin dudas
# Rutas que desde el móvil no se sirven: actúan sobre Windows o son la gestión de los propios móviles.
SOLO_PC = ("/api/abrir-carpeta", "/api/abrir-salida", "/api/mini", "/mini", "/api/actualizar", "/api/movil")
LIBRES = ("/api/movil/canjear",)               # sin token: es justo donde se consigue
DEL_MOVIL = ("/api/movil/red",)                # con token, aunque estén bajo /api/movil
GALLETA = "hz"                                 # nombre de la cookie con el token
CLAVE_SCOPE = "hypazo_movil"                   # id del móvil en las peticiones que entran por el 8766

_lock = threading.Lock()
_codigos = {}                  # código -> hora en que caduca
_fallos = [0]


# ---------- dónde se guarda ----------
def _dir() -> str:
    d = os.path.join(hypazo.casa(), "config", "movil")
    os.makedirs(d, exist_ok=True)
    return d


def _leer() -> dict:
    try:
        with open(os.path.join(_dir(), "movil.json"), encoding="utf-8") as f:
            return {"activo": False, "moviles": [], **json.load(f)}
    except (OSError, ValueError):
        return {"activo": False, "moviles": []}


def _guardar(datos: dict) -> None:
    ruta = os.path.join(_dir(), "movil.json")
    with open(ruta + ".tmp", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(ruta + ".tmp", ruta)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ---------- red ----------
def ips() -> dict:
    """IPs de este PC: wifi/cable (privadas) y Tailscale (100.64.0.0/10)."""
    todas = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))          # no envía nada: solo elige la interfaz de la ruta por defecto
            todas.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        todas += socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        pass
    ts_red = ipaddress.ip_network("100.64.0.0/10")
    wifi, ts = [], []
    for ip in dict.fromkeys(todas):
        d = ipaddress.ip_address(ip)
        if d in ts_red:
            ts.append(ip)
        elif d.is_private and not d.is_loopback and not d.is_link_local:
            wifi.append(ip)
    return {"wifi": wifi, "tailscale": ts}


# ---------- certificado ----------
def certificado() -> tuple[str, str, str]:
    """(cert.pem, key.pem, huella SHA-256 en hex). Se crea la primera vez y dura 10 años."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    cert_pem, key_pem = os.path.join(_dir(), "cert.pem"), os.path.join(_dir(), "key.pem")
    if not (os.path.isfile(cert_pem) and os.path.isfile(key_pem)):
        clave = ec.generate_private_key(ec.SECP256R1())
        nombre = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Hypazo PC")])
        ahora = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(nombre).issuer_name(nombre)
                .public_key(clave.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(ahora - datetime.timedelta(days=1))
                .not_valid_after(ahora + datetime.timedelta(days=3650)).sign(clave, hashes.SHA256()))
        with open(key_pem, "wb") as f:
            f.write(clave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
        with open(cert_pem, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(cert_pem, "rb") as f:
        der = x509.load_pem_x509_certificate(f.read()).public_bytes(serialization.Encoding.DER)
    return cert_pem, key_pem, hashlib.sha256(der).hexdigest()


# ---------- emparejar y tokens ----------
def nuevo_codigo() -> str:
    codigo = "".join(secrets.choice(LETRAS) for _ in range(8))
    with _lock:
        ahora = time.time()
        for c in [c for c, t in _codigos.items() if t < ahora]:
            del _codigos[c]
        _codigos[codigo] = ahora + CADUCA_S
        _fallos[0] = 0
    return codigo


def canjear(codigo: str, nombre: str, anterior: str = "") -> dict:
    """Código del QR -> token de este móvil (solo se devuelve aquí, una vez).
    anterior: el token que tenía ese móvil, si se vuelve a emparejar; se sustituye en vez de duplicarlo."""
    codigo = codigo.strip().upper().replace("-", "").replace(" ", "")
    with _lock:
        caduca = _codigos.pop(codigo, None)
        if caduca is None or caduca < time.time():
            _fallos[0] += 1
            if _fallos[0] >= MAX_FALLOS:
                _codigos.clear()
            raise HTTPException(403, "Código no válido o caducado: genera otro QR en el PC.")
        datos = _leer()
        token = secrets.token_urlsafe(32)
        movil = {"id": secrets.token_hex(6), "nombre": nombre.strip()[:40] or "Móvil", "hash": _hash(token),
                 "creado": int(time.time()), "ultimo": 0}
        viejo = _hash(anterior) if anterior else None
        quedan = [m for m in datos["moviles"] if not (viejo and hmac.compare_digest(m["hash"], viejo))]
        datos["moviles"] = (quedan + [movil])[-MAX_MOVILES:]
        _guardar(datos)
    return {"token": token, "id": movil["id"]}


def quien(token: str) -> str | None:
    """Id del móvil dueño del token, o None. Compara en tiempo constante."""
    if not token:
        return None
    h = _hash(token)
    for m in _leer()["moviles"]:
        if hmac.compare_digest(m["hash"], h):
            return m["id"]
    return None


def _marcar_uso(mid: str) -> None:
    with _lock:
        datos = _leer()
        ahora = int(time.time())
        for m in datos["moviles"]:
            if m["id"] == mid and ahora - m.get("ultimo", 0) > 60:     # no escribir en disco a cada petición
                m["ultimo"] = ahora
                _guardar(datos)


def revocar(mid: str) -> bool:
    with _lock:
        datos = _leer()
        quedan = [m for m in datos["moviles"] if m["id"] != mid]
        _guardar({**datos, "moviles": quedan})
    return len(quedan) != len(datos["moviles"])


# ---------- la puerta del puerto 8766 ----------
class Guardia:
    """ASGI delante de la app: valida host, token y rutas, y pasa la petición como si fuera local."""

    def __init__(self, app, hosts=lambda: set(sum(ips().values(), []))):
        self.app, self.hosts = app, hosts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cab = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = cab.get("host", "").rsplit(":", 1)[0].strip("[]")
        ruta = scope["path"]
        if host not in self.hosts():
            return await _responder(send, 400, "Host no válido.")
        mid = None
        if ruta not in LIBRES:
            auth = cab.get("authorization", "")
            mid = quien(auth[7:] if auth.lower().startswith("bearer ") else _galleta(cab.get("cookie", "")))
            if mid is None:
                return await _responder(send, 401, "Este móvil no está emparejado: vuelve a escanear el QR.")
            if ruta not in DEL_MOVIL and any(ruta == p or ruta.startswith(p + "/") for p in SOLO_PC):
                return await _responder(send, 403, "Eso solo se puede hacer desde el PC.")
            _marcar_uso(mid)
        # El servidor de dentro solo acepta 127.0.0.1 (anti DNS rebinding): ya está comprobado aquí.
        headers = [(k, v) for k, v in scope["headers"] if k.lower() not in (b"host", b"authorization", b"cookie")]
        scope = {**scope, "headers": headers + [(b"host", b"127.0.0.1")], CLAVE_SCOPE: mid or "nuevo"}
        await self.app(scope, receive, send)


def _galleta(cookie: str) -> str:
    """El WebView del móvil manda el token en una cookie HttpOnly (el JS de la página no la ve)."""
    for trozo in cookie.split(";"):
        k, _, v = trozo.strip().partition("=")
        if k == GALLETA:
            return v
    return ""


async def _responder(send, codigo: int, texto: str):
    cuerpo = json.dumps({"detail": texto}, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": codigo,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(cuerpo)).encode())]})
    await send({"type": "http.response.body", "body": cuerpo})


def desde_movil(request: Request) -> bool:
    return CLAVE_SCOPE in request.scope


# ---------- el segundo servidor ----------
class Servidor:
    def __init__(self):
        self._srv, self._hilo, self.error, self.escuchando = None, None, "", []

    def encender(self, app) -> None:
        import uvicorn
        self.apagar()
        direcciones = sum(ips().values(), [])
        if not direcciones:
            self.error = "No encuentro la red: conecta el PC al wifi o abre Tailscale."
            return
        cert, clave, _ = certificado()
        socks, self.error = [], ""
        for ip in direcciones:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.bind((ip, PUERTO))
                socks.append(s)
            except OSError as e:
                s.close()
                self.error = f"No pude abrir el puerto {PUERTO} en {ip}: {e.strerror or e}"
        if not socks:
            return
        self.escuchando = [s.getsockname()[0] for s in socks]
        cfg = uvicorn.Config(Guardia(app, hosts=lambda: set(self.escuchando)), ssl_certfile=cert,
                             ssl_keyfile=clave, log_level="warning", access_log=False)
        self._srv = uvicorn.Server(cfg)
        self._srv.install_signal_handlers = lambda: None      # en un hilo: las señales son del principal
        self._hilo = threading.Thread(target=lambda: asyncio.run(self._srv.serve(sockets=socks)), daemon=True)
        self._hilo.start()

    def apagar(self) -> None:
        if self._srv:
            self._srv.should_exit = True
            self._hilo.join(5)
        self._srv, self._hilo, self.escuchando = None, None, []


servidor = Servidor()


def arrancar_si_activo(app) -> None:
    """Al abrir Hypazo: si el usuario dejó el modo móvil encendido, se vuelve a abrir."""
    if _leer()["activo"]:
        try:
            servidor.encender(app)
        except Exception as e:      # el móvil no debe impedir que abra la app de escritorio
            servidor.error = f"No pude abrir la conexión del móvil: {e}"


# ---------- API (Ajustes → Conectar el móvil) ----------
router = APIRouter()


def _solo_pc(request: Request):
    if desde_movil(request):
        raise HTTPException(403, "Eso solo se puede hacer desde el PC.")


def _vista() -> dict:
    datos = _leer()
    return {"activo": datos["activo"], "puerto": PUERTO, "ips": ips(), "escuchando": servidor.escuchando,
            "error": servidor.error,
            "moviles": [{k: m[k] for k in ("id", "nombre", "creado", "ultimo")} for m in datos["moviles"]]}


@router.get("/api/movil")
def ver(request: Request):
    _solo_pc(request)
    return _vista()


class Activar(BaseModel):
    activo: bool


@router.post("/api/movil")
def activar(a: Activar, request: Request):
    _solo_pc(request)
    with _lock:
        _guardar({**_leer(), "activo": a.activo})
    servidor.encender(request.app) if a.activo else servidor.apagar()
    return _vista()


@router.post("/api/movil/emparejar")
def emparejar(request: Request):
    _solo_pc(request)
    import urllib.parse
    import segno
    red = ips()
    if not (red["wifi"] or red["tailscale"]):
        raise HTTPException(409, "No encuentro la red: conecta el PC al wifi o abre Tailscale.")
    codigo = nuevo_codigo()
    enlace = "hypazo://emparejar?" + urllib.parse.urlencode(
        {"w": ",".join(red["wifi"]), "t": ",".join(red["tailscale"]), "p": PUERTO, "h": certificado()[2], "c": codigo})
    # viewBox sin tamaño fijo: el CSS lo escala entero (con width/height fijos se recortaba). Borde 4 = margen estándar.
    qr = segno.make(enlace, error="m").svg_inline(border=4, dark="#04050b", light="#ffffff", omitsize=True)
    huella = certificado()[2].upper()
    return {"codigo": f"{codigo[:4]}-{codigo[4:]}", "enlace": enlace, "qr": qr, "caduca_s": CADUCA_S,
            "huella": f"{huella[:4]} {huella[4:8]}"}    # para comprobarla a ojo si se empareja sin QR


@router.delete("/api/movil/moviles/{mid}")
def quitar(mid: str, request: Request):
    _solo_pc(request)
    if not revocar(mid):
        raise HTTPException(404, "Ese móvil ya no estaba emparejado.")
    return _vista()


@router.get("/api/movil/red")
def red(request: Request):
    """Las IPs de ahora: así el móvil se entera si el PC cambia de IP o se enciende Tailscale, sin reemparejar."""
    if not desde_movil(request):
        raise HTTPException(403, "Solo para la app del móvil.")
    return {**ips(), "puerto": PUERTO}


class Canje(BaseModel):
    codigo: str = Field(max_length=20)
    nombre: str = Field("", max_length=40)
    anterior: str = Field("", max_length=100)


@router.post("/api/movil/canjear")
def canjear_codigo(c: Canje, request: Request):
    if not desde_movil(request):
        raise HTTPException(403, "El código se canjea desde la app del móvil.")
    return {**canjear(c.codigo, c.nombre, c.anterior), "huella": certificado()[2]}
