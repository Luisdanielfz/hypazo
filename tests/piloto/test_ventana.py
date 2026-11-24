"""La ventana de Hypazo parece una app (no un navegador ni un «Script»)."""
import os
import sys
import types

import hypazo


class RegFalso:
    HKEY_CURRENT_USER, REG_SZ = "HKCU", 1

    def __init__(self):
        self.valores = {}

    def CreateKey(self, raiz, ruta):
        return (raiz, ruta)

    def SetValueEx(self, clave, nombre, _r, _tipo, valor):
        self.valores[(clave[1], nombre)] = valor

    def CloseKey(self, clave):
        pass


def test_identidad_propia_con_nombre_e_icono():
    reg, ids = RegFalso(), []
    hypazo.identidad(fijar=ids.append, reg=reg)
    clave = r"Software\Classes\AppUserModelId\Hypazo.App"
    assert ids == ["Hypazo.App"]
    assert reg.valores[(clave, "DisplayName")] == "Hypazo"
    assert reg.valores[(clave, "IconUri")].endswith(os.path.join("assets", "hypazo.ico"))


def test_identidad_que_falla_no_impide_abrir():
    def roto(*a):
        raise OSError("sin permisos")
    hypazo.identidad(fijar=roto, reg=types.SimpleNamespace(CreateKey=roto, HKEY_CURRENT_USER=0))


def test_pagina_de_espera_es_de_hypazo_y_no_sale_a_internet():
    html = hypazo.pagina_espera("http://127.0.0.1:8765")
    assert "Hypazo" in html and "Reconectando" in html and "http://127.0.0.1:8765" in html
    assert "https://" not in html and "<link" not in html and "src=\"http" not in html


class Evento:
    def __init__(self):
        self.manejadores = []

    def __iadd__(self, f):
        self.manejadores.append(f)
        return self


def test_si_no_carga_muestra_la_pagina_propia_sin_el_error_del_navegador():
    ajustes = types.SimpleNamespace(IsBuiltInErrorPageEnabled=True)
    mostrado = []
    core = types.SimpleNamespace(Settings=ajustes, NavigateToString=mostrado.append)
    wv = types.SimpleNamespace(CoreWebView2=None, CoreWebView2InitializationCompleted=Evento(),
                               NavigationCompleted=Evento())
    w = types.SimpleNamespace(native=types.SimpleNamespace(browser=types.SimpleNamespace(webview=wv)))
    assert hypazo.proteger(w, "http://127.0.0.1:8765") is True
    wv.CoreWebView2 = core
    wv.CoreWebView2InitializationCompleted.manejadores[0](wv, None)
    assert ajustes.IsBuiltInErrorPageEnabled is False
    navegar = wv.NavigationCompleted.manejadores[0]
    navegar(wv, types.SimpleNamespace(IsSuccess=True, WebErrorStatus="Unknown"))
    navegar(wv, types.SimpleNamespace(IsSuccess=False, WebErrorStatus="OperationCanceled"))   # una descarga, otra carga...
    navegar(wv, types.SimpleNamespace(IsSuccess=False, WebErrorStatus="ConnectionAborted"))
    assert mostrado == []
    navegar(wv, types.SimpleNamespace(IsSuccess=False, WebErrorStatus="CannotConnect"))       # el motor no responde
    assert len(mostrado) == 1 and "Reconectando" in mostrado[0] and "Reintentar" in mostrado[0]


def test_sin_webview2_no_se_rompe():
    assert hypazo.proteger(types.SimpleNamespace(native=None), "x") is False


def test_ventana_con_icono_fondo_oscuro_y_proteccion(monkeypatch):
    creadas, arranques = [], []
    w = types.SimpleNamespace(events=types.SimpleNamespace(shown=Evento()))
    falso = types.SimpleNamespace(create_window=lambda *a, **k: creadas.append(k) or w,
                                  start=lambda **k: arranques.append(k))
    monkeypatch.setitem(sys.modules, "webview", falso)
    monkeypatch.delitem(sys.modules, "app", raising=False)
    hypazo.ventana("http://127.0.0.1:8765")
    assert creadas[0]["background_color"] == "#04050b"
    assert arranques[0]["icon"].endswith("hypazo.ico")
    assert len(w.events.shown.manejadores) == 1


def test_la_galeria_no_falla_si_un_video_desaparece(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app as app_mod
    carpeta = tmp_path / "2026-11-24_ibai"
    carpeta.mkdir()
    for n in ("a.mp4", "b.mp4"):
        (carpeta / n).write_bytes(b"x")
    monkeypatch.setattr(app_mod, "SALIDA", str(tmp_path))
    real = os.stat

    def stat(p, *a, **k):
        if str(p).endswith("b.mp4"):
            raise FileNotFoundError(p)          # el cazador lo renombró justo ahora
        return real(p, *a, **k)
    monkeypatch.setattr(app_mod.os, "stat", stat)
    r = TestClient(app_mod.app).get("/api/clips")
    assert r.status_code == 200 and [c["nombre"] for c in r.json()[0]["clips"]] == ["a.mp4"]
