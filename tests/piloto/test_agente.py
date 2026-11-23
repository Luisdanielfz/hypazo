import json

import agente
import ia


def llamada(nombre, args, id_="c1"):
    return {"id": id_, "type": "function", "function": {"name": nombre, "arguments": json.dumps(args)}}


def guion(*respuestas):
    """IA falsa: devuelve las respuestas en orden y guarda lo que recibió."""
    vistas = []

    def llamar(cfg, mensajes, proveedor=None, modelo=None, herramientas=None):
        vistas.append({"mensajes": [dict(m) for m in mensajes], "herramientas": herramientas})
        texto, llamadas = respuestas[min(len(vistas), len(respuestas)) - 1]
        return {"texto": texto, "proveedor": "groq", "modelo": "m", "llamadas": llamadas}
    return llamar, vistas


def test_lectura_se_ejecuta_y_la_ia_contesta_con_el_resultado():
    hechas = []
    lecturas = {"buscar_clips": lambda a: hechas.append(a) or [{"carpeta": "c", "nombre": "envivo_01.mp4"}]}
    llamar, vistas = guion(("", [llamada("buscar_clips", {"texto": "velada"})]), ("Encontré 1 clip.", []))
    r = agente.responder({}, [{"role": "user", "content": "busca velada"}], lecturas, {}, llamar=llamar)
    assert r["texto"] == "Encontré 1 clip." and r["propuestas"] == []
    assert hechas == [{"texto": "velada"}]
    assert r["clips"] == [{"carpeta": "c", "nombre": "envivo_01.mp4"}]
    tool = vistas[1]["mensajes"][-1]
    assert tool["role"] == "tool" and tool["tool_call_id"] == "c1" and "envivo_01" in tool["content"]
    assert vistas[0]["herramientas"] and vistas[0]["mensajes"][0]["role"] == "system"


def test_una_accion_no_se_hace_sin_confirmar():
    hecho = []
    llamar, _ = guion(("Voy a pararlo.", [llamada("parar_caza", {})]))
    r = agente.responder({}, [{"role": "user", "content": "para"}], {}, {"parar_caza": lambda a: hecho.append(1)},
                         llamar=llamar)
    assert hecho == [] and r["texto"] == "Voy a pararlo."
    assert r["propuestas"] == [{"herramienta": "parar_caza", "args": {}, "resumen": "Parar el cazador"}]


def test_resumen_de_propuesta_legible():
    llamar, _ = guion(("", [llamada("empezar_caza", {"canal": "westcol", "plataforma": "kick"})]))
    r = agente.responder({}, [{"role": "user", "content": "caza"}], {}, {"empezar_caza": None}, llamar=llamar)
    assert r["propuestas"][0]["resumen"] == "Empezar a cazar a westcol en Kick"


def test_herramienta_desconocida_o_argumentos_rotos_no_rompen():
    malo = {"id": "c9", "type": "function", "function": {"name": "buscar_clips", "arguments": "{no json"}}
    llamar, vistas = guion(("", [llamada("borrar_todo", {}), malo]), ("Vale.", []))
    r = agente.responder({}, [{"role": "user", "content": "x"}], {"buscar_clips": lambda a: []}, {}, llamar=llamar)
    assert r["texto"] == "Vale."
    errores = [m["content"] for m in vistas[1]["mensajes"] if m["role"] == "tool"]
    assert len(errores) == 2 and all("error" in e for e in errores)


def test_se_corta_tras_pocas_vueltas():
    llamar, vistas = guion(("", [llamada("estado_cazador", {})]))
    r = agente.responder({}, [{"role": "user", "content": "x"}], {"estado_cazador": lambda a: {}}, {}, llamar=llamar)
    assert len(vistas) == agente.MAX_VUELTAS and r["texto"]


def test_si_ningun_proveedor_acepta_herramientas_contesta_sin_ellas():
    vistas = []

    def llamar(cfg, mensajes, proveedor=None, modelo=None, herramientas=None):
        vistas.append(herramientas)
        if herramientas:
            raise ia.ErrorIA("tools no soportado")
        return {"texto": "Hola", "proveedor": "x", "modelo": "m", "llamadas": []}
    r = agente.responder({}, [{"role": "user", "content": "hola"}], {}, {}, llamar=llamar)
    assert r["texto"].startswith("Hola") and vistas[-1] is None


GRUPOS = [
    {"carpeta": "PARA SUBIR", "clips": [{"nombre": "Golazo.mp4", "producido": True, "titulo": "Golazo"}]},
    {"carpeta": "2026-11-22_ibai", "clips": [
        {"nombre": "envivo_02.mp4", "score": 90, "hora": "21:10:00", "transcripcion": "la Velada del año"},
        {"nombre": "envivo_01.mp4", "score": 40, "hora": "20:00:00", "top_chat": [["JAJAJA", 30]]}]},
    {"carpeta": "2026-11-10_kick_westcol", "clips": [{"nombre": "envivo_01.mp4", "score": 99}]},
]


def test_buscar_por_palabra_sin_tildes_ni_mayusculas():
    r = agente.buscar(GRUPOS, texto="velada", hoy="2026-11-22")
    assert [(c["carpeta"], c["nombre"]) for c in r] == [("2026-11-22_ibai", "envivo_02.mp4")]
    assert "Velada" in r[0]["coincide"]


def test_buscar_por_chat_canal_dias_y_orden():
    assert agente.buscar(GRUPOS, texto="jajaja", hoy="2026-11-22")[0]["nombre"] == "envivo_01.mp4"
    assert [c["score"] for c in agente.buscar(GRUPOS, hoy="2026-11-22")][:3] == [99, 90, 40]
    assert {c["canal"] for c in agente.buscar(GRUPOS, dias=1, hoy="2026-11-22")} == {"ibai"}
    assert agente.buscar(GRUPOS, canal="westcol", hoy="2026-11-22")[0]["plataforma"] == "kick"
    assert len(agente.buscar(GRUPOS, limite=1, hoy="2026-11-22")) == 1


def test_resumen_cuenta_por_dia_y_por_subir():
    r = agente.resumen(GRUPOS, dias=30, hoy="2026-11-22")
    assert r["por_dia"] == {"2026-11-22": 2, "2026-11-10": 1} and r["para_subir"] == 1 and r["subidos"] == 0


def test_si_falla_a_mitad_no_contesta_sin_lo_consultado():
    import pytest
    n = []

    def llamar(cfg, mensajes, proveedor=None, modelo=None, herramientas=None):
        n.append(herramientas)
        if len(n) == 1:
            return {"texto": "", "proveedor": "x", "modelo": "m", "llamadas": [llamada("estado_cazador", {})]}
        raise ia.ErrorIA("429 límite")
    with pytest.raises(ia.ErrorIA):
        agente.responder({}, [{"role": "user", "content": "x"}], {"estado_cazador": lambda a: {}}, {}, llamar=llamar)
    assert len(n) == 2


def test_accion_con_argumentos_ilegibles_se_explica_bien():
    malo = {"id": "c1", "type": "function", "function": {"name": "parar_caza", "arguments": "{roto"}}
    llamar, vistas = guion(("", [malo]), ("Vale.", []))
    r = agente.responder({}, [{"role": "user", "content": "x"}], {}, {"parar_caza": None}, llamar=llamar)
    assert r["propuestas"] == [] and "ilegibles" in vistas[1]["mensajes"][-1]["content"]


def test_titulo_largo_se_recorta_en_la_tarjeta():
    r = agente.resumen_accion("producir_clip", {"carpeta": "c", "nombre": "n.mp4", "titulo": "x" * 300})
    assert len(r) < 140


def test_contexto_guarda_los_clips_encontrados_para_el_siguiente_mensaje():
    lecturas = {"buscar_clips": lambda a: [{"carpeta": "2026-11-22_ibai", "nombre": "envivo_02.mp4", "canal": "ibai",
                                            "fecha": "2026-11-22", "hora": "21:10:00", "score": 90}]}
    llamar, _ = guion(("", [llamada("buscar_clips", {})]), ("Uno.", []))
    r = agente.responder({}, [{"role": "user", "content": "x"}], lecturas, {}, llamar=llamar)
    assert "2026-11-22_ibai/envivo_02.mp4" in r["contexto"] and "90" in r["contexto"]


def test_recortar_deja_lo_mas_reciente_dentro_del_presupuesto():
    msgs = [{"role": "user", "content": "a" * 5000}, {"role": "assistant", "content": "b" * 5000},
            {"role": "user", "content": "ultima"}]
    r = agente.recortar(msgs, 6000)
    assert r[-1]["content"] == "ultima" and r[0]["role"] == "assistant" and sum(len(m["content"]) for m in r) <= 6000
    assert agente.recortar([{"role": "user", "content": "z" * 9000}], 6000)[0]["content"].endswith("z")


def test_sin_herramientas_avisa_de_que_no_miro_nada():
    def llamar(cfg, mensajes, proveedor=None, modelo=None, herramientas=None):
        if herramientas:
            raise ia.ErrorIA("tools no soportado")
        return {"texto": "Hola", "proveedor": "x", "modelo": "m", "llamadas": []}
    r = agente.responder({}, [{"role": "user", "content": "busca"}], {}, {}, llamar=llamar)
    assert r["texto"].startswith("Hola") and "herramientas" in r["texto"]


def test_resumen_de_las_acciones_nuevas():
    r = agente.resumen_accion
    assert r("marcar_clip", {"carpeta": "c", "nombre": "n.mp4", "estado": "descartado"}) == "Marcar n.mp4 (c) como descartado"
    assert r("marcar_clip", {"carpeta": "c", "nombre": "n.mp4", "estado": ""}) == "Quitar la marca de n.mp4 (c)"
    assert r("marcar_subido", {"nombre": "Golazo.mp4"}) == "Pasar Golazo.mp4 a SUBIDOS"
    assert r("analizar_vod", {"url": "https://www.twitch.tv/videos/1", "n": 5}) == \
        "Sacar los 5 mejores momentos del VOD https://www.twitch.tv/videos/1"
    assert r("clip_ya", {}) == "Hacer un clip ahora mismo"
    assert r("pausar_caza", {}) == "Pausar la caza automática" and r("reanudar_caza", {}) == "Reanudar la caza automática"
    assert {h["function"]["name"] for h in agente.HERRAMIENTAS} >= {"marcar_clip", "marcar_subido", "analizar_vod",
                                                                    "clip_ya", "pausar_caza", "reanudar_caza"}


def test_un_error_que_no_es_de_herramientas_no_se_disfraza():
    import pytest

    def llamar(cfg, mensajes, proveedor=None, modelo=None, herramientas=None):
        if herramientas:
            raise ia.ErrorIA("Ningún proveedor respondió. groq: 429 rate limit")
        return {"texto": "Voy a hacerlo", "proveedor": "x", "modelo": "m", "llamadas": []}
    with pytest.raises(ia.ErrorIA, match="429"):
        agente.responder({}, [{"role": "user", "content": "x"}], {}, {}, llamar=llamar)


def test_propuesta_con_clip_que_no_existe_vuelve_a_la_ia():
    llamar, vistas = guion(("", [llamada("marcar_subido", {"nombre": "MAL.mp4"})]),
                           ("", [llamada("marcar_subido", {"nombre": "BIEN.mp4"})]))
    validar = lambda nombre, a: None if a.get("nombre") == "BIEN.mp4" else "Ese clip no existe."
    r = agente.responder({}, [{"role": "user", "content": "x"}], {}, {"marcar_subido": None}, llamar=llamar,
                         validar=validar)
    assert [p["args"]["nombre"] for p in r["propuestas"]] == ["BIEN.mp4"]
    assert "no existe" in vistas[1]["mensajes"][-1]["content"]


def test_si_anuncia_una_accion_sin_pedirla_se_le_recuerda_una_vez():
    llamar, vistas = guion(("Voy a pausar la caza.", []), ("", [llamada("pausar_caza", {})]))
    r = agente.responder({}, [{"role": "user", "content": "pausa"}], {}, {"pausar_caza": None}, llamar=llamar)
    assert [p["herramienta"] for p in r["propuestas"]] == ["pausar_caza"]
    assert "herramienta" in vistas[1]["mensajes"][-1]["content"] and len(vistas) == 2


def test_una_respuesta_normal_no_se_repite():
    llamar, vistas = guion(("Voy a explicarte cómo funciona F9.", []))
    r = agente.responder({}, [{"role": "user", "content": "¿qué es F9?"}], {}, {"pausar_caza": None}, llamar=llamar)
    assert r["texto"].startswith("Voy a explicarte") and len(vistas) == 1


def test_explicar_que_no_se_puede_no_cuenta_como_anuncio():
    assert not agente.RE_ANUNCIA.search("El cazador no está en marcha ahora mismo, así que no se puede pausar.")
    assert agente.RE_ANUNCIA.search("Vale, voy a pausar la caza un momento.")


def test_una_explicacion_con_vamos_a_no_es_una_accion():
    assert not agente.RE_ANUNCIA.search("Vamos a ver cómo mejorar el título de tu clip.")
    assert agente.RE_ANUNCIA.search("Voy a producir el clip ahora.")


def test_otras_formas_de_decir_que_no_acepta_herramientas_caen_a_chat_normal():
    for msg in ("groq: 400 unsupported parameter: tools", "x: 400 'tool_choice' is not supported"):
        assert agente._sin_herramientas(ia.ErrorIA(msg))
    assert not agente._sin_herramientas(ia.ErrorIA("groq: 429 rate limit"))
