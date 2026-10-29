#!/usr/bin/env bash
# Instalador de Hi Claude! para Linux (probado en CachyOS/Arch + GNOME Wayland + PipeWire).
#   ./install.sh                 instala la app, los iconos y los atajos de GNOME
#   ./install.sh --no-shortcuts  sin tocar los atajos de teclado
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_ID="io.github.HiClaude"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
APP_DIR="$DATA_DIR/hi-claude"
BIN_DIR="$HOME/.local/bin"
CFG_DIR="$CONFIG_HOME/hi-claude"

say() { printf '\033[38;2;217;119;87m==>\033[0m %s\n' "$*"; }

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

# ------------------------------------------------------------------ versiones anteriores («Oye Claude»)
if [[ -f "$CONFIG_HOME/systemd/user/oye-claude.service" ]]; then
    say "Quitando el servicio en segundo plano de la versión 1"
    systemctl --user disable --now oye-claude.service 2>/dev/null || true
    rm -f "$CONFIG_HOME/systemd/user/oye-claude.service"
    systemctl --user daemon-reload
fi
if [[ -d "$DATA_DIR/oye-claude" && ! -d "$APP_DIR" ]]; then
    say "Migrando «Oye Claude» a «Hi Claude!» (se reutiliza el entorno ya descargado)"
    mv "$DATA_DIR/oye-claude" "$APP_DIR"
    rm -rf "$APP_DIR/oye_claude" "$APP_DIR/oye_claude.py"
fi
[[ -d "$CONFIG_HOME/oye-claude" && ! -d "$CFG_DIR" ]] && mv "$CONFIG_HOME/oye-claude" "$CFG_DIR"
[[ -d "$STATE_HOME/oye-claude" && ! -d "$STATE_HOME/hi-claude" ]] && mv "$STATE_HOME/oye-claude" "$STATE_HOME/hi-claude"
rm -f "$BIN_DIR/oye-claude" "$BIN_DIR/claude-voz" \
      "$DATA_DIR/applications/io.github.OyeClaude.desktop" \
      "$DATA_DIR/icons/hicolor/scalable/apps/io.github.OyeClaude.svg"

# ------------------------------------------------------------------ programa
say "Copiando la app a $APP_DIR"
mkdir -p "$APP_DIR" "$BIN_DIR" "$CFG_DIR"
rm -rf "$APP_DIR/hi_claude"
cp -r "$HERE/hi_claude" "$APP_DIR/hi_claude"
find "$APP_DIR/hi_claude" -name __pycache__ -prune -exec rm -rf {} +

# El venv usa los paquetes del sistema para GTK (python-gobject). Se rehace si Python
# cambió de versión (Arch lo actualiza a menudo) o si se creó sin acceso al sistema.
pyver() { "$1" -c 'import sys; print(*sys.version_info[:2])' 2>/dev/null; }
if [[ "$(pyver "$APP_DIR/venv/bin/python")" != "$(pyver python3)" ]] ||
   ! grep -q "include-system-site-packages = true" "$APP_DIR/venv/pyvenv.cfg" 2>/dev/null; then
    say "Creando entorno virtual de Python ($(python3 --version))"
    rm -rf "$APP_DIR/venv"
    python3 -m venv --system-site-packages "$APP_DIR/venv"
fi
PIP=("$APP_DIR/venv/bin/python" -m pip)  # no venv/bin/pip: su shebang apunta a la ruta antigua tras migrar
say "Instalando dependencias (Claude Agent SDK, faster-whisper, …)"
"${PIP[@]}" install -q --upgrade pip
"${PIP[@]}" install -q --upgrade -r "$HERE/requirements.txt"
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
    say "GPU NVIDIA detectada: instalando cuBLAS y cuDNN para Whisper (~1,2 GB la primera vez)"
    "${PIP[@]}" install -q -r "$HERE/requirements-gpu.txt"
fi

cat > "$BIN_DIR/hi-claude" <<EOF
#!/usr/bin/env bash
# Lanzador de Hi Claude! (generado por install.sh)
NV="\$(echo "$APP_DIR"/venv/lib/python*/site-packages/nvidia/*/lib | tr ' ' ':')"
[[ "\$NV" != *'*'* ]] && export LD_LIBRARY_PATH="\$NV\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export PYTHONPATH="$APP_DIR"
exec "$APP_DIR/venv/bin/python" -m hi_claude "\$@"
EOF
chmod 755 "$BIN_DIR/hi-claude"

if [[ ! -f "$CFG_DIR/config.toml" ]] || grep -q "^tmux_session" "$CFG_DIR/config.toml"; then
    [[ -f "$CFG_DIR/config.toml" ]] && mv "$CFG_DIR/config.toml" "$CFG_DIR/config.toml.v1"
    say "Creando configuración en $CFG_DIR/config.toml"
    sed "s|^claude_path = \"\"|claude_path = \"$(command -v claude)\"|" \
        "$HERE/config.example.toml" > "$CFG_DIR/config.toml"
fi

# ------------------------------------------------------------------ iconos y menú de aplicaciones
say "Instalando icono y entrada en el menú de aplicaciones"
install -Dm644 "$HERE/data/icons/$APP_ID.svg" "$DATA_DIR/icons/hicolor/scalable/apps/$APP_ID.svg"
gtk-update-icon-cache -q "$DATA_DIR/icons/hicolor" 2>/dev/null || true
# Variante monocroma para el tema de iconos YAMIS, si es el que usas
ICON_THEME="$(gsettings get org.gnome.desktop.interface icon-theme 2>/dev/null | tr -d "'")"
if [[ "$ICON_THEME" == "YAMIS" && -d "$DATA_DIR/icons/YAMIS/apps/scalable" ]]; then
    say "Tema YAMIS detectado: instalando la variante monocroma del icono"
    install -m644 "$HERE/data/icons/$APP_ID-yamis.svg" "$DATA_DIR/icons/YAMIS/apps/scalable/$APP_ID.svg"
    gtk-update-icon-cache -qf "$DATA_DIR/icons/YAMIS" 2>/dev/null || true
fi
mkdir -p "$DATA_DIR/applications"
sed "s|@BIN@|$BIN_DIR/hi-claude|g" "$HERE/data/$APP_ID.desktop" > "$DATA_DIR/applications/$APP_ID.desktop"
update-desktop-database -q "$DATA_DIR/applications" 2>/dev/null || true

say "Descargando el modelo de Whisper (solo la primera vez)"
PYTHONPATH="$APP_DIR" "$APP_DIR/venv/bin/python" - <<'EOF'
from faster_whisper import WhisperModel
from hi_claude.config import Config
cfg = Config.load()
print("  modelo:", cfg.model)
WhisperModel(cfg.model, device="cpu", compute_type="int8")
EOF

# ------------------------------------------------------------------ atajos de GNOME
if [[ "${1:-}" != "--no-shortcuts" ]] && command -v gsettings >/dev/null &&
   gsettings list-schemas | grep -qx org.gnome.settings-daemon.plugins.media-keys; then
    say "Configurando atajos: Super+C (abrir), Super+Alt+C (hablar), Ctrl+Super+C (recortar)"
    KEYS=org.gnome.settings-daemon.plugins.media-keys
    BASE=/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings
    current="$(gsettings get $KEYS custom-keybindings)"
    paths="$(python3 -c 'import ast, sys; c = sys.argv[1].removeprefix("@as ").strip(); print(*ast.literal_eval(c))' "$current")"
    # Si ya hay un atajo con esa combinación (de versiones anteriores o tuyo), se reutiliza.
    find_path() {
        for p in $paths; do
            [[ "$(gsettings get $KEYS.custom-keybinding:"$p" binding)" == "'$1'" ]] && { echo "$p"; return; }
        done
        echo "$BASE/$2/"
    }
    set_key() {  # atajo nombre-de-ruta nombre comando
        local p; p="$(find_path "$1" "$2")"
        gsettings set $KEYS.custom-keybinding:"$p" name "$3"
        gsettings set $KEYS.custom-keybinding:"$p" command "$4"
        gsettings set $KEYS.custom-keybinding:"$p" binding "$1"
        echo "$p"
    }
    new_paths=(
        "$(set_key '<Super>c' hi-claude 'Hi Claude!' "$BIN_DIR/hi-claude")"
        "$(set_key '<Super><Alt>c' hi-claude-voz 'Hi Claude! (voz)' "$BIN_DIR/hi-claude --voice")"
        "$(set_key '<Primary><Super>c' hi-claude-recorte 'Hi Claude! (recorte)' "$BIN_DIR/hi-claude --snip")"
    )
    gsettings set $KEYS custom-keybindings "$(python3 - "$current" "${new_paths[@]}" <<'EOF'
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
echo "  Super+C          abre Hi Claude!"
echo "  Super+Alt+C      abre Hi Claude! escuchando"
echo "  Ctrl+Super+C     recorta un trozo de pantalla y pregunta"
echo "  hi-claude .      abre la app en la carpeta actual"
