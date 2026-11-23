import subprocess
from types import SimpleNamespace

import clipeo


def _dimensiones(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", str(ruta)], capture_output=True, text=True)
    return r.stdout.strip()


def _video(ruta, segundos=2):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=1920x1080:rate=60:duration={segundos}", "-f", "lavfi", "-i",
                    f"sine=duration={segundos}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(ruta)], check=True)


def test_filtro_baja_a_30fps_y_difumina_a_baja_resolucion():
    # Medido en un i5-1334U: 134 s -> 54 s por clip de 45 s, con la misma imagen.
    f = clipeo.filtro_vertical("@canal")
    assert f.startswith("[0:v]fps=30,")
    assert "scale=270:480" in f and "boxblur=22" not in f


def test_codificador_usa_el_primero_que_funciona():
    probados = []

    def run(cmd, **kw):
        probados.append(cmd[cmd.index("-c:v") + 1])
        return SimpleNamespace(returncode=0 if cmd[cmd.index("-c:v") + 1] == "h264_qsv" else 1)

    assert clipeo.elegir_codificador(run) == "h264_qsv"
    assert probados[:2] == ["h264_nvenc", "h264_qsv"]


def test_codificador_sin_hardware_usa_x264():
    assert clipeo.elegir_codificador(lambda cmd, **kw: SimpleNamespace(returncode=1)) == "libx264"


def test_convertir_sigue_dando_1080x1920(tmp_path):
    _video(tmp_path / "e.ts")
    clipeo.convertir(str(tmp_path / "e.ts"), str(tmp_path / "s.mp4"), "@canal")
    assert _dimensiones(tmp_path / "s.mp4") == "1080,1920"


def test_split_sigue_dando_1080x1920(tmp_path):
    _video(tmp_path / "e.ts")
    clipeo.convertir_split(str(tmp_path / "e.ts"), str(tmp_path / "s.mp4"), "", "@canal", clipeo.LAYOUTS["auronplay"])
    assert _dimensiones(tmp_path / "s.mp4") == "1080,1920"


def test_respaldo_repite_con_x264_si_el_hardware_falla(monkeypatch):
    monkeypatch.setattr(clipeo, "_codificador", "h264_qsv")
    usados = []

    def correr(args):
        usados.append(args[1])
        if args[1] == "h264_qsv":
            raise subprocess.CalledProcessError(1, "ffmpeg")
        return "ok"
    assert clipeo.con_respaldo(correr, "5000k") == "ok"
    assert usados == ["h264_qsv", "libx264"]


def test_respaldo_sin_hardware_no_repite(monkeypatch):
    monkeypatch.setattr(clipeo, "_codificador", "libx264")
    llamadas = []

    def correr(args):
        llamadas.append(args)
        raise subprocess.CalledProcessError(1, "ffmpeg")
    try:
        clipeo.con_respaldo(correr)
    except subprocess.CalledProcessError:
        pass
    assert len(llamadas) == 1 and llamadas[0][-1] == "4000k"


def test_producir_y_cortar_usan_el_codificador_elegido(tmp_path, monkeypatch):
    import produccion
    from fastapi.testclient import TestClient
    import app as app_mod
    monkeypatch.setattr(clipeo, "_codificador", "h264_qsv")
    vistos = []
    real = subprocess.Popen

    def popen(cmd, **kw):
        if "-c:v" in cmd:
            vistos.append(cmd[cmd.index("-c:v") + 1])
        cmd = [("libx264" if x == "h264_qsv" else x) for x in cmd]   # el PC de pruebas puede no tener QSV
        return real(cmd, **kw)
    _video(tmp_path / "c.mp4")
    monkeypatch.setattr(produccion.subprocess, "Popen", popen)
    produccion.producir(str(tmp_path / "c.mp4"), titulo="T", subtitulos=False, marca={}, out=str(tmp_path / "o.mp4"))
    monkeypatch.undo()
    assert vistos == ["h264_qsv"] and (tmp_path / "o.mp4").exists()
    monkeypatch.setattr(clipeo, "_codificador", "h264_qsv")

    usados = []
    run_real = subprocess.run

    def run(cmd, **kw):
        if "-c:v" in cmd:
            usados.append(cmd[cmd.index("-c:v") + 1])
            cmd = [("libx264" if x == "h264_qsv" else x) for x in cmd]
        return run_real(cmd, **kw)
    monkeypatch.setattr(app_mod.subprocess, "run", run)
    monkeypatch.setattr(app_mod, "ruta_clip", lambda carpeta, nombre: str(tmp_path / "c.mp4"))
    monkeypatch.setattr(app_mod, "_guardar_meta", lambda ruta, meta: None)
    r = TestClient(app_mod.app).post("/api/clip/cortar", json={"carpeta": "x", "nombre": "c.mp4", "ini": 0, "fin": 1.5})
    assert r.status_code == 200 and usados == ["h264_qsv"]


def test_convertir_repite_con_x264_si_el_hardware_falla(tmp_path, monkeypatch):
    _video(tmp_path / "e.ts")
    monkeypatch.setattr(clipeo, "_codificador", "codificador_que_no_existe")
    clipeo.convertir(str(tmp_path / "e.ts"), str(tmp_path / "s.mp4"), "@canal")
    assert _dimensiones(tmp_path / "s.mp4") == "1080,1920"
