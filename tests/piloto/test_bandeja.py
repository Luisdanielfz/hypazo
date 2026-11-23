from bandeja import Bandeja, al_cerrar


class IconoFalso:
    def __init__(self):
        self.avisos = []

    def notify(self, texto, titulo):
        self.avisos.append((titulo, texto))


def test_menu_tiene_las_cuatro_acciones_y_abrir_por_defecto():
    hechos, menus = [], []
    acciones = {k: (lambda k=k: hechos.append(k)) for k in ("abrir", "clip", "pausa", "salir")}
    b = Bandeja(acciones, "no.ico", crear=lambda ico, menu: menus.append(menu) or IconoFalso())
    menu = menus[0]
    assert [t for t, _f, _d in menu][0] == "Abrir Hypazo" and menu[0][2] is True
    for _t, f, _d in menu:
        f()
    assert hechos == ["abrir", "clip", "pausa", "salir"]
    b.avisar("Clip listo", "Clip 3")
    assert b._icono.avisos == [("Clip listo", "Clip 3")]


def test_cerrar_sin_cazar_cierra():
    assert al_cerrar(lambda: False, lambda: 1 / 0, lambda *a: 1 / 0) is True


def test_cerrar_cazando_esconde_y_avisa():
    hechos = []
    assert al_cerrar(lambda: True, lambda: hechos.append("esconder"),
                     lambda t, x: hechos.append(t)) is False
    assert hechos == ["esconder", "Hypazo sigue cazando"]


def test_hypazo_conecta_la_bandeja_a_la_app_y_al_cierre(monkeypatch):
    import sys
    import types

    import bandeja
    import hypazo
    app = types.SimpleNamespace(_seguro=lambda f: f, clip_ya=lambda: None, _alternar_pausa=lambda: None,
                                _corriendo=lambda: True, avisador=None)
    monkeypatch.setitem(sys.modules, "app", app)

    class BFalsa:
        def __init__(self, acciones, ico):
            self.acciones, self.avisos = acciones, []

        def avisar(self, t, x):
            self.avisos.append(t)

    class Ventana:
        def __init__(self):
            self.cerrar, self.hechos = [], []
            self.events = types.SimpleNamespace(closing=self)

        def __iadd__(self, f):
            self.cerrar.append(f)
            return self

        def hide(self):
            self.hechos.append("hide")

        def destroy(self):
            self.hechos.append("destroy")
    monkeypatch.setattr(bandeja, "Bandeja", BFalsa)
    w = Ventana()
    b = hypazo._bandeja(w)
    assert app.avisador == b.avisar
    assert w.cerrar[0]() is False and w.hechos == ["hide"]        # cazando: se esconde
    b.acciones["salir"]()
    assert w.cerrar[0]() is True and "destroy" in w.hechos         # Salir sí cierra


def test_sin_app_cargada_no_hay_bandeja(monkeypatch):
    import sys

    import hypazo
    monkeypatch.delitem(sys.modules, "app", raising=False)
    assert hypazo._bandeja(object()) is None


def test_mini_ventana_se_crea_una_vez_y_se_reabre():
    import hypazo
    creadas = []

    class V:
        def __init__(self):
            self.mostrada, self.events = 0, types.SimpleNamespace(closed=Evento())

        def show(self):
            self.mostrada += 1

        def restore(self):
            pass

    class Evento(list):
        def __iadd__(self, f):
            self.append(f)
            return self

    import types
    wv = types.SimpleNamespace(create_window=lambda titulo, url, **kw: creadas.append((url, kw)) or V())
    abrir = hypazo._abridor_mini(wv, "http://127.0.0.1:8765/")
    abrir()
    abrir()
    assert len(creadas) == 1 and creadas[0][0] == "http://127.0.0.1:8765/mini" and creadas[0][1]["on_top"] is True
