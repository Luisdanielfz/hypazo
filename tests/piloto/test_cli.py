import json
import os
import socket

import hypazo


def test_version(capsys):
    assert hypazo.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == open(os.path.join(hypazo.AQUI, "VERSION")).read().strip()


def test_config_por_defecto(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    assert hypazo.config()["salida"] == str(tmp_path / "yo" / "Videos" / "Hypazo")


def test_setup_no_interactivo_guarda_config(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    assert hypazo.main(["setup", "--non-interactive"]) == 0
    datos = json.loads((tmp_path / "config" / "config.json").read_text(encoding="utf-8"))
    assert datos["salida"].endswith("Hypazo") and (tmp_path / "yo" / "Videos" / "Hypazo").is_dir()


def test_doctor_detecta_ffmpeg_ausente(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path / "vacio"))
    assert hypazo.main(["doctor"]) == 1
    salida = capsys.readouterr().out
    assert "[X] ffmpeg" in salida and "install.ps1" in salida


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_start_con_app_ya_abierta_solo_abre_ventana(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    abiertas = []
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        puerto = s.getsockname()[1]
        assert hypazo.start(puerto=puerto, abrir=abiertas.append, servir=lambda *a: 1 / 0) == 0
    assert abiertas == [f"http://127.0.0.1:{puerto}"]


def test_start_arranca_servidor_abre_ventana_y_al_cerrar_para(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    puerto, eventos, servidor = _puerto_libre(), [], socket.socket()

    def servir(p):
        servidor.bind(("127.0.0.1", p))
        servidor.listen()
        eventos.append("servidor")

    def abrir(url):
        eventos.append(("ventana", url, os.environ["CLIPEO_SALIDA"]))

    try:
        assert hypazo.start(puerto=puerto, abrir=abrir, servir=servir, parar=lambda: eventos.append("parar")) == 0
    finally:
        servidor.close()
    assert eventos == ["servidor", ("ventana", f"http://127.0.0.1:{puerto}", str(tmp_path / "yo" / "Videos" / "Hypazo")),
                       "parar"]


def test_ventana_sin_webview_usa_el_navegador(monkeypatch):
    abiertas = []
    monkeypatch.setitem(__import__("sys").modules, "webview", None)    # import webview -> ImportError
    hypazo.ventana("http://127.0.0.1:1", navegador=abiertas.append)
    assert abiertas == ["http://127.0.0.1:1"]


def test_casa_se_deduce_de_la_instalacion(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPAZO_HOME", raising=False)
    (tmp_path / "pm").mkdir()
    monkeypatch.setattr(hypazo, "AQUI", str(tmp_path / "hypazo"))
    assert hypazo.casa() == str(tmp_path)


def test_sin_consola_la_salida_va_a_un_registro(tmp_path, monkeypatch):
    # Regresión: con pythonw.exe (acceso directo) sys.stdout/sys.stderr son None y uvicorn fallaba al
    # configurar su registro: la app no abría y no decía nada.
    import sys
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    hypazo.salidas_sin_consola()
    print("hola registro")
    sys.stderr.write("error al registro\n")
    sys.stdout.flush(); sys.stderr.flush()
    texto = (tmp_path / "logs" / "hypazo.log").read_text(encoding="utf-8")
    assert "hola registro" in texto and "error al registro" in texto


def test_con_consola_no_toca_las_salidas(monkeypatch):
    import sys
    antes = sys.stdout
    hypazo.salidas_sin_consola()
    assert sys.stdout is antes
