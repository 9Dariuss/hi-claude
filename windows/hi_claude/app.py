"""Hi Claude!: Claude Code en una ventana de Windows, con voz y recortes de pantalla.

    hi-claude                 abre la app (o la trae al frente)
    hi-claude --voice         abre la app y empieza a escuchar
    hi-claude --snip          recorta un trozo de pantalla y pregunta a Claude por él
    hi-claude C:\\proyecto     abre la app en esa carpeta
    hi-claude --list-mics     lista los micrófonos (para input_device)
    hi-claude --atajos        registra los atajos globales (lo arranca Windows al iniciar sesión)
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import webview

from . import mainloop, winutil
from .chat import BG_DARK, BG_LIGHT, FG_DARK, FG_LIGHT, ChatController, ChatView, Voice, page_html
from .config import ACCENT_PRESETS, CACHE_DIR, CONFIG_PATH, DATA_DIR, Config, State
from .instance import Server, send_to_running

APP_NAME = "Hi Claude!"
VERSION = "3.0"
HERE = Path(__file__).parent
ICON = HERE / "hi-claude.ico"
MAX_CLAUDE_SIDE = 1568   # lado mayor recomendado para imágenes enviadas a Claude
MAX_PREVIEW_SIDE = 900
CONFIG_TEMPLATE = Path(__file__).resolve().parent.parent / "config.example.toml"


def pretty_path(path: str) -> str:
    return path.replace(str(Path.home()), "~", 1)


class Api:
    """Lo que chat.html puede llamar con window.pywebview.api.<método>().

    pywebview llama a estos métodos desde hilos sueltos: todos pasan al hilo de mainloop.
    (Los atributos empiezan por _ para que pywebview no los exponga a JS.)
    """

    def __init__(self, owner: "ChatWindow"):
        self._owner = owner

    def _do(self, name: str, *args) -> None:
        mainloop.idle_add(getattr(self._owner, name), *args)

    def ready(self): self._do("on_ready")
    def submit(self, text, via_voice=False): self._do("submit", str(text), bool(via_voice))
    def stop(self): self._do("stop")
    def escape(self): self._do("escape")
    def toggleVoice(self): self._do("toggle_voice")
    def newChat(self): self._do("new_chat")
    def chooseProject(self): self._do("choose_project")
    def openProject(self, path): self._do("set_project", str(path))
    def snip(self): mainloop.idle_add(self._owner.app.start_snip)
    def continueInMain(self): self._do("continue_in_main")
    def permission(self, req, response): self._do("answer_permission", str(req), str(response))
    def answer(self, req, index): self._do("answer_question", str(req), int(index))
    def setPref(self, key, value): mainloop.idle_add(self._owner.app.set_pref, str(key), value)
    def themeResolved(self, dark): self._do("apply_caption", bool(dark))
    def openConfig(self): mainloop.idle_add(self._owner.app.open_config)
    def copy(self, text): winutil.copy_text(str(text))

    def openUrl(self, url):
        url = str(url)
        if url.startswith(("http://", "https://", "mailto:")):
            webbrowser.open(url)


class ChatWindow:
    """Lo común a la ventana principal y a la del recorte: vista, Claude, micrófono y permisos."""

    compact = False

    def __init__(self, app: "App", project: str, title: str, width: int, height: int,
                 placeholder: str = "Escribe a Claude…"):
        self.app = app
        self.cfg, self.state = app.cfg, app.state
        self.project = project
        self.hwnd = 0
        self.closed = False
        self.view = ChatView()
        self.controller = ChatController(self.view, self.cfg, self.state, project, self._on_busy,
                                         self._on_finished, self.bring_to_front, self._on_model)
        self.voice = Voice(self.cfg, self.state, self.view, self.toast)
        dark = self._dark()
        self.window = webview.create_window(
            title, html=page_html(), js_api=Api(self), width=width, height=height, min_size=(420, 360),
            background_color=BG_DARK if dark else BG_LIGHT, text_select=True)
        self.view.window = self.window
        self.window.events.shown += lambda: mainloop.idle_add(self._on_shown)
        self.window.events.closed += lambda: mainloop.idle_add(self._on_closed)
        self.view.call("setAccent", self.state.accent, record=False)
        self.view.call("setScheme", self.state.color_scheme, record=False)
        self.view.call("setCompact", self.compact, record=False)
        self.view.call("setPlaceholder", placeholder, record=False)
        self.view.call("setPrefs", app.prefs_payload(), record=False)
        app.windows.append(self)

    # ------------------------------------------------------------------ ventana

    def _dark(self) -> bool:
        return self.state.color_scheme == "dark" or (self.state.color_scheme == "system" and winutil.system_dark())

    def _on_shown(self) -> None:
        try:
            self.hwnd = int(self.window.native.Handle.ToInt64())
        except Exception:
            self.hwnd = 0
        winutil.set_icon(self.hwnd, str(ICON))
        self.apply_caption(self._dark())
        self.bring_to_front()

    def on_ready(self) -> None:
        self.view.mark_ready()
        self.view.call("focusComposer", record=False)

    def apply_caption(self, dark: bool) -> None:
        winutil.set_caption(self.hwnd, dark, BG_DARK if dark else BG_LIGHT, FG_DARK if dark else FG_LIGHT)

    def bring_to_front(self) -> None:
        if self.closed:
            return
        try:
            self.window.restore()
        except Exception:
            pass
        winutil.bring_to_front(self.hwnd)

    def toast(self, text: str) -> None:
        self.view.call("toast", text, record=False)

    def close(self) -> None:
        try:
            self.window.destroy()
        except Exception:
            pass

    def _on_closed(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.voice.stop()
        self.controller.close()
        if self in self.app.windows:
            self.app.windows.remove(self)
        self.app.window_closed(self)

    # ------------------------------------------------------------------ Claude

    def _on_busy(self, busy: bool) -> None:
        pass

    def _on_model(self, model: str) -> None:
        pass

    def _on_finished(self, result: str) -> None:
        if not winutil.is_foreground(self.hwnd):
            winutil.flash(self.hwnd)

    def submit(self, text: str, via_voice: bool) -> None:
        if self.controller.busy:
            self.toast("Claude sigue trabajando: envíalo cuando termine")
            self.view.call("setComposerText", text, record=False)
            return
        self.controller.send(text, via_voice)

    def stop(self) -> None:
        if not self.voice.stop():
            self.controller.stop()

    def escape(self) -> None:
        self.stop()

    def toggle_voice(self) -> None:
        self.voice.toggle()

    def start_voice(self) -> None:
        self.bring_to_front()
        self.voice.start()

    def answer_permission(self, req: str, response: str) -> None:
        self.controller.answer_permission(req, response)

    def answer_question(self, req: str, index: int) -> None:
        self.controller.answer_question(req, index)

    # en la ventana del recorte no hay proyecto que cambiar ni conversación nueva
    def new_chat(self) -> None: ...
    def choose_project(self) -> None: ...
    def set_project(self, path: str) -> None: ...
    def continue_in_main(self) -> None: ...


class MainWindow(ChatWindow):
    def __init__(self, app: "App"):
        project = app.state.project or str(Path(app.cfg.default_project).expanduser())
        w, h = (app.state.window_size + [940, 800])[:2]
        super().__init__(app, project, APP_NAME, max(480, w), max(400, h))
        self.model = ""
        self.window.events.closing += self._remember_size
        self._update_project_ui()

    def _remember_size(self) -> None:
        try:
            if not self.window.maximized and not self.window.minimized:
                self.state.window_size = [int(self.window.width), int(self.window.height)]
                self.state.save()
        except Exception:
            pass

    def _update_project_ui(self) -> None:
        home = os.path.normcase(self.project) == os.path.normcase(str(Path.home()))
        title = APP_NAME if home else Path(self.project).name
        subtitle = pretty_path(self.project) + (f" · {self.model}" if self.model else "")
        self.view.call("setHeader", title, subtitle, record=False)
        self.view.call("setProject", pretty_path(self.project), record=False)
        self.view.call("setRecent", [[p, pretty_path(p)] for p in self.state.recent_projects], record=False)
        try:
            self.window.set_title(APP_NAME if home else f"{title} · {APP_NAME}")
        except Exception:
            pass

    def _on_model(self, model: str) -> None:
        if model:
            self.model = model
            self._update_project_ui()

    def new_chat(self) -> None:
        self.controller.new_chat(self.project)

    def choose_project(self) -> None:
        def ask():  # el diálogo bloquea: se abre fuera del hilo principal
            try:
                result = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=self.project)
            except Exception:
                return
            if result:
                mainloop.idle_add(self.set_project, str(result[0]))
        import threading
        threading.Thread(target=ask, daemon=True).start()

    def set_project(self, path: str) -> None:
        path = str(Path(path).expanduser())
        if not Path(path).is_dir():
            self.toast("Esa carpeta ya no existe")
            return
        self.project = path
        self.state.remember_project(path)
        self.model = ""
        self._update_project_ui()
        self.controller.new_chat(path)

    def continue_conversation(self, session_id: str | None, project: str, history: list[str]) -> None:
        """Trae aquí una conversación empezada en la ventana del recorte."""
        if project != self.project:
            self.project = project
            self.state.remember_project(project)
            self._update_project_ui()
        self.controller.new_chat(project, resume=session_id)
        self.view.replay(history)
        self.bring_to_front()


class QuickWindow(ChatWindow):
    """Ventanita para preguntar por un recorte; la respuesta aparece aquí mismo."""

    compact = True

    def __init__(self, app: "App", png_path: Path):
        from PIL import Image

        project = app.state.project or str(Path(app.cfg.default_project).expanduser())
        super().__init__(app, project, f"{APP_NAME} · Recorte", 560, 660, placeholder="Pregunta sobre la captura…")
        with Image.open(png_path) as img:
            img.load()
            self.png = self._png(img, MAX_CLAUDE_SIDE)
            preview = self._png(img, MAX_PREVIEW_SIDE)
        self.preview_uri = "data:image/png;base64," + base64.b64encode(preview).decode()
        self.view.call("setPreview", self.preview_uri, record=False)
        self.first = True

    @staticmethod
    def _png(img, max_side: int) -> bytes:
        img = img.convert("RGB")
        if max(img.size) > max_side:
            k = max_side / max(img.size)
            img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), 1)  # LANCZOS
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def submit(self, text: str, via_voice: bool) -> None:
        if self.first and not self.controller.busy:
            self.first = False
            self.view.call("markSent", record=False)
            self.controller.send(text, via_voice, image_png=self.png, image_uri=self.preview_uri)
        else:
            super().submit(text, via_voice)

    def escape(self) -> None:
        if self.voice.stop():
            return
        if self.controller.busy:
            self.controller.stop()
        else:
            self.close()

    def continue_in_main(self) -> None:
        if self.controller.busy:
            self.toast("Espera a que Claude termine")
            return
        self.app.continue_in_main(self.controller.claude.session_id, self.controller.project, list(self.view.history))
        self.close()


class App:
    def __init__(self):
        self.cfg = Config.load()
        self.state = State.load()
        self.windows: list[ChatWindow] = []
        self.main: MainWindow | None = None
        self._snipping = False

    # ------------------------------------------------------------------ ventanas

    def prefs_payload(self) -> dict:
        s = self.state
        return {"accent": s.accent, "color_scheme": s.color_scheme, "accept_edits": s.accept_edits,
                "auto_send": s.auto_send, "beep": s.beep, "presets": ACCENT_PRESETS, "version": VERSION,
                "hotkey_open": self.cfg.hotkey_open, "hotkey_voice": self.cfg.hotkey_voice,
                "hotkey_snip": self.cfg.hotkey_snip}

    def open_main(self) -> MainWindow:
        if self.main is None or self.main.closed:
            self.main = MainWindow(self)
        else:
            self.main.bring_to_front()
        return self.main

    def window_closed(self, win: ChatWindow) -> None:
        if win is self.main:
            self.main = None

    def command_line(self, args: list[str], cwd: str) -> None:
        if "--snip" in args:
            self.start_snip()
            return
        main = self.open_main()
        folders = [a for a in args if not a.startswith("-")]
        if folders:
            path = (Path(cwd) / folders[0]).expanduser().resolve()
            if path.is_dir() and str(path) != main.project:
                main.set_project(str(path))
        if "--voice" in args:
            main.start_voice()

    # ------------------------------------------------------------------ preferencias

    def set_pref(self, key: str, value) -> None:
        if key not in ("accent", "color_scheme", "accept_edits", "auto_send", "beep"):
            return
        if key == "accent":
            value = str(value).lower()
        setattr(self.state, key, value)
        self.state.save()
        payload = self.prefs_payload()
        for win in self.windows:
            if key == "accent":
                win.view.call("setAccent", value, record=False)
            elif key == "color_scheme":
                win.view.call("setScheme", value, record=False)
            elif key == "accept_edits":
                win.controller.claude.set_accept_edits(bool(value))
            win.view.call("setPrefs", payload, record=False)
        if key == "accept_edits" and self.main:
            self.main.toast("Claude editará archivos sin preguntar" if value else "Claude preguntará antes de editar")

    def open_config(self) -> None:
        if not CONFIG_PATH.exists():
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            text = CONFIG_TEMPLATE.read_text(encoding="utf-8") if CONFIG_TEMPLATE.exists() else ""
            CONFIG_PATH.write_text(text, encoding="utf-8")
        os.startfile(str(CONFIG_PATH))

    # ------------------------------------------------------------------ recorte

    def start_snip(self) -> None:
        if self._snipping:
            return
        self._snipping = True
        # si la ventana principal está delante, que no salga en la captura
        hide = [w for w in self.windows if winutil.is_foreground(w.hwnd)]
        for w in hide:
            w.window.minimize()
        import threading
        threading.Thread(target=self._snip_worker, args=(0.3 if hide else 0,), daemon=True).start()

    def _snip_worker(self, delay: float) -> None:
        time.sleep(delay)
        path = select_region(self.state.accent)
        mainloop.idle_add(self._snip_done, path)

    def _snip_done(self, path: Path | None) -> None:
        self._snipping = False
        if path is not None:
            QuickWindow(self, path)

    def continue_in_main(self, session_id: str | None, project: str, history: list[str]) -> None:
        self.open_main().continue_conversation(session_id, project, history)


def select_region(accent: str) -> Path | None:
    """Abre la selección a pantalla completa (otro proceso) y devuelve el PNG recortado, o None."""
    folder = CACHE_DIR / "recortes"
    folder.mkdir(parents=True, exist_ok=True)
    for old in sorted(folder.glob("*.png"))[:-19]:  # se guardan los últimos 20
        old.unlink(missing_ok=True)
    out = folder / time.strftime("recorte-%Y%m%d-%H%M%S.png")
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    result = subprocess.run([str(pyw if pyw.exists() else exe), str(HERE / "snip_overlay.py"), str(out), accent],
                            creationflags=0x08000000)  # CREATE_NO_WINDOW
    return out if result.returncode == 0 and out.exists() else None


# ---------------------------------------------------------------------- arranque

def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--list-mics" in args:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    winutil.set_app_id()
    winutil.allow_foreground()
    cwd = os.getcwd()
    server = Server(lambda a, c: mainloop.idle_add(app.command_line, a, c))
    if not server.claim():
        # ya hay una abierta: se le pasa la orden (con reintentos por si aún está arrancando)
        if send_to_running(args, cwd, tries=12):
            return 0
    app = App()
    mainloop.start()
    server.start()

    if "--snip" in args:
        path = select_region(app.state.accent)
        if path is None:
            return 0
        mainloop.idle_add(QuickWindow, app, path)
    else:
        mainloop.idle_add(app.command_line, args, cwd)

    # webview.start necesita una ventana creada antes de empezar
    deadline = time.monotonic() + 5
    while not app.windows and time.monotonic() < deadline:
        time.sleep(0.01)
    webview.start(gui="edgechromium", debug="HI_CLAUDE_DEBUG" in os.environ,
                  storage_path=str(DATA_DIR / "webview"))
    # al cerrar la última ventana no queda nada: ni micrófono ni procesos de Claude
    for win in list(app.windows):
        win.controller.close()
    return 0

