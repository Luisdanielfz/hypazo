import subprocess

import pytest

import envivo


def test_sin_anuncios_todo_el_clip():
    assert envivo.tramo_sin_anuncio([False] * 9, 5, 45) == (0, 45)


def test_anuncio_al_principio_se_quita():
    # Lo visto en las pruebas: el primer clip tras empezar a cazar arrastra los anuncios de Twitch.
    assert envivo.tramo_sin_anuncio([True, True, False, False, False, False, False, False, False], 5, 45) == (10, 45)


def test_anuncio_en_medio_se_queda_el_tramo_mas_largo():
    assert envivo.tramo_sin_anuncio([False, False, True, False, False, False, False, True, False], 5, 45) == (15, 35)


def test_empate_prefiere_el_tramo_mas_reciente():
    # El momento pedido está al final del clip.
    assert envivo.tramo_sin_anuncio([False, False, True, True, False, False], 5, 30) == (20, 30)


def test_todo_anuncio_es_none():
    assert envivo.tramo_sin_anuncio([True] * 9, 5, 45) is None


def _video(ruta, segundos):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=640x360:rate=30:duration={segundos}", "-f", "lavfi", "-i", f"sine=duration={segundos}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "30", "-c:a", "aac", "-shortest", str(ruta)],
                   check=True)


def _duracion(ruta):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(ruta)],
                       capture_output=True, text=True)
    return float(r.stdout.strip())


def test_quitar_anuncios_recorta_el_trozo(tmp_path):
    trozo = tmp_path / "clip_01.ts"
    _video(trozo, 30)
    salida = envivo.quitar_anuncios(str(trozo), detector=lambda ruta, t: t < 10)   # anuncio en los 10 primeros s
    assert 18 <= _duracion(salida) <= 22


def test_quitar_anuncios_sin_anuncio_no_toca_nada(tmp_path):
    trozo = tmp_path / "clip_01.ts"
    _video(trozo, 20)
    assert envivo.quitar_anuncios(str(trozo), detector=lambda ruta, t: False) == str(trozo)


def test_casi_todo_anuncio_avisa_claro(tmp_path):
    trozo = tmp_path / "clip_01.ts"
    _video(trozo, 30)
    with pytest.raises(RuntimeError, match="anuncios"):
        envivo.quitar_anuncios(str(trozo), detector=lambda ruta, t: t < 25)


def test_el_render_quita_los_anuncios_antes_de_cortar(tmp_path, monkeypatch):
    import queue
    from types import SimpleNamespace

    import autoclip
    orden = []
    monkeypatch.setattr(autoclip, "quitar_anuncios", lambda t: orden.append("anuncios") or t)
    monkeypatch.setattr(autoclip, "recortar", lambda *a, **k: orden.append("render"))
    monkeypatch.setattr(autoclip, "guardar_meta", lambda *a, **k: orden.append("meta"))
    trozo = tmp_path / "clip_01.ts"
    trozo.write_bytes(b"x")
    a = SimpleNamespace(credito="@c", segundos=45, canal="c", plataforma="twitch")
    sesiones = SimpleNamespace(tocar=lambda *x: None)
    meta = dict(puntaje=1, unicos=1, base=1, lineas=[], motivo="manual")
    autoclip._trabajo_clip(a, 1, str(trozo), False, "", None, str(tmp_path), meta, sesiones, "s", queue.Queue())()
    assert orden == ["anuncios", "render", "meta"]
    assert not trozo.exists()
