from autoclip import linea_medida
from serie_chat import SerieChat


def test_linea_medida_lleva_puntaje_normal_y_umbral():
    assert linea_medida(57, 20.04, 40, 1.8) == "[medida] 57 20.0 40.0"
    assert linea_medida(90, 30.0, 40, 1.8) == "[medida] 90 30.0 54.0"     # umbral = max(piso, normal × factor)


def test_serie_lee_medidas_y_las_aparta_del_registro():
    s = SerieChat()
    assert s.leer("[medida] 57 20.0 40.0", ahora=100.0) is True
    assert s.leer("   [estado] chat normal ~20/3s", ahora=101.0) is False
    assert s.datos() == {"puntos": [[100.0, 57, 20.0, 40.0]], "marcas": []}


def test_cada_clip_deja_una_marca():
    s = SerieChat()
    assert s.leer("   Clip 3 en cola de render (1 pendientes). Sigo cazando.", ahora=50.0) is False
    assert s.datos()["marcas"] == [50.0]


def test_serie_limitada_y_se_limpia():
    s = SerieChat()
    for i in range(SerieChat.MAXIMO + 10):
        s.leer(f"[medida] {i} 1.0 2.0", ahora=float(i))
    assert len(s.datos()["puntos"]) == SerieChat.MAXIMO and s.datos()["puntos"][-1][1] == SerieChat.MAXIMO + 9
    s.limpiar()
    assert s.datos() == {"puntos": [], "marcas": []}


def test_medida_rota_no_rompe():
    s = SerieChat()
    assert s.leer("[medida] x y z", ahora=1.0) is True and s.datos()["puntos"] == []
