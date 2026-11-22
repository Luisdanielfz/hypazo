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
