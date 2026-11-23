import comunidad


def _nodo(slug, vid, off, vistas, dur=30):
    return {"node": {"slug": slug, "viewCount": vistas, "videoOffsetSeconds": off, "durationSeconds": dur,
                     "video": {"id": vid} if vid else None}}


def test_clips_del_vod_filtra_por_video_quita_duplicados_y_ordena_por_vistas():
    paginas = {"LAST_DAY": [_nodo("a", "9", 100, 50), _nodo("b", "8", 200, 900)],
               "LAST_WEEK": [_nodo("a", "9", 100, 55), _nodo("c", "9", 4000, 300, dur=20), _nodo("d", None, 1, 5)],
               "LAST_MONTH": RuntimeError("failed integrity check")}

    def pedir(q, v):
        r = paginas[v["p"]]
        if isinstance(r, Exception):
            raise r
        return {"user": {"clips": {"edges": r}}}
    # el momento: unos segundos antes de que acabe el clip
    assert comunidad.clips_del_vod("auron", 9, pedir) == [(4015, 300), (125, 55)]


def test_sin_red_no_rompe_el_analisis():
    def caido(q, v):
        raise OSError("sin internet")
    assert comunidad.clips_del_vod("auron", 9, caido) == []


def test_respuesta_rara_de_twitch_no_rompe():
    assert comunidad.clips_del_vod("auron", 9, lambda q, v: {"user": None}) == []
    assert comunidad.clips_del_vod("auron", 9, lambda q, v: (_ for _ in ()).throw(KeyError("data"))) == []


def test_bono_crece_con_las_vistas_con_tope():
    assert comunidad.bono(0) == 0
    assert 8 <= comunidad.bono(10) <= 12
    assert comunidad.bono(10 ** 9) == comunidad.BONO_MAX


def test_repartir_suma_al_pico_cercano_o_crea_candidato():
    picos = [1000, 3000]
    clips = [(1010, 100), (1030, 20), (8000, 500), (8020, 7), (9000, 1)]
    extra = comunidad.repartir(picos, clips, separacion=60, max_nuevos=1)
    assert extra == {1000: 120, 8000: 507}      # 9000 no entra: solo 1 candidato nuevo


def test_vod_sube_el_momento_que_mas_clipeo_la_gente():
    import vod
    linea = [(0, 0, 1.0, 0)] * 200
    linea[50] = (60, 20, 10.0, 0)      # chat algo mejor
    linea[150] = (50, 18, 10.0, 0)     # chat algo peor, pero la gente lo clipeó mucho
    elegidos, score = vod.elegir([50, 150], linea, {}, {150: 800}, 1, 1.8, 10, 12.0)
    assert elegidos == [150] and score(150) <= 99
    assert vod.elegir([50, 150], linea, {}, {}, 1, 1.8, 10, 12.0)[0] == [50]
