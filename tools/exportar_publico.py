"""Crea el repositorio PÚBLICO y limpio de Hypazo: solo la lista blanca, sin historial, con email noreply.

Uso: python tools/exportar_publico.py <carpeta_destino>
El destino no debe existir (no se sobrescribe nada). No sube nada: el push es aparte.
"""
import os
import shutil
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AUTOR = "Luisdanielfz"
EMAIL = "147686231+Luisdanielfz@users.noreply.github.com"

LISTA_BLANCA = [
    "app.py", "app.html", "audio.py", "autoclip.py", "calibrar.py", "clipeo.py", "codigos.py", "credito.py",
    "envivo.py", "kick.py", "produccion.py", "resumen.py", "revision.py", "sesion.py", "vod.py", "hypazo.py",
    "sin_consola.py", "cola_render.py",
    "test_app.py", "layouts.json", "requirements.txt", "VERSION", "Clipeo.bat", "install.ps1", "README.md",
    "assets", "tests/piloto", "installer", ".github", "tools/exportar_publico.py",
]
GITIGNORE = """# Clips, segmentos y datos de uso: nunca al repositorio
salida/
buffer/
*.mp4
*.ts
*.jpg
codigos_detectados.txt
marca.json
__pycache__/
.venv/
dist/
"""


def exportar(destino: str) -> None:
    if os.path.exists(destino):
        raise SystemExit(f"{destino} ya existe: elige otra carpeta (no sobrescribo nada).")
    os.makedirs(destino)
    for rel in LISTA_BLANCA:
        origen = os.path.join(RAIZ, rel)
        meta = os.path.join(destino, rel)
        if os.path.isdir(origen):
            shutil.copytree(origen, meta, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            os.makedirs(os.path.dirname(meta), exist_ok=True)
            shutil.copy2(origen, meta)
    with open(os.path.join(destino, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(GITIGNORE)
    with open(os.path.join(destino, ".gitattributes"), "w", encoding="utf-8") as f:
        f.write("*.ps1 text eol=crlf\n*.iss text eol=crlf\n*.cmd text eol=crlf\n*.bat text eol=crlf\n")
    git = ["git", "-C", destino]
    subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
    subprocess.run(git + ["config", "user.name", AUTOR], check=True)
    subprocess.run(git + ["config", "user.email", EMAIL], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    with open(os.path.join(RAIZ, "VERSION"), encoding="utf-8") as f:
        version = f.read().strip()
    subprocess.run(git + ["commit", "-q", "-m", f"Hypazo {version}"], check=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    exportar(os.path.abspath(sys.argv[1]))
    print(f"Repositorio limpio creado en {sys.argv[1]}")
