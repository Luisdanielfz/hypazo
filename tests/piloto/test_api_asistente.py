import json

import pytest
from fastapi.testclient import TestClient

import app as app_mod
import ia


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPAZO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "yo"))
    return TestClient(app_mod.app)


def test_primer_uso_y_favoritos_se_guardan(cliente):
    p = cliente.get("/api/preferencias").json()
    assert p["bienvenida_vista"] is False and p["favoritos"] == [] and len(p["catalogo"]) >= 8
    r = cliente.post("/api/preferencias", json={"bienvenida_vista": True, "favoritos": [
        {"canal": "Ibai", "plataforma": "twitch"}, {"canal": "ibai", "plataforma": "twitch"},
        {"canal": "westcol", "plataforma": "kick"}]}).json()
    assert r["bienvenida_vista"] is True
    assert r["favoritos"] == [{"canal": "ibai", "plataforma": "twitch"}, {"canal": "westcol", "plataforma": "kick"}]
    assert cliente.get("/api/preferencias").json()["favoritos"] == r["favoritos"]


def test_favorito_invalido_400(cliente):
    assert cliente.post("/api/preferencias", json={"favoritos": [{"canal": "../x"}]}).status_code == 400


def test_la_clave_se_guarda_pero_nunca_se_devuelve(cliente, tmp_path):
    r = cliente.post("/api/ia/proveedor", json={"id": "groq", "clave": "gsk_super_secreta"})
    assert r.status_code == 200 and "gsk_super_secreta" not in r.text
    assert r.json()["ia"]["proveedores"]["groq"]["configurada"] is True
    guardada = json.loads((tmp_path / "home" / "config" / "config.json").read_text(encoding="utf-8"))
    assert guardada["ia"]["proveedores"]["groq"]["clave"] == "gsk_super_secreta"
    assert "gsk_super_secreta" not in cliente.get("/api/preferencias").text


def test_proveedor_desconocido_400(cliente):
    assert cliente.post("/api/ia/proveedor", json={"id": "nope"}).status_code == 400


def test_chat_sin_proveedores_502_con_explicacion(cliente):
    r = cliente.post("/api/ia/chat", json={"mensajes": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 502 and "Ajustes" in r.json()["detail"]


def test_chat_transmite_la_respuesta(cliente, monkeypatch):
    vistos = {}

    def abrir(cfg, mensajes, proveedor, modelo):
        vistos.update(sistema=mensajes[0]["role"], proveedor=proveedor)
        return "groq", "llama", iter(["Ho", "la"])
    monkeypatch.setattr(ia, "abrir_stream", abrir)
    r = cliente.post("/api/ia/chat", json={"mensajes": [{"role": "user", "content": "hola"}]})
    assert r.text == "Hola" and r.headers["x-proveedor"] == "Groq" and r.headers["x-modelo"] == "llama"
    assert vistos == {"sistema": "system", "proveedor": None}


def test_conversaciones_ida_y_vuelta(cliente):
    conv = [{"id": "abcdef12", "titulo": "Títulos", "hora": 1.0,
             "mensajes": [{"role": "user", "content": "hola"}, {"role": "assistant", "content": "¡hola!"}]}]
    assert cliente.put("/api/ia/conversaciones", json={"conversaciones": conv}).status_code == 200
    assert cliente.get("/api/ia/conversaciones").json()["conversaciones"] == conv
    assert cliente.put("/api/ia/conversaciones", json={"conversaciones": [{**conv[0], "id": "../x"}]}).status_code == 422


def test_textos_de_clip_sin_ia_son_basicos_y_se_guardan(cliente, tmp_path, monkeypatch):
    mp4 = tmp_path / "envivo_01.mp4"
    mp4.write_bytes(b"x")
    (tmp_path / "envivo_01.json").write_text(json.dumps({"canal": "ibai", "plataforma": "twitch"}), encoding="utf-8")
    monkeypatch.setattr(app_mod, "ruta_clip", lambda c, n: str(mp4))
    r = cliente.post("/api/clip/textos", json={"carpeta": "2026-11-22_ibai", "nombre": "envivo_01.mp4"}).json()
    assert r["fuente"] == "basico" and "twitch.tv/ibai" in r["redes"]["tiktok"]
    assert json.loads((tmp_path / "envivo_01.json").read_text(encoding="utf-8"))["textos"]["fuente"] == "basico"


def test_otro_host_se_rechaza_dns_rebinding():
    r = TestClient(app_mod.app, base_url="http://evil.example").get("/api/preferencias")
    assert r.status_code == 400
