"""
codigos.py - Detector de codigos en el LIVE (OCR del OCR de Windows).

Vigila el directo y, apenas aparezca algo con pinta de codigo (regalo de GTA 6,
Steam, etc.), lo lee, SUENA una alarma, lo muestra grande, lo guarda en
codigos_detectados.txt y guarda el frame para que lo verifiques con tus ojos.

TU canjeas el codigo (esto solo te avisa y te lo lee lo mas rapido posible).

Uso:
    python codigos.py rubius
Ctrl+C para parar.
"""
import os
import re
import subprocess
import sys
import time

import winocr
from PIL import Image

from envivo import resolver_url

OCR_LANG = "es"
FRAME = "frame_ocr.jpg"
LOG = "codigos_detectados.txt"

# Codigos tipo XXXXX-XXXXX-XXXXX (con guiones) o tokens largos alfanumericos.
PAT_GRUPO = re.compile(r"[A-Z0-9]{4,6}(?:-[A-Z0-9]{4,6}){2,4}")
PAT_LARGO = re.compile(r"\b[A-Z0-9]{12,30}\b")


def _mezcla(s):
    return any(c.isalpha() for c in s) and any(c.isdigit() for c in s)


def grab(url):
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-err_detect", "ignore_err",
         "-i", url, "-frames:v", "1", "-q:v", "2", FRAME],
        capture_output=True,
    )
    return os.path.exists(FRAME) and os.path.getsize(FRAME) > 0


def ocr():
    try:
        img = Image.open(FRAME)
        img = img.resize((int(img.width * 1.4), int(img.height * 1.4)))
        return winocr.recognize_pil_sync(img, OCR_LANG)["text"]
    except Exception:
        return ""


def buscar(texto):
    U = texto.upper()
    U2 = re.sub(r"\s*-\s*", "-", U)   # une codigos que el OCR partio con espacios
    hits = set()
    for base in (U, U2):
        for m in PAT_GRUPO.findall(base):
            hits.add(m)
    for m in PAT_LARGO.findall(U):
        if _mezcla(m):
            hits.add(m)
    return hits


def copiar(texto):
    """Deja el codigo en el portapapeles (Ctrl+V listo). Usa 'clip' de Windows."""
    try:
        subprocess.run("clip", input=texto, text=True, shell=True, check=False)
        return True
    except Exception:
        return False


def alerta(code, copiado=False):
    t = time.strftime("%H:%M:%S")
    marca = "  [COPIADO - pega con Ctrl+V]" if copiado else ""
    print("\n" + "=" * 52)
    print(f"   POSIBLE CODIGO  [{t}]   ->   {code}{marca}")
    print("   Verifica el frame y CANJEALO YA.")
    print("=" * 52)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{t}  {code}\n")
    try:
        import shutil
        shutil.copy(FRAME, f"codigo_{t.replace(':', '')}.jpg")
    except Exception:
        pass
    try:
        import winsound
        for _ in range(4):
            winsound.Beep(1200, 250)
    except Exception:
        print("\a\a\a")


def main():
    canal = sys.argv[1] if len(sys.argv) > 1 else "rubius"
    url = resolver_url(canal)
    print(f"Vigilando codigos en el live de {canal}. Ctrl+C para parar.")
    vistos = set()
    fallos = 0
    while True:
        if not grab(url):
            fallos += 1
            if fallos > 3:
                try:
                    url = resolver_url(canal)
                    fallos = 0
                except Exception:
                    pass
            time.sleep(1)
            continue
        fallos = 0
        nuevos = [c for c in buscar(ocr()) if c not in vistos]
        if nuevos:
            # El mas "codigo" (con guiones, o el mas largo) va al portapapeles.
            principal = max(nuevos, key=lambda c: ("-" in c, len(c)))
            copiado_ok = copiar(principal)
            for c in nuevos:
                vistos.add(c)
                alerta(c, copiado=(c == principal and copiado_ok))
        time.sleep(1)


if __name__ == "__main__":
    main()
