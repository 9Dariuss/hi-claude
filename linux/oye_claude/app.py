"""Oye Claude: Claude Code en una ventana de GNOME, con entrada por voz.

    oye-claude                 abre la app (o la trae al frente)
    oye-claude --voice         abre la app y empieza a escuchar
    oye-claude ~/proyecto      abre la app en esa carpeta
    oye-claude --list-mics     lista los micrófonos (para input_device)
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, WebKit  # noqa: E402

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from . import render  # noqa: E402
from .claude import ClaudeWorker  # noqa: E402
from .config import Config, State  # noqa: E402
from .voice import VoiceInput  # noqa: E402

APP_ID = "io.github.OyeClaude"
HERE = Path(__file__).parent

CSS = """
.composer { background: alpha(@view_fg_color, 0.06); border-radius: 24px; padding: 6px 6px 6px 16px; }
.composer textview, .composer textview text { background: transparent; }
.composer.listening { box-shadow: 0 0 0 2px @error_color; }
.mic-button.listening { background: @error_color; color: white; }
.status-label { font-size: 0.9em; }
"""


class ChatView(WebKit.WebView):
    def __init__(self):
        super().__init__()
        self._ready = False
        self._pending: list[str] = []
        settings = self.get_settings()
        settings.set_enable_developer_extras("OYE_CLAUDE_DEBUG" in os.environ)
        settings.set_javascript_can_open_windows_automatically(False)
        self.connect("load-changed", self._on_load)
        self.connect("decide-policy", self._on_policy)
        page = (HERE / "chat.html").read_text().replace("/*PYGMENTS*/", render.pygments_css())
        self.load_html(page, "file:///oye-claude/")

    def _on_load(self, _view, event):
        if event == WebKit.LoadEvent.FINISHED:
            self._ready = True
            for js in self._pending:
                self._eval(js)
            self._pending.clear()

    def _on_policy(self, _view, decision, kind):
        # los enlaces se abren en el navegador, nunca dentro de la app
        if kind == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith("file:///oye-claude/") and uri != "about:blank":
                Gtk.UriLauncher.new(uri).launch(self.get_root(), None, None, None)
                decision.ignore()
                return True
        return False

    def _eval(self, js: str) -> None:
        self.evaluate_javascript(js, -1, None, None, None, None, None)

    def set_dark(self, dark: bool) -> None:
        # mismo color que --bg en chat.html, para que no se vea un destello al cargar
        color = Gdk.RGBA()
        color.parse("#1d1d20" if dark else "#ffffff")
        self.set_background_color(color)
        self.call("setDark", dark)

    def call(self, fn: str, *args: Any) -> None:
        js = f"{fn}({', '.join(json.dumps(a, ensure_ascii=False) for a in args)})"
        if self._ready:
            self._eval(js)
        else:
            self._pending.append(js)


class Window(Adw.ApplicationWindow):
    def __init__(self, app: "App"):
        super().__init__(application=app, title="Oye Claude", default_width=920, default_height=780)
        self.cfg = app.cfg
        self.state = app.state
        self.project = self.state.project or str(Path(self.cfg.default_project).expanduser())
        self.started = 0.0
        self.stream_id: str | None = None
        self.stream_text = ""
        self.stream_dirty = False
        self.counter = 0
        self.last_was_voice = False

        self.claude = ClaudeWorker(self.on_message, self.on_claude_error, self.ask_permission, self.cfg.claude_path)
        self.claude.cwd = self.project
        self.claude.accept_edits = self.state.accept_edits
        self.voice = VoiceInput(self.cfg, self._voice_state, self._voice_text, self._voice_error)

        self._build()
        self._update_project_ui()
        self.connect("close-request", self._on_close)
        GLib.timeout_add(80, self._flush_stream)

    # ------------------------------------------------------------------ interfaz

    def _build(self) -> None:
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title="Claude")
        header.set_title_widget(self.title)

        # clic: elegir carpeta · flecha: proyectos recientes
        self.recent_menu = Gio.Menu()
        project_btn = Adw.SplitButton(icon_name="folder-open-symbolic", menu_model=self.recent_menu,
                                      tooltip_text="Cambiar de proyecto (Ctrl+O)", dropdown_tooltip="Proyectos recientes")
        project_btn.set_action_name("win.open-project")
        header.pack_start(project_btn)

        menu = Gio.Menu()
        menu.append("Aceptar ediciones sin preguntar", "win.accept-edits")
        menu.append("Atajos de teclado", "win.shortcuts")
        menu.append("Acerca de Oye Claude", "win.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menú"))
        new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Nueva conversación (Ctrl+N)")
        new_btn.set_action_name("win.new-chat")
        header.pack_end(new_btn)
        view.add_top_bar(header)

        self.chat = ChatView()
        self.chat.set_vexpand(True)
        view.set_content(self.chat)

        # --- barra inferior: [texto…] [🎙] [➤]
        bottom = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                         margin_start=16, margin_end=16, margin_bottom=12, margin_top=6)
        clamp = Adw.Clamp(maximum_size=780, child=bottom)

        self.status = Gtk.Label(xalign=0, css_classes=["dim-label", "status-label"], margin_start=16)
        self.status.set_visible(False)
        bottom.append(self.status)

        self.composer = Gtk.Box(spacing=6, css_classes=["composer"])
        self.input = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, top_margin=8, bottom_margin=8,
                                  accepts_tab=False)
        self.input.update_property([Gtk.AccessibleProperty.PLACEHOLDER], ["Pregunta o pide algo a Claude…"])
        placeholder = Gtk.Label(label="Pregunta o pide algo a Claude…", xalign=0, valign=Gtk.Align.START,
                                css_classes=["dim-label"], can_target=False, margin_top=8)
        overlay = Gtk.Overlay(child=self.input)
        overlay.add_overlay(placeholder)
        self.input.get_buffer().connect("changed", lambda b: placeholder.set_visible(b.get_char_count() == 0))
        scroller = Gtk.ScrolledWindow(child=overlay, hexpand=True, propagate_natural_height=True,
                                      max_content_height=200, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.composer.append(scroller)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.input.add_controller(keys)

        self.level = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER, width_request=60, visible=False)
        self.composer.append(self.level)
        self.mic_btn = Gtk.Button(icon_name="audio-input-microphone-symbolic", valign=Gtk.Align.END,
                                  css_classes=["circular", "flat", "mic-button"], tooltip_text="Hablar (Ctrl+M)")
        self.mic_btn.connect("clicked", lambda _b: self.toggle_voice())
        self.composer.append(self.mic_btn)
        self.send_btn = Gtk.Button(icon_name="go-up-symbolic", valign=Gtk.Align.END,
                                   css_classes=["circular", "suggested-action"], tooltip_text="Enviar (Intro)")
        self.send_btn.connect("clicked", lambda _b: self._on_send_clicked())
        self.composer.append(self.send_btn)
        bottom.append(self.composer)
        view.add_bottom_bar(clamp)

        # --- acciones y atajos
        def action(name, cb, accels=()):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            self.add_action(a)
            if accels:
                self.get_application().set_accels_for_action(f"win.{name}", list(accels))

        action("open-project", self.choose_project, ["<Ctrl>o"])
        action("new-chat", self.new_chat, ["<Ctrl>n"])
        action("voice", self.toggle_voice, ["<Ctrl>m"])
        action("stop", self.stop, ["Escape"])
        action("about", self._about)
        action("shortcuts", self._shortcuts, ["<Ctrl>question"])
        accept = Gio.SimpleAction.new_stateful("accept-edits", None, GLib.Variant.new_boolean(self.state.accept_edits))
        accept.connect("change-state", self._on_accept_edits)
        self.add_action(accept)
        open_recent = Gio.SimpleAction.new("open-recent", GLib.VariantType.new("s"))
        open_recent.connect("activate", lambda _a, v: self.set_project(v.get_string()))
        self.add_action(open_recent)

        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", lambda *_: self.chat.set_dark(style.get_dark()))
        style.connect("notify::accent-color-rgba", lambda *_: self._apply_accent())
        self.chat.set_dark(style.get_dark())
        self._apply_accent()
        self.input.grab_focus()

    def _apply_accent(self) -> None:
        rgba = Adw.StyleManager.get_default().get_accent_color_rgba()
        self.chat.call("setAccent", rgba.to_string())

    def _update_project_ui(self) -> None:
        name = Path(self.project).name or self.project
        pretty = self.project.replace(str(Path.home()), "~", 1)
        self.title.set_title(name if self.project != str(Path.home()) else "Claude")
        self.title.set_subtitle(pretty)
        self.chat.call("setProject", f"Proyecto: {pretty}")
        self.recent_menu.remove_all()
        for p in self.state.recent_projects:
            item = Gio.MenuItem.new(p.replace(str(Path.home()), "~", 1), None)
            item.set_action_and_target_value("win.open-recent", GLib.Variant.new_string(p))
            self.recent_menu.append_item(item)

    def _set_busy(self, busy: bool) -> None:
        self.chat.call("setBusy", busy)
        self.send_btn.set_icon_name("media-playback-stop-symbolic" if busy else "go-up-symbolic")
        self.send_btn.set_tooltip_text("Detener (Esc)" if busy else "Enviar (Intro)")
        self.send_btn.set_css_classes(["circular", "destructive-action" if busy else "suggested-action"])

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    # ------------------------------------------------------------------ proyecto / conversación

    def choose_project(self) -> None:
        dialog = Gtk.FileDialog(title="Elige la carpeta del proyecto", initial_folder=Gio.File.new_for_path(self.project))

        def done(d, result):
            try:
                folder = d.select_folder_finish(result)
            except GLib.Error:
                return
            self.set_project(folder.get_path())

        dialog.select_folder(self, None, done)

    def set_project(self, path: str) -> None:
        self.project = path
        self.state.remember_project(path)
        self._update_project_ui()
        self.new_chat()

    def new_chat(self) -> None:
        self.claude.new_conversation(self.project)
        self.chat.call("clearChat")
        self.stream_id = None
        self._set_busy(False)

    def _on_accept_edits(self, action, value) -> None:
        action.set_state(value)
        self.state.accept_edits = value.get_boolean()
        self.state.save()
        self.claude.set_accept_edits(self.state.accept_edits)
        self.toast("Claude editará archivos sin preguntar" if self.state.accept_edits
                   else "Claude preguntará antes de editar")

    # ------------------------------------------------------------------ enviar

    def _on_key(self, _ctrl, keyval, _code, state) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not state & Gdk.ModifierType.SHIFT_MASK:
            self._on_send_clicked()
            return True
        return False

    def _on_send_clicked(self) -> None:
        if self.claude.busy:
            self.stop()
        else:
            self.send_input()

    def send_input(self, via_voice: bool = False) -> None:
        buf = self.input.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
        if not text:
            return
        if self.claude.busy:
            self.toast("Claude sigue trabajando: envíalo cuando termine")
            return
        buf.set_text("")
        self.chat.call("addUser", text, via_voice)
        self.started = time.monotonic()
        self._set_busy(True)
        self.claude.busy = True  # evita doble envío antes de que el hilo lo marque
        self.claude.send(text)

    def stop(self) -> None:
        if self.voice.active:
            self.voice.stop()
        elif self.claude.busy:
            self.claude.interrupt()

    # ------------------------------------------------------------------ mensajes de Claude

    def _new_id(self) -> str:
        self.counter += 1
        return f"m{self.counter}"

    def _flush_stream(self) -> bool:
        if self.stream_dirty and self.stream_id:
            self.chat.call("setAssistant", self.stream_id, render.markdown(self.stream_text), True)
            self.stream_dirty = False
        return True

    def on_message(self, msg: Any) -> None:
        # Los subagentes trabajan "dentro" de su tarjeta: no se muestran sus mensajes sueltos.
        if getattr(msg, "parent_tool_use_id", None):
            return
        if isinstance(msg, StreamEvent):
            event = msg.event
            if event.get("type") == "content_block_start" and event.get("content_block", {}).get("type") == "text":
                self.stream_id, self.stream_text = self._new_id(), ""
            elif event.get("type") == "content_block_delta" and event.get("delta", {}).get("type") == "text_delta":
                if self.stream_id:
                    self.stream_text += event["delta"].get("text", "")
                    self.stream_dirty = True
        elif isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    block_id = self.stream_id or self._new_id()
                    self.chat.call("setAssistant", block_id, render.markdown(block.text), False)
                    self.stream_id, self.stream_dirty = None, False
                elif isinstance(block, ToolUseBlock):
                    icon, title, detail = render.describe_tool(block.name, block.input, self.project)
                    self.chat.call("addTool", block.id, icon, title, detail)
            if msg.error:
                self.chat.call("addNote", f"Error: {msg.error}", "error")
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    text = render.tool_result_text(block.content)
                    html = ""
                    if block.is_error and text:
                        html = f'<pre class="result err">{GLib.markup_escape_text(text[:3000])}</pre>'
                    self.chat.call("setToolResult", block.tool_use_id, not block.is_error, html)
        elif isinstance(msg, ResultMessage):
            self._finish_turn(msg)
        elif isinstance(msg, SystemMessage) and msg.subtype == "init":
            model = msg.data.get("model", "")
            if model:
                self.title.set_subtitle(f"{self.project.replace(str(Path.home()), '~', 1)} · {model}")

    def _finish_turn(self, msg: ResultMessage) -> None:
        if self.stream_id:  # texto que quedó a medias (p. ej. al interrumpir)
            self.chat.call("setAssistant", self.stream_id, render.markdown(self.stream_text), False)
            self.stream_id = None
        self.chat.call("finishRunningTools")
        self._set_busy(False)
        secs = msg.duration_ms / 1000
        if msg.subtype == "success" and not msg.is_error:
            self.chat.call("addDone", f"Hecho en {secs:.0f} s")
        elif msg.terminal_reason == "interrupted" or msg.subtype == "error_during_execution":
            self.chat.call("addNote", "Detenido", "")
        else:
            detail = "; ".join(msg.errors or []) or msg.result or msg.subtype
            self.chat.call("addNote", f"Claude no pudo terminar: {GLib.markup_escape_text(detail)}", "error")
        if not self.is_active():
            self._notify("Claude ha terminado", (msg.result or "")[:140])

    def on_claude_error(self, text: str) -> None:
        self._set_busy(False)
        self.chat.call("finishRunningTools")
        self.chat.call("addNote", f"Error: {GLib.markup_escape_text(text)}", "error")

    def _notify(self, title: str, body: str) -> None:
        n = Gio.Notification.new(title)
        n.set_body(body)
        self.get_application().send_notification("done", n)

    # ------------------------------------------------------------------ permisos

    def ask_permission(self, name: str, tool_input: dict, respond) -> None:
        if name == "AskUserQuestion":
            self._ask_questions(tool_input, respond)
            return
        heading, detail = render.permission_summary(name, tool_input, self.project)
        dialog = Adw.AlertDialog(heading=heading, body="Claude quiere hacer esto en tu proyecto.")
        label = Gtk.Label(label=detail, wrap=True, wrap_mode=2, xalign=0, yalign=0,
                          css_classes=["monospace"], margin_top=10, margin_bottom=10,
                          margin_start=12, margin_end=12)
        dialog.set_extra_child(Gtk.ScrolledWindow(child=label, propagate_natural_height=True, max_content_height=260,
                                                  hscrollbar_policy=Gtk.PolicyType.NEVER, css_classes=["card"]))
        dialog.add_response("deny", "Denegar")
        dialog.add_response("always", "Permitir siempre")
        dialog.add_response("allow", "Permitir")
        dialog.set_response_appearance("deny", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("allow", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("allow")
        dialog.set_close_response("deny")

        def on_response(_d, response):
            if response == "deny":
                respond(PermissionResultDeny(message="El usuario ha denegado el permiso"))
            else:
                respond(PermissionResultAllow(), always=response == "always")

        dialog.connect("response", on_response)
        self.present()
        dialog.present(self)

    def _ask_questions(self, tool_input: dict, respond) -> None:
        questions = list(tool_input.get("questions", []))
        answers: dict[str, str] = {}

        def ask_next():
            if not questions:
                respond(PermissionResultAllow(updated_input={**tool_input, "answers": answers}))
                return
            q = questions.pop(0)
            dialog = Adw.AlertDialog(heading=q.get("header") or "Claude pregunta", body=q.get("question", ""))
            options = q.get("options", [])[:4]
            for i, opt in enumerate(options):
                dialog.add_response(str(i), opt.get("label", f"Opción {i + 1}"))
            dialog.add_response("cancel", "Cancelar")
            dialog.set_close_response("cancel")
            if options:
                dialog.set_response_appearance("0", Adw.ResponseAppearance.SUGGESTED)

            def on_response(_d, response):
                if response == "cancel":
                    respond(PermissionResultDeny(message="El usuario no ha respondido"))
                    return
                answers[q.get("question", "")] = options[int(response)].get("label", "")
                ask_next()

            dialog.connect("response", on_response)
            dialog.present(self)

        self.present()
        ask_next()

    # ------------------------------------------------------------------ voz

    def toggle_voice(self) -> None:
        if self.voice.active:
            self.voice.stop()
        else:
            self.voice.start()

    def start_voice(self) -> None:
        if not self.voice.active:
            self.voice.start()

    def _voice_state(self, state: str) -> None:
        GLib.idle_add(self._apply_voice_state, state)

    def _apply_voice_state(self, state: str) -> bool:
        listening = state == "listening"
        for widget in (self.composer, self.mic_btn):
            (widget.add_css_class if listening else widget.remove_css_class)("listening")
        self.mic_btn.set_icon_name("media-playback-stop-symbolic" if listening else "audio-input-microphone-symbolic")
        self.mic_btn.set_tooltip_text("Terminar y transcribir" if listening else "Hablar (Ctrl+M)")
        self.level.set_visible(listening)
        self.status.set_visible(state != "idle")
        self.status.set_label({"listening": "🎙 Escuchando… habla y haz una pausa al terminar",
                               "transcribing": "✍️ Transcribiendo…"}.get(state, ""))
        if listening:
            GLib.timeout_add(50, self._update_level)
        return False

    def _update_level(self) -> bool:
        if not self.level.get_visible():
            return False
        self.level.set_value(min(1.0, max(0.0, (self.voice.level_db + 60) / 45)))
        return True

    def _voice_text(self, text: str) -> None:
        def apply():
            buf = self.input.get_buffer()
            current = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
            buf.set_text(f"{current} {text}".strip())
            if self.cfg.auto_send and not self.claude.busy:
                self.send_input(via_voice=True)
            else:
                self.input.grab_focus()
            return False
        GLib.idle_add(apply)

    def _voice_error(self, text: str) -> None:
        GLib.idle_add(lambda: self.toast(text) and False)

    # ------------------------------------------------------------------ varios

    def _on_close(self, *_):
        self.voice.stop()
        self.claude.shutdown()
        return False

    def _about(self) -> None:
        Adw.AboutDialog(
            application_name="Oye Claude", application_icon=APP_ID, developer_name="9Dariuss",
            version="2.0", website="https://github.com/9Dariuss/oye-claude",
            comments="Claude Code en una ventana, con entrada por voz local (faster-whisper).",
            license_type=Gtk.License.MIT_X11,
        ).present(self)

    def _shortcuts(self) -> None:
        rows = [("Super + C", "Abrir Oye Claude"), ("Super + Alt + C", "Abrir y hablar"),
                ("Intro", "Enviar"), ("Mayús + Intro", "Nueva línea"), ("Ctrl + M", "Hablar / terminar de hablar"),
                ("Esc", "Detener a Claude o la escucha"), ("Ctrl + N", "Nueva conversación"),
                ("Ctrl + O", "Cambiar de proyecto")]
        dialog = Adw.AlertDialog(heading="Atajos de teclado")
        grid = Gtk.Grid(column_spacing=24, row_spacing=8)
        for i, (keys, what) in enumerate(rows):
            grid.attach(Gtk.Label(label=keys, xalign=0, css_classes=["monospace"]), 0, i, 1, 1)
            grid.attach(Gtk.Label(label=what, xalign=0), 1, i, 1, 1)
        dialog.set_extra_child(grid)
        dialog.add_response("ok", "Cerrar")
        dialog.present(self)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.cfg = Config.load()
        self.state = State.load()
        self.window: Window | None = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def do_activate(self):
        if self.window is None:
            self.window = Window(self)
        self.window.present()

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        self.activate()
        folders = [a for a in args if not a.startswith("-")]
        if folders:
            path = Path(command_line.get_cwd() or ".", folders[0]).expanduser().resolve()
            if path.is_dir() and str(path) != self.window.project:
                self.window.set_project(str(path))
        if "--voice" in args:
            self.window.start_voice()
        return 0


def main() -> int:
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    if "--list-mics" in sys.argv:
        import sounddevice as sd
        print(sd.query_devices())
        return 0
    if Config.load().device != "cpu":
        from .voice import ensure_cuda_libs
        ensure_cuda_libs()
    return App().run(sys.argv)
