import autoclip
import vod


def test_comandos_y_bots_son_ruido():
    assert autoclip.es_ruido(b"pepe", b"!followage")
    assert autoclip.es_ruido(b"pepe", b"  !sorteo")
    assert autoclip.es_ruido(b"nightbot", b"sigueme en twitter")
    assert autoclip.es_ruido(b"StreamElements", b"hola")
    assert not autoclip.es_ruido(b"pepe", b"jajaja que crack")
    assert not autoclip.es_ruido(b"pepe", b"!!! GOL")       # hype, no un comando


def test_emotes_de_risa_del_canal_pesan_como_risa():
    for risa in (b"auronrisitas", b"rubiusxd", b"ibailul", b"jsjsjs", b"jejeje", b"kekw"):
        assert autoclip.peso(risa) == 2, risa
    assert autoclip.peso(b"buenas tardes") == 1
    assert autoclip.peso(b"control total") == 1
    for normal in (b"una sonrisa", b"la brisa", b"significante", b"lolita", b"lulu", b"mexdo", b"kekos"):
        assert autoclip.peso(normal) == 1, normal
    assert autoclip.peso(b"xd") == 2 and autoclip.peso(b"lol que bueno") == 2


def test_top_chat_junta_repeticiones_y_quita_comandos():
    lineas = ["a: auronRisitas auronRisitas auronRisitas", "b: auronRisitas auronRisitas",
              "c: auronrisitas", "d: !followage", "nightbot: hola", "e: GG"]
    top = autoclip.resumen_chat(lineas)
    assert top[0] == ("auronRisitas", 3)       # se ve como lo escribió el primero
    assert all(not t.startswith("!") and t != "hola" for t, _ in top)


def test_vod_ignora_comandos_al_puntuar():
    msgs = [(5, "pepe", "!sorteo")] * 50 + [(5, "nightbot", "jajaja")] * 50
    linea = vod.linea_de_tiempo(msgs, 10, 1.8, 1)
    assert linea[5][0] == 0
