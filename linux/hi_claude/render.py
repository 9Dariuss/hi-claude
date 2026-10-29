"""Convierte lo que devuelve Claude en HTML legible para la vista de chat."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_formatter = HtmlFormatter(nowrap=True)


def _highlight(code: str, lang: str, attrs: str) -> str:
    try:
        lexer = get_lexer_by_name(lang) if lang else None
    except ClassNotFound:
        lexer = None
    body = highlight(code, lexer, _formatter) if lexer else html.escape(code)
    label = f'<span class="lang">{html.escape(lang)}</span>' if lang else ""
    return f'<pre class="code">{label}<code>{body}</code></pre>'


# html=False: el HTML que escriba Claude se muestra como texto, nunca se ejecuta
_md = MarkdownIt("commonmark", {"html": False, "linkify": False, "highlight": _highlight}) \
    .enable(["table", "strikethrough"])


def markdown(text: str) -> str:
    return _md.render(text)


def pygments_css() -> str:
    light = HtmlFormatter(style="friendly").get_style_defs("html:not(.dark) pre.code")
    dark = HtmlFormatter(style="monokai").get_style_defs("html.dark pre.code")
    return light + "\n" + dark


# --------------------------------------------------------------------------- herramientas

def _short(path: str, cwd: str) -> str:
    try:
        return str(Path(path).relative_to(cwd))
    except ValueError:
        return path.replace(str(Path.home()), "~", 1)


def _code(text: str) -> str:
    return f"<code>{html.escape(text)}</code>"


def _pre(text: str, cls: str = "") -> str:
    return f'<pre class="{cls}">{html.escape(text)}</pre>'


def _clip(text: str, limit: int = 4000) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} caracteres más)"


def describe_tool(name: str, inp: dict[str, Any], cwd: str) -> tuple[str, str, str]:
    """→ (icono, título en HTML, detalle en HTML) de una llamada a herramienta."""
    path = _short(inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or "", cwd)
    match name:
        case "Read":
            return "📄", f"Leyendo {_code(path)}", ""
        case "Write":
            return "📝", f"Creando {_code(path)}", _pre(_clip(inp.get("content", "")), "diff-add")
        case "Edit":
            detail = _pre(_clip(inp.get("old_string", "")), "diff-del") + _pre(_clip(inp.get("new_string", "")), "diff-add")
            return "✏️", f"Editando {_code(path)}", detail
        case "MultiEdit":
            detail = "".join(_pre(_clip(e.get("old_string", ""), 1500), "diff-del") +
                             _pre(_clip(e.get("new_string", ""), 1500), "diff-add") for e in inp.get("edits", []))
            return "✏️", f"Editando {_code(path)}", detail
        case "NotebookEdit":
            return "✏️", f"Editando {_code(path)}", _pre(_clip(inp.get("new_source", "")), "diff-add")
        case "Bash":
            title = html.escape(inp.get("description") or "") or _code(inp.get("command", "")[:80])
            return "⌨️", f"Ejecutando: {title}", _pre(inp.get("command", ""), "cmd")
        case "Glob":
            return "🔎", f"Buscando archivos {_code(inp.get('pattern', ''))}", ""
        case "Grep":
            where = f" en {_code(path)}" if path else ""
            return "🔎", f"Buscando {_code(inp.get('pattern', ''))}{where}", ""
        case "WebFetch":
            return "🌐", f"Leyendo {_code(inp.get('url', ''))}", ""
        case "WebSearch":
            return "🌐", f"Buscando en la web «{html.escape(inp.get('query', ''))}»", ""
        case "TodoWrite":
            marks = {"completed": "✅", "in_progress": "⏳", "pending": "▫️"}
            items = "".join(f"<li>{marks.get(t.get('status'), '▫️')} {html.escape(t.get('content', ''))}</li>"
                            for t in inp.get("todos", []))
            return "📋", "Plan de trabajo", f'<ul class="todos">{items}</ul>'
        case "Task" | "Agent":
            return "🤖", f"Subagente: {html.escape(inp.get('description', ''))}", _pre(_clip(inp.get("prompt", ""), 2000))
        case _:
            short = name.removeprefix("mcp__").replace("__", " · ")
            return "🔧", html.escape(short), _pre(_clip(json.dumps(inp, ensure_ascii=False, indent=2), 2000))


def permission_summary(name: str, inp: dict[str, Any], cwd: str) -> tuple[str, str]:
    """→ (pregunta, detalle en texto plano) para el diálogo de permiso."""
    path = _short(inp.get("file_path") or inp.get("notebook_path") or "", cwd)
    match name:
        case "Bash":
            return "¿Ejecutar este comando?", inp.get("command", "")
        case "Write":
            return f"¿Crear o sobrescribir {path}?", _clip(inp.get("content", ""), 600)
        case "Edit" | "MultiEdit" | "NotebookEdit":
            return f"¿Editar {path}?", _clip(inp.get("new_string", "") or inp.get("new_source", ""), 600)
        case "WebFetch":
            return "¿Abrir esta página web?", inp.get("url", "")
        case _:
            return f"¿Usar la herramienta {name}?", _clip(json.dumps(inp, ensure_ascii=False, indent=2), 600)


def tool_result_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif isinstance(item, dict) and item.get("type") == "image":
            parts.append("[imagen]")
    return "\n".join(parts)
