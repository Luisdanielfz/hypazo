import json
import os

import pytest

from revision import Clip, Revision, clips_de, emparejar


def poner_clip(salida, carpeta, nombre, sesion="abcd1234", origen="automatico", t=1000.0, mp4=True):
    d = salida / carpeta
    d.mkdir(parents=True, exist_ok=True)
    if mp4:
        (d / f"{nombre}.mp4").write_bytes(b"x")
    meta = {"sesion": sesion, "origen": origen, "tiempo_directo": t, "hora": "12:00:00",
            "ventana_directo": None if t is None else [t - 45, t]}
    (d / f"{nombre}.json").write_text(json.dumps(meta), encoding="utf-8")
    return f"{carpeta}/{nombre}"


def clip(id, origen, t):
    return Clip(id, "c", id, origen, t, None if t is None else (t - 45, t))


def test_solapamiento_empareja():
    a, m = clip("a", "automatico", 1000), clip("m", "manual", 1015)
    assert emparejar([a, m], set(), set()) == {"m": ("a", 30.0)}


def test_sin_solape_no_empareja():
    assert emparejar([clip("a", "automatico", 1000), clip("m", "manual", 1100)], set(), set()) == {}


def test_elige_mayor_solape():
    clips = [clip("a1", "automatico", 1000), clip("a2", "automatico", 1030), clip("m", "manual", 1035)]
    assert emparejar(clips, set(), set())["m"][0] == "a2"


def test_automatico_solo_una_vez():
    clips = [clip("a", "automatico", 1000), clip("m1", "manual", 1005), clip("m2", "manual", 1010)]
    assert list(emparejar(clips, set(), set()).values()).count(("a", 40.0)) + \
        list(emparejar(clips, set(), set()).values()).count(("a", 35.0)) == 1


def test_descartado_y_deshecho_no_emparejan():
    a, m = clip("a", "automatico", 1000), clip("m", "manual", 1015)
    assert emparejar([a, m], set(), {"a"}) == {}
    assert emparejar([a, m], {"m"}, set()) == {}


def test_sin_tiempo_no_empareja():
    assert emparejar([clip("a", "automatico", 1000), clip("m", "manual", None)], set(), set()) == {}


def test_deshacer_persiste_entre_instancias(tmp_path):
    Revision(str(tmp_path), "abcd1234").deshacer_pareja("c/m")
    assert Revision(str(tmp_path), "abcd1234").estado()["deshechos"] == ["c/m"]
    r = Revision(str(tmp_path), "abcd1234")
    r.rehacer_pareja("c/m")
    assert r.estado()["deshechos"] == []


def test_etiqueta_valida_e_invalida(tmp_path):
    r = Revision(str(tmp_path), "abcd1234")
    r.etiqueta("c/a", "risa")
    assert r.estado()["etiquetas"] == {"c/a": "risa"}
    r.etiqueta("c/a", None)
    assert r.estado()["etiquetas"] == {}
    with pytest.raises(ValueError):
        r.etiqueta("c/a", "epico")


def test_decisiones(tmp_path):
    r = Revision(str(tmp_path), "abcd1234")
    r.decidir("c/a", "descartar", origen="automatico")
    r.decidir("c/f", "aprobar", origen="forzado")
    with pytest.raises(ValueError):
        r.decidir("c/a", "aprobar", origen="automatico")
    assert r.decision("c/a", "automatico") == "descartar"
    assert r.decision("c/f", "forzado") == "aprobar"
    assert r.decision("c/otro", "forzado") == "pendiente"
    assert r.decision("c/otro", "manual") == "conservar"


def test_escapados(tmp_path):
    r = Revision(str(tmp_path), "abcd1234")
    r.escapado_añadir(3900, "callado")
    r.escapado_añadir(60, "risa")
    r.escapado_quitar(0)
    assert r.estado()["escapados"] == [{"t_s": 60, "tipo": "risa"}]
    with pytest.raises(ValueError):
        r.escapado_añadir(-5, "risa")


def test_descartar_no_toca_archivos(tmp_path):
    poner_clip(tmp_path, "2026-11-22_auron", "envivo_01")
    antes = sorted(os.listdir(tmp_path / "2026-11-22_auron"))
    Revision(str(tmp_path), "abcd1234").decidir("2026-11-22_auron/envivo_01", "descartar", origen="automatico")
    assert sorted(os.listdir(tmp_path / "2026-11-22_auron")) == antes


def test_estado_corrupto(tmp_path):
    (tmp_path / "_revision").mkdir()
    (tmp_path / "_revision" / "abcd1234.json").write_text("{", encoding="utf-8")
    r = Revision(str(tmp_path), "abcd1234")
    assert r.aviso and r.estado()["etiquetas"] == {}
    assert (tmp_path / "_revision" / "abcd1234.json.roto").exists()


def test_json_sin_mp4_se_ignora_y_filtra_por_sesion(tmp_path):
    poner_clip(tmp_path, "c", "envivo_01", t=2000)
    poner_clip(tmp_path, "c", "envivo_02", mp4=False)
    poner_clip(tmp_path, "c", "envivo_03", sesion="otra0000")
    poner_clip(tmp_path, "c", "envivo_04", t=None)
    poner_clip(tmp_path, "c", "envivo_05", t=1000)
    poner_clip(tmp_path, "_papelera", "envivo_06")
    assert [c.id for c in clips_de(str(tmp_path), "abcd1234")] == ["c/envivo_05", "c/envivo_01", "c/envivo_04"]


@pytest.mark.parametrize("roto", ['{"etiquetas": []}', '{"decisiones": {"c/a": "zzz"}}',
                                  '{"escapados": [{"x": 1}]}', '{"deshechos": 5}', '[]'])
def test_estado_con_forma_mala_es_roto(tmp_path, roto):
    (tmp_path / "_revision").mkdir()
    (tmp_path / "_revision" / "abcd1234.json").write_text(roto, encoding="utf-8")
    r = Revision(str(tmp_path), "abcd1234")
    assert r.aviso and r.estado() == {"etiquetas": {}, "decisiones": {}, "deshechos": [], "escapados": []}


def test_ventana_de_reloj_empareja_sin_hora_de_inicio(tmp_path):
    for nombre, origen, reloj in (("a", "automatico", 5000.0), ("m", "manual", 5010.0)):
        d = tmp_path / "c"
        d.mkdir(exist_ok=True)
        (d / f"{nombre}.mp4").write_bytes(b"x")
        meta = {"sesion": "abcd1234", "origen": origen, "tiempo_directo": None, "ventana_directo": None,
                "ventana_reloj": [reloj - 45, reloj]}
        (d / f"{nombre}.json").write_text(json.dumps(meta), encoding="utf-8")
    clips = clips_de(str(tmp_path), "abcd1234")
    assert emparejar(clips, set(), set()) == {"c/m": ("c/a", 35.0)}
