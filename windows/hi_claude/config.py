"""Configuración (%APPDATA%\\hi-claude\\config.toml) y preferencias guardadas (%LOCALAPPDATA%\\hi-claude)."""

from __future__ import annotations

import json
import os
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "hi-claude" / "config.toml"
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "hi-claude"
STATE_PATH = DATA_DIR / "state.json"
CACHE_DIR = DATA_DIR / "cache"
LOG_PATH = DATA_DIR / "hi-claude.log"

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
    claude_path: str = ""           # vacío = `claude` del PATH o, si no hay, el que trae el Agent SDK
    default_project: str = "~"
    # --- atajos globales (los registra `hi-claude --atajos`, que arranca con Windows)
    hotkey_open: str = "Win+Alt+C"
    hotkey_voice: str = "Win+Alt+V"
    hotkey_snip: str = "Win+Alt+X"

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> "Config":
        cfg = cls()
        if path.exists():
            known = {f.name for f in fields(cls)}
            for key, value in tomllib.loads(path.read_text(encoding="utf-8")).items():
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
    window_size: list[int] = field(default_factory=lambda: [940, 800])

    @classmethod
    def load(cls) -> "State":
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in {f.name for f in fields(cls)}})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")

    def remember_project(self, path: str) -> None:
        self.project = path
        self.recent_projects = [path] + [p for p in self.recent_projects if p != path][:7]
        self.save()
