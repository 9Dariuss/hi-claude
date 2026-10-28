"""Puente con Claude Code mediante el Claude Agent SDK.

El SDK es asyncio y GTK tiene su propio bucle: el SDK vive en un hilo con su
propio event loop y todo lo que llega se reenvía a la interfaz con GLib.idle_add.
"""

from __future__ import annotations

import asyncio
import shutil
import threading
from concurrent.futures import Future
from pathlib import Path
from typing import Any, Callable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
from gi.repository import GLib

# Herramientas de solo lectura: nunca piden permiso en la app.
READ_ONLY_TOOLS = {"Read", "Glob", "Grep", "LS", "TodoWrite", "NotebookRead", "WebSearch", "Task", "Agent"}

# (nombre, input, responder) → la UI llama a responder(resultado, siempre) cuando el usuario decide;
# siempre=True recuerda la herramienta durante el resto de la conversación.
PermissionAsker = Callable[[str, dict[str, Any], Callable[..., None]], None]


class ClaudeWorker:
    def __init__(self, on_message: Callable[[Any], None], on_error: Callable[[str], None],
                 ask_permission: PermissionAsker, claude_path: str = ""):
        self.on_message = on_message
        self.on_error = on_error
        self.ask_permission = ask_permission
        self.cli_path = claude_path or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
        self.cwd = str(Path.home())
        self.accept_edits = False
        self.always_allowed: set[str] = set()
        self.client: ClaudeSDKClient | None = None
        self.busy = False

        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="claude-sdk").start()

    # ---------------------------------------------------------------- API para la UI (hilo GTK)

    def send(self, text: str) -> None:
        self._submit(self._send(text))

    def interrupt(self) -> None:
        self._submit(self._interrupt())

    def new_conversation(self, cwd: str | None = None) -> None:
        if cwd:
            self.cwd = cwd
        self._submit(self._reset())

    def set_accept_edits(self, value: bool) -> None:
        self.accept_edits = value
        self._submit(self._apply_permission_mode())

    def shutdown(self) -> None:
        fut = self._submit(self._reset())
        try:
            fut.result(timeout=3)
        except Exception:
            pass

    # ---------------------------------------------------------------- interno (hilo asyncio)

    def _submit(self, coro) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def _ui(self, fn: Callable, *args) -> None:
        GLib.idle_add(lambda: fn(*args) and False)

    def _permission_mode(self) -> str:
        return "acceptEdits" if self.accept_edits else "default"

    async def _connect(self) -> ClaudeSDKClient:
        if self.client is None:
            options = ClaudeAgentOptions(
                cwd=self.cwd,
                cli_path=self.cli_path,
                include_partial_messages=True,
                permission_mode=self._permission_mode(),
                can_use_tool=self._can_use_tool,
                # igual que `claude` en la terminal: tu CLAUDE.md, ajustes y permisos
                setting_sources=["user", "project", "local"],
                stderr=lambda line: None,
            )
            client = ClaudeSDKClient(options)
            await client.connect()
            self.client = client
        return self.client

    async def _send(self, text: str) -> None:
        self.busy = True
        try:
            client = await self._connect()
            await client.query(text)
            async for message in client.receive_response():
                self._ui(self.on_message, message)
        except Exception as exc:
            self._ui(self.on_error, f"{type(exc).__name__}: {exc}")
            await self._reset()
        finally:
            self.busy = False

    async def _interrupt(self) -> None:
        if self.client and self.busy:
            try:
                await self.client.interrupt()
            except Exception as exc:
                self._ui(self.on_error, f"No se pudo detener: {exc}")

    async def _reset(self) -> None:
        self.always_allowed.clear()
        client, self.client = self.client, None
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def _apply_permission_mode(self) -> None:
        if self.client:
            await self.client.set_permission_mode(self._permission_mode())

    async def _can_use_tool(self, name: str, tool_input: dict[str, Any], context: ToolPermissionContext):
        if name in READ_ONLY_TOOLS or name in self.always_allowed:
            return PermissionResultAllow()
        future: asyncio.Future = self.loop.create_future()

        def respond(result: Any, always: bool = False) -> None:  # llamado desde el hilo GTK
            if always:
                self.always_allowed.add(name)
            self.loop.call_soon_threadsafe(lambda: future.done() or future.set_result(result))

        self._ui(self.ask_permission, name, tool_input, respond)
        try:
            return await future
        except asyncio.CancelledError:
            return PermissionResultDeny(message="Cancelado", interrupt=True)
