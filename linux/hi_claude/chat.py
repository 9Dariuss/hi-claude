"""Piezas de chat que comparten la ventana principal y la ventana rápida del recorte."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from gi.repository import Adw, Gdk, Gio, GLib, Gtk, WebKit

from claude_agent_sdk import (
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

from . import render
from .claude import ClaudeWorker
from .config import Config, State
from .voice import VoiceInput

HERE = Path(__file__).parent
BASE_URI = "file:///hi-claude/"
# fondo de la vista web = --bg de chat.html, para que no destelle al cargar
BG_LIGHT, BG_DARK = "#faf9f6", "#1f1e1c"


class ChatView(WebKit.WebView):
    """La conversación, dibujada en HTML. call() llama a las funciones JS de chat.html."""

    def __init__(self, on_suggestion: Callable[[str], None] | None = None):
        super().__init__()
        self._ready = False
        self._pending: list[str] = []
        self.history: list[str] = []  # llamadas de contenido, para pasar la conversación a otra ventana
        self.on_suggestion = on_suggestion
        settings = self.get_settings()
        settings.set_enable_developer_extras("HI_CLAUDE_DEBUG" in os.environ)
        settings.set_javascript_can_open_windows_automatically(False)
        manager = self.get_user_content_manager()
        manager.register_script_message_handler("hi", None)
        manager.connect("script-message-received::hi", self._on_script_message)
        self.connect("load-changed", self._on_load)
        self.connect("decide-policy", self._on_policy)
        hand = (HERE / "hand.svg").read_text()
        page = ((HERE / "chat.html").read_text()
                .replace("/*PYGMENTS*/", render.pygments_css())
                .replace("/*HAND*/", hand))
        self.load_html(page, BASE_URI)

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
            if not uri.startswith(BASE_URI) and uri != "about:blank":
                Gtk.UriLauncher.new(uri).launch(self.get_root(), None, None, None)
                decision.ignore()
                return True
        return False

    def _on_script_message(self, _manager, value) -> None:
        try:
            msg = json.loads(value.to_string())
        except ValueError:
            return
        if msg.get("type") == "suggest" and self.on_suggestion:
            self.on_suggestion(msg.get("text", ""))

    def _eval(self, js: str) -> None:
        self.evaluate_javascript(js, -1, None, None, None, None, None)

    def call(self, fn: str, *args: Any, record: bool = True) -> None:
        js = f"{fn}({', '.join(json.dumps(a, ensure_ascii=False) for a in args)})"
        if record:
            self.history.append(js)
        if self._ready:
            self._eval(js)
        else:
            self._pending.append(js)

    def replay(self, history: list[str]) -> None:
        for js in history:
            self.history.append(js)
            if self._ready:
                self._eval(js)
            else:
                self._pending.append(js)

    def set_theme(self, dark: bool, accent: str) -> None:
        color = Gdk.RGBA()
        color.parse(BG_DARK if dark else BG_LIGHT)
        self.set_background_color(color)
        self.call("setDark", dark, record=False)
        self.call("setAccent", accent, record=False)


class Composer(Gtk.Box):
    """Cuadro de texto con micrófono y botón enviar/detener."""

    def __init__(self, cfg: Config, state: State, on_submit: Callable[[str, bool], None],
                 on_stop: Callable[[], None], on_error: Callable[[str], None],
                 placeholder: str = "Escribe a Claude…"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.state = state
        self.on_submit, self.on_stop, self.on_error = on_submit, on_stop, on_error
        self.busy = False

        self.status = Gtk.Label(xalign=0, css_classes=["composer-status"], visible=False, margin_start=14)
        self.append(self.status)

        self.box = Gtk.Box(spacing=6, css_classes=["composer"])
        self.input = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, hexpand=True, top_margin=9, bottom_margin=9,
                                  accepts_tab=False)
        self.input.update_property([Gtk.AccessibleProperty.PLACEHOLDER], [placeholder])
        hint = Gtk.Label(label=placeholder, xalign=0, valign=Gtk.Align.START, css_classes=["dim-label"],
                         can_target=False, margin_top=9)
        overlay = Gtk.Overlay(child=self.input)
        overlay.add_overlay(hint)
        self.input.get_buffer().connect("changed", lambda b: hint.set_visible(b.get_char_count() == 0))
        self.box.append(Gtk.ScrolledWindow(child=overlay, hexpand=True, propagate_natural_height=True,
                                           max_content_height=200, hscrollbar_policy=Gtk.PolicyType.NEVER))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.input.add_controller(keys)

        self.level = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER, width_request=56, visible=False)
        self.box.append(self.level)
        self.mic_btn = Gtk.Button(icon_name="audio-input-microphone-symbolic", valign=Gtk.Align.END,
                                  css_classes=["circular", "flat", "mic-button"], tooltip_text="Hablar (Ctrl+M)")
        self.mic_btn.connect("clicked", lambda _b: self.toggle_voice())
        self.box.append(self.mic_btn)
        self.send_btn = Gtk.Button(icon_name="go-up-symbolic", valign=Gtk.Align.END,
                                   css_classes=["circular", "suggested-action", "send-button"],
                                   tooltip_text="Enviar (Intro)")
        self.send_btn.connect("clicked", lambda _b: self.on_stop() if self.busy else self.submit())
        self.box.append(self.send_btn)
        self.append(self.box)

        self.voice = VoiceInput(cfg, self._voice_state, self._voice_text, self._voice_error)

    # ---------------------------------------------------------------- texto

    def text(self) -> str:
        buf = self.input.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()

    def set_text(self, text: str) -> None:
        self.input.get_buffer().set_text(text)

    def _on_key(self, _ctrl, keyval, _code, mods) -> bool:
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not mods & Gdk.ModifierType.SHIFT_MASK:
            if not self.busy:
                self.submit()
            return True
        return False

    def submit(self, via_voice: bool = False) -> None:
        text = self.text()
        if text and not self.busy:
            self.set_text("")
            self.on_submit(text, via_voice)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.send_btn.set_icon_name("media-playback-stop-symbolic" if busy else "go-up-symbolic")
        self.send_btn.set_tooltip_text("Detener (Esc)" if busy else "Enviar (Intro)")
        (self.send_btn.add_css_class if busy else self.send_btn.remove_css_class)("busy")

    def focus(self) -> None:
        self.input.grab_focus()

    # ---------------------------------------------------------------- voz

    def toggle_voice(self) -> None:
        if self.voice.active:
            self.voice.stop()
        else:
            self.start_voice()

    def start_voice(self) -> None:
        if not self.voice.active:
            self.voice.beep = self.state.beep
            self.voice.start()

    def stop_voice(self) -> bool:
        if self.voice.active:
            self.voice.stop()
            return True
        return False

    def _voice_state(self, state: str) -> None:
        GLib.idle_add(self._apply_voice_state, state)

    def _apply_voice_state(self, state: str) -> bool:
        listening = state == "listening"
        for widget in (self.box, self.mic_btn):
            (widget.add_css_class if listening else widget.remove_css_class)("listening")
        self.mic_btn.set_icon_name("media-playback-stop-symbolic" if listening else "audio-input-microphone-symbolic")
        self.mic_btn.set_tooltip_text("Terminar y transcribir" if listening else "Hablar (Ctrl+M)")
        self.level.set_visible(listening)
        self.status.set_visible(state != "idle")
        self.status.set_label({"listening": "Escuchando… haz una pausa al terminar",
                               "transcribing": "Transcribiendo…"}.get(state, ""))
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
            self.set_text(f"{self.text()} {text}".strip())
            if self.state.auto_send and not self.busy:
                self.submit(via_voice=True)
            else:
                self.focus()
            return False
        GLib.idle_add(apply)

    def _voice_error(self, text: str) -> None:
        GLib.idle_add(lambda: self.on_error(text) and False)


class ChatController:
    """Une una ChatView con un ClaudeWorker: envía, muestra la respuesta y pide permisos."""

    def __init__(self, window: Gtk.Window, view: ChatView, cfg: Config, state: State,
                 project: str, on_busy: Callable[[bool], None],
                 on_model: Callable[[str], None] | None = None):
        self.window, self.view, self.state = window, view, state
        self.project = project
        self.on_busy = on_busy
        self.on_model = on_model or (lambda _m: None)
        self.stream_id: str | None = None
        self.stream_text = ""
        self.stream_dirty = False
        self.counter = 0
        self.claude = ClaudeWorker(self.on_message, self.on_error, self.ask_permission, cfg.claude_path)
        self.claude.cwd = project
        self.claude.accept_edits = state.accept_edits
        self._timer = GLib.timeout_add(80, self._flush_stream)

    @property
    def busy(self) -> bool:
        return self.claude.busy

    def send(self, text: str, via_voice: bool = False, image_png: bytes | None = None,
             image_uri: str | None = None) -> None:
        if self.claude.busy:
            return
        self.view.call("addUser", text, via_voice, image_uri)
        self._set_busy(True)
        self.claude.busy = True  # evita doble envío antes de que el hilo lo marque
        self.claude.send(text, [image_png] if image_png else [])

    def stop(self) -> None:
        if self.claude.busy:
            self.claude.interrupt()

    def new_chat(self, project: str | None = None, resume: str | None = None) -> None:
        if project:
            self.project = project
        self.claude.new_conversation(self.project, resume=resume)
        self.view.history.clear()
        self.view.call("clearChat", record=False)
        self.stream_id = None
        self._set_busy(False)

    def close(self) -> None:
        GLib.source_remove(self._timer)
        self.claude.shutdown()

    def _set_busy(self, busy: bool) -> None:
        self.view.call("setBusy", busy, record=False)
        self.on_busy(busy)

    # ---------------------------------------------------------------- mensajes

    def _new_id(self) -> str:
        self.counter += 1
        return f"m{id(self)}-{self.counter}"

    def _flush_stream(self) -> bool:
        if self.stream_dirty and self.stream_id:
            self.view.call("setAssistant", self.stream_id, render.markdown(self.stream_text), True, record=False)
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
                    self.view.call("setAssistant", block_id, render.markdown(block.text), False)
                    self.stream_id, self.stream_dirty = None, False
                elif isinstance(block, ToolUseBlock):
                    icon, title, detail = render.describe_tool(block.name, block.input, self.project)
                    self.view.call("addTool", block.id, icon, title, detail)
            if msg.error:
                self.view.call("addNote", f"Error: {msg.error}", "error")
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    text = render.tool_result_text(block.content)
                    html = ""
                    if block.is_error and text:
                        html = f'<pre class="result err">{GLib.markup_escape_text(text[:3000])}</pre>'
                    self.view.call("setToolResult", block.tool_use_id, not block.is_error, html)
        elif isinstance(msg, ResultMessage):
            self._finish_turn(msg)
        elif isinstance(msg, SystemMessage) and msg.subtype == "init":
            self.on_model(msg.data.get("model", ""))

    def _finish_turn(self, msg: ResultMessage) -> None:
        if self.stream_id:  # texto que quedó a medias (p. ej. al interrumpir)
            self.view.call("setAssistant", self.stream_id, render.markdown(self.stream_text), False)
            self.stream_id = None
        self.view.call("finishRunningTools")
        self._set_busy(False)
        secs = msg.duration_ms / 1000
        if msg.subtype == "success" and not msg.is_error:
            self.view.call("addDone", f"Hecho en {secs:.0f} s")
        elif msg.terminal_reason == "interrupted" or msg.subtype == "error_during_execution":
            self.view.call("addNote", "Detenido", "")
        else:
            detail = "; ".join(msg.errors or []) or msg.result or msg.subtype
            self.view.call("addNote", f"Claude no pudo terminar: {GLib.markup_escape_text(detail)}", "error")
        if not self.window.is_active():
            note = Gio.Notification.new("Claude ha terminado")
            note.set_body((msg.result or "")[:140])
            self.window.get_application().send_notification("done", note)

    def on_error(self, text: str) -> None:
        self._set_busy(False)
        self.view.call("finishRunningTools")
        self.view.call("addNote", f"Error: {GLib.markup_escape_text(text)}", "error")

    # ---------------------------------------------------------------- permisos

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
        self.window.present()
        dialog.present(self.window)

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
            dialog.present(self.window)

        self.window.present()
        ask_next()
