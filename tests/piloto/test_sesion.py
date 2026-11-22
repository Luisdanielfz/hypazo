import itertools
import os

from sesion import Sesiones


def nuevas(tmp_path):
    ids = (f"{i:08x}" for i in itertools.count(1))
    return Sesiones(str(tmp_path), nuevo_id=lambda: next(ids))


def test_primera_sesion(tmp_path):
    s = nuevas(tmp_path)
    sid = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=1010.0)
    d = s.datos(sid)
    assert d["estado_inicio"] == "completo" and d["cortes"] == [] and d["canal"] == "auronplay"
    assert s.tiempo(sid, 1100.0) == 100.0


def test_arranque_tardio_es_parcial(tmp_path):
    s = nuevas(tmp_path)
    sid = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=1090.0)
    assert s.datos(sid)["estado_inicio"] == "parcial"


def test_sin_inicio_es_desconocido_y_tiempo_none(tmp_path):
    s = nuevas(tmp_path)
    sid = s.abrir("westcol", "kick", inicio=None, ahora=1000.0)
    assert s.datos(sid)["estado_inicio"] == "desconocido"
    assert s.tiempo(sid, 1100.0) is None


def test_rearranque_en_599_s_misma_sesion_con_corte(tmp_path):
    s = nuevas(tmp_path)
    a = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=1010.0)
    s.cerrar(a, 2000.0)
    b = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=2599.0)
    assert a == b
    assert s.datos(a)["cortes"] == [{"en": 1000.0, "dura": 599.0}]


def test_rearranque_en_600_s_sesion_nueva(tmp_path):
    s = nuevas(tmp_path)
    a = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=1010.0)
    s.cerrar(a, 2000.0)
    assert s.abrir("auronplay", "twitch", inicio=1000.0, ahora=2600.0) != a


def test_otro_canal_sesion_nueva(tmp_path):
    s = nuevas(tmp_path)
    a = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=1010.0)
    s.tocar(a, 1100.0)
    assert s.abrir("auronplay", "kick", inicio=1000.0, ahora=1150.0) != a


def test_tocar_guarda_fin_sin_cerrar(tmp_path):
    s = nuevas(tmp_path)
    a = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=1010.0)
    s.tocar(a, 1500.0)
    assert nuevas(tmp_path).abrir("auronplay", "twitch", inicio=1000.0, ahora=1700.0) == a


def test_persiste_y_es_atomico(tmp_path):
    s = nuevas(tmp_path)
    a = s.abrir("auronplay", "twitch", inicio=1000.0, ahora=1010.0)
    carpeta = tmp_path / "_sesiones"
    assert (carpeta / f"{a}.json").exists()
    assert not [f for f in os.listdir(carpeta) if f.endswith(".tmp")]
    assert [x["id"] for x in nuevas(tmp_path).lista()] == [a]
