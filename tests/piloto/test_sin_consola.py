import subprocess
import sys

import sin_consola


def test_anade_create_no_window_si_no_hay_flags():
    assert sin_consola.con_flags({}) == {"creationflags": subprocess.CREATE_NO_WINDOW}


def test_respeta_flags_propios():
    assert sin_consola.con_flags({"creationflags": 0x10}) == {"creationflags": 0x10 | subprocess.CREATE_NO_WINDOW}


def test_activar_aplica_a_todo_subprocess():
    # Regresión: sin consola (acceso directo), cada ffmpeg o yt-dlp abría una ventana de terminal.
    sin_consola.activar()
    sin_consola.activar()           # idempotente
    vistos = []
    original = sin_consola._Popen_init_original

    def espia(self, *a, **kw):
        vistos.append(kw.get("creationflags", 0))
        return original(self, *a, **kw)

    sin_consola._Popen_init_original = espia
    try:
        subprocess.run([sys.executable, "-c", "pass"], check=True)
    finally:
        sin_consola._Popen_init_original = original
    assert vistos and vistos[0] & subprocess.CREATE_NO_WINDOW


def test_entradas_lo_activan():
    for modulo in ("app.py", "autoclip.py", "vod.py"):
        assert "sin_consola.activar()" in open(modulo, encoding="utf-8").read(), modulo
