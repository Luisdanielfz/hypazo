import json

import pytest

from revision import Clip, Revision
from resumen import construir, guardar, texto_exacto, texto_legible, validar

SESION = {"id": "abcd1234", "canal": "auronplay", "plataforma": "twitch", "inicio": 1000.0,
          "estado_inicio": "parcial", "cortes": [{"en": 6730.0, "dura": 180.0}], "abierta": 1100.0,
          "fin": 14260.0}


def c(id, origen, t):
    return Clip(id, "2026-11-22_auronplay", id, origen, t, None if t is None else (t - 45, t))


CLIPS = [c("a1", "automatico", 2538), c("a2", "automatico", 3482), c("a3", "automatico", 4611),
         c("m1", "manual", 4625), c("m2", "manual", 9044), c("f1", "forzado", 10931)]


def estado(tmp_path, **cambios):
    r = Revision(str(tmp_path), "abcd1234")
    r.etiqueta("a1", "risa")
    r.decidir("a2", "descartar", origen="automatico")
    r.escapado_añadir(3900, "callado")
    for clip_id, valor in cambios.items():
        r.decidir(clip_id, valor, origen="forzado")
    return r.estado()


def test_forma_completa(tmp_path):
    r = construir(SESION, CLIPS, estado(tmp_path))
    assert r["formato"] == 1 and r["plataforma"] == "twitch"
    assert r["sesion"] == {"duracion": "03:41:00", "inicio": "parcial",
                           "cortes": [{"en": "01:52:10", "dura_s": 180}]}
    assert r["clips"][0] == {"tiempo": "00:42:18", "origen": "automatico", "etiqueta": "risa",
                             "estado": "conservado", "pareja": None}
    assert r["clips"][2] == {"tiempo": "01:17:05", "origen": "manual", "etiqueta": None,
                             "estado": "conservado", "pareja": {"con": "01:16:51", "regla": "automatica"}}
    assert r["clips"][3]["pareja"] == "se_escapo"
    assert r["clips"][4] == {"tiempo": "03:02:11", "origen": "forzado", "etiqueta": None,
                             "estado": "pendiente", "pareja": None}
    assert r["escapados_recordados"] == [{"tiempo": "≈ 01:05:00", "tipo": "callado"}]
    validar(r)


def test_descartados_solo_cuentan(tmp_path):
    r = construir(SESION, CLIPS, estado(tmp_path))
    assert "00:58:02" not in texto_exacto(r)
    assert r["automaticos"] == {"conservados": 2, "descartados": 1}


def test_forzado_descartado_no_aparece_ni_cuenta(tmp_path):
    r = construir(SESION, CLIPS, estado(tmp_path, f1="descartar"))
    assert [x["origen"] for x in r["clips"]].count("forzado") == 0
    assert r["automaticos"] == {"conservados": 2, "descartados": 1}


def test_pareja_corregida(tmp_path):
    rev = Revision(str(tmp_path), "abcd1234")
    rev.deshacer_pareja("m1")
    r = construir(SESION, CLIPS, rev.estado())
    assert [x["pareja"] for x in r["clips"] if x["tiempo"] == "01:17:05"] == [{"regla": "corregida"}]


def test_tiempo_desconocido(tmp_path):
    sesion = {**SESION, "inicio": None, "estado_inicio": "desconocido", "cortes": [{"en": None, "dura": 90.0}]}
    r = construir(sesion, [c("m1", "manual", None)], Revision(str(tmp_path), "abcd1234").estado())
    assert r["clips"][0]["tiempo"] == "desconocido" and r["sesion"]["duracion"] is None
    assert r["sesion"]["cortes"] == [{"en": "desconocido", "dura_s": 90}]
    validar(r)


def test_sin_rutas_fechas_canal_ni_chat(tmp_path):
    exacto = texto_exacto(construir(SESION, CLIPS, estado(tmp_path)))
    for prohibido in ("auronplay", "2026-11-22", ":\\", "/", ".mp4", "a1", "hora", "top_chat", "db"):
        assert prohibido not in exacto


def test_validar_rechaza_clave_extra(tmp_path):
    r = construir(SESION, CLIPS, estado(tmp_path))
    r["clips"][0]["canal"] = "auronplay"
    with pytest.raises(ValueError):
        validar(r)
    r2 = construir(SESION, CLIPS, estado(tmp_path))
    r2["clips"][0]["etiqueta"] = "C:\\Users\\x"
    with pytest.raises(ValueError):
        validar(r2)


def test_archivo_igual_a_texto_exacto_y_nombres(tmp_path):
    r = construir(SESION, CLIPS, estado(tmp_path))
    assert guardar(r, str(tmp_path)) == "resumen-piloto-1.json"
    assert guardar(r, str(tmp_path)) == "resumen-piloto-2.json"
    ruta = tmp_path / "_resumenes" / "resumen-piloto-1.json"
    assert ruta.read_text(encoding="utf-8") == texto_exacto(r)
    assert json.loads(ruta.read_text(encoding="utf-8")) == r


def test_legible(tmp_path):
    txt = texto_legible(construir(SESION, CLIPS, estado(tmp_path)))
    assert "automáticos: 2 conservados · 1 descartado" in txt
    assert "≈ 01:05:00  callado" in txt and "se escapó" in txt
