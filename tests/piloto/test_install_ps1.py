import json
import os
import subprocess


def traza(r):
    """Una línea con la salida de PowerShell: así se ve en el resumen de pytest (y en CI) por qué falló."""
    return repr((r.returncode, r.stdout[-700:], r.stderr[-700:]))

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PS1 = os.path.join(RAIZ, "install.ps1")


def ps(*args, env=None):
    return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS1, *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**os.environ, **(env or {})}, timeout=120)


def test_manifest_lista_las_etapas_en_orden():
    r = ps("-Manifest")
    assert r.returncode == 0, r.stdout + r.stderr
    etapas = json.loads(r.stdout.strip().splitlines()[-1])
    assert [e["name"] for e in etapas] == ["prerequisites", "repository", "venv", "python-deps", "config",
                                           "products", "setup", "complete"]


def test_sha_incorrecto_para_con_mensaje_claro(tmp_path):
    r = ps("-Stage", "prerequisites", env={"HYPAZO_HOME": str(tmp_path / "casa con espacio ñ"),
                                           "HYPAZO_TEST_BAD_SHA": "uv"})
    assert r.returncode == 1, traza(r)
    assert "no coincide con su huella SHA-256" in r.stdout, traza(r)
    assert not list((tmp_path / "casa con espacio ñ" / "pm").glob("uv/*/uv.exe"))


def test_scripts_ascii_sin_bom():
    # Con `irm | iex`, un BOM o un carácter no ASCII antes de param() rompe el script en PowerShell 5.1.
    for f in (PS1, os.path.join(RAIZ, "installer", "desinstalar.ps1")):
        datos = open(f, "rb").read()
        assert not datos.startswith(b"\xef\xbb\xbf")
        datos.decode("ascii")


def test_iex_dentro_de_un_script_dot_sourced_si_ejecuta(tmp_path):
    # Regresión: con `iex` dentro de un script cargado con `.`, el instalador no debe saltarse la instalación.
    script = tmp_path / "llamador.ps1"
    script.write_text(f"$env:HYPAZO_TEST_BAD_SHA='uv'; $env:HYPAZO_HOME='{tmp_path / 'casa'}'\n"
                      f"iex ((Get-Content -Raw '{PS1}') + \"`n\")\n'SIGUE ABIERTA'\n", encoding="ascii")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", f"& {{ . '{script}' }}"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert "Hypazo - instalacion" in r.stdout and "no coincide con su huella SHA-256" in r.stdout, traza(r)
    assert "SIGUE ABIERTA" in r.stdout, traza(r)


def test_hypazo_cmd_sin_rutas_escritas(tmp_path):
    # Regresión: una ruta con tildes escrita en el .cmd la lee mal cmd.exe (otra página de códigos).
    casa = tmp_path / "José instalación"
    script = tmp_path / "productos.ps1"
    script.write_text(f". '{PS1}'\n$script:Casa='{casa}'; $script:Bin=Join-Path $script:Casa 'bin'\n"
                      "$pathAntes=[Environment]::GetEnvironmentVariable('Path','User')\n"
                      "Stage-Products\n[Environment]::SetEnvironmentVariable('Path',$pathAntes,'User')\n",
                      encoding="utf-8-sig")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    datos = (casa / "bin" / "hypazo.cmd").read_bytes()
    datos.decode("ascii")
    assert b"%~dp0" in datos and "José".encode("utf-8") not in datos, r.stdout + r.stderr
