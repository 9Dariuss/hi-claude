"""Atajos globales (`hi-claude --atajos`): Win+Alt+C, Win+Alt+V y Win+Alt+X por defecto.

En Linux los atajos los gestiona GNOME. En Windows no hay nada equivalente que admita la
tecla Windows, así que este proceso pequeño arranca con la sesión (carpeta Inicio), registra
los atajos con RegisterHotKey y se queda dormido esperando: no usa CPU ni abre el micrófono.
Al pulsar un atajo avisa a la app si está abierta o la abre.

Win+C y Ctrl+Win+C los reserva Windows (Copilot y filtros de color): por eso se usa Win+Alt.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path

from . import instance, winutil
from .config import Config

MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8, "super": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
HOTKEY_MUTEX = "Local\\hi-claude-atajos"
LAUNCHER = Path(__file__).resolve().parent.parent / "hi-claude.pyw"


def log(msg: str) -> None:  # (no se importa voice: este proceso vive siempre y debe ocupar poco)
    if sys.stderr:
        print(time.strftime("[%H:%M:%S]"), msg, file=sys.stderr, flush=True)


def parse(combo: str) -> tuple[int, int]:
    """«Win+Alt+C» → (modificadores, tecla virtual)."""
    mods, key = 0, None
    for part in combo.replace(" ", "").split("+"):
        low = part.lower()
        if low in MODS:
            mods |= MODS[low]
        elif len(part) == 1:
            key = ord(part.upper())
        elif low.startswith("f") and low[1:].isdigit():
            key = 0x6F + int(low[1:])  # F1 = 0x70
        else:
            raise ValueError(f"tecla desconocida en «{combo}»: {part}")
    if key is None:
        raise ValueError(f"falta la tecla en «{combo}»")
    return mods, key


def pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def launch(args: list[str]) -> None:
    winutil.allow_foreground()
    if instance.send_to_running(args, str(Path.home())):
        return
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([pythonw(), str(LAUNCHER), *args], cwd=str(Path.home()), creationflags=flags,
                     close_fds=True)


def run() -> int:
    mutex = winutil.NamedMutex(HOTKEY_MUTEX)
    if mutex.already_existed:
        log("los atajos ya están activos")
        return 0
    cfg = Config.load()
    actions = {1: (cfg.hotkey_open, []), 2: (cfg.hotkey_voice, ["--voice"]), 3: (cfg.hotkey_snip, ["--snip"])}
    user32 = ctypes.windll.user32
    registered = 0
    for hid, (combo, _args) in actions.items():
        try:
            mods, vk = parse(combo)
        except ValueError as exc:
            log(f"atajo no válido: {exc}")
            continue
        if user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk):
            registered += 1
            log(f"atajo {combo} listo")
        else:
            log(f"no se pudo registrar {combo}: ya lo usa Windows u otro programa (cámbialo en config.toml)")
    if not registered:
        return 1
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY and msg.wParam in actions:
            try:
                launch(actions[msg.wParam][1])
            except Exception as exc:
                log(f"no se pudo abrir Hi Claude!: {exc!r}")
    return 0
