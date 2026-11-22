import json

import ia
import textos_clip

META = {"canal": "ibai", "plataforma": "twitch", "directo": "VELADA DEL AÑO | Just Chatting", "motivo": "chat",
        "top_chat": [["JAJAJA", 30], ["OMG", 12]]}


def test_basico_sin_ia_lleva_credito_y_plantillas():
    t = textos_clip.basico(META)
    assert t["fuente"] == "basico" and len(t["titulos"]) == 3
    assert "twitch.tv/ibai" in t["redes"]["tiktok"]
    assert t["redes"]["shorts"]["titulo"].endswith("#shorts") and len(t["redes"]["shorts"]["titulo"]) <= 100
    assert t["redes"]["reels"].count("#") <= 5


def test_con_ia_usa_su_respuesta_y_limpia(monkeypatch):
    def chat(cfg, mensajes, **kw):
        assert kw["json_modo"] is True and "JAJAJA" in mensajes[-1]["content"]
        return {"texto": json.dumps({"titulos": ["IBAI NO PUEDE MÁS", "x" * 300, "Tercero"],
                                     "hashtags": ["#ibai", "velada", "#Velada", "humor con espacios"]}),
                "proveedor": "groq", "modelo": "m"}
    monkeypatch.setattr(ia, "chat", chat)
    t = textos_clip.generar(META, {"orden": ["groq"]}, transcripcion="no me lo puedo creer")
    assert t["fuente"] == "ia" and t["proveedor"] == "groq"
    assert t["titulos"][0] == "IBAI NO PUEDE MÁS" and len(t["titulos"][1]) <= 90
    assert t["hashtags"][:3] == ["#ibai", "#velada", "#humorconespacios"]


def test_si_la_ia_falla_vuelve_al_basico_con_aviso(monkeypatch):
    def chat(*a, **k):
        raise ia.ErrorIA("Ningún proveedor respondió.")
    monkeypatch.setattr(ia, "chat", chat)
    t = textos_clip.generar(META, {})
    assert t["fuente"] == "basico" and "Ningún proveedor" in t["aviso"]


def test_respuesta_ia_sin_json_vuelve_al_basico(monkeypatch):
    monkeypatch.setattr(ia, "chat", lambda *a, **k: {"texto": "lo siento", "proveedor": "groq", "modelo": "m"})
    assert textos_clip.generar(META, {})["fuente"] == "basico"
