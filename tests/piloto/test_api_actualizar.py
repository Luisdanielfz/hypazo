import io

import pytest
from fastapi.testclient import TestClient

import app as app_mod
import hypazo


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setitem(app_mod._estado, "proc", None)
    monkeypatch.setattr(hypazo, "version_actual", lambda: "0.3.1")
    return TestClient(app_mod.app)


def test_version_informa_si_hay_nueva(cliente, monkeypatch):
    monkeypatch.setattr(hypazo, "ultima_version", lambda: "v0.4.0")
    monkeypatch.setattr(hypazo, "instalado", lambda: True)
    assert cliente.get("/api/version").json() == {"actual": "0.3.1", "ultima": "v0.4.0", "hay_nueva": True,
                                                  "instalado": True}


def test_version_sin_conexion(cliente, monkeypatch):
    monkeypatch.setattr(hypazo, "ultima_version", lambda: None)
    monkeypatch.setattr(hypazo, "instalado", lambda: True)
    d = cliente.get("/api/version").json()
    assert d["ultima"] is None and d["hay_nueva"] is False


def test_actualizar_fuera_de_la_instalacion_409(cliente, monkeypatch):
    # En la carpeta de desarrollo, actualizar haría checkout de etiquetas en el repo de trabajo.
    monkeypatch.setattr(hypazo, "instalado", lambda: False)
    assert cliente.post("/api/actualizar").status_code == 409


def test_actualizar_con_el_cazador_en_marcha_409(cliente, monkeypatch):
    class Proc:
        stdin = io.StringIO()

        def poll(self):
            return None
    monkeypatch.setattr(hypazo, "instalado", lambda: True)
    app_mod._estado["proc"] = Proc()
    assert cliente.post("/api/actualizar").status_code == 409


def test_actualizar_lanza_hypazo_update(cliente, monkeypatch):
    llamadas = []
    monkeypatch.setattr(hypazo, "instalado", lambda: True)
    monkeypatch.setattr(app_mod, "_lanzar_update",
                        lambda: llamadas.append("update") or (0, "Hypazo actualizado"))
    r = cliente.post("/api/actualizar")
    assert r.status_code == 200 and r.json()["ok"] is True and llamadas == ["update"]


def test_actualizar_fallido_devuelve_el_error(cliente, monkeypatch):
    monkeypatch.setattr(hypazo, "instalado", lambda: True)
    monkeypatch.setattr(app_mod, "_lanzar_update", lambda: (1, "git fetch falló"))
    r = cliente.post("/api/actualizar")
    assert r.status_code == 500 and "git fetch" in r.json()["detail"]
