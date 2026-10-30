"""Punto de entrada. Se importa poco aquí para que `--atajos` (que vive siempre) ocupe poca memoria."""

from __future__ import annotations

import os
import sys

from .config import LOG_PATH


def setup_logging() -> None:
    """Con pythonw no hay consola: lo que se escribiría en ella va a hi-claude.log."""
    if sys.stderr is None or sys.stdout is None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2_000_000:
            LOG_PATH.replace(LOG_PATH.with_suffix(".log.1"))
        log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def run() -> None:
    setup_logging()
    if "--atajos" in sys.argv:
        from . import hotkeys
        code = hotkeys.run()
    else:
        from . import app
        code = app.main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)  # sin esperar a hilos sueltos: al cerrar no queda nada
