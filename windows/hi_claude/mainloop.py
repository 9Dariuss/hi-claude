"""Un «bucle principal» propio, como el de GLib en Linux.

pywebview llama a la API de JS desde hilos sueltos y el SDK de Claude vive en su propio
hilo asyncio. Para no tener que pensar en carreras, toda la lógica de la interfaz
(ChatController, ventanas, preferencias) se ejecuta en un único hilo: este.
"""

from __future__ import annotations

import heapq
import itertools
import sys
import threading
import time
import traceback
from typing import Callable

_lock = threading.Condition()
_queue: list[tuple[float, int, Callable[[], object]]] = []
_counter = itertools.count()
_thread: threading.Thread | None = None


def idle_add(fn: Callable, *args) -> None:
    """Ejecuta fn(*args) en el hilo principal en cuanto pueda."""
    timeout_add(0, fn, *args)


def timeout_add(ms: int, fn: Callable, *args) -> None:
    """Ejecuta fn(*args) dentro de `ms` milisegundos. Si devuelve True, se repite."""
    def run():
        if fn(*args) is True:
            timeout_add(ms, fn, *args)
    with _lock:
        heapq.heappush(_queue, (time.monotonic() + ms / 1000, next(_counter), run))
        _lock.notify()


def in_main_thread() -> bool:
    return threading.current_thread() is _thread


def _run() -> None:
    while True:
        with _lock:
            while not _queue or _queue[0][0] > time.monotonic():
                _lock.wait(None if not _queue else max(0.0, _queue[0][0] - time.monotonic()))
            _, _, fn = heapq.heappop(_queue)
        try:
            fn()
        except Exception:
            traceback.print_exc(file=sys.stderr)


def start() -> None:
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_run, daemon=True, name="hi-claude-main")
        _thread.start()
