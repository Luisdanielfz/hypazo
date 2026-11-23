import progreso
from produccion import pct_ffmpeg


def test_poner_y_quitar_tareas():
    progreso.limpiar()
    progreso.poner("c/a.mp4", "Transcribiendo lo que se dice")
    progreso.poner("c/a.mp4", "Montando el vídeo", 42)
    assert progreso.lista() == {"c/a.mp4": {"paso": "Montando el vídeo", "pct": 42}}
    progreso.quitar("c/a.mp4")
    assert progreso.lista() == {}


def test_pct_sale_de_las_lineas_de_ffmpeg():
    assert pct_ffmpeg("out_time_us=5000000", 10.0) == 50
    assert pct_ffmpeg("out_time_ms=12000000", 10.0) == 99      # nunca 100 antes de terminar
    assert pct_ffmpeg("frame=10", 10.0) is None
    assert pct_ffmpeg("out_time_us=N/A", 10.0) is None
    assert pct_ffmpeg("out_time_us=100", 0) is None


def test_producir_avisa_de_cada_paso(tmp_path, monkeypatch):
    import produccion
    pasos = []
    monkeypatch.setattr(produccion, "transcribir", lambda p: [])
    monkeypatch.setattr(produccion, "_duracion", lambda p: 2.0)
    src = tmp_path / "x.mp4"
    import subprocess
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=320x568:d=2",
                    "-f", "lavfi", "-i", "anullsrc", "-t", "2", "-shortest", str(src)], check=True)
    out, _n = produccion.producir(str(src), "HOLA", True, out=str(tmp_path / "o.mp4"),
                                  aviso=lambda paso, pct=None: pasos.append(paso))
    assert out.endswith("o.mp4") and pasos[0].startswith("Transcribiendo") and "Montando el vídeo" in pasos


def test_si_el_aviso_falla_ffmpeg_no_se_queda_vivo(tmp_path, monkeypatch):
    import subprocess

    import pytest

    import produccion
    vivos = []
    real = subprocess.Popen

    def popen(*a, **k):
        p = real(*a, **k)
        vivos.append(p)
        return p
    monkeypatch.setattr(produccion.subprocess, "Popen", popen)
    monkeypatch.setattr(produccion, "transcribir", lambda p: [])
    monkeypatch.setattr(produccion, "_duracion", lambda p: 2.0)
    src = tmp_path / "x.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=320x568:d=2",
                    str(src)], check=True)

    def aviso(paso, pct=None):
        if pct:
            raise RuntimeError("fallo al avisar")
    with pytest.raises(RuntimeError):
        produccion.producir(str(src), "", False, out=str(tmp_path / "o.mp4"), aviso=aviso)
    assert vivos and all(p.poll() is not None for p in vivos)
