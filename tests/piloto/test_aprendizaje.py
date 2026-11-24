import json
import random

import aprendizaje


def _clip(carpeta, nombre, **meta):
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / nombre).write_bytes(b"")
    (carpeta / (nombre[:-4] + ".json")).write_text(json.dumps(meta), encoding="utf-8")


def _meta(bueno, rnd, canal="ibai"):
    """Con gritos fuertes lo guardas; sin gritos lo descartas (con algo de ruido)."""
    grito = rnd.uniform(10, 25) if bueno else rnd.uniform(0, 12)
    return {"canal": canal, "puntaje": rnd.randint(40, 90), "normal": 10, "personas": rnd.randint(10, 40),
            "grito_db": grito, "motivo": "chat", "estado": "bueno" if bueno else "descartado"}


def test_muestras_etiqueta_y_salta_copias_manuales_y_sin_decidir(tmp_path):
    base = {"canal": "ibai", "puntaje": 50, "normal": 10, "personas": 20, "grito_db": 5, "motivo": "chat"}
    _clip(tmp_path / "2026-11-23_ibai", "a.mp4", **base, estado="bueno")
    _clip(tmp_path / "2026-11-23_ibai", "b.mp4", **base, estado="descartado")
    _clip(tmp_path / "2026-11-23_ibai", "c.mp4", **base)                                   # sin decidir
    _clip(tmp_path / "2026-11-23_ibai", "d.mp4", **{**base, "motivo": "manual"}, estado="bueno")
    _clip(tmp_path / "2026-11-23_ibai", "e_corte.mp4", **base, estado="bueno", de="a.mp4")
    _clip(tmp_path / "PARA SUBIR", "f.mp4", **base, estado="bueno", producido=True)
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "g.mp4", **base)                   # borrado = no lo quería
    _clip(tmp_path / "2026-11-23_ibai", "h.mp4", canal="ibai", estado="bueno")            # sin señales
    m = aprendizaje.muestras(str(tmp_path))
    assert sorted(y for _c, _x, y in m) == [0, 0, 1] and all(c == "ibai" for c, _x, _y in m)


def test_aprende_cuando_hay_bastantes_y_acierta_mas_que_sin_aprender():
    rnd = random.Random(1)
    muestras = [("ibai", aprendizaje.senales(_meta(b, rnd)), int(b)) for b in [True, False] * 30]
    r = aprendizaje.modelos(muestras)
    assert r["ibai"]["activo"] and r["ibai"]["acierto"] > r["ibai"]["base"]
    assert r["ibai"]["senal"] == "los gritos"
    fuerte = aprendizaje.prob(r, {"canal": "ibai", "puntaje": 60, "normal": 10, "personas": 20, "grito_db": 22})
    flojo = aprendizaje.prob(r, {"canal": "ibai", "puntaje": 60, "normal": 10, "personas": 20, "grito_db": 1})
    assert 99 >= fuerte > 70 > 30 > flojo >= 1


def test_con_pocos_o_solo_buenos_no_aprende_y_dice_cuanto_falta():
    rnd = random.Random(2)
    pocos = [("ibai", aprendizaje.senales(_meta(b, rnd)), int(b)) for b in [True, False] * 5]
    r = aprendizaje.modelos(pocos)
    assert not r["ibai"]["activo"] and r["ibai"]["falta"] == aprendizaje.MIN_TOTAL - 10
    solo_buenos = [("ibai", aprendizaje.senales(_meta(True, rnd)), 1) for _ in range(50)]
    r = aprendizaje.modelos(solo_buenos)
    assert not r["ibai"]["activo"] and r["ibai"]["falta"] == aprendizaje.MIN_POR_CLASE      # faltan descartados
    assert aprendizaje.prob(r, _meta(True, rnd)) is None


def test_un_streamer_nuevo_usa_lo_aprendido_con_todos():
    rnd = random.Random(3)
    muestras = [(c, aprendizaje.senales(_meta(b, rnd, c)), int(b)) for c in ("ibai", "auron") for b in [True, False] * 8]
    r = aprendizaje.modelos(muestras)
    assert not r["ibai"]["activo"] and r[aprendizaje.TODOS]["activo"]
    assert aprendizaje.prob(r, {"canal": "nuevo", "puntaje": 60, "normal": 10, "personas": 20, "grito_db": 22}) > 50


def test_cache_no_reentrena_si_nada_cambia(tmp_path, monkeypatch):
    rnd = random.Random(4)
    for i, b in enumerate([True, False] * 20):
        _clip(tmp_path / "2026-11-23_ibai", f"c{i}.mp4", **_meta(b, rnd))
    a = aprendizaje.Aprendizaje(lambda: str(tmp_path), cada=0)
    llamadas = []
    real = aprendizaje.modelos
    monkeypatch.setattr(aprendizaje, "modelos", lambda m: llamadas.append(1) or real(m))
    a.resumen(); a.resumen()
    assert len(llamadas) == 1


def test_en_la_papelera_un_bueno_sigue_siendo_bueno(tmp_path):
    base = {"canal": "ibai", "puntaje": 50, "normal": 10, "personas": 20, "grito_db": 5, "motivo": "chat"}
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "subido_y_limpiado.mp4", **base, estado="bueno")
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "descartado.mp4", **base, estado="descartado")
    assert sorted(y for _c, _x, y in aprendizaje.muestras(str(tmp_path))) == [0, 1]


def test_vaciar_la_papelera_no_borra_lo_aprendido(tmp_path):
    import shutil
    base = {"canal": "ibai", "puntaje": 50, "normal": 10, "personas": 20, "grito_db": 5, "motivo": "chat"}
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "x.mp4", **base)
    _clip(tmp_path / "2026-11-23_ibai", "y.mp4", **base, estado="bueno")
    antes = sorted(aprendizaje.muestras(str(tmp_path)))
    assert aprendizaje.archivar_papelera(str(tmp_path)) == 1
    shutil.rmtree(tmp_path / "_papelera")
    assert sorted(aprendizaje.muestras(str(tmp_path))) == antes


def _app(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_mod
    monkeypatch.setattr(app_mod, "SALIDA", str(tmp_path))
    monkeypatch.setattr(app_mod._aprende, "cada", 0)
    for c in (app_mod.PARA_SUBIR, app_mod.SUBIDOS):
        (tmp_path / c).mkdir(exist_ok=True)
    return app_mod, TestClient(app_mod.app)


def test_la_galeria_trae_la_probabilidad_y_ajustes_el_estado(tmp_path, monkeypatch):
    _app_mod, c = _app(tmp_path, monkeypatch)
    rnd = random.Random(5)
    for i, b in enumerate([True, False] * 20):
        _clip(tmp_path / "2026-11-23_ibai", f"c{i:02d}.mp4", **_meta(b, rnd))
    _clip(tmp_path / "2026-11-23_ibai", "nuevo.mp4", **{**_meta(True, rnd), "estado": ""})
    clips = {x["nombre"]: x for g in c.get("/api/clips").json() for x in g["clips"]}
    assert 0 <= clips["nuevo.mp4"]["prob"] <= 100
    filas = {f["canal"]: f for f in c.get("/api/aprendizaje").json()}
    assert filas["ibai"]["activo"] and filas["ibai"]["n"] == 40 and "modelo" not in filas["ibai"]


def test_sin_aprender_no_hay_probabilidad(tmp_path, monkeypatch):
    _app_mod, c = _app(tmp_path, monkeypatch)
    _clip(tmp_path / "2026-11-23_ibai", "a.mp4", canal="ibai", puntaje=50, normal=10, personas=5, grito_db=1, estado="bueno")
    clip = c.get("/api/clips").json()[0]["clips"][0]
    assert "prob" not in clip
    fila = next(f for f in c.get("/api/aprendizaje").json() if f["canal"] == "ibai")
    assert fila["falta"] == aprendizaje.MIN_TOTAL - 1 and not fila["activo"]


def test_vaciar_papelera_desde_limpieza_guarda_lo_aprendido(tmp_path, monkeypatch):
    _app_mod, c = _app(tmp_path, monkeypatch)
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "x.mp4", canal="ibai", puntaje=50, normal=10, personas=5, grito_db=1)
    assert c.post("/api/limpieza", json={"categoria": "papelera"}).status_code == 200
    assert not (tmp_path / "_papelera").exists() and len(aprendizaje.muestras(str(tmp_path))) == 1


def test_archivar_dos_veces_o_con_restos_no_cuenta_doble(tmp_path):
    base = {"canal": "ibai", "puntaje": 50, "normal": 10, "personas": 20, "grito_db": 5, "motivo": "chat"}
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "x.mp4", **base)
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "y.mp4", **base, estado="descartado")
    assert aprendizaje.archivar_papelera(str(tmp_path)) == 2
    assert len(aprendizaje.muestras(str(tmp_path))) == 2        # siguen en la papelera (no se pudo borrar): no dobles
    assert aprendizaje.archivar_papelera(str(tmp_path)) == 0     # «Vaciar» otra vez: nada nuevo
    assert len(aprendizaje.muestras(str(tmp_path))) == 2


def test_historial_antiguo_de_tres_campos_se_sigue_leyendo(tmp_path):
    (tmp_path / aprendizaje.HISTORIAL).write_text('["ibai", [1, 2, 0.5, 0], 0]\nroto\n', encoding="utf-8")
    assert aprendizaje.muestras(str(tmp_path)) == [("ibai", (1.0, 2.0, 0.5, 0.0), 0)]


def test_streamer_con_datos_que_no_aprende_no_toma_el_general():
    rnd = random.Random(6)
    ruido = [("ibai", (rnd.random(), rnd.random(), rnd.random(), 0.0), i % 2) for i in range(40)]
    otros = [("auron", aprendizaje.senales(_meta(b, rnd, "auron")), int(b)) for b in [True, False] * 30]
    r = aprendizaje.modelos(ruido + otros)
    assert not r["ibai"]["activo"] and r["ibai"]["falta"] == 0
    assert aprendizaje.prob(r, {"canal": "ibai", "puntaje": 60, "normal": 10, "personas": 20, "grito_db": 22}) is None


def test_producir_marca_el_original_como_bueno(tmp_path, monkeypatch):
    app_mod, c = _app(tmp_path, monkeypatch)
    import produccion
    _clip(tmp_path / "2026-11-23_ibai", "a.mp4", canal="ibai", puntaje=50, normal=10, personas=5, grito_db=1)
    monkeypatch.setattr(produccion, "producir", lambda src, *a, out=None, **k: (open(out, "wb").close(), out)[1:] + (0, {"inicio": 0.0, "cold_open": False}))
    assert c.post("/api/clip/producir", json={"carpeta": "2026-11-23_ibai", "nombre": "a.mp4"}).status_code == 200
    assert app_mod._meta(str(tmp_path / "2026-11-23_ibai" / "a.mp4"))["estado"] == "bueno"


def test_limpiar_originales_subidos_los_guarda_como_buenos(tmp_path, monkeypatch):
    app_mod, c = _app(tmp_path, monkeypatch)
    _clip(tmp_path / "2026-11-23_ibai", "a.mp4", canal="ibai", puntaje=50, normal=10, personas=5, grito_db=1)
    _clip(tmp_path / "SUBIDOS", "A - TITULO.mp4", producido=True, de="a.mp4", origen="2026-11-23_ibai")
    assert c.post("/api/limpieza", json={"categoria": "originales_subidos"}).json()["n"] == 1
    assert [y for _c, _x, y in aprendizaje.muestras(str(tmp_path))] == [1]


def test_si_no_se_puede_guardar_lo_aprendido_no_se_vacia(tmp_path, monkeypatch):
    app_mod, c = _app(tmp_path, monkeypatch)
    _clip(tmp_path / "_papelera" / "2026-11-23_ibai", "x.mp4", canal="ibai", puntaje=50, normal=10, personas=5, grito_db=1)

    def roto(salida):
        raise OSError("disco lleno")
    monkeypatch.setattr(aprendizaje, "archivar_papelera", roto)
    assert c.post("/api/limpieza", json={"categoria": "papelera"}).status_code == 503
    assert (tmp_path / "_papelera").exists()
