import json
import subprocess

import efectos
import produccion


def _video(ruta, segundos):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=1080x1920:rate=30:duration={segundos}", "-f", "lavfi", "-i",
                    f"sine=frequency=440:duration={segundos}", "-af", "volume=0.1", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(ruta)], check=True)


def _frame(ruta, t):
    from PIL import Image
    import io
    png = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", str(t), "-i", str(ruta), "-frames:v", "1",
                          "-vf", "scale=108:192", "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("L")


def _diferencia(a, b):
    from PIL import ImageChops, ImageStat
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def _pico_db(ruta, ini, dur):
    r = subprocess.run(["ffmpeg", "-nostdin", "-ss", str(ini), "-t", str(dur), "-i", str(ruta), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    return float(r.stderr.split("max_volume:")[1].split("dB")[0])


def test_zoom_y_golpe_van_al_pico():
    z = efectos.zoom(13.0, 1080, 1920)
    assert "eval=frame" in z and "crop=1080:1920" in z and f"{13.0 - efectos.ANTES:.3f}" in z
    assert efectos.golpe(13.0).endswith(f"adelay={int((13.0 - efectos.ANTES) * 1000)}|{int((13.0 - efectos.ANTES) * 1000)}")


def test_rotulo_de_contexto_en_los_subtitulos(tmp_path):
    ass = tmp_path / "s.ass"
    produccion.escribir_ass([], "TITULO", 20, str(ass), marca={}, contexto=(2.5, 5.5, "Auron intenta {duchar}"))
    texto = ass.read_text(encoding="utf-8")
    assert "Style: contexto," in texto
    assert r"Dialogue: 1,0:00:02.50,0:00:05.50,contexto,,0,0,0,,{\fad(200,300)}Auron intenta (duchar)" in texto


def test_producir_con_zoom_golpe_y_contexto(tmp_path, monkeypatch):
    _video(tmp_path / "c.mp4", 20)                       # pico = 20 - 7 = 13
    monkeypatch.setattr(produccion, "transcribir", lambda src: [])
    normal, _n, _i = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "n.mp4"))
    out, _n, info = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "e.mp4"),
                                        zoom=True, golpe=True, contexto="Prueba de contexto")
    assert info["zoom"] and info["golpe"]
    assert _diferencia(_frame(normal, 1), _frame(out, 1)) < 3          # antes del momento: igual
    assert _diferencia(_frame(normal, 13), _frame(out, 13)) > 8        # en el momento: zoom
    assert _pico_db(out, 12.1, 0.6) > _pico_db(normal, 12.1, 0.6) + 6   # el golpe se oye
    assert abs(produccion._duracion(out) - 20) < 0.3


def test_sin_pico_conocido_no_hay_zoom_ni_golpe(tmp_path, monkeypatch):
    _video(tmp_path / "c.mp4", 12)
    monkeypatch.setattr(produccion, "transcribir", lambda src: [])
    _o, _n, info = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "e.mp4"),
                                       zoom=True, golpe=True, remate=None)
    assert not info["zoom"] and not info["golpe"]


def test_la_ia_propone_tambien_el_rotulo(monkeypatch):
    import ia
    import textos_clip
    monkeypatch.setattr(ia, "chat", lambda cfg, m, **k: {"texto": json.dumps(
        {"titulos": ["A"], "hashtags": ["#a"], "contexto": "  Auron   intenta duchar a Lucía " + "x" * 80}),
        "proveedor": "groq", "modelo": "m"})
    t = textos_clip.generar({"canal": "auronplay"}, {"orden": ["groq"]})
    assert t["contexto"].startswith("Auron intenta duchar a Lucía") and len(t["contexto"]) <= textos_clip.MAX_CONTEXTO
    assert textos_clip.basico({"canal": "auronplay"})["contexto"] == ""


def test_el_golpe_no_satura_aunque_el_audio_vaya_a_tope(tmp_path, monkeypatch):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=1080x1920:rate=30:duration=12", "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                    "-af", "volume=6", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                    str(tmp_path / "c.mp4")], check=True)
    monkeypatch.setattr(produccion, "transcribir", lambda src: [])
    out, _n, _i = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "e.mp4"),
                                      golpe=True)
    assert _pico_db(out, 3.5, 1.5) <= -0.2


def test_pico_muy_al_principio_sin_zoom_ni_golpe(tmp_path, monkeypatch):
    _video(tmp_path / "c.mp4", 7.5)                       # pico = 0.5 s: no hay sitio para acercarse
    monkeypatch.setattr(produccion, "transcribir", lambda src: [])
    _o, _n, info = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "e.mp4"),
                                       zoom=True, golpe=True)
    assert not info["zoom"] and not info["golpe"]


def test_zoom_con_tamano_impar_recorta_par():
    assert "crop=1080:1918" in efectos.zoom(13.0, 1081, 1919)
