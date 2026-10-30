# Memoria del proyecto «Hi Claude!» — para portarlo a Windows

> **Cómo usar este archivo**: en Windows, abre Claude Code en una carpeta con este repo clonado y dile:
> *«Lee docs/MEMORIA-WINDOWS.md y haz la versión de Windows en la carpeta `windows/`»*.
> Todo el contexto necesario está aquí.

## Objetivo

**Hi Claude!** es una app de escritorio para usar Claude Code sin aspecto de terminal, legible, con tres atajos globales:

| Atajo en Linux | Qué hace |
|---|---|
| Super + C | Abre la app |
| Super + Alt + C | Abre la app **escuchando**: el usuario habla, hace una pausa, se transcribe y se envía |
| Ctrl + Super + C | **Recorte**: congela la pantalla, el usuario arrastra para seleccionar y, al soltar, sale una ventanita para preguntar a Claude por esa imagen. La respuesta aparece en la ventanita, con un botón para pasar la conversación a la ventana principal |

Más requisitos:
- **Nada en segundo plano**: el micrófono solo se abre al escuchar.
- **Idioma: español.**
- **La voz se transcribe en local** con faster-whisper.
- **Color principal**: naranja Claude `#d97757` por defecto, personalizable (8 colores predefinidos + selector libre) y aplicado a toda la interfaz.
- **Paleta cálida**: crema `#faf9f6` en claro y `#1f1e1c` en oscuro, más un modo claro/oscuro/sistema.

## Usuario y equipo

- Escribe en español.
- Linux: CachyOS + GNOME 51 Wayland.
- Dos monitores: 1920×1080 en (0,0) y 2560×1440 en (1920,149).
- Python 3.14, Ryzen 5 2600X (12 hilos), 16 GB de RAM, **RTX 3050 6 GB**.
- Micrófono **Razer Seiren Mini** (USB), con ganancia alta: ruido de fondo ~-38 dBFS.
- Tema de iconos **YAMIS**: monocromo, siluetas planas en `#d8dee9`, `class="ColorScheme-Text"` + `currentColor`, viewBox de 64 px y sin placa de fondo.

## Icono

Un estallido de rayos al estilo del logo de Claude, pero **original** (no se copia el logo, que es marca de Anthropic): los rayos largos son los dedos y el pulgar de una **mano saludando**, los cortos forman la palma, y hay tres líneas de movimiento. Está en `linux/data/icons/`:
- `io.github.HiClaude.svg`: naranja sobre una placa crema;
- `io.github.HiClaude-yamis.svg`: la variante monocroma;
- `generar_iconos.py`: genera ambos.

En Windows hará falta un `.ico` (multi-tamaño, p. ej. con Pillow desde el PNG que da `rsvg-convert`/`cairosvg`).

## Versión Linux actual (v3, `linux/hi_claude/`) — funcionando y probada

| Archivo | Qué hace | ¿Portable? |
|---|---|---|
| `claude.py` | `ClaudeWorker`: el Claude Agent SDK (`ClaudeSDKClient`) en un hilo con su propio event loop asyncio. API: `send(text, images)`, `interrupt`, `new_conversation(cwd, resume=session_id)`, `set_accept_edits`. Las imágenes van como bloques `{"type":"image","source":{"type":"base64",...}}` en un mensaje de entrada por streaming. `can_use_tool` crea un `asyncio.Future` y espera la respuesta de la UI (`respond(result, always)`). Las herramientas de solo lectura no preguntan. | Sí, cambiando `GLib.idle_add` |
| `chat.py` | `ChatView` (WebKit + mensajes JS → Python con `window.webkit.messageHandlers.hi`; guarda el `history` de llamadas JS para pasar una conversación a otra ventana), `Composer` (texto + 🎙 + enviar/detener), `ChatController` (mensajes del SDK → vista, streaming cada 80 ms, permisos, `AskUserQuestion`). Lo usan la ventana principal y la del recorte. | La lógica de `ChatController` sí |
| `snip.py` | Captura con el portal `org.freedesktop.portal.Screenshot` (no interactivo; borra el archivo que el portal deja en Imágenes). `SnipOverlay`: una ventana a pantalla completa por monitor (`fullscreen_on_monitor`) con su trozo de captura, oscurecida, y selección con `GestureDrag` y cairo. `QuickWindow`: vista previa → chat compacto; envía la imagen (lado máximo 1568 px) con la primera pregunta. | No (rehacer) |
| `theme.py` | El color principal en GTK (`--accent-bg-color`) y la paleta cálida, que se elige desde Python según `Adw.StyleManager.get_dark()`. Avisa a las ChatView (`setDark`, `setAccent`). | Idea sí |
| `render.py` | Markdown → HTML (`markdown-it-py` con `html=False` + tablas; Pygments) y `describe_tool()` («Leyendo `x`», diffs…). | 100 % |
| `chat.html` | La vista: paleta con variables CSS y `color-mix()` derivado de `--accent`, avatar con la mano (`hand.svg`), herramientas en línea de tiempo, pantalla de inicio con sugerencias que se pueden pulsar, burbuja de usuario con imagen. JS: `addUser(text, viaVoz, imagenDataUri)`, `setAssistant`, `addTool`, `setToolResult`, `finishRunningTools`, `addNote`, `addDone`, `setBusy`, `setDark`, `setAccent`, `setCompact`, `setProject`, `clearChat`. | 100 % |
| `voice.py` | Micrófono + VAD por energía, faster-whisper con GPU y vuelta a CPU, un único modelo compartido (`get_transcriber`), `clean_command()`. | Sí, salvo `ensure_cuda_libs` |
| `config.py` | `Config` (TOML técnico) y `State` (JSON: proyecto, recientes, `accent`, `color_scheme`, `accept_edits`, `auto_send`, `beep`). | Rutas: `%APPDATA%` / `%LOCALAPPDATA%` |
| `app.py` | `MainWindow` (GTK4/libadwaita), `PreferencesDialog` (muestras de color + `Gtk.ColorDialogButton`, estilo, interruptores), `App` (instancia única por D-Bus con `--voice` y `--snip`; minimiza la ventana principal antes de capturar). | No |
| `install.sh` | venv con `--system-site-packages`, lanzador `hi-claude`, `.desktop`, icono (más la variante en YAMIS si es el tema activo), 3 atajos con `gsettings` (reutiliza los que ya tengan la misma combinación) y migración desde «Oye Claude». | No |

Flujo de mensajes del SDK que maneja la UI:

- `StreamEvent` `content_block_start`(text) / `content_block_delta`(text_delta): texto en vivo.
- `AssistantMessage`: `TextBlock` fija el texto y `ToolUseBlock` crea una tarjeta.
- `UserMessage` con `ToolResultBlock`: marca la tarjeta con ✓ o ✗.
- `ResultMessage`: «Hecho en N s», «Detenido» o un error.
- Se ignoran los mensajes con `parent_tool_use_id` (subagentes).

## Plan para Windows

**Recomendación: reutilizar `claude.py`, `render.py`, `chat.html`, `voice.py`, `config.py` y la lógica de `ChatController`, y cambiar solo las ventanas.**

| Linux | Windows |
|---|---|
| GTK4 + WebKitGTK (`app.py`, `chat.py`) | **pywebview** (Edge WebView2, incluido en Windows 10/11) cargando el mismo `chat.html`. El cuadro de texto, los botones y las Preferencias pasan a ser HTML dentro de la propia página, y JS → Python con `window.pywebview.api`. Alternativa: PySide6 + `QWebEngineView`. |
| `GLib.idle_add` | `window.evaluate_js(...)` es thread-safe en pywebview; basta con una función `ui_call`. |
| `Adw.AlertDialog` (permisos) | Un diálogo modal en HTML/CSS dentro de `chat.html` que responde por la API JS → Python. |
| `theme.py` (CSS de GTK) | Todo es HTML: basta `setAccent` / `setDark`. Para el modo del sistema, leer `AppsUseLightTheme` del registro o usar `prefers-color-scheme` en WebView2. |
| Recorte: portal + `SnipOverlay` | Captura con **`mss`** (todos los monitores; ojo con el escalado por monitor: llamar a `SetProcessDpiAwareness(2)` al arrancar) y selección en una ventana **tkinter** sin bordes, a pantalla completa y siempre encima, por monitor (o una sola que cubra el escritorio virtual) con la imagen y un `Canvas`. Alternativa: `QWidget` de PySide6. |
| Instancia única por D-Bus | Mutex con nombre (`CreateMutexW`) + named pipe o socket local en `127.0.0.1` para pasarle `--voice` / `--snip` a la instancia abierta. |
| Atajos con `gsettings` | Accesos directos del menú Inicio con «Tecla de método abreviado» (solo **Ctrl+Alt+letra**). Para usar la tecla Windows, un script de **AutoHotkey v2** en `shell:startup`: `#c::`, `#!c::`, `^#c::`. Ojo: **Ctrl+Win+C** activa los filtros de color de Windows si están habilitados (Configuración → Accesibilidad → Filtros de color → desactivar su atajo). |
| `ensure_cuda_libs` (LD_LIBRARY_PATH + `os.execv`) | `os.add_dll_directory()` sobre cada `site-packages/nvidia/*/bin` **antes** de importar faster_whisper. |
| `install.sh` | `install.ps1`: venv en `%LOCALAPPDATA%\hi-claude`, `pip install -r requirements.txt pywebview mss`, accesos directos `.lnk` (`WScript.Shell`) con el `.ico`, y `requirements-gpu.txt` si existe `nvidia-smi`. |
| `claude_path` | `claude.exe` (Claude Code nativo de Windows), o lo que devuelva `where claude`. |

## Lecciones aprendidas (¡no repetir errores!)

1. **No usar `initial_prompt` en Whisper**: con ruido devuelve el prompt tal cual. Hay que filtrar segmentos con `no_speech_prob >= 0.6` o `avg_logprob <= -1.0`.
2. **Ruido de fondo = percentil 15 de los últimos 5 s** de niveles, no una media «fuera de la voz»: con un micro de ganancia alta todo parecía voz y el umbral nunca se adaptaba.
3. Python 3.14 funciona: hay ruedas de `ctranslate2`, `faster-whisper`, `sounddevice` y `claude-agent-sdk`.
4. **GPU**: RTX 3050 con `int8_float16` → `small` tarda 0,28 s por frase (en CPU, 2,6 s). VRAM ~420 MB. cuBLAS/cuDNN se instalan con pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12` 9.x). Si la GPU falla al cargar (driver recién actualizado), se vuelve a la CPU.
5. **v1 descartada (etiqueta `v1-tmux`; la v2 «Oye Claude» está en `v2-oye-claude`)**: un daemon que escuchaba siempre «Oye Claude» con Whisper. Gastaba CPU con cualquier conversación cercana (Discord, vídeos) y necesitaba tmux para escribir en la terminal (en Wayland no se puede inyectar teclado). El usuario prefirió **atajo + app propia**.
6. **Agent SDK**:
   - Pon `setting_sources=["user","project","local"]` para que respete el `CLAUDE.md` y los permisos del usuario como el CLI.
   - `include_partial_messages=True` da el streaming.
   - `can_use_tool` no se llama en `bypassPermissions`.
   - Para `AskUserQuestion`, se responde con `PermissionResultAllow(updated_input={**input, "answers": {pregunta: etiqueta}})`. **Sin probar todavía** con una pregunta real de Claude.
7. En WebKit, el color de fondo oscuro debe ir en `<html>` y no solo en `<body>`, o queda una franja blanca bajo la conversación.
8. Una etiqueta seleccionable dentro de un diálogo recibe el foco y aparece con todo el texto seleccionado: mejor no seleccionable.
9. Para probar la UI sin tocarla: `Gtk.WidgetPaintable` + `renderer.render_texture()` → PNG. En Windows, pywebview no tiene equivalente directo: usar una captura de la ventana con `PIL.ImageGrab`.
10. El instalador debe **rehacer el venv** si cambió la versión de Python del sistema. Al mover un venv de carpeta, `venv/bin/pip` queda roto (su shebang apunta a la ruta antigua): usa siempre `venv/bin/python -m pip`.
11. **GTK no aplica `@media (prefers-color-scheme: dark)`** según `Adw.StyleManager`: la paleta se genera desde Python con `get_dark()` y se recarga en `notify::dark`. Si no, la cabecera queda clara con el texto claro.
12. **Portal de capturas en GNOME**: la primera captura no interactiva pide permiso al usuario (unos 10 s hasta que acepta); después tarda ~0,6 s. Devuelve una sola imagen con todos los monitores (4480×1589 aquí); para repartirla, usa la caja que los envuelve según `Gdk.Monitor.get_geometry()`.
13. Antes de capturar, minimiza la ventana principal si está delante, o saldrá en la captura.
14. Para pasar una conversación a otra ventana: guarda las llamadas JS de contenido (`history`) y repítelas, y retoma la sesión del SDK con `resume=session_id`. Los ids de los bloques llevan `id(controller)` para que no choquen.

## Estado en Windows (v3.0, `windows/`) — hecho y probado en Windows 11

- [x] `windows/hi_claude/app.py` con pywebview + diálogo de permisos y Preferencias en HTML
- [x] Instancia única con `--voice`, `--snip` y carpeta reenviados a la ventana abierta (mutex + named pipe, ~1 s)
- [x] Recorte: `mss` + selección a pantalla completa por monitor (tkinter, proceso aparte) + ventanita de chat con la imagen + ⤢ para seguir en la principal
- [x] `windows/install.ps1` + `Instalar Hi Claude.cmd` + `desinstalar.ps1` + icono `.ico` + accesos directos + atajos globales propios (sin AutoHotkey)
- [x] Probado: texto con streaming, tablas y código; Permitir / Permitir siempre / Denegar; AskUserQuestion; Preferencias (color, oscuro); voz en CPU (transcripción local de una frase en español en 2 s); recorte en los dos monitores; instalador en una carpeta de prueba
- [ ] Sin probar todavía: Claude real de punta a punta desde la app instalada (en el PC de prueba Claude Code no tenía sesión iniciada fuera de la app de escritorio), voz con GPU NVIDIA, un atajo pulsado con el teclado de verdad

## Lecciones de Windows

1. **Atajos**: `RegisterHotKey` falla con Win+C (Copilot) y Ctrl+Win+C (filtros de color): error 1409, ya registrados. Win+Shift+C también está cogido. Libres: Win+Alt+C/V/X/S, Ctrl+Alt+C. Por eso los atajos de Windows son **Win+Alt+C / V / X**, configurables (`hotkey_*`).
2. Para que funcionen con la app cerrada hace falta algo residente: en vez de AutoHotkey, `hi-claude --atajos` (ctypes `RegisterHotKey` + `GetMessageW`, dormido) desde un acceso directo en `shell:startup`. Llama a `AllowSetForegroundWindow(ASFW_ANY)` antes de avisar a la app para que pueda ponerse delante. Importa lo mínimo (no `voice`, que trae numpy).
3. **pywebview** (6.x, WinForms + WebView2) funciona con Python 3.14 (pythonnet 3.2). `window.run_js()` no espera respuesta: va bien para el streaming. Los atributos de la clase de la API deben empezar por `_` o pywebview intenta exponerlos a JS.
4. Toda la lógica de la interfaz corre en un hilo propio (`mainloop.py`, el equivalente a `GLib.idle_add`/`timeout_add`): la API de JS llega desde hilos sueltos de pywebview y el SDK desde su hilo asyncio.
5. **No uses `keys` como nombre de función global en chat.html**: en WebView2 choca con algo del entorno («keys is not a function»). Se llama `kbd()`.
6. `navigator.clipboard` no funciona en una página cargada con `html=` (no es contexto seguro): copiar va por la API de Python (`win32clipboard`).
7. **Barra de título**: `DwmSetWindowAttribute` con `DWMWA_CAPTION_COLOR` (35) y `DWMWA_TEXT_COLOR` (36) la pinta del color de fondo de la app en Windows 11 (crema / `#1f1e1c`), y `DWMWA_USE_IMMERSIVE_DARK_MODE` (20) la oscurece en Windows 10. El `hwnd` sale de `window.native.Handle`.
8. Icono en la barra de tareas: `SetCurrentProcessExplicitAppUserModelID` (si no, sale el de Python) + `WM_SETICON` con el `.ico`.
9. El `.ico` se dibuja con Pillow (`windows/data/generar_ico.py`) con la misma geometría que el SVG: en Windows no hay rsvg/cairo.
10. Recorte: con `SetProcessDpiAwarenessContext(-4)` (per-monitor v2) `mss` y la geometría de tkinter usan píxeles reales y cuadran en monitores con distinto escalado. El trozo sin oscurecer se rehace con un `after(16)` para no saturar.
11. **WebView2 deja de pintar las ventanas tapadas**: las capturas con `PrintWindow` salen viejas. Para pruebas automáticas: `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows`.
12. **Claude Code dentro de la app de escritorio de Claude** no deja sesión iniciada para el CLI: `claude auth status` → `loggedIn: false` aunque exista `~/.claude/.credentials.json`. Hi Claude! necesita `claude auth login` una vez; el instalador lo detecta y lo lanza. El Agent SDK trae su propio `claude.exe` (firmado por Anthropic), así que no hace falta instalar Claude Code aparte.
13. Los procesos lanzados desde la app de escritorio de Claude (MSIX) ven `%LOCALAPPDATA%` y `%APPDATA%` **virtualizados** (`Packages\Claude_…\LocalCache`): instalar desde ahí no deja nada visible para el usuario. El instalador lo tiene que ejecutar el usuario (doble clic).
14. Con `pythonw` no hay `sys.stderr`: se redirige a `hi-claude.log` (`launch.py`). El comando `hi-claude.cmd` usa `python.exe` para ver los mensajes en la terminal.
15. Los `.ps1` con tildes deben guardarse en **UTF-8 con BOM**, o PowerShell 5.1 los lee como ANSI.
16. Smart App Control: Python de python.org, el `claude.exe` del SDK y WebView2 están firmados; las ruedas de pip (numpy, ctranslate2, pillow…) cargaron sin problema en un equipo con Smart App Control activado.
17. faster-whisper descarga el modelo con avisos de enlaces simbólicos (Windows sin modo desarrollador): son inofensivos; `HF_HUB_DISABLE_SYMLINKS_WARNING=1` los calla.
