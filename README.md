# 🎙️ Oye Claude

Activa **Claude Code** en tu terminal con la voz. Di **«Oye Claude»** o **«Hey Claude»** seguido de lo que quieras y la orden aparece escrita (y enviada) en la terminal donde corre `claude`.

```
Tú:      «Oye Claude, revisa por qué fallan los tests»
Daemon:  🔔 → transcribe → escribe en la sesión tmux "claude" → Enter
Claude:  ● Voy a ejecutar los tests...
```

- 100 % local: la voz se transcribe en tu PC con [faster-whisper](https://github.com/SYSTRAN/faster-whisper). No se envía audio a ningún sitio.
- Usa la **GPU NVIDIA** si la hay (≈10× más rápido: la orden se transcribe en ~0,3 s) y si no, la CPU.
- Funciona en español e inglés y entiende variantes: «Hey Claude», «Oye Claude», «Ey Clod», «Ok Claude»…
- Arranca solo con la sesión gráfica (servicio systemd de usuario).
- Si Claude no está abierto, lo abre en una terminal nueva.

| Plataforma | Estado |
|---|---|
| Linux (Arch/CachyOS, GNOME Wayland, PipeWire) | ✅ [`linux/`](linux/) |
| Mantenimiento y diagnóstico | 📘 [docs/MANTENIMIENTO.md](docs/MANTENIMIENTO.md) |
| Windows | 🛠️ pendiente — ver [docs/MEMORIA-WINDOWS.md](docs/MEMORIA-WINDOWS.md) |

---

## Cómo funciona

```
 micrófono ──► VAD por energía ──► frase ──► Silero VAD ¿es voz? ──► Whisper "base" (primeros 2 s)
                                                   │
                                     ¿empieza por «oye/hey claude»?
                                         no │            │ sí
                                    (ignorar)            ▼
                                            ¿hay orden en la misma frase?
                                              sí │              │ no
                                                 │       🔔 pitido, escucha
                                                 │       la siguiente frase
                                                 ▼              ▼
                                         Whisper "small" transcribe la orden
                                                         │
                       tmux send-keys -t claude "orden" + Enter  ──►  Claude Code
```

1. **Escucha continua** con `sounddevice` a 16 kHz. Un detector de voz por energía calcula el ruido de fondo (percentil 15 de los últimos 5 s) y corta el audio en frases cuando hay ~0,7 s de silencio.
2. **Filtro de voz real**: Silero VAD (incluido en faster-whisper, ~10 ms) descarta teclado, golpes y ruido para no gastar CPU en Whisper.
3. **Detección de la palabra de activación**: cada frase con voz se pasa por Whisper `base` con 2 hilos (~1 s) y se busca con una expresión regular tolerante (`hey|oye|ey|ok…` + `claude|clod|cloud|claudio…`). Así no hace falta entrenar un modelo de wake word.
4. **Transcripción de la orden** con Whisper `small` (más preciso). Si dijiste solo «Oye Claude», suena un pitido y espera la orden hasta 8 s.
5. **Envío a Claude**: Claude Code corre dentro de una sesión de **tmux** llamada `claude`. El daemon escribe con `tmux send-keys`, que funciona igual en X11 y en Wayland (en Wayland las herramientas tipo `xdotool` no pueden escribir en otras ventanas).

### Órdenes especiales

| Dices | Hace |
|---|---|
| «Oye Claude, cancela» / «para» / «detente» | Pulsa `Esc` (interrumpe a Claude) |
| «Oye Claude, nueva conversación» / «limpia» | Envía `/clear` |

---

## Instalación en Linux

### 1. Requisitos

```bash
sudo pacman -S --needed tmux portaudio python
```

(Debian/Ubuntu: `sudo apt install tmux libportaudio2 python3-venv`)

Y Claude Code instalado (`claude` en el PATH):

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

### 2. Instalar

```bash
git clone https://github.com/9Dariuss/oye-claude.git
cd oye-claude/linux
./install.sh
```

El instalador:

- copia el daemon a `~/.local/share/oye-claude/` y crea un entorno virtual de Python con sus dependencias;
- crea los comandos `oye-claude` y `claude-voz` en `~/.local/bin/`;
- crea la configuración en `~/.config/oye-claude/config.toml`;
- si detecta una GPU NVIDIA (`nvidia-smi`), instala cuBLAS y cuDNN dentro del entorno virtual (~1,2 GB, sin tocar el sistema);
- descarga los modelos de Whisper (`base` ~150 MB, `small` ~480 MB, solo la primera vez);
- instala y arranca el servicio `oye-claude.service` de systemd (usuario).

Usa `./install.sh --no-service` si prefieres arrancarlo a mano con `oye-claude`.

### 3. Usar

Abre Claude en tu proyecto **a través de `claude-voz`** (en lugar de `claude`):

```bash
cd ~/mi-proyecto
claude-voz
```

`claude-voz` arranca Claude dentro de la sesión tmux `claude` (o se une a ella si ya existe). Ahora di:

> «Oye Claude, explícame la estructura de este proyecto»

Si no tienes ninguna sesión abierta, el daemon la crea en `workdir` (por defecto `~`) y abre una ventana de Alacritty conectada a ella.

> **Consejo tmux**: para salir de la ventana sin cerrar Claude pulsa `Ctrl+b` y luego `d`. Vuelve con `claude-voz`.

### 4. Comprobar y ajustar

```bash
oye-claude --list-devices     # lista micrófonos
oye-claude --test-mic         # barra de nivel en vivo; debe marcar VOZ solo al hablar
oye-claude --say "hola"       # prueba el envío a Claude sin usar la voz
journalctl --user -u oye-claude -f    # logs del servicio (lo que oye y lo que ignora)
```

Tras cambiar `~/.config/oye-claude/config.toml`:

```bash
systemctl --user restart oye-claude
```

Ajustes útiles:

| Clave | Para qué |
|---|---|
| `input_device` | Elegir micrófono (nombre o índice de `--list-devices`) |
| `vad_margin_db` | Súbelo (15–18) si el ruido corta mal las frases; bájalo si no te detecta |
| `device` | `auto` (GPU si hay), `cuda` o `cpu` |
| `command_model` | `medium` o `large-v3-turbo` para más precisión (con GPU va de sobra) |
| `claude_command` | p. ej. `"claude --continue"` para retomar la última conversación |
| `terminal` | `"kitty"`, `"gnome-terminal --"`, `"konsole -e"`… |
| `workdir` | Carpeta donde se abre Claude si no había sesión |

### Desinstalar

```bash
systemctl --user disable --now oye-claude
rm -rf ~/.local/share/oye-claude ~/.config/oye-claude ~/.local/bin/oye-claude ~/.local/bin/claude-voz ~/.config/systemd/user/oye-claude.service
```

---

## Problemas frecuentes

Guía completa paso a paso: **[docs/MANTENIMIENTO.md](docs/MANTENIMIENTO.md)**.

- **Tras actualizar Python con pacman deja de arrancar** → `~/oye-claude/linux/install.sh` rehace el entorno virtual.

- **No se activa nunca** → mira `journalctl --user -u oye-claude -f`. Si aparece `(ignorado) …` con lo que dijiste mal escrito, añade esa variante a `WAKE_RE` en `oye_claude.py`. Si no aparece nada, revisa `--test-mic`.
- **Se activa solo / con la tele** → sube `vad_margin_db`; el regex exige que la frase *empiece* con algo parecido a «oye/hey» + «claude».
- **La primera orden se pierde al abrir Claude** → sube `claude_startup_s` (Claude tarda en arrancar).
- **`claude` no encontrado en el servicio** → pon la ruta completa en `claude_command` (el instalador lo hace con `command -v claude`).
- **Pide confirmar confianza en la carpeta** → la primera vez que Claude se abre en una carpeta nueva pregunta si confías en ella; contesta en la ventana.

## Estructura del repo

```
linux/
  oye_claude.py          daemon (escucha, detecta, transcribe, envía)
  install.sh             instalador
  claude-voz             abre/une la sesión tmux "claude"
  oye-claude.service     servicio systemd de usuario
  config.example.toml    configuración con valores por defecto
  requirements.txt
  requirements-gpu.txt   cuBLAS/cuDNN para usar la GPU NVIDIA
docs/
  MANTENIMIENTO.md       guía paso a paso: uso, actualizaciones, diagnóstico
  MEMORIA-WINDOWS.md     contexto para portarlo a Windows con Claude
```

## Licencia

MIT
