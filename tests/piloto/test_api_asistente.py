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


def test_agente_devuelve_texto_y_propuestas(cliente, monkeypatch):
    import agente
    vistos = {}

    def responder(cfg, mensajes, lecturas, acciones, proveedor=None, modelo=None, validar=None):
        vistos.update(lecturas=set(lecturas), acciones=set(acciones))
        return {"texto": "Lo paro", "proveedor": "groq", "modelo": "m", "clips": [],
                "propuestas": [{"herramienta": "parar_caza", "args": {}, "resumen": "Parar el cazador"}]}
    monkeypatch.setattr(agente, "responder", responder)
    r = cliente.post("/api/ia/agente", json={"mensajes": [{"role": "user", "content": "para"}]}).json()
    assert r["texto"] == "Lo paro" and r["proveedor"] == "Groq" and r["propuestas"][0]["herramienta"] == "parar_caza"
    assert vistos["lecturas"] == {"buscar_clips", "estado_cazador", "resumen"}
    assert vistos["acciones"] == {"empezar_caza", "parar_caza", "producir_clip", "generar_textos", "marcar_clip",
                                  "marcar_subido", "analizar_vod", "clip_ya", "pausar_caza", "reanudar_caza"}


def test_agente_sin_proveedores_502(cliente):
    r = cliente.post("/api/ia/agente", json={"mensajes": [{"role": "user", "content": "hola"}]})
    assert r.status_code == 502 and "Ajustes" in r.json()["detail"]


def test_accion_confirmada_se_hace(cliente, monkeypatch):
    hecho = []
    monkeypatch.setattr(app_mod, "stop", lambda: hecho.append(1) or {"ok": True})
    r = cliente.post("/api/ia/accion", json={"herramienta": "parar_caza", "args": {}})
    assert r.status_code == 200 and hecho == [1] and r.json()["ok"] is True


def test_accion_desconocida_o_canal_malo_400(cliente):
    assert cliente.post("/api/ia/accion", json={"herramienta": "borrar_todo", "args": {}}).status_code == 422
    r = cliente.post("/api/ia/accion", json={"herramienta": "empezar_caza", "args": {"canal": "../x"}})
    assert r.status_code == 400


def test_el_contexto_guardado_vuelve_a_la_ia_y_se_conserva(cliente, monkeypatch):
    import agente
    vistos = {}

    def responder(cfg, mensajes, lecturas, acciones, proveedor=None, modelo=None, validar=None):
        vistos["m"] = mensajes
        return {"texto": "ok", "proveedor": "groq", "modelo": "m", "clips": [], "propuestas": [], "contexto": ""}
    monkeypatch.setattr(agente, "responder", responder)
    hist = [{"role": "user", "content": "busca"}, {"role": "assistant", "content": "2 clips", "ctx": "[Datos] a/b.mp4"},
            {"role": "user", "content": "produce el segundo"}]
    cliente.post("/api/ia/agente", json={"mensajes": hist})
    assert vistos["m"][1] == {"role": "assistant", "content": "2 clips\n\n[Datos] a/b.mp4"}
    conv = [{"id": "abcdef12", "titulo": "t", "hora": 1.0, "mensajes": hist}]
    cliente.put("/api/ia/conversaciones", json={"conversaciones": conv})
    assert cliente.get("/api/ia/conversaciones").json()["conversaciones"][0]["mensajes"][1]["ctx"] == "[Datos] a/b.mp4"


def test_progreso_de_textos_se_ve_y_se_limpia(cliente, tmp_path, monkeypatch):
    import progreso
    import textos_clip
    vistos = []
    mp4 = tmp_path / "envivo_01.mp4"
    mp4.write_bytes(b"x")
    monkeypatch.setattr(app_mod, "ruta_clip", lambda c, n: str(mp4))
    monkeypatch.setattr(ia, "disponibles", lambda cfg: [{"id": "groq"}])
    monkeypatch.setattr(app_mod, "_transcripcion", lambda m, meta: vistos.append(progreso.lista()) or "hola")
    monkeypatch.setattr(textos_clip, "generar", lambda meta, cfg, t: vistos.append(progreso.lista()) or {"fuente": "ia"})
    cliente.post("/api/clip/textos", json={"carpeta": "2026-11-22_ibai", "nombre": "envivo_01.mp4"})
    clave = "2026-11-22_ibai/envivo_01.mp4"
    assert vistos[0][clave]["paso"].startswith("Transcribiendo") and "IA" in vistos[1][clave]["paso"]
    assert cliente.get("/api/progreso").json() == {}


def test_las_medidas_van_a_la_grafica_y_no_al_registro():
    import io
    app_mod._log.clear()
    app_mod._serie.limpiar()

    class Proc:
        stdout = io.StringIO("[medida] 57 20.0 40.0\n   [estado] chat normal\n")

        def wait(self):
            return 0
    app_mod._leer_salida(Proc())
    assert not any("[medida]" in l for l in app_mod._log)
    assert app_mod.status()["serie"]["puntos"][0][1:] == [57, 20.0, 40.0]


def _para_subir(tmp_path, monkeypatch):
    sal = tmp_path / "salida"
    (sal / "PARA SUBIR").mkdir(parents=True)
    (sal / "SUBIDOS").mkdir()
    (sal / "PARA SUBIR" / "Golazo.mp4").write_bytes(b"x")
    (sal / "PARA SUBIR" / "Golazo.json").write_text('{"producido": true}', encoding="utf-8")
    monkeypatch.setattr(app_mod, "SALIDA", str(sal))
    return sal


def test_marcar_redes_y_con_las_tres_pasa_a_subidos(cliente, tmp_path, monkeypatch):
    sal = _para_subir(tmp_path, monkeypatch)
    ref = {"carpeta": "PARA SUBIR", "nombre": "Golazo.mp4"}
    r = cliente.post("/api/clip/redes", json={**ref, "red": "tiktok", "hecho": True}).json()
    assert r == {"subido_en": ["tiktok"], "movido": False}
    cliente.post("/api/clip/redes", json={**ref, "red": "shorts", "hecho": True})
    assert cliente.post("/api/clip/redes", json={**ref, "red": "shorts", "hecho": False}).json()["subido_en"] == ["tiktok"]
    cliente.post("/api/clip/redes", json={**ref, "red": "shorts", "hecho": True})
    r = cliente.post("/api/clip/redes", json={**ref, "red": "reels", "hecho": True}).json()
    assert r["movido"] is True and (sal / "SUBIDOS" / "Golazo.mp4").exists()
    assert json.loads((sal / "SUBIDOS" / "Golazo.json").read_text(encoding="utf-8"))["subido_en"] == ["reels", "shorts", "tiktok"]


def test_redes_solo_en_para_subir_y_red_valida(cliente, tmp_path, monkeypatch):
    _para_subir(tmp_path, monkeypatch)
    assert cliente.post("/api/clip/redes", json={"carpeta": "PARA SUBIR", "nombre": "Golazo.mp4", "red": "x", "hecho": True}).status_code == 422
    assert cliente.post("/api/clip/redes", json={"carpeta": "2026-11-22_ibai", "nombre": "a.mp4", "red": "tiktok", "hecho": True}).status_code == 400


def test_mini_ventana_solo_en_escritorio(cliente, monkeypatch):
    monkeypatch.setattr(app_mod, "abrir_mini", None)
    assert cliente.post("/api/mini").status_code == 409
    hecho = []
    monkeypatch.setattr(app_mod, "abrir_mini", lambda: hecho.append(1))
    assert cliente.post("/api/mini").status_code == 200 and hecho == [1]
    assert "Hypazo mini" in cliente.get("/mini").text


def test_acciones_nuevas_pasan_por_sus_endpoints(cliente, monkeypatch):
    vistos = []
    monkeypatch.setattr(app_mod, "clip_estado", lambda e: vistos.append(("estado", e.estado)) or {"ok": True})
    monkeypatch.setattr(app_mod, "clip_mover", lambda m: vistos.append(("mover", m.carpeta, m.destino)) or {"ok": True})
    monkeypatch.setattr(app_mod, "vod", lambda v: vistos.append(("vod", v.n)) or {"ok": True})
    monkeypatch.setattr(app_mod, "clip_ya", lambda: vistos.append(("ya",)) or {"ok": True})
    monkeypatch.setattr(app_mod, "pausa", lambda: vistos.append(("pausa",)) or {"ok": True})
    monkeypatch.setattr(app_mod, "reanudar", lambda: vistos.append(("reanudar",)) or {"ok": True})
    hacer = lambda h, a: cliente.post("/api/ia/accion", json={"herramienta": h, "args": a}).status_code
    assert hacer("marcar_clip", {"carpeta": "c", "nombre": "n.mp4", "estado": "bueno"}) == 200
    assert hacer("marcar_clip", {"carpeta": "c", "nombre": "n.mp4", "estado": "borrado"}) == 400
    assert hacer("marcar_subido", {"nombre": "Golazo.mp4"}) == 200
    assert hacer("analizar_vod", {"url": "https://www.twitch.tv/videos/1", "n": 99}) == 400
    assert hacer("analizar_vod", {"url": "https://www.twitch.tv/videos/1", "n": 5}) == 200
    for h in ("clip_ya", "pausar_caza", "reanudar_caza"):
        assert hacer(h, {}) == 200
    assert vistos == [("estado", "bueno"), ("mover", "PARA SUBIR", "SUBIDOS"), ("vod", 5), ("ya",), ("pausa",), ("reanudar",)]


def test_validar_propuestas_antes_de_ensenarlas(cliente, tmp_path, monkeypatch):
    import api_asistente
    _para_subir(tmp_path, monkeypatch)
    v = api_asistente.validar_propuesta
    assert v("marcar_subido", {"nombre": "Golazo.mp4"}) is None
    assert "no existe" in v("marcar_subido", {"nombre": "Golaz.mp4"})
    assert v("producir_clip", {"carpeta": "../x", "nombre": "a.mp4"})
    assert v("analizar_vod", {"url": "https://youtube.com/x"})
    assert v("analizar_vod", {"url": "https://www.twitch.tv/videos/123"}) is None
    monkeypatch.setattr(app_mod, "_corriendo", lambda: False)
    assert "no está en marcha" in v("clip_ya", {}) and v("pausar_caza", {}) and v("empezar_caza", {"canal": "ibai"}) is None
    monkeypatch.setattr(app_mod, "_corriendo", lambda: True)
    assert v("clip_ya", {}) is None and "párala" in v("empezar_caza", {"canal": "ibai"})


def test_marcar_las_tres_redes_a_la_vez_no_pierde_ninguna(tmp_path, monkeypatch):
    import threading
    import time as _t
    sal = _para_subir(tmp_path, monkeypatch)
    leer = app_mod._meta
    monkeypatch.setattr(app_mod, "_meta", lambda mp4: (_t.sleep(0.05), leer(mp4))[1])   # que se crucen
    hilos = [threading.Thread(target=app_mod.clip_redes, args=(app_mod.Red(carpeta="PARA SUBIR", nombre="Golazo.mp4",
                                                                         red=r, hecho=True),))
             for r in ("tiktok", "shorts", "reels")]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert (sal / "SUBIDOS" / "Golazo.mp4").exists()
