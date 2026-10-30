"""Una sola instancia: la segunda llamada (`--voice`, `--snip`, una carpeta…) solo avisa a la primera.

En Linux lo hace D-Bus; aquí, un mutex con nombre y una «named pipe» local.
"""

from __future__ import annotations

import getpass
import os
import threading
import time
from multiprocessing.connection import Client, Listener
from typing import Callable

from .winutil import NamedMutex

_user = "".join(c for c in getpass.getuser() if c.isalnum()) or "user"
PIPE = rf"\\.\pipe\hi-claude-{_user}"
MUTEX = f"Local\\hi-claude-{_user}"
AUTH = b"hi-claude"


def send_to_running(args: list[str], cwd: str, tries: int = 1) -> bool:
    """Pasa los argumentos a la instancia abierta. False si no hay ninguna."""
    for i in range(tries):
        try:
            with Client(PIPE, family="AF_PIPE", authkey=AUTH) as conn:
                conn.send({"args": args, "cwd": cwd})
                return True
        except (FileNotFoundError, ConnectionError, OSError):
            if i < tries - 1:
                time.sleep(0.25)
    return False


class Server:
    """Escucha a las siguientes llamadas mientras la app está abierta."""

    def __init__(self, on_command: Callable[[list[str], str], None]):
        self.on_command = on_command
        self.mutex: NamedMutex | None = None

    def claim(self) -> bool:
        """True si somos la primera instancia."""
        self.mutex = NamedMutex(MUTEX)
        return not self.mutex.already_existed

    def start(self) -> None:
        self.listener = Listener(PIPE, family="AF_PIPE", authkey=AUTH)
        threading.Thread(target=self._serve, daemon=True, name="hi-claude-instance").start()

    def _serve(self) -> None:
        while True:
            try:
                with self.listener.accept() as conn:
                    msg = conn.recv()
                self.on_command(list(msg.get("args", [])), str(msg.get("cwd") or os.getcwd()))
            except Exception:
                time.sleep(0.1)
