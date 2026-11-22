"""Icono de Hypazo junto al reloj de Windows: avisos y control sin tener la ventana delante.

Menú: Abrir Hypazo · ¡Clip ya! (F9) · Pausar/Reanudar (F8) · Salir.
Cerrar la ventana mientras se caza la esconde aquí en vez de parar el cazador.
"""
import os
import threading


def _imagen(ruta_ico):
    from PIL import Image
    try:
        return Image.open(ruta_ico)
    except OSError:                 # sin icono: un cuadrado con los colores de la marca
        return Image.new("RGB", (64, 64), (0, 200, 220))


class Bandeja:
    def __init__(self, acciones: dict, ruta_ico: str, crear=None):
        """acciones: abrir, clip, pausa, salir (funciones sin argumentos)."""
        self._acciones = acciones
        crear = crear or self._crear_pystray
        self._icono = crear(ruta_ico, self._menu())

    def _menu(self):
        a = self._acciones
        return [("Abrir Hypazo", a["abrir"], True), ("¡Clip ya! (F9)", a["clip"], False),
                ("Pausar / reanudar caza (F8)", a["pausa"], False), ("Salir", a["salir"], False)]

    @staticmethod
    def _crear_pystray(ruta_ico, menu):
        import pystray
        # pystray rechaza funciones con más de 2 argumentos (aunque tengan valor por defecto)
        items = [pystray.MenuItem(texto, (lambda f: lambda: f())(f), default=defecto) for texto, f, defecto in menu]
        icono = pystray.Icon("hypazo", _imagen(ruta_ico), "Hypazo", pystray.Menu(*items))
        threading.Thread(target=icono.run, daemon=True).start()
        return icono

    def avisar(self, titulo: str, texto: str) -> None:
        try:
            self._icono.notify(texto, titulo)
        except Exception:           # Windows sin notificaciones (modo concentración, etc.)
            pass

    def quitar(self) -> None:
        try:
            self._icono.stop()
        except Exception:
            pass


def al_cerrar(cazando, esconder, avisar) -> bool:
    """Manejador del cierre de la ventana. False = no cerrar (se esconde en la bandeja)."""
    if not cazando():
        return True
    esconder()
    avisar("Hypazo sigue cazando", "La ventana está junto al reloj. Ábrela desde el icono o usa F9 / F8.")
    return False


RUTA_ICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "hypazo.ico")
