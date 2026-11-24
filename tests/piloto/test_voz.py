import numpy as np

import voz

STREAMER = np.eye(256, dtype=np.float32)[0]
JUEGO = np.eye(256, dtype=np.float32)[1]


def _palabras(*frases):
    """frases = [(ini, "texto", quién)] -> palabras [(ini, fin, texto)] y {segundo: quién} para la huella falsa."""
    out, quien = [], {}
    for ini, texto, q in frases:
        for k, w in enumerate(texto.split()):
            a = ini + k * 0.4
            out.append((a, a + 0.35, w))
        quien[ini] = q
    return out, quien


def _huella(quien):
    def h(audio, a, b):
        dueno = max(k for k in quien if k <= a + 1e-6)
        return STREAMER if quien[dueno] == "s" else JUEGO
    return h


def test_fbank_da_80_bandas_centradas():
    f = voz.fbank(np.random.default_rng(0).standard_normal(16000).astype(np.float32) * 0.1)
    assert f.shape[1] == 80 and 95 <= f.shape[0] <= 100 and abs(float(f.mean())) < 1e-3


def test_aprende_de_un_clip_limpio_y_luego_quita_otras_voces():
    # 1º clip: solo habla el streamer -> aprende su voz (sin perfil, nunca filtra a ciegas)
    solo, quien1 = _palabras((0, "hola chat qué tal estamos hoy", "s"), (5, "vamos vamos vamos vamos", "s"))
    quedan, perfil = voz.filtrar(solo, None, huella=_huella(quien1))
    assert quedan == solo and float(np.dot(perfil, STREAMER)) > 0.99
    # 2º clip: con el perfil, fuera la voz del juego
    p, quien = _palabras((0, "hola chat qué tal estamos hoy", "s"), (5, "jason dame las llaves ya mismo", "j"),
                         (10, "no me lo puedo creer de verdad", "s"))
    quedan, _ = voz.filtrar(p, None, perfil=perfil, huella=_huella(quien))
    textos = " ".join(w for _a, _b, w in quedan)
    assert "jason" not in textos and "hola" in textos and "creer" in textos


def test_con_perfil_guardado_manda_el_perfil_aunque_el_juego_hable_mas():
    p, quien = _palabras((0, "uno dos tres cuatro cinco seis siete", "j"), (5, "ocho nueve diez once doce", "j"),
                         (10, "jajaja qué bueno", "s"))
    quedan, _ = voz.filtrar(p, None, perfil=STREAMER, huella=_huella(quien))
    assert [w for _a, _b, w in quedan] == ["jajaja", "qué", "bueno"]


def test_frase_corta_sigue_a_su_vecina():
    p, quien = _palabras((0, "esto lo dice el streamer seguro", "s"), (3.2, "sí", "j"), (8, "el juego dice esto otro", "j"),
                         (14, "y vuelve el streamer a hablar aquí", "s"))
    quedan, _ = voz.filtrar(p, None, perfil=STREAMER, huella=_huella(quien))
    assert "sí" in [w for _a, _b, w in quedan]        # demasiado corta para su huella: va con la frase de al lado


def test_con_una_sola_voz_o_sin_modelo_no_toca_nada():
    p, quien = _palabras((0, "solo una frase larga del streamer", "s"))
    assert voz.filtrar(p, None, huella=_huella(quien)) == (p, None)
    assert voz.filtrar(p, None, huella=None) == (p, None)


def test_perfiles_por_streamer_se_guardan_y_mezclan(tmp_path):
    ruta = str(tmp_path / "_voces.json")
    assert voz.perfil_de(ruta, "ibai") is None
    voz.guardar_perfil(ruta, "ibai", STREAMER)
    voz.guardar_perfil(ruta, "ibai", JUEGO)          # un clip raro no borra lo aprendido: se mezcla
    p = voz.perfil_de(ruta, "ibai")
    assert float(np.dot(p, STREAMER)) > float(np.dot(p, JUEGO)) > 0


def test_producir_solo_con_la_voz_del_streamer(tmp_path, monkeypatch):
    import subprocess
    import produccion
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=1080x1920:rate=30:duration=6", "-f", "lavfi", "-i", "sine=duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(tmp_path / "c.mp4")], check=True)
    p, _ = _palabras((0.5, "hola chat", "s"), (3, "jason ven", "j"))
    monkeypatch.setattr(produccion, "transcribir", lambda src: p)
    vistos = {}

    def filtrar(palabras, audio, perfil=None):
        vistos.update(perfil=perfil, n_audio=len(audio))
        return palabras[:2], STREAMER
    monkeypatch.setattr(voz, "filtrar", filtrar)
    _o, n, info = produccion.producir(str(tmp_path / "c.mp4"), marca={}, out=str(tmp_path / "o.mp4"),
                                      solo_streamer=True, perfil=JUEGO)
    assert n == 2 and info["perfil"] is STREAMER and vistos["perfil"] is JUEGO and vistos["n_audio"] > 16000 * 5
    _o, n, info = produccion.producir(str(tmp_path / "c.mp4"), marca={}, out=str(tmp_path / "o.mp4"))
    assert n == 4 and info["perfil"] is None


def test_la_app_guarda_el_perfil_del_streamer(tmp_path, monkeypatch):
    import json
    from fastapi.testclient import TestClient
    import app as app_mod
    import produccion
    monkeypatch.setattr(app_mod, "SALIDA", str(tmp_path))
    for c in (app_mod.PARA_SUBIR, app_mod.SUBIDOS):
        (tmp_path / c).mkdir()
    carpeta = tmp_path / "2026-11-24_ibai"
    carpeta.mkdir()
    (carpeta / "a.mp4").write_bytes(b"")
    (carpeta / "a.json").write_text(json.dumps({"canal": "ibai"}), encoding="utf-8")
    pedidos = {}

    def producir(src, *a, out=None, **k):
        pedidos.update(k)
        open(out, "wb").close()
        return out, 0, {"inicio": 0.0, "cold_open": False, "zoom": False, "golpe": False, "perfil": STREAMER}
    monkeypatch.setattr(produccion, "producir", producir)
    r = TestClient(app_mod.app).post("/api/clip/producir", json={"carpeta": carpeta.name, "nombre": "a.mp4",
                                                                 "solo_streamer": True})
    assert r.status_code == 200 and "perfil" not in r.json()
    assert pedidos["solo_streamer"] is True and pedidos["perfil"] is None
    assert float(np.dot(voz.perfil_de(str(tmp_path / "_voces.json"), "ibai"), STREAMER)) > 0.99


def test_sin_perfil_y_sin_voz_dominante_no_filtra_ni_aprende():
    # el juego habla más que el streamer en el primer clip: no se sabe quién es quién
    p, quien = _palabras((0, "uno dos tres cuatro cinco seis siete", "j"), (5, "ocho nueve diez once doce", "j"),
                         (10, "jajaja qué bueno es esto", "s"))
    assert voz.filtrar(p, None, huella=_huella(quien)) == (p, None)


def test_perfil_roto_en_disco_se_rehace(tmp_path):
    ruta = tmp_path / "_voces.json"
    ruta.write_text("[1, 2, 3]", encoding="utf-8")
    voz.guardar_perfil(str(ruta), "ibai", STREAMER)
    ruta.write_text('{"ibai": [1, 2, 3]}', encoding="utf-8")         # tamaño que no es el del modelo
    voz.guardar_perfil(str(ruta), "ibai", STREAMER)
    assert float(np.dot(voz.perfil_de(str(ruta), "ibai"), STREAMER)) > 0.99
    assert voz.perfil_de(str(ruta), "otro") is None


def test_sin_modelo_no_lo_reintenta_en_cada_clip(monkeypatch):
    intentos = []

    def cargar():
        intentos.append(1)
        raise OSError("sin internet")
    monkeypatch.setattr(voz, "_cargar", cargar)
    monkeypatch.setattr(voz, "_fallo", 0.0)
    assert voz.huella_modelo() is None and voz.huella_modelo() is None
    assert len(intentos) == 1
