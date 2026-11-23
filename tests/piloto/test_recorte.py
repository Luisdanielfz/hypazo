import json
import os

import pytest
from fastapi.testclient import TestClient

import api_recortes
import app as app_mod
import autoclip
import clipeo

CARA, JUEGO = "480:365:0:715", "1060:1080:420:0"


@pytest.fixture
def layouts(tmp_path, monkeypatch):
    ruta = tmp_path / "layouts.json"
    monkeypatch.setattr(clipeo, "LAYOUTS_JSON", str(ruta))
    monkeypatch.setattr(app_mod, "LAYOUTS_JSON", str(ruta))
    monkeypatch.setattr(clipeo, "LAYOUTS", {})
    return ruta


def test_validar_guarda_la_marca_manual_y_rechaza_recortes_minimos():
    limpio = app_mod.validar_layouts({"Ibai": {"face": CARA, "game": JUEGO, "manual": True}})
    assert limpio == {"ibai": {"face": CARA, "game": JUEGO, "manual": True}}
    assert "manual" not in app_mod.validar_layouts({"ibai": {"face": CARA, "game": JUEGO}})["ibai"]
    with pytest.raises(ValueError, match="pequeño"):
        app_mod.validar_layouts({"ibai": {"face": "8:8:0:0", "game": JUEGO}})


def test_la_calibracion_automatica_no_pisa_un_recorte_manual(layouts):
    layouts.write_text(json.dumps({"ibai": {"face": CARA, "game": JUEGO, "manual": True}}), encoding="utf-8")
    assert clipeo.guardar_layout("ibai", {"face": "1:1:1:1", "game": "2:2:2:2"}) is False
    assert json.loads(layouts.read_text(encoding="utf-8"))["ibai"]["face"] == CARA
    assert clipeo.guardar_layout("otro", {"face": CARA, "game": JUEGO}) is True


def test_vigilar_camara_con_recorte_manual_solo_avisa(monkeypatch):
    import calibrar
    monkeypatch.setattr(calibrar, "frames_de", lambda *a, **k: [object()])
    monkeypatch.setattr(calibrar, "es_anuncio", lambda img: False)
    monkeypatch.setattr(calibrar, "cara_dentro", lambda img, face: False)
    monkeypatch.setattr(autoclip, "auto_layout", lambda *a: pytest.fail("no debe recalibrar un recorte manual"))
    lay = {"face": CARA, "game": JUEGO, "manual": True}
    nuevo, msg = autoclip.vigilar_camara("ibai", "twitch", lay, lambda *a: None)
    assert nuevo is lay and "Ajustes" in msg


def test_el_cazador_recoge_el_recorte_guardado_en_caliente(layouts):
    assert autoclip.recargar_layout("ibai", 0.0) == (None, 0.0)          # sin archivo: nada
    layouts.write_text(json.dumps({"ibai": {"face": CARA, "game": JUEGO, "manual": True}}), encoding="utf-8")
    lay, marca = autoclip.recargar_layout("ibai", 0.0)
    assert lay == {"face": CARA, "game": JUEGO, "manual": True} and marca == os.path.getmtime(layouts)
    assert autoclip.recargar_layout("ibai", marca) == (None, marca)      # sin cambios: nada


def test_frame_del_directo_y_ultimo_guardado_si_no_esta_en_vivo(tmp_path, monkeypatch):
    from PIL import Image
    png = tmp_path / "f.png"
    Image.new("RGB", (1920, 1080)).save(png)
    c = TestClient(app_mod.app)
    monkeypatch.setattr(api_recortes, "_frame_en_vivo", lambda canal, plat: str(png))
    r = c.get("/api/frame", params={"canal": "ibai"})
    assert r.status_code == 200 and r.headers["x-ancho"] == "1920" and r.headers["x-alto"] == "1080"
    assert "x-viejo" not in r.headers

    def caido(canal, plat):
        raise RuntimeError("offline")
    monkeypatch.setattr(api_recortes, "_frame_en_vivo", caido)
    monkeypatch.setattr(api_recortes, "_frame_guardado", lambda canal, plat: str(png))
    r = c.get("/api/frame", params={"canal": "ibai"})
    assert r.status_code == 200 and int(r.headers["x-viejo"]) >= 0
    monkeypatch.setattr(api_recortes, "_frame_guardado", lambda canal, plat: None)
    assert c.get("/api/frame", params={"canal": "ibai"}).status_code == 404
    assert c.get("/api/frame", params={"canal": "../x"}).status_code == 400


def test_actualizar_no_borra_los_recortes_del_usuario(tmp_path, monkeypatch):
    import hypazo
    monkeypatch.setattr(hypazo, "AQUI", str(tmp_path))
    ruta = tmp_path / "layouts.json"
    ruta.write_text(json.dumps({"ibai": {"face": CARA, "game": JUEGO, "manual": True}}), encoding="utf-8")
    monkeypatch.setattr(hypazo, "herramienta", lambda n: n)

    def ejecutar(cmd, **kw):
        if "checkout" in cmd:      # la versión nueva trae sus recortes por defecto
            ruta.write_text(json.dumps({"ibai": {"face": "1:1:1:1", "game": "2:2:2:2"},
                                        "nuevo": {"face": CARA, "game": JUEGO}}), encoding="utf-8")
        return 0
    monkeypatch.setattr(hypazo, "_ejecutar", ejecutar)
    monkeypatch.setattr(hypazo.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "v9.9.9"})())
    assert hypazo.update() == 0
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["ibai"]["face"] == CARA and datos["ibai"]["manual"] is True and "nuevo" in datos


def test_recorte_que_se_sale_del_frame_se_rechaza_al_guardar():
    with pytest.raises(ValueError, match="se sale"):
        app_mod.validar_layouts({"ibai": {"face": CARA, "game": "1100:1080:900:0"}})          # 900+1100 > 1920
    with pytest.raises(ValueError, match="se sale"):
        app_mod.validar_layouts({"ibai": {"face": "480:365:900:400", "game": "720:720:0:0", "frame": "1280x720"}})
    ok = app_mod.validar_layouts({"ibai": {"face": "300:228:0:492", "game": "706:720:287:0", "frame": "1280x720"}})
    assert ok["ibai"]["frame"] == "1280x720"
    with pytest.raises(ValueError):
        app_mod.validar_layouts({"ibai": {"face": CARA, "game": JUEGO, "frame": "x"}})


def test_auto_calibrar_respeta_el_recorte_manual_aunque_empezara_sin_recorte(layouts, monkeypatch):
    import calibrar
    layouts.write_text(json.dumps({"ibai": {"face": CARA, "game": JUEGO, "manual": True}}), encoding="utf-8")
    monkeypatch.setattr(calibrar, "calibrar", lambda *a, **k: {"face": "1:1:1:1", "game": "2:2:2:2", "aviso": ""})
    lay, msg = autoclip.auto_layout("ibai", "twitch", clipeo.guardar_layout)
    assert lay["face"] == CARA and "mano" in msg


def test_recarga_en_caliente_ignora_entradas_rotas(layouts):
    layouts.write_text(json.dumps({"ibai": {"face": CARA}}), encoding="utf-8")
    assert autoclip.recargar_layout("ibai", 0.0)[0] is None


def test_frame_roto_o_error_raro_no_da_500(tmp_path, monkeypatch):
    roto = tmp_path / "roto.png"
    roto.write_bytes(b"\x89PNG medio")
    c = TestClient(app_mod.app)

    def raro(canal, plat):
        raise ValueError("cv2 se quejó")
    monkeypatch.setattr(api_recortes, "_frame_en_vivo", raro)
    monkeypatch.setattr(api_recortes, "_frame_guardado", lambda canal, plat: str(roto))
    assert c.get("/api/frame", params={"canal": "ibai"}).status_code == 404
