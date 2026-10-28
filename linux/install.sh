#!/usr/bin/env bash
# Instalador de Oye Claude para Linux (probado en CachyOS/Arch + GNOME Wayland + PipeWire).
#   ./install.sh                 instala la app, el icono y los atajos de GNOME
#   ./install.sh --no-shortcuts  sin tocar los atajos de teclado
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_ID="io.github.OyeClaude"
APP_DIR="$HOME/.local/share/oye-claude"
BIN_DIR="$HOME/.local/bin"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/oye-claude"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"

say() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }

# ------------------------------------------------------------------ requisitos
missing=()
for cmd in python3 claude; do
    command -v "$cmd" >/dev/null || missing+=("$cmd")
done
ldconfig -p 2>/dev/null | grep libportaudio >/dev/null || missing+=("portaudio")
python3 - 2>/dev/null <<'EOF' || missing+=("gtk4 libadwaita webkitgtk-6.0 python-gobject")
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); gi.require_version("WebKit", "6.0")
from gi.repository import Gtk, Adw, WebKit
EOF
if ((${#missing[@]})); then
    echo "Faltan: ${missing[*]}"
    echo "  Arch/CachyOS:  sudo pacman -S --needed python python-gobject gtk4 libadwaita webkitgtk-6.0 portaudio"
    echo "  Debian/Ubuntu: sudo apt install python3-venv python3-gi gir1.2-adw-1 gir1.2-webkit-6.0 libportaudio2"
    echo "  Claude Code:   curl -fsSL https://claude.ai/install.sh | bash"
    exit 1
fi

# ------------------------------------------------------------------ versión 1 (daemon + tmux)
if [[ -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/oye-claude.service" ]]; then
    say "Quitando el servicio en segundo plano de la versión anterior"
    systemctl --user disable --now oye-claude.service 2>/dev/null || true
    rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/oye-claude.service"
    systemctl --user daemon-reload
fi
rm -f "$BIN_DIR/claude-voz" "$APP_DIR/oye_claude.py"

# ------------------------------------------------------------------ programa
say "Copiando la app a $APP_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR" "$CFG_DIR"
rm -rf "$APP_DIR/oye_claude"
cp -r "$HERE/oye_claude" "$APP_DIR/oye_claude"
find "$APP_DIR/oye_claude" -name __pycache__ -prune -exec rm -rf {} +

# El venv usa los paquetes del sistema para GTK (python-gobject). Se rehace si Python
# cambió de versión (Arch lo actualiza a menudo) o si se creó sin acceso al sistema.
pyver() { "$1" -c 'import sys; print(*sys.version_info[:2])' 2>/dev/null; }
if [[ "$(pyver "$APP_DIR/venv/bin/python")" != "$(pyver python3)" ]] ||
   ! grep -q "include-system-site-packages = true" "$APP_DIR/venv/pyvenv.cfg" 2>/dev/null; then
    say "Creando entorno virtual de Python ($(python3 --version))"
    rm -rf "$APP_DIR/venv"
    python3 -m venv --system-site-packages "$APP_DIR/venv"
fi
say "Instalando dependencias (Claude Agent SDK, faster-whisper, …)"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q --upgrade -r "$HERE/requirements.txt"
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
    say "GPU NVIDIA detectada: instalando cuBLAS y cuDNN para Whisper (~1,2 GB la primera vez)"
    "$APP_DIR/venv/bin/pip" install -q -r "$HERE/requirements-gpu.txt"
fi

cat > "$BIN_DIR/oye-claude" <<EOF
#!/usr/bin/env bash
# Lanzador de Oye Claude (generado por install.sh)
NV="\$(echo "$APP_DIR"/venv/lib/python*/site-packages/nvidia/*/lib | tr ' ' ':')"
[[ "\$NV" != *'*'* ]] && export LD_LIBRARY_PATH="\$NV\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export PYTHONPATH="$APP_DIR"
exec "$APP_DIR/venv/bin/python" -m oye_claude "\$@"
EOF
chmod 755 "$BIN_DIR/oye-claude"

if [[ ! -f "$CFG_DIR/config.toml" ]] || grep -q "^tmux_session" "$CFG_DIR/config.toml"; then
    [[ -f "$CFG_DIR/config.toml" ]] && mv "$CFG_DIR/config.toml" "$CFG_DIR/config.toml.v1"
    say "Creando configuración en $CFG_DIR/config.toml"
    sed "s|^claude_path = \"\"|claude_path = \"$(command -v claude)\"|" \
        "$HERE/config.example.toml" > "$CFG_DIR/config.toml"
fi

# ------------------------------------------------------------------ icono y menú de aplicaciones
say "Instalando icono y entrada en el menú de aplicaciones"
install -Dm644 "$HERE/data/$APP_ID.svg" "$DATA_DIR/icons/hicolor/scalable/apps/$APP_ID.svg"
mkdir -p "$DATA_DIR/applications"
sed "s|@BIN@|$BIN_DIR/oye-claude|g" "$HERE/data/$APP_ID.desktop" > "$DATA_DIR/applications/$APP_ID.desktop"
gtk-update-icon-cache -q "$DATA_DIR/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$DATA_DIR/applications" 2>/dev/null || true

say "Descargando el modelo de Whisper (solo la primera vez)"
PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" - <<'EOF'
from faster_whisper import WhisperModel
from oye_claude.config import Config
cfg = Config.load()
print("  modelo:", cfg.model)
WhisperModel(cfg.model, device="cpu", compute_type="int8")
EOF

# ------------------------------------------------------------------ atajos de GNOME
if [[ "${1:-}" != "--no-shortcuts" ]] && command -v gsettings >/dev/null &&
   gsettings list-schemas | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
    say "Configurando atajos: Super+C (abrir) y Super+Alt+C (hablar)"
    KEYS=org.gnome.settings-daemon.plugins.media-keys
    BASE=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
    current="$(gsettings get $KEYS custom-keybindings)"
    # Un atajo existente con <Super>c (p. ej. el que abría claude en la terminal) se reutiliza.
    open_path=""
    for p in $(python3 -c 'import ast, sys; c = sys.argv[1].removeprefix("@as ").strip(); print(*ast.literal_eval(c))' "$current"); do
        [[ "$(gsettings get $KEYS.custom-keybinding:"$p" binding)" == "'<Super>c'" ]] && open_path="$p"
    done
    open_path="${open_path:-$BASE/oye-claude/}"
    voice_path="$BASE/oye-claude-voz/"
    set_key() {  # ruta nombre comando atajo
        gsettings set $KEYS.custom-keybinding:"$1" name "$2"
        gsettings set $KEYS.custom-keybinding:"$1" command "$3"
        gsettings set $KEYS.custom-keybinding:"$1" binding "$4"
    }
    set_key "$open_path" "Oye Claude" "$BIN_DIR/oye-claude" "<Super>c"
    set_key "$voice_path" "Oye Claude (voz)" "$BIN_DIR/oye-claude --voice" "<Super><Alt>c"
    gsettings set $KEYS custom-keybindings "$(python3 - "$current" "$open_path" "$voice_path" <<'EOF'
import ast, sys
current = sys.argv[1].removeprefix("@as ").strip()
paths = ast.literal_eval(current) if current else []
for p in sys.argv[2:]:
    if p not in paths:
        paths.append(p)
print(paths)
EOF
)"
fi

echo
echo "Listo."
echo "  Super+C         abre Oye Claude"
echo "  Super+Alt+C     abre Oye Claude escuchando"
echo "  oye-claude .    abre la app en la carpeta actual"
