from autoclip import meta_piloto


def test_manual_es_manual():
    assert meta_piloto("manual", "abcd1234", 1000.0, 45)["origen"] == "manual"


def test_chat_y_audio_son_automatico():
    assert meta_piloto("chat", "abcd1234", 1000.0, 45)["origen"] == "automatico"
    assert meta_piloto("audio", "abcd1234", 1000.0, 45)["origen"] == "automatico"


def test_ventana_45_s():
    m = meta_piloto("chat", "abcd1234", 1000.04, 45)
    assert m == {"sesion": "abcd1234", "origen": "automatico", "tiempo_directo": 1000.0,
                 "ventana_directo": [955.0, 1000.0]}


def test_tiempo_none_sin_ventana():
    m = meta_piloto("manual", "abcd1234", None, 45)
    assert m["tiempo_directo"] is None and m["ventana_directo"] is None


def test_ventana_de_reloj_siempre():
    m = meta_piloto("manual", "abcd1234", None, 45, reloj=5000.0)
    assert m["ventana_reloj"] == [4955.0, 5000.0]


def test_latido_toca_la_sesion_cada_30_s():
    from autoclip import latido

    class S:
        tocadas = []

        def tocar(self, sid, ahora):
            self.tocadas.append(ahora)
    s = S()
    assert latido(s, "abcd1234", 100.0, 80.0) == 80.0 and s.tocadas == []
    assert latido(s, "abcd1234", 110.0, 80.0) == 110.0 and s.tocadas == [110.0]
