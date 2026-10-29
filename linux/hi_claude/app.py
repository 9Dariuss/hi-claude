"""Hi Claude!: Claude Code en una ventana de GNOME, con voz y recortes de pantalla.

    hi-claude                 abre la app (o la trae al frente)
    hi-claude --voice         abre la app y empieza a escuchar
    hi-claude --snip          recorta un trozo de pantalla y pregunta a Claude por él
    hi-claude ~/proyecto      abre la app en esa carpeta
    hi-claude --list-mics     lista los micrófonos (para input_device)
"""

from __future__ import annotations

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .chat import ChatController, ChatView, Composer  # noqa: E402
from .config import ACCENT_PRESETS, Config, State  # noqa: E402
from .theme import Theme  # noqa: E402

APP_ID = "io.github.HiClaude"
APP_NAME = "Hi Claude!"
VERSION = "3.0"
GLOBAL_SHORTCUTS = [("<Super>c", f"Abrir {APP_NAME}"), ("<Super><Alt>c", "Abrir y hablar"),
                    ("<Primary><Super>c", "Recortar pantalla y preguntar")]


def pretty_path(path: str) -> str:
    return path.replace(str(Path.home()), "~", 1)


def shortcut_rows(group: Adw.PreferencesGroup, rows: list[tuple[str, str]]) -> None:
    for accel, what in rows:
        row = Adw.ActionRow(title=what)
        row.add_suffix(Gtk.ShortcutLabel(accelerator=accel, valign=Gtk.Align.CENTER))
        group.add(row)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: "App"):
        super().__init__(application=app, title=APP_NAME, default_width=940, default_height=800)
        self.app = app
        self.cfg, self.state = app.cfg, app.state
        self.project = self.state.project or str(Path(self.cfg.default_project).expanduser())
        self._build()
        self.controller = ChatController(self, self.chat, self.cfg, self.state, self.project,
                                         self.composer.set_busy, self._on_model)
        app.theme.connect(self.chat.set_theme)
        self._update_project_ui()
        self.connect("close-request", self._on_close)

    # ------------------------------------------------------------------ interfaz

    def _build(self) -> None:
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView(top_bar_style=Adw.ToolbarStyle.FLAT)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        self.title = Adw.WindowTitle(title=APP_NAME)
        header.set_title_widget(self.title)

        # clic: elegir carpeta · flecha: proyectos recientes
        self.recent_menu = Gio.Menu()
        project_btn = Adw.SplitButton(icon_name="folder-open-symbolic", menu_model=self.recent_menu,
                                      tooltip_text="Cambiar de proyecto (Ctrl+O)", dropdown_tooltip="Proyectos recientes")
        project_btn.set_action_name("win.open-project")
        header.pack_start(project_btn)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Aceptar ediciones sin preguntar", "win.accept-edits")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Preferencias", "win.preferences")
        section.append("Atajos de teclado", "win.shortcuts")
        section.append(f"Acerca de {APP_NAME}", "win.about")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menú"))
        new_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Nueva conversación (Ctrl+N)")
        new_btn.set_action_name("win.new-chat")
        header.pack_end(new_btn)
        snip_btn = Gtk.Button(icon_name="edit-cut-symbolic", tooltip_text="Recortar pantalla (Ctrl+Super+C)")
        snip_btn.connect("clicked", lambda _b: self.app.start_snip())
        header.pack_end(snip_btn)
        view.add_top_bar(header)

        self.chat = ChatView(on_suggestion=lambda text: self._submit(text, False))
        self.chat.set_vexpand(True)
        view.set_content(self.chat)

        self.composer = Composer(self.cfg, self.state, self._submit, self.stop, self.toast,
                                 placeholder="Escribe a Claude…")
        bottom = Adw.Clamp(maximum_size=760, child=self.composer, margin_start=18, margin_end=18,
                           margin_bottom=16, margin_top=4)
        view.add_bottom_bar(bottom)

        def action(name, cb, accels=()):
            a = Gio.SimpleAction.new(name, None)
            a.connect("activate", lambda *_: cb())
            self.add_action(a)
            if accels:
                self.app.set_accels_for_action(f"win.{name}", list(accels))

        action("open-project", self.choose_project, ["<Ctrl>o"])
        action("new-chat", self.new_chat, ["<Ctrl>n"])
        action("voice", self.composer.toggle_voice, ["<Ctrl>m"])
        action("stop", self.stop, ["Escape"])
        action("preferences", lambda: PreferencesDialog(self.app, self).present(self), ["<Ctrl>comma"])
        action("about", self._about)
        action("shortcuts", self._shortcuts, ["<Ctrl>question"])
        accept = Gio.SimpleAction.new_stateful("accept-edits", None, GLib.Variant.new_boolean(self.state.accept_edits))
        accept.connect("change-state", self._on_accept_edits)
        self.add_action(accept)
        open_recent = Gio.SimpleAction.new("open-recent", GLib.VariantType.new("s"))
        open_recent.connect("activate", lambda _a, v: self.set_project(v.get_string()))
        self.add_action(open_recent)
        self.composer.focus()

    def _update_project_ui(self) -> None:
        home = self.project == str(Path.home())
        self.title.set_title(APP_NAME if home else Path(self.project).name)
        self.title.set_subtitle(pretty_path(self.project))
        self.chat.call("setProject", pretty_path(self.project), record=False)
        self.recent_menu.remove_all()
        for p in self.state.recent_projects:
            item = Gio.MenuItem.new(pretty_path(p), None)
            item.set_action_and_target_value("win.open-recent", GLib.Variant.new_string(p))
            self.recent_menu.append_item(item)

    def _on_model(self, model: str) -> None:
        if model:
            self.title.set_subtitle(f"{pretty_path(self.project)} · {model}")

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    # ------------------------------------------------------------------ acciones

    def _submit(self, text: str, via_voice: bool) -> None:
        if self.controller.busy:
            self.toast("Claude sigue trabajando: envíalo cuando termine")
            self.composer.set_text(text)
            return
        self.controller.send(text, via_voice)

    def stop(self) -> None:
        if not self.composer.stop_voice():
            self.controller.stop()

    def start_voice(self) -> None:
        self.composer.start_voice()

    def choose_project(self) -> None:
        dialog = Gtk.FileDialog(title="Elige la carpeta del proyecto",
                                initial_folder=Gio.File.new_for_path(self.project))

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
        self.controller.new_chat(path)

    def new_chat(self) -> None:
        self.controller.new_chat(self.project)

    def continue_conversation(self, session_id: str | None, project: str, history: list[str]) -> None:
        """Trae aquí una conversación empezada en la ventana del recorte."""
        if project != self.project:
            self.project = project
            self.state.remember_project(project)
            self._update_project_ui()
        self.controller.new_chat(project, resume=session_id)
        self.chat.replay(history)

    def _on_accept_edits(self, action, value) -> None:
        action.set_state(value)
        self.state.accept_edits = value.get_boolean()
        self.state.save()
        self.controller.claude.set_accept_edits(self.state.accept_edits)
        self.toast("Claude editará archivos sin preguntar" if self.state.accept_edits
                   else "Claude preguntará antes de editar")

    def _on_close(self, *_):
        self.composer.stop_voice()
        self.app.theme.disconnect(self.chat.set_theme)
        self.controller.close()
        self.app.window = None
        return False

    def _about(self) -> None:
        Adw.AboutDialog(
            application_name=APP_NAME, application_icon=APP_ID, developer_name="9Dariuss",
            version=VERSION, website="https://github.com/9Dariuss/hi-claude",
            comments="Claude Code en una ventana, con voz local y recortes de pantalla.",
            license_type=Gtk.License.MIT_X11,
        ).present(self)

    def _shortcuts(self) -> None:
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(title="En todo el escritorio")
        shortcut_rows(group, GLOBAL_SHORTCUTS)
        page.add(group)
        group = Adw.PreferencesGroup(title="En la app")
        shortcut_rows(group, [("Return", "Enviar"), ("<Shift>Return", "Nueva línea"),
                              ("<Primary>m", "Hablar / terminar de hablar"), ("Escape", "Detener"),
                              ("<Primary>n", "Nueva conversación"), ("<Primary>o", "Cambiar de proyecto"),
                              ("<Primary>comma", "Preferencias")])
        page.add(group)
        content = Adw.ToolbarView(content=page)
        content.add_top_bar(Adw.HeaderBar())
        Adw.Dialog(title="Atajos de teclado", content_width=440, content_height=620, child=content).present(self)


class PreferencesDialog(Adw.PreferencesDialog):
    def __init__(self, app: "App", window: MainWindow):
        super().__init__(title="Preferencias")
        self.app = app
        state = app.state
        page = Adw.PreferencesPage(title="General", icon_name="preferences-system-symbolic")
        self.add(page)

        # --- apariencia
        look = Adw.PreferencesGroup(title="Apariencia")
        page.add(look)
        self.color_row = Adw.ActionRow(title="Color principal")
        self.picker = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER,
                                            tooltip_text="Elegir cualquier color")
        self.picker.set_rgba(self._rgba(state.accent))
        self.picker.connect("notify::rgba", self._on_custom_color)
        self.color_row.add_suffix(self.picker)
        look.add(self.color_row)

        swatch_row = Adw.PreferencesRow(activatable=False)
        box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8, min_children_per_line=4,
                          column_spacing=10, row_spacing=10, margin_top=12, margin_bottom=12,
                          margin_start=12, margin_end=12, homogeneous=True)
        self.swatches: list[tuple[Gtk.Button, str]] = []
        for i, (name, color) in enumerate(ACCENT_PRESETS):
            btn = Gtk.Button(css_classes=["swatch", f"swatch-{i}"], tooltip_text=name, halign=Gtk.Align.CENTER)
            btn.connect("clicked", lambda _b, c=color: self._set_accent(c))
            box.append(btn)
            self.swatches.append((btn, color))
        swatch_row.set_child(box)
        look.add(swatch_row)

        schemes = [("system", "Como el sistema"), ("light", "Claro"), ("dark", "Oscuro")]
        keys = [s[0] for s in schemes]
        scheme_row = Adw.ComboRow(title="Estilo", model=Gtk.StringList.new([s[1] for s in schemes]))
        scheme_row.set_selected(keys.index(state.color_scheme) if state.color_scheme in keys else 0)
        scheme_row.connect("notify::selected", lambda r, _p: app.theme.set_color_scheme(keys[r.get_selected()]))
        look.add(scheme_row)

        # --- Claude
        claude = Adw.PreferencesGroup(title="Claude")
        page.add(claude)
        edits = Adw.SwitchRow(title="Aceptar ediciones sin preguntar",
                              subtitle="Claude podrá crear y editar archivos sin pedir permiso cada vez",
                              active=state.accept_edits)
        edits.connect("notify::active", lambda r, _p: window.activate_action("win.accept-edits", None)
                      if r.get_active() != state.accept_edits else None)
        claude.add(edits)

        # --- voz
        voice = Adw.PreferencesGroup(title="Voz")
        page.add(voice)
        auto = Adw.SwitchRow(title="Enviar al terminar de hablar",
                             subtitle="Si lo desactivas, puedes revisar el texto antes de enviarlo",
                             active=state.auto_send)
        auto.connect("notify::active", lambda r, _p: self._set_state("auto_send", r.get_active()))
        voice.add(auto)
        beep = Adw.SwitchRow(title="Pitido al empezar a escuchar", active=state.beep)
        beep.connect("notify::active", lambda r, _p: self._set_state("beep", r.get_active()))
        voice.add(beep)

        # --- atajos globales (solo informativo)
        shortcuts = Adw.PreferencesGroup(title="Atajos globales",
                                         description="Se cambian en Configuración → Teclado → Atajos personalizados")
        shortcut_rows(shortcuts, GLOBAL_SHORTCUTS)
        page.add(shortcuts)

        self._refresh_swatches()

    @staticmethod
    def _rgba(color: str) -> Gdk.RGBA:
        rgba = Gdk.RGBA()
        rgba.parse(color)
        return rgba

    def _set_state(self, key: str, value) -> None:
        setattr(self.app.state, key, value)
        self.app.state.save()

    def _set_accent(self, color: str) -> None:
        self.app.theme.set_accent(color)
        self.picker.set_rgba(self._rgba(color))
        self._refresh_swatches()

    def _on_custom_color(self, button, _pspec) -> None:
        c = button.get_rgba()
        color = "#{:02x}{:02x}{:02x}".format(round(c.red * 255), round(c.green * 255), round(c.blue * 255))
        if color != self.app.state.accent:
            self.app.theme.set_accent(color)
            self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        current = self.app.state.accent.lower()
        name = next((n for n, c in ACCENT_PRESETS if c == current), "Personalizado")
        self.color_row.set_subtitle(f"{name} · {current}")
        for btn, color in self.swatches:
            btn.set_child(Gtk.Image(icon_name="object-select-symbolic") if color == current else None)


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        GLib.set_application_name(APP_NAME)
        self.cfg = Config.load()
        self.state = State.load()
        self.window: MainWindow | None = None
        self.theme: Theme | None = None
        self._snipping = False

    def do_startup(self):
        Adw.Application.do_startup(self)
        self.theme = Theme(self.state)

    def do_activate(self):
        if self.window is None:
            self.window = MainWindow(self)
        self.window.present()

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()[1:]
        if "--snip" in args:
            self.start_snip()
            return 0
        self.activate()
        folders = [a for a in args if not a.startswith("-")]
        if folders:
            path = Path(command_line.get_cwd() or ".", folders[0]).expanduser().resolve()
            if path.is_dir() and str(path) != self.window.project:
                self.window.set_project(str(path))
        if "--voice" in args:
            self.window.start_voice()
        return 0

    # ------------------------------------------------------------------ recorte

    def start_snip(self) -> None:
        from .snip import QuickWindow, SnipOverlay, take_screenshot

        if self._snipping:
            return
        self._snipping = True
        self.hold()  # que la app no se cierre mientras llega la captura

        def on_shot(pixbuf, error):
            if pixbuf is None:
                self._snip_finished()
                self._notify_error(error)
                return
            SnipOverlay(self, pixbuf, self.state.accent, on_selected)

        def on_selected(snip):
            if snip is not None:
                QuickWindow(self, snip)
            self._snip_finished()

        # si la ventana principal está delante, que no salga en la captura
        if self.window and self.window.is_active():
            self.window.minimize()
            GLib.timeout_add(300, lambda: take_screenshot(on_shot) and False)
        else:
            take_screenshot(on_shot)

    def _snip_finished(self) -> None:
        self._snipping = False
        self.release()

    def _notify_error(self, text: str) -> None:
        note = Gio.Notification.new(f"{APP_NAME}: no se pudo recortar")
        note.set_body(text)
        self.send_notification("snip-error", note)

    def continue_in_main(self, session_id: str | None, project: str, history: list[str]) -> None:
        self.activate()
        self.window.continue_conversation(session_id, project, history)


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
