import cortes


def _frase(ini, texto, paso=0.3):
    """Palabras seguidas desde ini: [(ini, fin, palabra)]."""
    return [(ini + k * paso, ini + k * paso + 0.25, w) for k, w in enumerate(texto.split())]


def test_frases_se_cortan_en_pausas_y_puntos():
    p = _frase(0, "hola que tal.") + _frase(1.2, "vamos a ver") + _frase(5, "esto es otra")
    assert [round(t, 2) for t, _ in cortes.frases(p)] == [0, 1.2, 5]
    assert round(cortes.frases(p)[2][1], 2) == round(5 - (1.2 + 0.6 + 0.25), 2)   # pausa antes


def test_empieza_en_la_frase_tras_una_pausa_clara_lo_mas_cerca_del_pico():
    pico = 45
    p = (_frase(2, "relleno de antes de todo") + _frase(10, "otra cosa sin pausa")
         + _frase(20, "ahora empieza la historia") + _frase(27, "sigue contando") + _frase(44, "nooo"))
    assert cortes.inicio(p, pico) == 27 - cortes.MARGEN        # 18 s de contexto; 10 y 20 quedan más lejos


def test_sin_pausas_claras_busca_unos_20_s_antes_del_pico():
    pico = 45
    p = []
    t = 0.0
    while t < 50:                     # frases cada 4 s con pausas cortas
        p += _frase(t, "bla bla bla bla bla")
        t += 2.2
    ini = cortes.inicio(p, pico)
    assert 12 <= pico - ini <= 40 and abs((pico - ini) - 20) < 2.5


def test_sin_voz_o_sin_frases_en_rango_no_corta():
    assert cortes.inicio([], 45) == 0.0
    assert cortes.inicio(_frase(40, "solo al final"), 45) == 0.0


def test_tramos_con_y_sin_cold_open():
    assert cortes.tramos(52, 45, ini=0, cold_open=False) == [(0, 52)]
    assert cortes.tramos(52, 45, ini=20, cold_open=True) == [(45 - 2, 45 + 0.5), (20, 52)]
    assert cortes.tramos(10, 1, ini=0, cold_open=True) == [(0, 1.5), (0, 10)]    # pico muy al principio


def test_recolocar_palabras_en_el_video_montado():
    p = [(19.0, 19.5, "fuera"), (21.0, 21.4, "dentro"), (43.5, 44.0, "pico"), (44.8, 45.6, "corta")]
    nuevas = cortes.recolocar(p, [(43, 45.5), (20, 52)])
    assert [(round(a, 2), round(b, 2), w) for a, b, w in nuevas] == [
        (0.5, 1.0, "pico"), (3.5, 3.9, "dentro"), (26.0, 26.5, "pico"), (27.3, 28.1, "corta")]


def _video(ruta, segundos):
    import subprocess
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=1080x1920:rate=30:duration={segundos}", "-f", "lavfi", "-i",
                    f"sine=duration={segundos}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                    "-shortest", str(ruta)], check=True)


def test_producir_corta_en_la_frase_y_abre_con_el_momento(tmp_path, monkeypatch):
    import produccion
    _video(tmp_path / "c.mp4", 30)                                # pico = 30 - 7 = 23
    monkeypatch.setattr(produccion, "transcribir", lambda src: _frase(0.5, "relleno") + _frase(5, "la historia empieza aquí"))
    out, n, info = produccion.producir(str(tmp_path / "c.mp4"), titulo="T", subtitulos=False, marca={},
                                       out=str(tmp_path / "o.mp4"), ajustar=True, cold_open=True, remate=7.0)
    assert info["inicio"] == round(5 - cortes.MARGEN, 2) and info["cold_open"] is True
    esperado = (30 - info["inicio"]) + cortes.CO_ANTES + cortes.CO_DESPUES
    assert abs(produccion._duracion(out) - esperado) < 0.4


def test_producir_sin_opciones_deja_el_clip_entero(tmp_path, monkeypatch):
    import produccion
    _video(tmp_path / "c.mp4", 12)
    monkeypatch.setattr(produccion, "transcribir", lambda src: [])
    out, n, info = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "o.mp4"))
    assert info == {"inicio": 0.0, "cold_open": False} and abs(produccion._duracion(out) - 12) < 0.3


def test_ultima_palabra_que_se_pasa_unos_ms_no_se_pierde():
    assert cortes.recolocar([(9.5, 10.05, "fin")], [(0, 10)]) == [(9.5, 10.05, "fin")]


def test_recortar_a_mano_recoloca_el_pico_o_lo_olvida(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    import app as app_mod
    carpeta = tmp_path / "2026-11-23_ibai"
    carpeta.mkdir()
    _video(carpeta / "c.mp4", 30)                                   # pico en 30 - 7 = 23
    (carpeta / "c.json").write_text(json.dumps({"remate": 7.0}), encoding="utf-8")
    monkeypatch.setattr(app_mod, "SALIDA", str(tmp_path))
    c = TestClient(app_mod.app)
    r1 = c.post("/api/clip/cortar", json={"carpeta": carpeta.name, "nombre": "c.mp4", "ini": 10, "fin": 26}).json()
    r2 = c.post("/api/clip/cortar", json={"carpeta": carpeta.name, "nombre": "c.mp4", "ini": 0, "fin": 20}).json()
    assert app_mod._remate(str(carpeta / r1["nombre"])) == 3.0        # el pico sigue dentro: 26 - 23
    assert app_mod._remate(str(carpeta / r2["nombre"])) is None       # el corte acaba antes del pico


def test_sin_pico_conocido_no_corta_ni_abre_con_el_momento(tmp_path, monkeypatch):
    import produccion
    _video(tmp_path / "c.mp4", 30)
    monkeypatch.setattr(produccion, "transcribir", lambda src: _frase(5, "la historia empieza aquí"))
    _o, _n, info = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "o.mp4"),
                                       ajustar=True, cold_open=True, remate=None)
    assert info == {"inicio": 0.0, "cold_open": False}


def test_si_whisper_falla_sin_subtitulos_el_clip_sale_igual(tmp_path, monkeypatch):
    import produccion
    _video(tmp_path / "c.mp4", 12)

    def roto(src):
        raise ImportError("faster_whisper")
    monkeypatch.setattr(produccion, "transcribir", roto)
    out, _n, info = produccion.producir(str(tmp_path / "c.mp4"), subtitulos=False, marca={}, out=str(tmp_path / "o.mp4"),
                                        ajustar=True)
    assert info["inicio"] == 0.0 and abs(produccion._duracion(out) - 12) < 0.3
