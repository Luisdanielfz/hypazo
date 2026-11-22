from autoclip import interpretar, meta_piloto


def test_clip_normal():
    assert interpretar("clip", False) == ("manual", False)


def test_clip_en_pausa_es_forzado():
    assert interpretar("clip", True) == ("forzado", True)


def test_pausa_y_reanudar():
    assert interpretar("pausa", False) == (None, True)
    assert interpretar("reanudar", True) == (None, False)


def test_linea_vacia_es_clip():
    assert interpretar("", False) == ("manual", False)


def test_orden_desconocida_no_hace_nada():
    assert interpretar("hola", True) == (None, True)


def test_meta_forzado_revisar():
    m = meta_piloto("forzado", "abcd1234", 1000.0, 45)
    assert m["origen"] == "forzado" and m["revisar"] is True
    assert "revisar" not in meta_piloto("manual", "abcd1234", 1000.0, 45)
