import centinela

IBAI, AURON, WEST = ("ibai", "twitch"), ("auronplay", "twitch"), ("westcol", "kick")


class Falso:
    def __init__(self, favs, vivos, activo=True):
        self.favs, self.vivos, self.activo, self.corre, self.arrancados = favs, set(vivos), activo, False, []
        self.fallan = set()

    def centinela(self):
        return centinela.Centinela(corriendo=lambda: self.corre, arrancar=self.arrancar,
                                   ajustes=lambda: (self.activo, self.favs), consultar=lambda favs: (set(self.vivos), set(favs) - self.fallan))

    def arrancar(self, fav):
        self.arrancados.append(fav)
        self.corre = True


def test_arranca_el_primer_favorito_en_directo_por_orden():
    f = Falso([AURON, IBAI, WEST], {WEST, IBAI})
    c = f.centinela()
    c.vuelta()
    assert f.arrancados == [IBAI] and "ibai" in c.texto


def test_apagado_o_ya_cazando_no_hace_nada():
    f = Falso([IBAI], {IBAI}, activo=False)
    f.centinela().vuelta()
    assert f.arrancados == []
    f = Falso([IBAI], {IBAI})
    f.corre = True
    c = f.centinela()
    c.vuelta()
    assert f.arrancados == [] and "caza en marcha" in c.estado()


def test_recien_activado_no_dice_apagado():
    f = Falso([IBAI], set())
    c = f.centinela()
    assert "menos de un minuto" in c.estado()
    f.activo = False
    assert c.estado() == "Apagado."


def test_si_lo_paras_a_mano_no_lo_vuelve_a_arrancar_hasta_que_termine_su_directo():
    f = Falso([IBAI, AURON], {IBAI})
    c = f.centinela()
    c.parado_a_mano(*IBAI)
    c.vuelta()
    assert f.arrancados == [] and "ibai" in c.texto and "paraste" in c.texto
    f.vivos = {IBAI, AURON}
    c.vuelta()
    assert f.arrancados == [AURON]
    f.corre, f.vivos = False, set()      # ibai termina: queda perdonado
    c.vuelta()
    f.vivos = {IBAI}
    c.vuelta()
    assert f.arrancados == [AURON, IBAI]


def test_si_falla_al_arrancar_no_se_cae():
    f = Falso([IBAI], {IBAI})
    c = centinela.Centinela(corriendo=lambda: False, arrancar=lambda fav: 1 / 0,
                            ajustes=lambda: (True, [IBAI]), consultar=lambda favs: ({IBAI}, {IBAI}))
    c.vuelta()
    assert "No pude" in c.texto


def test_en_directo_twitch_en_una_sola_consulta_y_kick_aparte():
    consultas = []

    def pedir(q, v):
        consultas.append(v)
        return {"u0": {"stream": {"id": "1"}}, "u1": {"stream": None}, "u2": None}

    def kick(canal):
        return {"livestream": {"id": 5}} if canal == "westcol" else {"livestream": None}
    vivos, vistos = centinela.en_directo([IBAI, AURON, ("nadie", "twitch"), WEST, ("otro", "kick")], pedir, kick)
    assert vivos == {IBAI, WEST} and len(consultas) == 1 and consultas[0]["c0"] == "ibai"
    assert vistos == {IBAI, AURON, ("nadie", "twitch"), WEST, ("otro", "kick")}


def test_en_directo_sin_red_da_vacio():
    def caido(*a):
        raise OSError("sin red")
    assert centinela.en_directo([IBAI, WEST], caido, caido) == (set(), set())     # sin red: nada comprobado
    assert centinela.en_directo([IBAI], lambda q, v: {}, caido) == (set(), set())     # respuesta sin datos
    assert centinela.en_directo([IBAI], lambda q, v: {"u0": None}, caido) == (set(), {IBAI})   # canal que no existe


def _app(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_mod
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    return app_mod, TestClient(app_mod.app)


def test_se_activa_desde_preferencias_y_se_ve_en_el_estado(tmp_path, monkeypatch):
    app_mod, c = _app(tmp_path, monkeypatch)
    assert c.get("/api/preferencias").json()["centinela"] is False
    assert c.post("/api/preferencias", json={"centinela": True}).json()["centinela"] is True
    activo, favs = app_mod._ajustes_centinela()
    assert activo is True and favs == []
    assert "minuto" in c.get("/api/status").json()["centinela"]


def test_arranca_con_los_ultimos_ajustes_y_split_si_hay_recorte(tmp_path, monkeypatch):
    import hypazo
    import api_recortes
    app_mod, _ = _app(tmp_path, monkeypatch)
    hypazo.guardar_config({"ultimo_arranque": {"piso": 77, "factor": 2.5, "credito": "@otro", "raro": 1}})
    monkeypatch.setattr(api_recortes, "_leer_layouts", lambda: {"ibai": {}})
    arrancados = []
    monkeypatch.setattr(app_mod, "start", lambda a: arrancados.append(a))
    app_mod._arrancar_favorito(("ibai", "twitch"))
    app_mod._arrancar_favorito(("westcol", "kick"))
    a, b = arrancados
    assert (a.canal, a.plataforma, a.piso, a.factor, a.split, a.credito) == ("ibai", "twitch", 77, 2.5, True, "")
    assert (b.canal, b.plataforma, b.split) == ("westcol", "kick", False)


def test_parar_a_mano_avisa_al_centinela(monkeypatch):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_corriendo", lambda: True)
    monkeypatch.setattr(app_mod.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setitem(app_mod._estado, "proc", type("P", (), {"pid": 1})())
    monkeypatch.setitem(app_mod._estado, "fav", ("ibai", "twitch"))
    monkeypatch.setattr(app_mod._centinela, "saltar", set())
    app_mod.stop()
    assert ("ibai", "twitch") in app_mod._centinela.saltar


def test_si_falla_la_consulta_no_olvida_que_lo_paraste():
    f = Falso([IBAI], {IBAI})
    c = f.centinela()
    c.parado_a_mano(*IBAI)
    f.vivos, f.fallan = set(), {IBAI}        # Twitch no contesta: no sabemos si terminó
    c.vuelta()
    f.vivos, f.fallan = {IBAI}, set()
    c.vuelta()
    assert f.arrancados == []


def test_si_la_caza_muere_al_empezar_no_la_relanza_cada_minuto(monkeypatch):
    reloj = [1000.0]
    monkeypatch.setattr(centinela.time, "time", lambda: reloj[0])
    f = Falso([IBAI], {IBAI})
    c = f.centinela()
    c.vuelta()
    f.corre = False                          # se cayó enseguida
    reloj[0] += 60
    c.vuelta()
    assert f.arrancados == [IBAI] and "reintento" in c.texto
    reloj[0] += centinela.REINTENTO_S
    c.vuelta()
    assert f.arrancados == [IBAI, IBAI]


def test_si_arrancas_a_mano_mientras_consulta_no_da_error():
    estado = {"corre": False}

    def consultar(favs):
        estado["corre"] = True               # el usuario pulsó Empezar mientras tanto
        return {IBAI}, {IBAI}
    c = centinela.Centinela(corriendo=lambda: estado["corre"], arrancar=lambda f: 1 / 0,
                            ajustes=lambda: (True, [IBAI]), consultar=consultar)
    c.vuelta()
    assert "No pude" not in c.texto
