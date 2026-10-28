# Memoria del proyecto «Oye Claude» — para portarlo a Windows

> **Cómo usar este archivo**: en Windows, abre Claude Code en una carpeta con este repo clonado y dile:
> *«Lee docs/MEMORIA-WINDOWS.md y haz la versión de Windows en la carpeta `windows/`»*.
> Todo el contexto necesario está aquí.

## Objetivo

Una **app de escritorio** para usar Claude Code sin aspecto de terminal, más legible, con **entrada por voz al pulsar un atajo**:

- un atajo **abre la app**;
- otro atajo **abre la app escuchando**: el usuario habla, hace una pausa, se transcribe y se envía.

Nada en segundo plano: el micrófono solo se abre al escuchar. Idioma: **español**. La voz se transcribe en local (faster-whisper).

## Usuario y equipo

- Escribe en español.
- Linux: CachyOS + GNOME Wayland.
- Python 3.14, Ryzen 5 2600X (12 hilos), 16 GB de RAM, **RTX 3050 6 GB**.
- Micrófono **Razer Seiren Mini** (USB), con ganancia alta: ruido de fondo ~-38 dBFS.
- Atajos en Linux: **Super+C** abre la app y **Super+Alt+C** la abre escuchando (elegidos por el usuario).

## Versión Linux actual (v2, `linux/oye_claude/`) — funcionando y probada

| Archivo | Qué hace | ¿Portable? |
|---|---|---|
| `claude.py` | `ClaudeWorker`: el Claude Agent SDK (`ClaudeSDKClient`) en un hilo con su propio event loop asyncio. API: `send`, `interrupt`, `new_conversation(cwd)`, `set_accept_edits`. Reenvía cada mensaje a la UI con `GLib.idle_add`. `can_use_tool` crea un `asyncio.Future`, pide a la UI un diálogo y espera la respuesta (`respond(result, always)`). Las herramientas de solo lectura (Read, Glob, Grep, WebSearch, TodoWrite, Task…) no preguntan. | Sí, cambiando `GLib.idle_add` por el mecanismo de la UI nueva |
| `render.py` | Markdown → HTML (`markdown-it-py` con `html=False` + tablas; Pygments para el código); `describe_tool()` da icono/título/detalle por herramienta («Leyendo `x`», «Editando `x`» con diff rojo/verde, «Ejecutando: …»); `permission_summary()` da el texto de los diálogos. | 100 % |
| `chat.html` | Vista del chat: CSS con variables (modo claro/oscuro con la clase `dark` en `<html>`, color de acento) y funciones JS: `addUser`, `setAssistant(id, html, streaming)`, `addTool`, `setToolResult`, `finishRunningTools`, `addNote`, `addDone`, `setBusy`, `setDark`, `setAccent`, `setProject`, `clearChat`. | 100 % |
| `voice.py` | `Listener` (micrófono + VAD por energía), `Transcriber` (faster-whisper con GPU y vuelta a CPU), `VoiceInput` (una toma por hilo con callbacks `on_state` "listening"/"transcribing"/"idle", `on_text`, `on_error`; carga el modelo mientras ya graba), `clean_command()` (quita un «Oye Claude,» inicial). | Sí, salvo `ensure_cuda_libs` |
| `config.py` | `Config` (TOML) y `State` (JSON: último proyecto, recientes, `accept_edits`). | Rutas de Windows: `%APPDATA%` / `%LOCALAPPDATA%` |
| `app.py` | Ventana **GTK4 + libadwaita** con un WebKit WebView para el chat, cuadro de texto (Intro envía, Mayús+Intro nueva línea), botón 🎙 con barra de nivel, botón enviar/detener, botón de proyecto con recientes, diálogos `Adw.AlertDialog` para permisos y para `AskUserQuestion`, notificación al terminar si la ventana no está activa. Instancia única con `Gtk.Application` + `HANDLES_COMMAND_LINE`: `--voice` en una segunda llamada hace que la ventana existente escuche. | **No** (GTK en Windows es mala idea) |
| `install.sh` | venv con `--system-site-packages` (para `gi`), lanzador `~/.local/bin/oye-claude`, `.desktop` + icono SVG, atajos con `gsettings` (reutiliza el que ya tuviera Super+C), retira el servicio de la v1. | No |

Flujo de mensajes del SDK que maneja la UI:

- `StreamEvent` `content_block_start`(text) / `content_block_delta`(text_delta): texto en vivo, que se repinta cada 80 ms.
- `AssistantMessage`: `TextBlock` fija el texto final y `ToolUseBlock` crea una tarjeta.
- `UserMessage` con `ToolResultBlock`: marca la tarjeta con ✓ o ✗.
- `ResultMessage`: «Hecho en N s», «Detenido» o un error.
- Se ignoran los mensajes con `parent_tool_use_id` (subagentes).

## Plan para Windows

**Recomendación: reutilizar `claude.py`, `render.py`, `chat.html`, `voice.py` y `config.py`, y cambiar solo la ventana.**

| Linux | Windows |
|---|---|
| GTK4 + WebKitGTK (`app.py`) | **pywebview** (usa Edge WebView2, ya incluido en Windows 10/11) cargando el mismo `chat.html`. El cuadro de texto y los botones pasan a ser HTML dentro de la propia página, y JS → Python con `window.pywebview.api`. Alternativa: PySide6 + `QWebEngineView`. |
| `GLib.idle_add` | `window.evaluate_js(...)` es thread-safe en pywebview; basta con una función `ui_call`. |
| `Adw.AlertDialog` (permisos) | Un diálogo modal en HTML/CSS dentro de `chat.html` (más bonito y portable) que responde por la API JS → Python. |
| Instancia única por D-Bus | Mutex con nombre (`CreateMutexW`) + named pipe o socket local en `127.0.0.1` para pasarle `--voice` a la instancia abierta. |
| Atajos con `gsettings` | Acceso directo en el menú Inicio con «Tecla de método abreviado» (solo permite **Ctrl+Alt+letra**: p. ej. Ctrl+Alt+C abrir y Ctrl+Alt+V voz). Si se quiere la tecla Windows: un pequeño script de **AutoHotkey v2** (`#c::`, `#!c::`) en `shell:startup`. |
| `ensure_cuda_libs` (LD_LIBRARY_PATH + `os.execv`) | `os.add_dll_directory()` sobre cada `site-packages/nvidia/*/bin` **antes** de importar faster_whisper (no hace falta relanzar). |
| `install.sh` | `install.ps1`: venv en `%LOCALAPPDATA%\oye-claude`, `pip install -r requirements.txt pywebview`, accesos directos `.lnk` (con `WScript.Shell`) en el menú Inicio, y `requirements-gpu.txt` si `nvidia-smi` existe. |
| `claude_path` | `claude.exe` (Claude Code nativo de Windows), o lo que devuelva `where claude`. |

## Lecciones aprendidas (¡no repetir errores!)

1. **No usar `initial_prompt` en Whisper**: con ruido devuelve el prompt tal cual. Hay que filtrar segmentos con `no_speech_prob >= 0.6` o `avg_logprob <= -1.0`.
2. **Ruido de fondo = percentil 15 de los últimos 5 s** de niveles, no una media «fuera de la voz»: con un micro de ganancia alta todo parecía voz y el umbral nunca se adaptaba.
3. Python 3.14 funciona: hay ruedas de `ctranslate2`, `faster-whisper`, `sounddevice` y `claude-agent-sdk`.
4. **GPU**: RTX 3050 con `int8_float16` → `small` tarda 0,28 s por frase (en CPU, 2,6 s). VRAM ~420 MB. cuBLAS/cuDNN se instalan con pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12` 9.x). Si la GPU falla al cargar (driver recién actualizado), se vuelve a la CPU.
5. **v1 descartada (etiqueta `v1-tmux`)**: un daemon que escuchaba siempre «Oye Claude» con Whisper. Gastaba CPU con cualquier conversación cercana (Discord, vídeos) y necesitaba tmux para escribir en la terminal (en Wayland no se puede inyectar teclado). El usuario prefirió **atajo + app propia**.
6. **Agent SDK**:
   - Pon `setting_sources=["user","project","local"]` para que respete el `CLAUDE.md` y los permisos del usuario como el CLI.
   - `include_partial_messages=True` da el streaming.
   - `can_use_tool` no se llama en `bypassPermissions`.
   - Para `AskUserQuestion`, se responde con `PermissionResultAllow(updated_input={**input, "answers": {pregunta: etiqueta}})`. **Sin probar todavía** con una pregunta real de Claude.
7. En WebKit, el color de fondo oscuro debe ir en `<html>` y no solo en `<body>`, o queda una franja blanca bajo la conversación.
8. Una etiqueta seleccionable dentro de un diálogo recibe el foco y aparece con todo el texto seleccionado: mejor no seleccionable.
9. Para probar la UI sin tocarla: `Gtk.WidgetPaintable` + `renderer.render_texture()` → PNG. En Windows, pywebview no tiene equivalente directo: usar una captura de la ventana con `PIL.ImageGrab`.
10. El instalador debe **rehacer el venv** si cambió la versión de Python del sistema.

## Checklist al terminar en Windows

- [ ] `windows/app.py` con pywebview + diálogo de permisos en HTML (añadir los controles de entrada a `chat.html` o a una copia)
- [ ] Instancia única y `--voice` reenviado a la ventana abierta
- [ ] `windows/install.ps1` + accesos directos con atajo (o script AutoHotkey)
- [ ] Probar: enviar texto, permiso de edición, interrumpir, voz con GPU y sin GPU
- [ ] Actualizar la tabla de plataformas y añadir «Instalación en Windows» en el `README.md`
- [ ] Añadir aquí las lecciones nuevas de Windows
