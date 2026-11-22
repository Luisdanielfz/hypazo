import os

from clips_vivos import ClipsVivos


def test_sigue_un_clip_de_la_cola_a_listo(tmp_path):
    salida = str(tmp_path)
    v = ClipsVivos(salida)
    assert v.leer("   Clip 3 en cola de render (1 pendientes). Sigo cazando.") is None
    assert v.lista()[0]["estado"] == "cola"
    v.leer("   Renderizando clip 3...")
    assert v.lista()[0]["estado"] == "renderizando"
    mp4 = os.path.join(salida, "2026-11-22_ibai", "envivo_03.mp4")
    evento = v.leer(f"   CLIP GUARDADO: {mp4}")
    c = v.lista()[0]
    assert evento == ("listo", c)
    assert (c["n"], c["estado"], c["carpeta"], c["nombre"]) == (3, "listo", "2026-11-22_ibai", "envivo_03.mp4")


def test_fallo_guarda_el_motivo():
    v = ClipsVivos("C:/x")
    v.leer("   Clip 2 en cola de render (1 pendientes). Sigo cazando.")
    tipo, c = v.leer("   (clip 2 fallo, lo salto: Twitch estaba poniendo anuncios)")
    assert tipo == "fallo" and c["estado"] == "fallo" and "anuncios" in c["error"]


def test_lista_lo_mas_nuevo_primero_y_limitada():
    v = ClipsVivos("C:/x")
    for n in range(1, 15):
        v.leer(f"   Clip {n} en cola de render ({n} pendientes). Sigo cazando.")
    lista = v.lista()
    assert [c["n"] for c in lista[:2]] == [14, 13] and len(lista) == 8


def test_clip_guardado_fuera_de_la_salida_no_da_ruta():
    v = ClipsVivos("C:/salida")
    tipo, c = v.leer("   CLIP GUARDADO: D:/otro/envivo_01.mp4")
    assert tipo == "listo" and c["carpeta"] is None


def test_lineas_ajenas_no_cambian_nada():
    v = ClipsVivos("C:/x")
    assert v.leer("[estado] chat normal ~30/3s") is None and v.lista() == []


def test_fallo_con_mensaje_en_varias_lineas_tambien_cuenta():
    v = ClipsVivos("C:/x")
    tipo, c = v.leer("   (clip 5 fallo, lo salto: ffmpeg dijo:")
    assert tipo == "fallo" and c["n"] == 5 and c["error"].startswith("ffmpeg")
