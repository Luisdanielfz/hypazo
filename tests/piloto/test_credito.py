from credito import credito_final


def test_vacio_twitch():
    assert credito_final("", "AuronPlay", "twitch") == "twitch.tv/auronplay"


def test_vacio_kick():
    assert credito_final("", "Westcol", "kick") == "kick.com/westcol"


def test_solo_espacios_usa_defecto():
    assert credito_final("   ", "auronplay", "twitch") == "twitch.tv/auronplay"


def test_respeta_credito_propio():
    assert credito_final(" @auronplay ", "auronplay", "twitch") == "@auronplay"
