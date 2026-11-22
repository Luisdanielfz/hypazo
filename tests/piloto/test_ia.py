import json

import httpx
import pytest

import ia


def cfg(**provs):
    return {"orden": list(provs), "proveedores": provs}


def cliente(respuestas, vistos=None):
    """httpx.Client falso: respuestas = {host: (status, cuerpo)}."""
    def manejar(req):
        if vistos is not None:
            vistos.append((req.url.host, req.headers.get("authorization"), json.loads(req.content or b"{}")))
        status, cuerpo = respuestas[req.url.host]
        if isinstance(cuerpo, str):
            return httpx.Response(status, text=cuerpo)
        return httpx.Response(status, json=cuerpo)
    return httpx.Client(transport=httpx.MockTransport(manejar))


def ok(texto):
    return (200, {"choices": [{"message": {"content": texto}}]})


def test_catalogo_tiene_muchos_proveedores_y_sin_claves():
    ids = [p["id"] for p in ia.catalogo()]
    assert {"groq", "gemini", "openrouter", "mistral", "cerebras", "github", "ollama", "personalizado"} <= set(ids)
    assert all("clave" not in p for p in ia.catalogo())


def test_publico_nunca_devuelve_la_clave():
    c = cfg(groq={"clave": "gsk_secreta", "modelo": "", "activo": True})
    pub = ia.publico(c)
    assert "gsk_secreta" not in json.dumps(pub)
    assert pub["proveedores"]["groq"]["configurada"] is True


def test_actualizar_es_inmutable_y_clave_vacia_conserva_la_anterior():
    antes = cfg(groq={"clave": "k1", "modelo": "", "activo": True})
    despues = ia.actualizar(antes, "groq", {"clave": "", "modelo": "m2"})
    assert antes["proveedores"]["groq"]["modelo"] == "" and despues["proveedores"]["groq"] == \
        {"clave": "k1", "modelo": "m2", "activo": True}
    assert ia.actualizar(despues, "groq", {"borrar_clave": True})["proveedores"]["groq"]["clave"] == ""


def test_actualizar_rechaza_proveedor_o_url_invalidos():
    with pytest.raises(ValueError):
        ia.actualizar(cfg(), "inventado", {})
    with pytest.raises(ValueError):
        ia.actualizar(cfg(), "personalizado", {"url": "file:///c:/windows"})


def test_disponibles_respeta_orden_y_salta_los_que_no_tienen_clave():
    c = cfg(gemini={"clave": "g", "modelo": "", "activo": True}, groq={"clave": "", "modelo": "", "activo": True},
            mistral={"clave": "m", "modelo": "", "activo": False})
    assert [d["id"] for d in ia.disponibles(c)] == ["gemini"]


def test_chat_usa_el_primero_y_manda_la_clave():
    vistos = []
    c = cfg(groq={"clave": "gsk", "modelo": "", "activo": True})
    r = ia.chat(c, [{"role": "user", "content": "hola"}], cliente=cliente({"api.groq.com": ok("¡Hola!")}, vistos))
    assert r == {"texto": "¡Hola!", "proveedor": "groq", "modelo": ia.PROVEEDORES["groq"]["modelo"]}
    assert vistos[0][1] == "Bearer gsk" and vistos[0][2]["messages"][-1]["content"] == "hola"


def test_chat_pasa_al_siguiente_si_uno_falla():
    c = cfg(groq={"clave": "a", "modelo": "", "activo": True}, gemini={"clave": "b", "modelo": "x", "activo": True})
    r = ia.chat(c, [{"role": "user", "content": "hola"}],
                cliente=cliente({"api.groq.com": (429, "rate limit"), "generativelanguage.googleapis.com": ok("ok")}))
    assert r["proveedor"] == "gemini" and r["modelo"] == "x"


def test_chat_sin_proveedores_explica_que_hacer():
    with pytest.raises(ia.ErrorIA, match="Ajustes"):
        ia.chat(cfg(), [{"role": "user", "content": "hola"}], cliente=cliente({}))


def test_chat_con_todos_fallando_resume_los_errores():
    c = cfg(groq={"clave": "a", "modelo": "", "activo": True})
    with pytest.raises(ia.ErrorIA, match="groq.*401"):
        ia.chat(c, [{"role": "user", "content": "hola"}], cliente=cliente({"api.groq.com": (401, "bad key")}))


def test_stream_junta_los_trozos_sse():
    sse = ('data: {"choices":[{"delta":{"content":"Ho"}}]}\n\n'
           'data: {"choices":[{"delta":{"content":"la"}}]}\n\n'
           'data: {"choices":[{"delta":{}}]}\n\ndata: [DONE]\n\n')
    c = cfg(groq={"clave": "a", "modelo": "", "activo": True})
    prov, modelo, trozos = ia.abrir_stream(c, [{"role": "user", "content": "hola"}],
                                           cliente=cliente({"api.groq.com": (200, sse)}))
    assert prov == "groq" and "".join(trozos) == "Hola"


def test_modelos_lista_ids():
    c = cfg(groq={"clave": "a", "modelo": "", "activo": True})
    lista = ia.modelos(c, "groq", cliente=cliente({"api.groq.com": (200, {"data": [{"id": "b"}, {"id": "a"}]})}))
    assert lista == ["a", "b"]


def test_la_clave_no_sale_en_los_errores():
    c = cfg(groq={"clave": "gsk_SECRETA", "modelo": "", "activo": True})
    with pytest.raises(ia.ErrorIA) as e:
        ia.chat(c, [{"role": "user", "content": "hola"}],
                cliente=cliente({"api.groq.com": (401, "Invalid API Key: gsk_SECRETA")}))
    assert "gsk_SECRETA" not in str(e.value) and "***" in str(e.value)


def test_url_personalizada_malformada_se_rechaza_al_guardar():
    with pytest.raises(ValueError):
        ia.actualizar(cfg(), "personalizado", {"url": "http://[x/v1"})
