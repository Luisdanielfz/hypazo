import importlib

import clipeo


def test_salida_respeta_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("CLIPEO_SALIDA", str(tmp_path))
    try:
        assert importlib.reload(clipeo).SALIDA == str(tmp_path)
    finally:
        monkeypatch.delenv("CLIPEO_SALIDA")
        importlib.reload(clipeo)


def test_salida_por_defecto(monkeypatch):
    monkeypatch.delenv("CLIPEO_SALIDA", raising=False)
    assert importlib.reload(clipeo).SALIDA == "salida"
