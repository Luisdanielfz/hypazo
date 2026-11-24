"""Conectar el móvil: token, rutas solo del PC, emparejado y que lo local no cambia."""
import json
import time

import pytest
from fastapi.testclient import TestClient

import app as app_mod
import movil


@pytest.fixture
def casa(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    monkeypatch.setattr(movil, "ips", lambda: {"wifi": ["192.168.1.5"], "tailscale": ["100.70.1.2"]})
    movil._codigos.clear()
    movil._fallos[0] = 0
    return tmp_path


@pytest.fixture
def pc(casa):
    return TestClient(app_mod.app)


@pytest.fixture
def remoto(casa):
    return TestClient(movil.Guardia(app_mod.app, hosts=lambda: {"testserver"}))


def _emparejar(pc, remoto):
    codigo = pc.post("/api/movil/emparejar").json()["codigo"]
    r = remoto.post("/api/movil/canjear", json={"codigo": codigo, "nombre": "Mi Poco"})
    assert r.status_code == 200
    return r.json()


def test_sin_token_401_y_con_token_pasa(pc, remoto):
    assert remoto.get("/api/clips").status_code == 401
    assert remoto.get("/api/clips", headers={"Authorization": "Bearer inventado"}).status_code == 401
    t = _emparejar(pc, remoto)
    r = remoto.get("/api/clips", headers={"Authorization": f"Bearer {t['token']}"})
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_token_en_cookie_tambien_vale(pc, remoto):
    t = _emparejar(pc, remoto)
    assert remoto.get("/api/clips", headers={"Cookie": f"otra=1; hz={t['token']}"}).status_code == 200
    assert remoto.get("/api/clips", headers={"Cookie": "hz=falso"}).status_code == 401


def test_el_token_no_se_guarda_en_claro(pc, remoto, casa):
    t = _emparejar(pc, remoto)
    guardado = (casa / "home" / "config" / "movil" / "movil.json").read_text(encoding="utf-8")
    assert t["token"] not in guardado
    assert t["token"] not in pc.get("/api/movil").text


def test_host_ajeno_400(casa):
    c = TestClient(movil.Guardia(app_mod.app, hosts=lambda: {"192.168.1.5"}))
    assert c.get("/api/clips").status_code == 400        # Host: testserver no es una IP del PC


def test_revocar_corta_el_acceso(pc, remoto):
    t = _emparejar(pc, remoto)
    cab = {"Authorization": f"Bearer {t['token']}"}
    assert remoto.get("/api/status", headers=cab).status_code == 200
    assert pc.delete(f"/api/movil/moviles/{t['id']}").status_code == 200
    assert remoto.get("/api/status", headers=cab).status_code == 401


@pytest.mark.parametrize("metodo,ruta", [("post", "/api/abrir-carpeta"), ("post", "/api/abrir-salida"),
                                         ("post", "/api/mini"), ("get", "/mini"), ("post", "/api/actualizar"),
                                         ("get", "/api/movil"), ("post", "/api/movil/emparejar"),
                                         ("delete", "/api/movil/moviles/x")])
def test_rutas_solo_del_pc_dan_403_desde_el_movil(pc, remoto, metodo, ruta):
    t = _emparejar(pc, remoto)
    r = getattr(remoto, metodo)(ruta, headers={"Authorization": f"Bearer {t['token']}"})
    assert r.status_code == 403


def test_desde_el_movil_no_se_tocan_claves_de_ia(pc, remoto):
    cab = {"Authorization": f"Bearer {_emparejar(pc, remoto)['token']}"}
    for cuerpo in ({"id": "groq", "clave": "gsk_x"}, {"id": "groq", "borrar_clave": True},
                   {"id": "ollama", "url": "http://evil"}):
        assert remoto.post("/api/ia/proveedor", json=cuerpo, headers=cab).status_code == 403
    assert remoto.post("/api/ia/proveedor", json={"id": "groq", "activo": False}, headers=cab).status_code == 200


def test_el_movil_puede_pedir_las_ips_de_ahora(pc, remoto):
    cab = {"Authorization": f"Bearer {_emparejar(pc, remoto)['token']}"}
    r = remoto.get("/api/movil/red", headers=cab).json()
    assert r == {"wifi": ["192.168.1.5"], "tailscale": ["100.70.1.2"], "puerto": 8766}
    assert remoto.get("/api/movil/red").status_code == 401


def test_reemparejar_sustituye_al_movil_en_vez_de_duplicarlo(pc, remoto):
    t = _emparejar(pc, remoto)
    codigo = pc.post("/api/movil/emparejar").json()["codigo"]
    r = remoto.post("/api/movil/canjear", json={"codigo": codigo, "nombre": "Mi Poco", "anterior": t["token"]}).json()
    assert [m["id"] for m in pc.get("/api/movil").json()["moviles"]] == [r["id"]]
    assert remoto.get("/api/status", headers={"Authorization": f"Bearer {t['token']}"}).status_code == 401
    codigo = pc.post("/api/movil/emparejar").json()["codigo"]          # otro móvil (sin anterior): se suma
    remoto.post("/api/movil/canjear", json={"codigo": codigo, "nombre": "Otro"})
    assert len(pc.get("/api/movil").json()["moviles"]) == 2


def test_codigo_de_un_solo_uso(pc, remoto):
    codigo = pc.post("/api/movil/emparejar").json()["codigo"]
    assert remoto.post("/api/movil/canjear", json={"codigo": codigo}).status_code == 200
    assert remoto.post("/api/movil/canjear", json={"codigo": codigo}).status_code == 403


def test_codigo_caducado(pc, remoto, monkeypatch):
    codigo = pc.post("/api/movil/emparejar").json()["codigo"]
    ahora = time.time()
    monkeypatch.setattr(movil.time, "time", lambda: ahora + movil.CADUCA_S + 1)
    assert remoto.post("/api/movil/canjear", json={"codigo": codigo}).status_code == 403


def test_muchos_fallos_anulan_los_codigos(pc, remoto):
    codigo = pc.post("/api/movil/emparejar").json()["codigo"]
    for _ in range(movil.MAX_FALLOS):
        remoto.post("/api/movil/canjear", json={"codigo": "AAAAAAAA"})
    assert remoto.post("/api/movil/canjear", json={"codigo": codigo}).status_code == 403


def test_canjear_solo_desde_el_movil(pc):
    codigo = pc.post("/api/movil/emparejar").json()["codigo"]
    assert pc.post("/api/movil/canjear", json={"codigo": codigo}).status_code == 403


def test_qr_lleva_ips_puerto_huella_y_codigo(pc):
    r = pc.post("/api/movil/emparejar").json()
    e = r["enlace"]
    assert e.startswith("hypazo://emparejar?") and "192.168.1.5" in e and "100.70.1.2" in e and "p=8766" in e
    assert r["codigo"].replace("-", "") in e and r["qr"].startswith("<svg")
    assert movil.certificado()[2] in e and len(movil.certificado()[2]) == 64


def test_el_certificado_se_crea_una_vez(casa):
    assert movil.certificado()[2] == movil.certificado()[2]


def test_apagado_por_defecto_y_local_sin_token(pc):
    v = pc.get("/api/movil").json()
    assert v["activo"] is False and v["moviles"] == [] and v["puerto"] == 8766
    assert pc.get("/api/clips").status_code == 200       # el escritorio sigue igual: sin token
    assert TestClient(app_mod.app, base_url="http://evil.com").get("/api/clips").status_code == 400


def test_activar_guarda_y_enciende(pc, monkeypatch, casa):
    llamadas = []
    monkeypatch.setattr(movil.servidor, "encender", lambda app: llamadas.append("on"))
    monkeypatch.setattr(movil.servidor, "apagar", lambda: llamadas.append("off"))
    assert pc.post("/api/movil", json={"activo": True}).json()["activo"] is True
    assert json.loads((casa / "home" / "config" / "movil" / "movil.json").read_text(encoding="utf-8"))["activo"]
    pc.post("/api/movil", json={"activo": False})
    assert llamadas == ["on", "off"]


def test_servidor_real_https_con_token(casa, monkeypatch):
    """El 8766 de verdad: TLS con el certificado propio y token obligatorio."""
    import httpx
    monkeypatch.setattr(movil, "ips", lambda: {"wifi": ["127.0.0.1"], "tailscale": []})
    monkeypatch.setattr(movil, "PUERTO", 18766)
    s = movil.Servidor()
    s.encender(app_mod.app)
    try:
        assert s.escuchando == ["127.0.0.1"], s.error
        cert = movil.certificado()[0]
        for _ in range(50):
            try:
                r = httpx.get("https://127.0.0.1:18766/api/status", verify=False, timeout=2)
                break
            except httpx.ConnectError:
                time.sleep(0.1)
        assert r.status_code == 401 and cert
    finally:
        s.apagar()
