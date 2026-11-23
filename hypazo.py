"""Comando `hypazo`: abrir la app, configurar, revisar la instalación y actualizar.

Lo instala install.ps1 (o el .exe) como %LOCALAPPDATA%\\hypazo\\bin\\hypazo.cmd.
Uso: hypazo [start] | setup [--non-interactive] | doctor | update [--channel stable|main] | version
"""
import argparse
import glob
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

AQUI = os.path.dirname(os.path.abspath(__file__))
PUERTO = 8765
MODULOS = ("fastapi", "uvicorn", "cv2", "yt_dlp", "faster_whisper", "numpy", "PIL", "webview", "pystray")


def casa() -> str:
    """<home> de la instalación. El acceso directo lanza Python sin pasar por hypazo.cmd (sin HYPAZO_HOME):
    entonces se deduce de dónde está el código (<home>/hypazo), si al lado está la carpeta pm."""
    if os.environ.get("HYPAZO_HOME"):
        return os.environ["HYPAZO_HOME"]
    arriba = os.path.dirname(AQUI)
    if os.path.isdir(os.path.join(arriba, "pm")):
        return arriba
    return os.path.join(os.environ.get("LOCALAPPDATA", ""), "hypazo")


def _ruta_config() -> str:
    return os.path.join(casa(), "config", "config.json")


def config() -> dict:
    por_defecto = {"salida": os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Videos", "Hypazo"),
                   "credito": ""}
    try:
        with open(_ruta_config(), encoding="utf-8") as f:
            return {**por_defecto, **json.load(f)}
    except (OSError, ValueError):
        return por_defecto


def guardar_config(datos: dict) -> None:
    os.makedirs(os.path.dirname(_ruta_config()), exist_ok=True)
    tmp = _ruta_config() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _ruta_config())


def herramienta(nombre: str) -> str | None:
    """Binario de <home>\\pm (lo que descargó el instalador) o, si no, del PATH."""
    for patron in (f"pm/{nombre}/*/{nombre}.exe", f"pm/*/*/bin/{nombre}.exe", f"pm/*/*/cmd/{nombre}.exe"):
        hallado = sorted(glob.glob(os.path.join(casa(), patron)))
        if hallado:
            return hallado[-1]
    return shutil.which(nombre)


def _puerto_ocupado(puerto: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", puerto)) == 0


ESPERA_SERVIDOR_S = 30


def salidas_sin_consola() -> None:
    """Con pythonw.exe (el acceso directo) no hay consola: sys.stdout y sys.stderr son None y cualquier
    print o el registro de uvicorn rompen la app sin avisar. Se mandan a <home>/logs/hypazo.log."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    carpeta = os.path.join(casa(), "logs")
    os.makedirs(carpeta, exist_ok=True)
    registro = open(os.path.join(carpeta, "hypazo.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stdout or registro
    sys.stderr = sys.stderr or registro


def ventana(url: str, navegador=webbrowser.open) -> None:
    """Ventana nativa de Windows (WebView2, el motor de Edge) con la interfaz de Hypazo.
    Se bloquea hasta que el usuario la cierra. Sin pywebview o sin WebView2, abre el navegador."""
    bandeja = None
    try:
        import webview
        w = webview.create_window("Hypazo", url, width=1280, height=860, min_size=(900, 600))
        bandeja = _bandeja(w)
        app = sys.modules.get("app")
        if app is not None:
            app.abrir_mini = _abridor_mini(webview, url)
        webview.start()
    except Exception:              # pywebview ausente o WebView2 no disponible: que la app siga usable
        navegador(url)
    finally:
        if bandeja:
            bandeja.quitar()


def _abridor_mini(webview, url: str):
    """Función que abre la mini ventana (siempre encima) o la trae al frente si ya está abierta."""
    abierta, lock = {}, threading.Lock()

    def abrir():
        with lock:                  # dos clics seguidos no abren dos mini ventanas
            v = abierta.get("v")
            if v is not None:
                v.show()
                v.restore()
                return
            v = webview.create_window("Hypazo mini", url.rstrip("/") + "/mini", width=360, height=210,
                                      on_top=True, resizable=False)
            v.events.closed += lambda: abierta.pop("v", None)
            abierta["v"] = v
    return abrir


def _bandeja(w):
    """Icono junto al reloj, solo en el proceso que sirve la app (si no, habría uno por ventana)."""
    app = sys.modules.get("app")
    if app is None:
        return None
    try:
        from bandeja import RUTA_ICO, Bandeja, al_cerrar
        saliendo = []

        def salir():
            saliendo.append(1)
            w.destroy()
        b = Bandeja({"abrir": lambda: (w.show(), w.restore()), "clip": app._seguro(app.clip_ya),
                     "pausa": app._seguro(app._alternar_pausa), "salir": salir}, RUTA_ICO)
    except Exception:              # sin pystray o sin bandeja: la app sigue, sin icono ni avisos
        return None
    app.avisador = b.avisar
    w.events.closing += lambda: True if saliendo else al_cerrar(app._corriendo, w.hide, b.avisar)
    return b


def _servir(puerto: int) -> None:
    import uvicorn
    import app                     # después de fijar CLIPEO_SALIDA: app.py la lee al importarse
    uvicorn.run(app.app, host="127.0.0.1", port=puerto, log_level="warning")


def _parar_cazador() -> None:
    try:
        import app
        app.stop()                 # un cazador en marcha no debe quedar huérfano al cerrar la ventana
    except Exception:
        pass


def start(puerto: int = PUERTO, abrir=ventana, servir=_servir, parar=_parar_cazador) -> int:
    url = f"http://127.0.0.1:{puerto}"
    if _puerto_ocupado(puerto):           # ya abierta: otra ventana sobre el mismo servidor
        abrir(url)
        return 0
    cfg = config()
    os.makedirs(cfg["salida"], exist_ok=True)
    os.environ["CLIPEO_SALIDA"] = cfg["salida"]
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    pm = [os.path.dirname(h) for h in (herramienta("ffmpeg"), herramienta("git")) if h]
    os.environ["PATH"] = os.pathsep.join(pm + [os.environ.get("PATH", "")])   # ffmpeg/yt-dlp del cazador
    if AQUI not in sys.path:
        sys.path.insert(0, AQUI)
    os.chdir(AQUI)                        # autoclip y compañía usan rutas relativas al código
    threading.Thread(target=servir, args=(puerto,), daemon=True).start()
    fin = time.monotonic() + ESPERA_SERVIDOR_S
    while not _puerto_ocupado(puerto):
        if time.monotonic() > fin:
            print("La app no arrancó a tiempo: ejecuta `hypazo doctor` para ver qué falla.")
            return 1
        time.sleep(0.1)
    try:
        abrir(url)
    finally:
        parar()
    return 0


def setup(interactivo: bool = True) -> int:
    cfg = config()
    if interactivo:
        print("Configuración de Hypazo (Enter = dejar como está)")
        cfg["salida"] = input(f"  Carpeta de clips [{cfg['salida']}]: ").strip() or cfg["salida"]
        cfg["credito"] = input(f"  Crédito por defecto (vacío = enlace al canal) [{cfg['credito']}]: ").strip() \
            or cfg["credito"]
    os.makedirs(cfg["salida"], exist_ok=True)
    guardar_config(cfg)
    print(f"Listo. Los clips se guardan en {cfg['salida']}")
    return 0


def doctor() -> list[tuple[str, bool, str]]:
    arreglo = "vuelve a ejecutar el instalador: iex (irm https://raw.githubusercontent.com/Luisdanielfz/hypazo/main/install.ps1)"
    filas = [(n, herramienta(n) is not None, arreglo) for n in ("uv", "git", "ffmpeg", "ffprobe")]
    for m in MODULOS:
        filas.append((f"python: {m}", importlib.util.find_spec(m) is not None, "ejecuta: hypazo update"))
    salida = config()["salida"]
    try:
        os.makedirs(salida, exist_ok=True)
        prueba = os.path.join(salida, ".hypazo-prueba")
        open(prueba, "w").close()
        os.remove(prueba)
        filas.append((f"carpeta de clips ({salida})", True, ""))
    except OSError:
        filas.append((f"carpeta de clips ({salida})", False, "elige otra con: hypazo setup"))
    filas.append((f"puerto {PUERTO}", True, "en uso: la app ya está abierta" if _puerto_ocupado(PUERTO) else "libre"))
    return filas


RELEASES = "https://api.github.com/repos/Luisdanielfz/hypazo/releases/latest"


def version_actual() -> str:
    with open(os.path.join(AQUI, "VERSION"), encoding="utf-8") as f:
        return f.read().strip()


def ultima_version(abrir=None) -> str | None:
    """Etiqueta de la última versión publicada en GitHub (p. ej. 'v0.4.0'), o None sin conexión."""
    import urllib.request
    abrir = abrir or (lambda url, timeout: urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "hypazo"}), timeout=timeout))
    try:
        with abrir(RELEASES, timeout=8) as r:
            return json.load(r).get("tag_name")
    except (OSError, ValueError):
        return None


def _numeros(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split(".") if x.isdigit())


def hay_nueva(actual: str, ultima: str | None) -> bool:
    return bool(ultima) and _numeros(ultima) > _numeros(actual)


def instalado() -> bool:
    """¿Es la app instalada (el código vive en <home>/hypazo)? En la carpeta de desarrollo, actualizar
    haría checkout de etiquetas en el repo de trabajo: no se permite."""
    c = os.path.realpath(casa())
    return os.path.isdir(os.path.join(c, "pm")) and os.path.realpath(AQUI).startswith(c + os.sep)


def _ejecutar(cmd, **kw) -> int:
    print("$ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=AQUI, **kw)


def _leer_recortes() -> dict | None:
    try:
        with open(os.path.join(AQUI, "layouts.json"), encoding="utf-8-sig") as f:
            datos = json.load(f)
        return datos if isinstance(datos, dict) else None
    except (OSError, ValueError):
        return None


def _restaurar_recortes(guardados: dict | None) -> None:
    """Tras el checkout: los recortes del usuario ganan a los que trae la versión nueva (que añade los suyos)."""
    if not guardados:
        return
    ruta = os.path.join(AQUI, "layouts.json")
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({**(_leer_recortes() or {}), **guardados}, f, indent=2)
    os.replace(tmp, ruta)


def update(canal: str = "stable") -> int:
    git, uv = herramienta("git"), herramienta("uv")
    if not git or not uv:
        print("Falta git o uv: vuelve a ejecutar el instalador.")
        return 1
    if _ejecutar([git, "fetch", "--tags", "--force", "origin"]) != 0:
        return 1
    destino = "origin/main"
    if canal == "stable":
        etiquetas = subprocess.run([git, "tag", "--list", "v*", "--sort=-v:refname"], cwd=AQUI,
                                   capture_output=True, text=True).stdout.split()
        destino = etiquetas[0] if etiquetas else "origin/main"
    recortes = _leer_recortes()          # checkout --force pisaría los recortes ajustados por el usuario
    ok = _ejecutar([git, "checkout", "--force", destino]) == 0
    _restaurar_recortes(recortes)
    if not ok:
        return 1
    # python.exe y no pythonw.exe: uv pregunta cosas al intérprete y pythonw no devuelve nada.
    python = os.path.join(os.path.dirname(sys.executable), "python.exe") if sys.platform == "win32" else sys.executable
    if _ejecutar([uv, "pip", "install", "--python", python, "-r", os.path.join(AQUI, "requirements.txt")]) != 0:
        return 1
    # Rehace los accesos directos (p. ej. al pasar de la consola a la ventana nativa en 0.2.0).
    return _ejecutar(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                      os.path.join(AQUI, "install.ps1"), "-Stage", "complete"], env=dict(os.environ, HYPAZO_HOME=casa()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hypazo", description="Hypazo: clips de directos de Twitch y Kick")
    sub = ap.add_subparsers(dest="orden")
    sub.add_parser("start", help="abrir la app (por defecto)")
    s = sub.add_parser("setup", help="configuración guiada")
    s.add_argument("--non-interactive", action="store_true")
    sub.add_parser("doctor", help="revisar la instalación")
    u = sub.add_parser("update", help="actualizar a la última versión")
    u.add_argument("--channel", choices=("stable", "main"), default=os.environ.get("HYPAZO_INSTALL_CHANNEL", "stable"))
    sub.add_parser("version")
    salidas_sin_consola()
    a = ap.parse_args(argv)

    if a.orden == "version":
        with open(os.path.join(AQUI, "VERSION"), encoding="utf-8") as f:
            print(f.read().strip())
        return 0
    if a.orden == "setup":
        return setup(interactivo=not a.non_interactive)
    if a.orden == "doctor":
        filas = doctor()
        for nombre, ok, nota in filas:
            print(f"[{'OK' if ok else 'X'}] {nombre}" + ("" if ok else f"  ->  {nota}"))
        return 0 if all(ok for _, ok, _ in filas) else 1
    if a.orden == "update":
        return update(a.channel)
    return start()


if __name__ == "__main__":
    sys.exit(main())
