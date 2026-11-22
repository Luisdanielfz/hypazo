import json

import pytest
from fastapi.testclient import TestClient

import app as app_mod
from sesion import Sesiones

SID = "abcd1234"


def poner_clip(salida, nombre, origen, t):
    d = salida / "2026-11-22_auronplay"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{nombre}.mp4").write_bytes(b"x")
    meta = {"sesion": SID, "origen": origen, "tiempo_directo": t, "ventana_directo": [t - 45, t],
            "hora": "12:00:00", "top_chat": ["hola"]}
    (d / f"{nombre}.json").write_text(json.dumps(meta), encoding="utf-8")


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "SALIDA", str(tmp_path))
    Sesiones(str(tmp_path), nuevo_id=lambda: SID).abrir("auronplay", "twitch", 1000.0, 1010.0)
    poner_clip(tmp_path, "envivo_01", "automatico", 4611)
    poner_clip(tmp_path, "envivo_02", "manual", 4625)
    poner_clip(tmp_path, "envivo_03", "forzado", 9000)
    return TestClient(app_mod.app)


def test_id_invalido_404(cliente):
    for malo in ("..", "abc", "x" * 40, "ABCD1234", "00000000"):
        assert cliente.get(f"/api/revision/sesion/{malo}").status_code == 404
    assert cliente.get("/api/revision/sesion/..%2F..%2Fapp").status_code == 404


def test_sesion_no_expone_rutas(cliente, tmp_path):
    r = cliente.get(f"/api/revision/sesion/{SID}")
    assert r.status_code == 200
    texto = r.text
    assert str(tmp_path).replace("\\", "\\\\") not in texto and "C:\\\\" not in texto
    d = r.json()
    assert [c["url"] for c in d["clips"]][0] == "/salida/2026-11-22_auronplay/envivo_01.mp4"
    assert d["parejas"] == {"2026-11-22_auronplay/envivo_02": {"con": "2026-11-22_auronplay/envivo_01", "solape": 31.0}}


def test_lista_sesiones(cliente):
    d = cliente.get("/api/revision/sesiones").json()
    assert d[0]["id"] == SID and d[0]["n_clips"] == 3


def test_post_etiqueta_persiste(cliente):
    clip = "2026-11-22_auronplay/envivo_01"
    assert cliente.post(f"/api/revision/sesion/{SID}", json={"accion": "etiqueta", "clip": clip, "valor": "risa"}).status_code == 200
    assert cliente.get(f"/api/revision/sesion/{SID}").json()["estado"]["etiquetas"] == {clip: "risa"}


def test_accion_invalida_400(cliente):
    url = f"/api/revision/sesion/{SID}"
    assert cliente.post(url, json={"accion": "borrar", "clip": "x"}).status_code in (400, 422)
    assert cliente.post(url, json={"accion": "etiqueta", "clip": "2026-11-22_auronplay/envivo_01", "valor": "epico"}).status_code == 400
    assert cliente.post(url, json={"accion": "etiqueta", "clip": "otra/cosa", "valor": "risa"}).status_code == 400


def test_forzado_aprobar(cliente):
    url = f"/api/revision/sesion/{SID}"
    clip = "2026-11-22_auronplay/envivo_03"
    assert cliente.post(url, json={"accion": "decidir", "clip": clip, "valor": "aprobar"}).status_code == 200
    assert cliente.post(url, json={"accion": "decidir", "clip": "2026-11-22_auronplay/envivo_01", "valor": "aprobar"}).status_code == 400
    assert '"aprobado"' in cliente.get(f"/api/revision/resumen/{SID}").json()["exacto"]


def test_resumen_guardar_devuelve_solo_nombre(cliente, tmp_path):
    r = cliente.get(f"/api/revision/resumen/{SID}").json()
    assert "auronplay" not in r["exacto"] and "top_chat" not in r["exacto"]
    g = cliente.post(f"/api/revision/resumen/{SID}/guardar").json()
    assert g == {"guardado": "resumen-piloto-1.json"}
    assert (tmp_path / "_resumenes" / "resumen-piloto-1.json").read_text(encoding="utf-8") == r["exacto"]


def test_endpoints_existentes_siguen(cliente):
    assert cliente.get("/api/status").status_code == 200
    assert cliente.get("/api/clips").status_code == 200
