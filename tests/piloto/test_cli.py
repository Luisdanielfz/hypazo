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


def test_start_con_puerto_ocupado_abre_navegador(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    abiertas = []
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        puerto = s.getsockname()[1]
        assert hypazo.start(puerto=puerto, abrir=abiertas.append, lanzar=lambda *a, **k: 1 / 0) == 0
    assert abiertas == [f"http://127.0.0.1:{puerto}"]
