import os
import subprocess

import clipeo


def test_split_con_chat_en_ruta_absoluta(tmp_path):
    # Regresión: con los clips en Vídeos\Hypazo la ruta del .ass es absoluta (C:/...) y los ':' sin escapar
    # rompían el filtro de ffmpeg: ningún clip split salía.
    carpeta = tmp_path / "Vídeos de José" / "Hypazo"
    carpeta.mkdir(parents=True)
    entrada = tmp_path / "entrada.ts"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=1920x1080:rate=30:duration=3", "-f", "lavfi", "-i", "sine=duration=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(entrada)], check=True)
    ass = carpeta / "chat_01.ass"
    clipeo.escribir_ass([(0.5, "usuario: hola"), (1.5, "otro: jaja")], str(ass))
    salida = carpeta / "clip.mp4"
    clipeo.convertir_split(str(entrada), str(salida), str(ass), "@canal", clipeo.LAYOUTS["auronplay"])
    assert salida.exists() and salida.stat().st_size > 0
