import io

import pytest
from fastapi.testclient import TestClient

import app as app_mod


class ProcFalso:
    def __init__(self):
        self.stdin = io.StringIO()

    def poll(self):
        return None


@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setitem(app_mod._estado, "proc", None)
    monkeypatch.setitem(app_mod._estado, "pausado", False)
    return TestClient(app_mod.app)


def test_api_pausa_escribe_orden(cliente):
    proc = ProcFalso()
    app_mod._estado["proc"] = proc
    assert cliente.post("/api/pausa").status_code == 200
    assert cliente.post("/api/reanudar").status_code == 200
    assert proc.stdin.getvalue() == "pausa\nreanudar\n"


def test_api_pausa_sin_cazador_409(cliente):
    assert cliente.post("/api/pausa").status_code == 409


def test_status_refleja_pausa(cliente):
    app_mod._estado["proc"] = ProcFalso()
    cliente.post("/api/pausa")
    assert cliente.get("/api/status").json()["pausado"] is True
    cliente.post("/api/reanudar")
    assert cliente.get("/api/status").json()["pausado"] is False
