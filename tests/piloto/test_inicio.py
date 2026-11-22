import subprocess
from types import SimpleNamespace

from envivo import inicio_directo


def ejecutor(salida="", error=None):
    def ejecutar(cmd, **kw):
        if error:
            raise error
        return SimpleNamespace(stdout=salida, returncode=0)
    return ejecutar


def test_timestamp_valido():
    assert inicio_directo("auronplay", ejecutar=ejecutor("1795300000\n")) == 1795300000.0


def test_na_es_none():
    assert inicio_directo("auronplay", ejecutar=ejecutor("NA\n")) is None


def test_vacio_es_none():
    assert inicio_directo("auronplay", ejecutar=ejecutor("")) is None


def test_timeout_es_none():
    err = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=40)
    assert inicio_directo("auronplay", ejecutar=ejecutor(error=err)) is None


def test_error_es_none():
    assert inicio_directo("x", "kick", ejecutar=ejecutor(error=OSError("no yt-dlp"))) is None
