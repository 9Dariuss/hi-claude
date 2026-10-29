"""Modo recorte (Ctrl+Super+C): capturas un trozo de pantalla y le preguntas a Claude por él.

1. Se captura la pantalla entera con el portal de escritorio (en GNOME, la primera vez
   pide permiso; luego es instantáneo).
2. Se muestra congelada a pantalla completa en cada monitor y arrastras para seleccionar.
3. Al soltar el clic se abre una ventana pequeña para escribir (o dictar) la pregunta;
   la respuesta aparece en esa misma ventana.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Callable

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from .chat import ChatController, ChatView, Composer  # noqa: E402
from .config import CACHE_DIR  # noqa: E402

PORTAL = "org.freedesktop.portal.Desktop"
MAX_CLAUDE_SIDE = 1568   # lado mayor recomendado para imágenes enviadas a Claude
MAX_PREVIEW_SIDE = 900


# --------------------------------------------------------------------------- captura

def take_screenshot(done: Callable[[GdkPixbuf.Pixbuf | None, str], None]) -> None:
    """Pide una captura de todos los monitores al portal; llama done(pixbuf, error)."""
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    token = f"hiclaude{int(time.time() * 1000)}"
    sender = bus.get_unique_name()[1:].replace(".", "_")
    request = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
    sub_id = 0

    def on_response(_conn, _sender, _path, _iface, _signal, params):
        bus.signal_unsubscribe(sub_id)
        code, results = params.unpack()
        uri = results.get("uri")
        if code != 0 or not uri:
            done(None, "Captura cancelada o sin permiso")
            return
        path = Gio.File.new_for_uri(uri).get_path()
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
        except GLib.Error as exc:
            done(None, f"No se pudo leer la captura: {exc.message}")
            return
        finally:
            # el portal la guarda en Imágenes; es solo para nosotros
            Path(path).unlink(missing_ok=True)
        done(pixbuf, "")

    sub_id = bus.signal_subscribe(PORTAL, "org.freedesktop.portal.Request", "Response", request,
                                  None, Gio.DBusSignalFlags.NO_MATCH_RULE, on_response)
    options = {"handle_token": GLib.Variant("s", token), "interactive": GLib.Variant("b", False)}

    def on_called(conn, result):
        try:
            conn.call_finish(result)
        except GLib.Error as exc:
            bus.signal_unsubscribe(sub_id)
            done(None, f"El portal de capturas no responde: {exc.message}")

    bus.call(PORTAL, "/org/freedesktop/portal/desktop", "org.freedesktop.portal.Screenshot", "Screenshot",
             GLib.Variant("(sa{sv})", ("", options)), None, Gio.DBusCallFlags.NONE, -1, None, on_called)


def png_bytes(pixbuf: GdkPixbuf.Pixbuf, max_side: int) -> bytes:
    w, h = pixbuf.get_width(), pixbuf.get_height()
    if max(w, h) > max_side:
        k = max_side / max(w, h)
        pixbuf = pixbuf.scale_simple(max(1, int(w * k)), max(1, int(h * k)), GdkPixbuf.InterpType.BILINEAR)
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    return bytes(data)


# --------------------------------------------------------------------------- selección

class SnipArea(Gtk.DrawingArea):
    def __init__(self, pixbuf: GdkPixbuf.Pixbuf, accent: str, on_done: Callable[[tuple | None], None]):
        super().__init__(hexpand=True, vexpand=True, can_focus=True, focusable=True)
        self.pixbuf, self.on_done = pixbuf, on_done
        self.accent = Gdk.RGBA()
        self.accent.parse(accent)
        self.start: tuple[float, float] | None = None
        self.rect: tuple[float, float, float, float] | None = None
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.add_controller(drag)

    def _begin(self, _g, x, y):
        self.start, self.rect = (x, y), (x, y, 0, 0)
        self.queue_draw()

    def _update(self, _g, dx, dy):
        x, y = self.start
        self.rect = (min(x, x + dx), min(y, y + dy), abs(dx), abs(dy))
        self.queue_draw()

    def _end(self, _g, dx, dy):
        self._update(_g, dx, dy)
        x, y, w, h = self.rect
        if w < 8 or h < 8:  # un clic suelto: no vale como selección
            self.rect = None
            self.queue_draw()
            return
        sx = self.pixbuf.get_width() / self.get_width()
        sy = self.pixbuf.get_height() / self.get_height()
        self.on_done((int(x * sx), int(y * sy), max(1, int(w * sx)), max(1, int(h * sy))))

    def _draw(self, _area, cr, width, height):
        sx, sy = width / self.pixbuf.get_width(), height / self.pixbuf.get_height()

        def paint_shot():
            cr.save()
            cr.scale(sx, sy)
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
            cr.restore()

        paint_shot()
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.paint()
        if self.rect and self.rect[2] > 0:
            x, y, w, h = self.rect
            cr.save()
            cr.rectangle(x, y, w, h)
            cr.clip()
            paint_shot()
            cr.restore()
            cr.set_source_rgba(self.accent.red, self.accent.green, self.accent.blue, 1)
            cr.set_line_width(2)
            cr.rectangle(x + 1, y + 1, w - 2, h - 2)
            cr.stroke()
            label = f"{int(w / sx)} × {int(h / sy)}"
            cr.select_font_face("Adwaita Sans")
            cr.set_font_size(13)
            ext = cr.text_extents(label)
            ly = y - 10 if y > 34 else y + h + 22
            cr.set_source_rgba(self.accent.red, self.accent.green, self.accent.blue, 0.95)
            _rounded(cr, x, ly - 16, ext.x_advance + 16, 24, 8)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 1)
            cr.move_to(x + 8, ly)
            cr.show_text(label)
        else:
            text = "Arrastra para recortar  ·  Esc para cancelar"
            cr.select_font_face("Adwaita Sans")
            cr.set_font_size(16)
            ext = cr.text_extents(text)
            bx, by = (width - ext.x_advance) / 2 - 18, 40
            cr.set_source_rgba(0.1, 0.1, 0.1, 0.85)
            _rounded(cr, bx, by, ext.x_advance + 36, 40, 20)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 1)
            cr.move_to(bx + 18, by + 26)
            cr.show_text(text)


def _rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


class SnipOverlay:
    """Una ventana a pantalla completa por monitor con la captura congelada encima."""

    def __init__(self, app: Gtk.Application, shot: GdkPixbuf.Pixbuf, accent: str,
                 on_done: Callable[[GdkPixbuf.Pixbuf | None], None]):
        self.on_done = on_done
        self.windows: list[Gtk.Window] = []
        monitors = Gdk.Display.get_default().get_monitors()
        geoms = [(monitors.get_item(i), monitors.get_item(i).get_geometry()) for i in range(monitors.get_n_items())]
        min_x = min(g.x for _m, g in geoms)
        min_y = min(g.y for _m, g in geoms)
        span_w = max(g.x + g.width for _m, g in geoms) - min_x
        span_h = max(g.y + g.height for _m, g in geoms) - min_y
        kx, ky = shot.get_width() / span_w, shot.get_height() / span_h

        for monitor, g in geoms:
            ox, oy = int((g.x - min_x) * kx), int((g.y - min_y) * ky)
            w = min(int(g.width * kx), shot.get_width() - ox)
            h = min(int(g.height * ky), shot.get_height() - oy)
            part = shot.new_subpixbuf(ox, oy, w, h)
            win = Gtk.Window(application=app, decorated=False, title="Recorte")
            area = SnipArea(part, accent, lambda r, part=part: self._finish(part, r))
            win.set_child(area)
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._on_key)
            win.add_controller(keys)
            win.fullscreen_on_monitor(monitor)
            win.present()
            self.windows.append(win)

    def _on_key(self, _c, keyval, *_):
        if keyval == Gdk.KEY_Escape:
            self._finish(None, None)
            return True
        return False

    def _finish(self, part, rect) -> None:
        for win in self.windows:
            win.destroy()
        self.windows.clear()
        if part is None or rect is None:
            self.on_done(None)
        else:
            x, y, w, h = rect
            w, h = min(w, part.get_width() - x), min(h, part.get_height() - y)
            # copia: la subimagen comparte memoria con la captura completa
            self.on_done(part.new_subpixbuf(x, y, w, h).copy())


# --------------------------------------------------------------------------- ventana rápida

class QuickWindow(Adw.Window):
    """Ventanita para preguntar por un recorte; la respuesta aparece aquí mismo."""

    def __init__(self, app, snip: GdkPixbuf.Pixbuf):
        super().__init__(application=app, title="Hi Claude!", default_width=560, default_height=640)
        self.app = app
        self.png = png_bytes(snip, MAX_CLAUDE_SIDE)
        preview_png = png_bytes(snip, MAX_PREVIEW_SIDE)
        self.preview_uri = "data:image/png;base64," + base64.b64encode(preview_png).decode()
        self._save_copy(snip)

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView(top_bar_style=Adw.ToolbarStyle.FLAT)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        title = Gtk.Box(spacing=8)
        title.append(Gtk.Image(icon_name="io.github.HiClaude", pixel_size=20))
        title.append(Gtk.Label(label="Pregunta sobre el recorte", css_classes=["heading"]))
        header.set_title_widget(title)
        self.open_btn = Gtk.Button(icon_name="view-fullscreen-symbolic", tooltip_text="Seguir en la app principal",
                                   visible=False)
        self.open_btn.connect("clicked", lambda _b: self._open_in_main())
        header.pack_start(self.open_btn)
        view.add_top_bar(header)

        # contenido: primero la vista previa; tras enviar, la conversación
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        picture = Gtk.Picture(paintable=Gdk.Texture.new_for_pixbuf(snip), content_fit=Gtk.ContentFit.CONTAIN,
                              can_shrink=True, css_classes=["snip-preview"], overflow=Gtk.Overflow.HIDDEN)
        preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_start=18, margin_end=18,
                          margin_top=6, margin_bottom=6)
        preview.append(picture)
        hint = Gtk.Label(label="¿Qué quieres saber de esto? Escríbelo o dicta con el micrófono.",
                         wrap=True, css_classes=["dim-label"])
        preview.append(hint)
        self.stack.add_named(preview, "preview")
        self.chat = ChatView()
        self.chat.call("setCompact", True, record=False)
        self.stack.add_named(self.chat, "chat")
        view.set_content(self.stack)

        project = app.state.project or str(Path(app.cfg.default_project).expanduser())
        self.controller = ChatController(self, self.chat, app.cfg, app.state, project, self._on_busy)
        self.composer = Composer(app.cfg, app.state, self._submit, self.controller.stop, self.toast,
                                 placeholder="Pregunta sobre la captura…")
        self.composer.set_margin_start(14)
        self.composer.set_margin_end(14)
        self.composer.set_margin_bottom(14)
        view.add_bottom_bar(self.composer)
        self.first = True

        app.theme.connect(self.chat.set_theme)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", self._on_close)
        self.present()
        self.composer.focus()

    def _save_copy(self, snip: GdkPixbuf.Pixbuf) -> None:
        # una copia del último recorte, por si Claude necesita abrirlo o quieres reutilizarlo
        folder = CACHE_DIR / "recortes"
        folder.mkdir(parents=True, exist_ok=True)
        for old in sorted(folder.glob("*.png"))[:-19]:
            old.unlink(missing_ok=True)
        snip.savev(str(folder / time.strftime("recorte-%Y%m%d-%H%M%S.png")), "png", [], [])

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def _submit(self, text: str, via_voice: bool) -> None:
        if self.first:
            self.first = False
            self.stack.set_visible_child_name("chat")
            self.controller.send(text, via_voice, image_png=self.png, image_uri=self.preview_uri)
            self.open_btn.set_visible(True)
        else:
            self.controller.send(text, via_voice)

    def _on_busy(self, busy: bool) -> None:
        self.composer.set_busy(busy)

    def _on_key(self, _c, keyval, *_):
        if keyval == Gdk.KEY_Escape:
            if self.composer.stop_voice():
                return True
            if self.controller.busy:
                self.controller.stop()
            else:
                self.close()
            return True
        return False

    def _open_in_main(self) -> None:
        if self.controller.busy:
            self.toast("Espera a que Claude termine")
            return
        self.app.continue_in_main(self.controller.claude.session_id, self.controller.project, list(self.chat.history))
        self.close()

    def _on_close(self, *_):
        self.composer.stop_voice()
        self.app.theme.disconnect(self.chat.set_theme)
        self.controller.close()
        return False
