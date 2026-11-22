import glob
import os
import subprocess
import threading

import autoclip
import envivo
from cola_render import Renderizador


def test_encargar_no_bloquea_al_cazador():
    # Regresión: el render (1-2 min) iba dentro del bucle y el cazador se quedaba ciego.
    soltar = threading.Event()
    r = Renderizador(avisar=lambda m: None)
    r.encargar("1", soltar.wait)          # un render que no termina hasta que lo soltamos
    assert r.pendientes() == 1            # encargar volvió enseguida
    soltar.set()
    assert r.esperar(5)
    assert r.pendientes() == 0


def test_renders_en_orden_y_un_fallo_no_para_la_cola():
    hechos, avisos = [], []
    r = Renderizador(avisar=avisos.append)
    r.encargar("1", lambda: hechos.append(1))
    r.encargar("2", lambda: 1 / 0)
    r.encargar("3", lambda: hechos.append(3))
    assert r.esperar(5)
    assert hechos == [1, 3]
    assert any("clip 2 fallo" in a for a in avisos)


def test_atraso_por_hueco_o_avalancha():
    # Regresión: el chat acumulado durante un render entraba de golpe y parecía un pico.
    assert autoclip.es_atraso(ahora=10.0, ultima_vuelta=7.5, n_eventos=3)        # bucle parado 2,5 s
    assert autoclip.es_atraso(ahora=10.0, ultima_vuelta=9.9, n_eventos=218)      # avalancha en una lectura
    assert not autoclip.es_atraso(ahora=10.0, ultima_vuelta=9.9, n_eventos=20)


def _segmentos(carpeta, segundos=20):
    os.makedirs(carpeta, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=640x360:rate=30:duration={segundos}", "-f", "lavfi", "-i", f"sine=duration={segundos}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac", "-shortest",
                    "-f", "segment", "-segment_time", "5", "-reset_timestamps", "1",
                    os.path.join(carpeta, "seg%03d.ts")], check=True)


def _duracion(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", ruta],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def test_instantanea_guarda_el_momento_en_su_propio_archivo(tmp_path, monkeypatch):
    monkeypatch.setattr(envivo, "BUF", str(tmp_path / "buffer"))
    _segmentos(envivo.BUF)
    a = envivo.instantanea(10, str(tmp_path / "clip_01.ts"))
    b = envivo.instantanea(5, str(tmp_path / "clip_02.ts"))
    assert a and b and a != b
    assert 8 <= _duracion(a) <= 12 and 3 <= _duracion(b) <= 7


def test_instantanea_sin_buffer_es_none(tmp_path, monkeypatch):
    monkeypatch.setattr(envivo, "BUF", str(tmp_path / "vacio"))
    os.makedirs(envivo.BUF)
    assert envivo.instantanea(10, str(tmp_path / "x.ts")) is None


def test_render_desde_instantanea(tmp_path, monkeypatch):
    monkeypatch.setattr(envivo, "BUF", str(tmp_path / "buffer"))
    monkeypatch.setattr(envivo, "es_anuncio_clip", lambda p: False)
    _segmentos(envivo.BUF)
    clip = envivo.instantanea(10, str(tmp_path / "buffer" / "clip_07.ts"))
    envivo.recortar("@canal", 10, 7, str(tmp_path / "salida"), unido=clip)
    assert glob.glob(str(tmp_path / "salida" / "envivo_07.mp4"))


def test_tras_un_paron_no_cuenta_hasta_ponerse_al_dia():
    # Regresión (directo real): tras un parón, el chat acumulado entra en varias lecturas de ~100
    # mensajes, no en una sola; contarlas daba "max 406" con un normal de 50.
    a = autoclip.Atraso()
    assert a.contar(ahora=1.0, n_eventos=5)                 # normal
    assert not a.contar(ahora=4.0, n_eventos=100)           # parón de 3 s: atrasado
    assert not a.contar(ahora=4.1, n_eventos=100)           # sigue entrando acumulado
    assert not a.contar(ahora=4.2, n_eventos=90)
    assert a.contar(ahora=4.6, n_eventos=4)                 # ya al día: vuelve a contar
    assert a.contar(ahora=5.0, n_eventos=30)
