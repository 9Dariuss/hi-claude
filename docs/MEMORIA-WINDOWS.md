# Memoria del proyecto «Oye Claude» — para portarlo a Windows

> **Cómo usar este archivo**: en Windows, abre Claude Code en una carpeta con este repo clonado y dile:
> *«Lee docs/MEMORIA-WINDOWS.md y haz la versión de Windows en la carpeta `windows/`»*.
> Todo el contexto necesario está aquí.

## Objetivo

Que Claude Code se active por voz: al decir **«Hey Claude» / «Oye Claude»** (y variantes) la orden que sigue se escribe y se envía en la terminal donde corre `claude`. Idioma principal: **español** (también inglés). Todo local, sin enviar audio a la nube.

## Lo que ya existe (Linux, `linux/`) — funcionando

- Equipo original: CachyOS (Arch), GNOME **Wayland**, PipeWire, Python 3.14, 12 núcleos, 16 GB RAM, sin GPU usada (CPU int8). Shell del usuario: fish. Terminal: Alacritty.
- Micrófono: **Razer Seiren Mini** (USB). Ruido de fondo medido: ~-38 dBFS (ganancia alta), voz a ~-25 dBFS o más.
- `linux/oye_claude.py` es el daemon. Partes:
  1. `Listener` — `sounddevice.InputStream` 16 kHz mono, tramas de 30 ms. VAD por energía: ruido = **percentil 15 de los últimos 5 s** de niveles; voz = nivel > ruido + 12 dB (y > -50 dBFS). Frase empieza tras 3 tramas de voz (con 300 ms de pre-roll) y termina con 700 ms de silencio (1300 ms para la orden).
  2. `Transcriber` — faster-whisper: `base` (2 hilos) para buscar la palabra de activación en los 2 primeros segundos, solo si Silero VAD confirma voz, `small` (beam 5) para la orden. `cpu_threads = núcleos/2`. Tiempos medidos: `base` ~0,9 s, `small` ~2,6 s por frase de 2 s.
  3. `WAKE_RE` — regex tolerante: `(hey|hei|ei|ey|oye|oie|ok|okay|hola…)` + `(claude|claud|claudio|clod|cloud|clau…)`. Si hay texto después → es la orden; si no → pitido y escucha la siguiente frase (máx 8 s).
  4. Órdenes especiales: «cancela/para/detente» → `Escape`; «nueva conversación/limpia» → `/clear`.
  5. `ClaudeSession` — **la única parte específica de Linux**: Claude corre en una sesión **tmux** llamada `claude`; se escribe con `tmux send-keys -l -- texto`, pausa 0,2 s, `send-keys Enter`. Si no existe la sesión, la crea (`tmux new-session -d -s claude -c workdir claude`) y abre `alacritty -e tmux attach -t claude`; tras crearla espera `claude_startup_s` (5 s) antes de escribir.
  6. Notificaciones con `notify-send`; pitidos generados con numpy + `sd.play`.
- Config en `~/.config/oye-claude/config.toml` (ver `linux/config.example.toml`), cargada con `tomllib` sobre una dataclass `Config`.
- Autoarranque: servicio systemd de usuario (`WantedBy=graphical-session.target`).
- `claude-voz`: script que abre/une la sesión tmux `claude` en la carpeta actual — el usuario lo usa en lugar de `claude`.

## Lecciones aprendidas (¡no repetir errores!)

1. **No usar `initial_prompt` con «Oye Claude» en Whisper**: con ruido, Whisper devuelve el prompt tal cual → falsas activaciones. Se quitó el prompt y se filtran segmentos con `no_speech_prob >= 0.6` o `avg_logprob <= -1.0`.
2. **El ruido de fondo no se puede aprender solo "fuera de la voz"** partiendo de -60 dB: con un micro de ganancia alta todo parecía voz y el umbral nunca se adaptaba. Solución: percentil bajo de una ventana deslizante.
3. Whisper escribe «Claude» de muchas formas con acento español (Clod, Cloud, Claudio…): por eso un regex amplio en vez de un modelo de wake word entrenado (openWakeWord/Porcupine requieren entrenar o licencia para «Oye Claude»).
4. En Wayland no se puede inyectar teclado en otras ventanas sin ydotool/permisos → por eso tmux. **En Windows sí se puede** (SendInput), así que tmux no es imprescindible.
5. Python 3.14 funciona: hay ruedas de `ctranslate2`, `faster-whisper`, `sounddevice`.
6. Hay que pausar ~0,2 s entre pegar el texto y pulsar Enter, o Claude Code puede tratarlo como pegado sin enviar.
7. **Consumo de CPU**: la primera versión gastaba ~85 % de un núcleo en reposo porque el VAD por energía se disparaba cada ~2,5 s con ruido y cada disparo lanzaba Whisper con 6 hilos. Solución: (a) filtro **Silero VAD** (`faster_whisper.vad.get_speech_timestamps`, ~10 ms) y solo se usa Whisper si hay ≥ 0,3 s de voz real; (b) el modelo de activación con `cpu_threads=2` (≈30 % menos CPU total que 6 hilos, +0,3 s de latencia); (c) ventana de activación de 2 s. Resultado: ~1,5 % de CPU en silencio. Cuando hay gente hablando cerca (Discord, vídeos) sí sube: es inherente a usar Whisper como detector.
8. Medido en Ryzen 5 2600X (CPU, int8): `base` 2 hilos ≈ 3 s de CPU / 1,3 s de espera por frase de 2 s; `tiny` ≈ 1,8 s / 0,6 s. **GPU (hecho)**: con la RTX 3050 (`device="cuda"`, `int8_float16`) `base` tarda 0,08 s y `small` 0,28 s por frase, con ~4× menos CPU; VRAM ~580 MB ambos modelos. cuBLAS/cuDNN se instalan con pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12` 9.x) dentro del venv. En Linux hace falta ponerlas en `LD_LIBRARY_PATH` antes de arrancar: `ensure_cuda_libs()` las añade y relanza el proceso con `os.execv`. **En Windows** el equivalente es `os.add_dll_directory()` sobre cada `site-packages/nvidia/*/bin` antes de importar faster_whisper (no hace falta relanzar). Si la GPU falla al cargar, se vuelve a CPU automáticamente.
9. El instalador debe **rehacer el venv** si la versión de Python del sistema cambió (Arch actualiza Python con frecuencia) y **reiniciar** el servicio (no solo `enable --now`) para cargar el código nuevo.

## Plan para Windows (`windows/`)

Reutilizar `oye_claude.py` casi entero (audio, VAD, Whisper, regex, `dispatch`, config son portables). Cambiar solo:

| Linux | Windows |
|---|---|
| `ClaudeSession` con tmux | `ClaudeWindow`: busca la ventana de Windows Terminal con título **«Claude (voz)»** con `pywinauto` (o `pywin32`), la trae al frente y escribe |
| abrir `alacritty -e tmux attach` | `wt.exe new-tab --title "Claude (voz)" --suppressApplicationTitle -d <workdir> claude` |
| `notify-send` | toast con `win11toast` o `plyer` (opcional) |
| systemd de usuario | Tarea programada «al iniciar sesión» (`schtasks /Create /SC ONLOGON …` con `pythonw.exe`) o acceso directo en `shell:startup` |
| `install.sh` | `install.ps1` (venv en `%LOCALAPPDATA%\oye-claude`, comandos en un dir del PATH, config en `%APPDATA%\oye-claude\config.toml`) |
| `claude-voz` | `claude-voz.cmd`: `wt -w 0 new-tab --title "Claude (voz)" --suppressApplicationTitle -d "%CD%" claude %*` |

### Escritura en la ventana (recomendado)

- Enfocar: `SetForegroundWindow` falla si el proceso no tiene el foco; truco habitual: enviar un `Alt` con `keybd_event` antes, o usar `pywinauto` `win.set_focus()`.
- Escribir: **pegar desde el portapapeles** (guardar portapapeles → poner texto → `Ctrl+V` → restaurar) es más fiable que teclear carácter a carácter con acentos/ñ. Luego 0,2 s y `Enter`. Para «cancela» → `Esc`.
- `--suppressApplicationTitle` es importante: si no, Claude Code cambia el título de la pestaña y no se encuentra la ventana. Alternativa: buscar por proceso hijo `claude.exe`.
- Alternativa sin foco: si el usuario usa Claude dentro de **WSL**, se puede mantener tmux y llamar `wsl.exe tmux send-keys …` desde el daemon en Windows (el audio siempre en el lado Windows; WSL tiene mal acceso al micro).

### Dependencias Windows

```
faster-whisper  sounddevice  numpy  pywinauto  pyperclip  (opcional: win11toast)
```
`sounddevice` trae PortAudio incluido en Windows. Si hay GPU NVIDIA: `device="cuda", compute_type="float16"` acelera mucho (requiere cuDNN/cuBLAS de CUDA 12).

### Checklist al terminar en Windows

- [ ] `windows/oye_claude.py` (o refactor a módulo común + backend por plataforma)
- [ ] `windows/install.ps1`, `windows/claude-voz.cmd`, `windows/config.example.toml`
- [ ] Probar: `--list-devices`, `--test-mic`, `--say "hola"`, y la activación real por voz
- [ ] Actualizar la tabla de plataformas y añadir sección «Instalación en Windows» en el `README.md`
- [ ] Añadir aquí las lecciones nuevas de Windows
