"""Piezas de chat que comparten la ventana principal y la ventana rápida del recorte.

Todo lo de aquí se ejecuta en el hilo de mainloop (el equivalente al bucle de GTK en Linux).
"""

from __future__ import annotations

import html
import itertools
import json
import time
from pathlib import Path
from typing import Any, Callable

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

from . import mainloop, render
from .claude import ClaudeWorker
from .config import Config, State
from .voice import VoiceInput

HERE = Path(__file__).parent
# fondo de la vista web = --bg de chat.html, para que no destelle al cargar
BG_LIGHT, BG_DARK = "#faf9f6", "#1f1e1c"
FG_LIGHT, FG_DARK = "#1f1e1c", "#eceae5"


def page_html() -> str:
    hand = (HERE / "hand.svg").read_text(encoding="utf-8")
    return ((HERE / "chat.html").read_text(encoding="utf-8")
            .replace("/*PYGMENTS*/", render.pygments_css())
            .replace("/*HAND*/", hand))


class ChatView:
    """La conversación, dibujada en HTML. call() llama a las funciones JS de chat.html."""

    def __init__(self):
        self.window = None          # webview.Window; lo pone la ventana al crearse
        self._ready = False
        self._pending: list[str] = []
        self.history: list[str] = []  # llamadas de contenido, para pasar la conversación a otra ventana

    def mark_ready(self) -> None:
        self._ready = True
        for js in self._pending:
            self._eval(js)
        self._pending.clear()

    def _eval(self, js: str) -> None:
        try:
            self.window.run_js(js)
        except Exception:  # la ventana se está cerrando
            pass

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


class Voice:
    """El micrófono de una ventana: une VoiceInput con el cuadro de texto de chat.html."""

    def __init__(self, cfg: Config, state: State, view: ChatView, on_error: Callable[[str], None]):
        self.state, self.view, self.on_error = state, view, on_error
        self.input = VoiceInput(cfg, lambda s: mainloop.idle_add(self._apply_state, s),
                                lambda t: mainloop.idle_add(self._text, t),
                                lambda e: mainloop.idle_add(self.on_error, e))
        self._listening = False

    @property
    def active(self) -> bool:
        return self.input.active

    def toggle(self) -> None:
        if self.input.active:
            self.input.stop()
        else:
            self.start()

    def start(self) -> None:
        if not self.input.active:
            self.input.beep = self.state.beep
            self.input.start()

    def stop(self) -> bool:
        if self.input.active:
            self.input.stop()
            return True
        return False

    def _apply_state(self, state: str) -> None:
        self._listening = state == "listening"
        self.view.call("setVoiceState", state, record=False)
        if self._listening:
            mainloop.timeout_add(50, self._update_level)

    def _update_level(self) -> bool:
        if not self._listening:
            return False
        self.view.call("setLevel", min(1.0, max(0.0, (self.input.level_db + 60) / 45)), record=False)
        return True

    def _text(self, text: str) -> None:
        self.view.call("voiceText", text, self.state.auto_send, record=False)


class ChatController:
    """Une una ChatView con un ClaudeWorker: envía, muestra la respuesta y pide permisos."""

    _ids = itertools.count(1)

    def __init__(self, view: ChatView, cfg: Config, state: State, project: str,
                 on_busy: Callable[[bool], None], on_finished: Callable[[str], None],
                 on_attention: Callable[[], None], on_model: Callable[[str], None] | None = None):
        self.view, self.state = view, state
        self.project = project
        self.on_busy = on_busy
        self.on_finished = on_finished      # (texto del resultado) para avisar si la ventana no está delante
        self.on_attention = on_attention    # trae la ventana al frente (permisos, preguntas)
        self.on_model = on_model or (lambda _m: None)
        self.uid = next(self._ids)
        self.stream_id: str | None = None
        self.stream_text = ""
        self.stream_dirty = False
        self.counter = 0
        self.requests: dict[str, tuple[str, dict, Callable]] = {}
        self.claude = ClaudeWorker(self.on_message, self.on_error, self.ask_permission, cfg.claude_path)
        self.claude.cwd = project
        self.claude.accept_edits = state.accept_edits
        self.closed = False
        mainloop.timeout_add(80, self._flush_stream)

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
        self._deny_pending()
        self.claude.new_conversation(self.project, resume=resume)
        self.view.history.clear()
        self.view.call("clearChat", record=False)
        self.stream_id = None
        self._set_busy(False)

    def close(self) -> None:
        self.closed = True
        self._deny_pending()
        self.claude.shutdown()

    def _set_busy(self, busy: bool) -> None:
        self.view.call("setBusy", busy, record=False)
        self.on_busy(busy)

    # ---------------------------------------------------------------- mensajes

    def _new_id(self) -> str:
        self.counter += 1
        return f"m{self.uid}-{self.counter}"

    def _flush_stream(self) -> bool:
        if self.closed:
            return False
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
                self.view.call("addNote", f"Error: {html.escape(str(msg.error))}", "error")
        elif isinstance(msg, UserMessage) and isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    text = render.tool_result_text(block.content)
                    result = ""
                    if block.is_error and text:
                        result = f'<pre class="result err">{html.escape(text[:3000])}</pre>'
                    self.view.call("setToolResult", block.tool_use_id, not block.is_error, result)
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
            self.view.call("addNote", f"Claude no pudo terminar: {html.escape(str(detail))}", "error")
        self.on_finished(msg.result or "")

    def on_error(self, text: str) -> None:
        self._set_busy(False)
        self.view.call("finishRunningTools")
        self.view.call("addNote", f"Error: {html.escape(text)}", "error")

    # ---------------------------------------------------------------- permisos

    def ask_permission(self, name: str, tool_input: dict, respond) -> None:
        req = f"r{self.uid}-{time.monotonic_ns()}"
        self.requests[req] = (name, tool_input, respond)
        self.on_attention()
        if name == "AskUserQuestion":
            self._ask_next_question(req, list(tool_input.get("questions", [])), {})
            return
        heading, detail = render.permission_summary(name, tool_input, self.project)
        self.view.call("askPermission", req, heading, detail, record=False)

    def answer_permission(self, req: str, response: str) -> None:
        entry = self.requests.pop(req, None)
        if not entry:
            return
        respond = entry[2]
        if response in ("allow", "always"):
            respond(PermissionResultAllow(), always=response == "always")
        else:
            respond(PermissionResultDeny(message="El usuario ha denegado el permiso"))

    def _ask_next_question(self, req: str, questions: list[dict], answers: dict[str, str]) -> None:
        name, tool_input, respond = self.requests[req]
        if not questions:
            self.requests.pop(req, None)
            respond(PermissionResultAllow(updated_input={**tool_input, "answers": answers}))
            return
        q = questions[0]
        options = [{"label": o.get("label", f"Opción {i + 1}"), "description": o.get("description", "")}
                   for i, o in enumerate(q.get("options", [])[:6])]
        self.requests[req] = (name, {**tool_input, "_queue": questions, "_answers": answers}, respond)
        self.view.call("askQuestion", req, q.get("header") or "Claude pregunta", q.get("question", ""), options,
                       record=False)

    def answer_question(self, req: str, index: int) -> None:
        entry = self.requests.get(req)
        if not entry:
            return
        name, data, respond = entry
        questions, answers = data.pop("_queue"), data.pop("_answers")
        self.requests[req] = (name, data, respond)
        q = questions[0]
        options = q.get("options", [])
        if index < 0 or index >= len(options):
            self.requests.pop(req, None)
            respond(PermissionResultDeny(message="El usuario no ha respondido"))
            return
        answers[q.get("question", "")] = options[index].get("label", "")
        self._ask_next_question(req, questions[1:], answers)

    def _deny_pending(self) -> None:
        for req, (_n, _i, respond) in list(self.requests.items()):
            respond(PermissionResultDeny(message="Cancelado", interrupt=True))
        self.requests.clear()
