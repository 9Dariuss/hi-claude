"""Configuración (~/.config/hi-claude/config.toml) y preferencias guardadas (~/.local/state/hi-claude)."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hi-claude" / "config.toml"
STATE_PATH = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "hi-claude" / "state.json"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hi-claude"

CLAUDE_ORANGE = "#d97757"

# Colores que se ofrecen en Preferencias (además, uno libre con el selector de color)
ACCENT_PRESETS = [
    ("Naranja Claude", CLAUDE_ORANGE),
    ("Coral", "#e66a5c"),
    ("Rosa", "#d6609a"),
    ("Morado", "#9a6ad8"),
    ("Azul", "#3f8be0"),
    ("Turquesa", "#2aa3a3"),
    ("Verde", "#4ba25a"),
    ("Ámbar", "#d99a2b"),
]


@dataclass
class Config:
    """Ajustes técnicos que se editan a mano en config.toml."""
    # --- voz
    # Micrófono: None = el predeterminado del sistema, o nombre/índice de --list-mics
    input_device: str | int | None = None
    model: str = "small"            # tiny, base, small, medium, large-v3-turbo...
    language: str = "es"
    device: str = "auto"            # "auto" (GPU NVIDIA si hay), "cuda" o "cpu"
    compute_type: str = "auto"      # "auto" = int8_float16 en GPU, int8 en CPU
    end_silence_ms: int = 1300      # silencio que termina la orden
    start_timeout_s: float = 8.0    # tiempo máximo esperando a que empieces a hablar
    max_utterance_s: float = 60.0
    vad_margin_db: float = 12.0
    vad_min_dbfs: float = -50.0
    # --- Claude
    claude_path: str = ""           # vacío = buscar `claude` en el PATH
    default_project: str = "~"

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        cfg = cls()
        if path.exists():
            known = {f.name for f in fields(cls)}
            for key, value in tomllib.loads(path.read_text()).items():
                if key in known:
                    setattr(cfg, key, value)
        return cfg


@dataclass
class State:
    """Lo que se cambia desde la propia app (Preferencias, proyecto…) y se recuerda."""
    project: str = ""
    recent_projects: list[str] = field(default_factory=list)
    accent: str = CLAUDE_ORANGE     # color principal
    color_scheme: str = "system"    # "system", "light" o "dark"
    accept_edits: bool = False
    auto_send: bool = True          # enviar lo dictado en cuanto termina la transcripción
    beep: bool = True

    @classmethod
    def load(cls) -> "State":
        try:
            data = json.loads(STATE_PATH.read_text())
            return cls(**{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False))

    def remember_project(self, path: str) -> None:
        self.project = path
        self.recent_projects = [path] + [p for p in self.recent_projects if p != path][:7]
        self.save()
