#!/usr/bin/env bash
# Instalador de Oye Claude para Linux (probado en CachyOS/Arch + GNOME Wayland + PipeWire).
#   ./install.sh            instala y activa el servicio
#   ./install.sh --no-service   instala sin arrancar el servicio systemd
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/oye-claude"
BIN_DIR="$HOME/.local/bin"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/oye-claude"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

say() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }

missing=()
for cmd in python3 tmux claude; do
    command -v "$cmd" >/dev/null || missing+=("$cmd")
done
if ((${#missing[@]})); then
    echo "Faltan: ${missing[*]}"
    echo "  tmux:   sudo pacman -S tmux      (Debian/Ubuntu: sudo apt install tmux)"
    echo "  claude: curl -fsSL https://claude.ai/install.sh | bash"
    exit 1
fi
# PortAudio lo necesita sounddevice
if ! ldconfig -p 2>/dev/null | grep libportaudio >/dev/null; then
    echo "Falta PortAudio: sudo pacman -S portaudio   (Debian/Ubuntu: sudo apt install libportaudio2)"
    exit 1
fi

say "Copiando archivos a $APP_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR" "$CFG_DIR" "$UNIT_DIR"
install -m 644 "$HERE/oye_claude.py" "$APP_DIR/oye_claude.py"
install -m 755 "$HERE/claude-voz" "$BIN_DIR/claude-voz"

# Tras actualizar Python con pacman (p. ej. 3.14 → 3.15) el venv queda roto: se rehace.
pyver() { "$1" -c 'import sys; print(*sys.version_info[:2])' 2>/dev/null; }
if [[ "$(pyver "$APP_DIR/venv/bin/python")" != "$(pyver python3)" ]]; then
    say "Creando entorno virtual de Python ($(python3 --version))"
    rm -rf "$APP_DIR/venv"
    python3 -m venv "$APP_DIR/venv"
fi
say "Instalando dependencias (faster-whisper, sounddevice)"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$HERE/requirements.txt"
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
    say "GPU NVIDIA detectada: instalando cuBLAS y cuDNN para Whisper (~1,2 GB la primera vez)"
    "$APP_DIR/venv/bin/pip" install -q -r "$HERE/requirements-gpu.txt"
fi

cat > "$BIN_DIR/oye-claude" <<EOF
#!/usr/bin/env bash
exec "$APP_DIR/venv/bin/python" -u "$APP_DIR/oye_claude.py" "\$@"
EOF
chmod 755 "$BIN_DIR/oye-claude"

if [[ ! -f "$CFG_DIR/config.toml" ]]; then
    say "Creando configuración en $CFG_DIR/config.toml"
    sed "s|^claude_command = \"claude\"|claude_command = \"$(command -v claude)\"|" \
        "$HERE/config.example.toml" > "$CFG_DIR/config.toml"
fi

say "Descargando modelos de Whisper (solo la primera vez)"
"$APP_DIR/venv/bin/python" - <<'EOF'
import tomllib, pathlib, os
from faster_whisper import WhisperModel
cfg = pathlib.Path(os.environ.get("XDG_CONFIG_HOME", pathlib.Path.home() / ".config")) / "oye-claude/config.toml"
data = tomllib.loads(cfg.read_text()) if cfg.exists() else {}
for name in {data.get("wake_model", "base"), data.get("command_model", "small")}:
    print("  modelo:", name)
    WhisperModel(name, device="cpu", compute_type="int8")
EOF

install -m 644 "$HERE/oye-claude.service" "$UNIT_DIR/oye-claude.service"
systemctl --user daemon-reload
if [[ "${1:-}" != "--no-service" ]]; then
    say "Activando servicio systemd de usuario"
    systemctl --user enable oye-claude.service
    systemctl --user restart oye-claude.service
    echo
    echo "Listo. Logs en vivo:  journalctl --user -u oye-claude -f"
else
    echo
    echo "Listo. Arráncalo a mano con:  oye-claude"
fi
echo "Abre Claude con voz en un proyecto:  cd ~/proyecto && claude-voz"
