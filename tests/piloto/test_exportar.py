import os
import subprocess
import sys

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(RAIZ, "tools"))

import exportar_publico  # noqa: E402


def test_exportar_solo_lista_blanca(tmp_path):
    destino = tmp_path / "publico"
    exportar_publico.exportar(str(destino))
    nombres = set(os.listdir(destino))
    for privado in ("docs", "CLAUDE.md", "links.txt", "cc.txt", "chat_demo.txt", "chat_test.txt",
                    "proto_rubius.py", "marca.json", ".impeccable", "skills-lock.json", "hypazo_app", "salida"):
        assert privado not in nombres
    assert {"install.ps1", "hypazo.py", "README.md", "app.py", ".github", "installer"} <= nombres
    autor = subprocess.run(["git", "-C", str(destino), "log", "--format=%an <%ae>"],
                           capture_output=True, text=True).stdout.strip()
    assert autor == "Luisdanielfz <147686231+Luisdanielfz@users.noreply.github.com>"
    archivos = subprocess.run(["git", "-C", str(destino), "ls-files"], capture_output=True, text=True).stdout
    assert ".mp4" not in archivos and "__pycache__" not in archivos


def test_no_sobrescribe(tmp_path):
    (tmp_path / "ya").mkdir()
    try:
        exportar_publico.exportar(str(tmp_path / "ya"))
        assert False, "debía negarse"
    except SystemExit as e:
        assert "ya existe" in str(e)
