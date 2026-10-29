"""Aspecto de la app: color principal personalizable y paleta cálida, en GTK y en las vistas de chat."""

from __future__ import annotations

from typing import Callable

from gi.repository import Adw, Gdk, Gtk

from .config import ACCENT_PRESETS, State

# Paleta cálida (blancos y grises tirando a crema) que combina con el naranja Claude.
# Se elige desde Python según el modo: @media (prefers-color-scheme) no sigue a Adw.StyleManager.
PALETTE = {
    False: ("--window-bg-color: #faf9f6; --view-bg-color: #faf9f6; --headerbar-bg-color: #faf9f6;"
            "--popover-bg-color: #fffdf9; --dialog-bg-color: #fffdf9;"
            "--hc-composer-bg: #ffffff; --hc-composer-border: rgb(0 0 0 / 9%);"),
    True: ("--window-bg-color: #1f1e1c; --view-bg-color: #1f1e1c; --headerbar-bg-color: #1f1e1c;"
           "--popover-bg-color: #2a2926; --dialog-bg-color: #2a2926;"
           "--hc-composer-bg: #2a2926; --hc-composer-border: rgb(255 255 255 / 8%);"),
}

BASE_CSS = """
:root { --headerbar-shade-color: transparent; }
.composer {
  background: var(--hc-composer-bg); border: 1px solid var(--hc-composer-border);
  border-radius: 26px; padding: 6px 6px 6px 18px;
  box-shadow: 0 3px 14px rgb(0 0 0 / 7%);
  transition: border-color 150ms, box-shadow 150ms;
}
.composer:focus-within {
  border-color: color-mix(in srgb, var(--accent-bg-color) 60%, transparent);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent-bg-color) 16%, transparent), 0 3px 14px rgb(0 0 0 / 7%);
}
.composer textview, .composer textview text { background: transparent; }
.composer.listening {
  border-color: var(--accent-bg-color);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent-bg-color) 22%, transparent);
}
.composer-status { color: var(--accent-color); font-weight: 600; font-size: 0.9em; }
.mic-button.listening { background: var(--accent-bg-color); color: var(--accent-fg-color); }
.send-button { min-width: 38px; min-height: 38px; }
.send-button.busy { background: color-mix(in srgb, var(--window-fg-color) 12%, transparent); color: var(--window-fg-color); }
levelbar block.filled { background: var(--accent-bg-color); }
.snip-preview { border-radius: 14px; border: 1px solid var(--hc-composer-border); }
.swatch { min-width: 30px; min-height: 30px; padding: 0; border-radius: 99px; }
.swatch image { color: white; -gtk-icon-shadow: 0 1px 2px rgb(0 0 0 / 40%); }
.title-hand { color: var(--accent-bg-color); }
"""


class Theme:
    """Mantiene el color principal y el modo claro/oscuro, y avisa a las vistas de chat."""

    def __init__(self, state: State):
        self.state = state
        self._listeners: list[Callable[[bool, str], None]] = []
        display = Gdk.Display.get_default()
        base = Gtk.CssProvider()
        base.load_from_string(BASE_CSS)
        Gtk.StyleContext.add_provider_for_display(display, base, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self._accent = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, self._accent, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.style = Adw.StyleManager.get_default()
        self.style.connect("notify::dark", lambda *_: self.apply())
        self.apply()

    @property
    def accent(self) -> str:
        return self.state.accent

    @property
    def dark(self) -> bool:
        return self.style.get_dark()

    def connect(self, listener: Callable[[bool, str], None]) -> None:
        """listener(oscuro, color) se llama ahora y cada vez que cambie el aspecto."""
        self._listeners.append(listener)
        listener(self.dark, self.accent)

    def disconnect(self, listener: Callable[[bool, str], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def set_accent(self, color: str) -> None:
        self.state.accent = color
        self.state.save()
        self.apply()

    def set_color_scheme(self, scheme: str) -> None:
        self.state.color_scheme = scheme
        self.state.save()
        self.apply()

    def apply(self) -> None:
        swatches = "".join(f".swatch-{i} {{ background: {color}; }}\n" for i, (_n, color) in enumerate(ACCENT_PRESETS))
        scheme = {"light": Adw.ColorScheme.FORCE_LIGHT,
                  "dark": Adw.ColorScheme.FORCE_DARK}.get(self.state.color_scheme, Adw.ColorScheme.DEFAULT)
        if self.style.get_color_scheme() != scheme:
            self.style.set_color_scheme(scheme)  # vuelve a llamar a apply() vía notify::dark si cambia
        self._accent.load_from_string(
            f":root {{ {PALETTE[self.dark]} --accent-bg-color: {self.accent}; --accent-fg-color: #ffffff; }}\n"
            f"{swatches}")
        self._notify()

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener(self.dark, self.accent)
