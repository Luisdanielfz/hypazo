"""Cola de render en segundo plano: el cazador encarga el clip y sigue vigilando el directo.

Antes el render (1-2 min) iba dentro del bucle del cazador: mientras tanto no leía el chat ni
atendía "Clip ya", y al volver el chat acumulado parecía un pico. Un solo hilo de render: los
clips salen en orden y no compiten por la CPU entre ellos.
"""
import queue
import threading


class Renderizador:
    def __init__(self, avisar=print):
        self._avisar = avisar
        self._cola = queue.Queue()
        threading.Thread(target=self._bucle, daemon=True).start()

    def encargar(self, nombre, trabajo) -> None:
        """Encola trabajo() y vuelve al instante."""
        self._cola.put((nombre, trabajo))

    def pendientes(self) -> int:
        return self._cola.unfinished_tasks

    def esperar(self, timeout: float) -> bool:
        """True si la cola se vació antes de timeout (para pruebas y para parar con calma)."""
        hecho = threading.Event()

        def vaciar():
            self._cola.join()
            hecho.set()
        threading.Thread(target=vaciar, daemon=True).start()
        return hecho.wait(timeout)

    def _bucle(self):
        while True:
            nombre, trabajo = self._cola.get()
            try:
                trabajo()
            except Exception as e:      # un clip malo no debe parar la cola
                self._avisar(f"   (clip {nombre} fallo, lo salto: {e})")
            finally:
                self._cola.task_done()
