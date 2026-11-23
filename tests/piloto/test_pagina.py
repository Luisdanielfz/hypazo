import re

from fastapi.testclient import TestClient

import app as app_mod


def test_la_pagina_carga_css_y_js_versionados_y_tiene_tres_pestanas():
    c = TestClient(app_mod.app)
    html = c.get("/").text
    for ruta in re.findall(r'"(/assets/app\.(?:css|js)\?v=\d+)"', html):
        assert c.get(ruta).status_code == 200
    assert len(re.findall(r'/assets/app\.(?:css|js)\?v=\d+', html)) == 2
    assert re.findall(r'role="tab" id="t-(\w+)"', html) == ["cazar", "clips", "ajustes"]
    assert 'id="tab-asistente" class="cajon"' in html     # el Asistente es un panel lateral, no una pestaña
