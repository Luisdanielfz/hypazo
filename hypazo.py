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
import webbrowser

AQUI = os.path.dirname(os.path.abspath(__file__))
PUERTO = 8765
MODULOS = ("fastapi", "uvicorn", "cv2", "yt_dlp", "faster_whisper", "numpy", "PIL")


def casa() -> str:
    return os.environ.get("HYPAZO_HOME") or os.path.join(os.environ.get("LOCALAPPDATA", ""), "hypazo")


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


def start(puerto: int = PUERTO, abrir=webbrowser.open, lanzar=subprocess.call) -> int:
    url = f"http://127.0.0.1:{puerto}"
    if _puerto_ocupado(puerto):           # ya abierta: solo se enseña
        abrir(url)
        return 0
    cfg = config()
    os.makedirs(cfg["salida"], exist_ok=True)
    env = dict(os.environ, CLIPEO_SALIDA=cfg["salida"], PYTHONIOENCODING="utf-8")
    pm = [os.path.dirname(h) for h in (herramienta("ffmpeg"), herramienta("git")) if h]
    env["PATH"] = os.pathsep.join(pm + [env.get("PATH", "")])
    return lanzar([sys.executable, os.path.join(AQUI, "app.py")], cwd=AQUI, env=env)


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


def _ejecutar(cmd, **kw) -> int:
    print("$ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=AQUI, **kw)


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
    if _ejecutar([git, "checkout", "--force", destino]) != 0:
        return 1
    return _ejecutar([uv, "pip", "install", "--python", sys.executable, "-r", os.path.join(AQUI, "requirements.txt")])


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
