"""Selección del recorte: congela la pantalla y deja arrastrar un rectángulo con el ratón.

Se ejecuta en un proceso aparte (python snip_overlay.py SALIDA.png COLOR) para que tkinter
y el escalado por monitor no se mezclen con las ventanas de la app:

1. Se captura cada monitor con mss, en píxeles reales (el proceso es «per-monitor DPI aware»).
2. Se muestra congelada y oscurecida a pantalla completa en cada monitor, con una ventana tkinter.
3. Al soltar el clic se guarda el trozo en SALIDA.png y el proceso termina con código 0.
   Esc (o el botón derecho) cancela: código 1.
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk

import mss
from PIL import Image, ImageEnhance, ImageTk

HINT = "Arrastra para recortar  ·  Esc para cancelar"


def dpi_aware() -> None:
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
    except (AttributeError, OSError):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)


def grab_monitors() -> list[tuple[dict, Image.Image]]:
    with mss.mss() as sct:
        out = []
        for mon in sct.monitors[1:]:
            shot = sct.grab(mon)
            out.append((dict(mon), Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")))
        return out


class Overlay:
    def __init__(self, out_path: str, accent: str):
        self.out_path, self.accent = out_path, accent
        self.result = 1
        self.root = tk.Tk()
        self.root.withdraw()
        self.screens = []
        for mon, img in grab_monitors():
            self.screens.append(Screen(self, mon, img))
        self.root.bind_all("<Escape>", lambda _e: self.finish(None, None))
        # que la ventana bajo el ratón reciba el teclado (Esc)
        self.root.after(60, self._focus)

    def _focus(self) -> None:
        x, y = self.root.winfo_pointerxy()
        for s in self.screens:
            if s.contains(x, y):
                s.focus()
                return
        if self.screens:
            self.screens[0].focus()

    def finish(self, screen: "Screen | None", box: tuple[int, int, int, int] | None) -> None:
        if screen is not None and box is not None:
            screen.image.crop(box).save(self.out_path, "PNG")
            self.result = 0
        self.root.quit()

    def run(self) -> int:
        self.root.mainloop()
        return self.result


class Screen:
    """La captura de un monitor, a pantalla completa, con la selección dibujada encima."""

    def __init__(self, overlay: Overlay, mon: dict, image: Image.Image):
        self.overlay, self.mon, self.image = overlay, mon, image
        self.win = tk.Toplevel(overlay.root)
        self.win.overrideredirect(True)
        self.win.geometry(f"{mon['width']}x{mon['height']}+{mon['left']}+{mon['top']}")
        self.win.attributes("-topmost", True)
        self.canvas = tk.Canvas(self.win, width=mon["width"], height=mon["height"], highlightthickness=0,
                                cursor="crosshair", bg="black")
        self.canvas.pack(fill="both", expand=True)
        self.dark = ImageTk.PhotoImage(ImageEnhance.Brightness(image).enhance(0.5))
        self.canvas.create_image(0, 0, image=self.dark, anchor="nw")
        self.bright_item = self.canvas.create_image(0, 0, anchor="nw")
        self.bright: ImageTk.PhotoImage | None = None
        self.rect_item = self.canvas.create_rectangle(0, 0, 0, 0, outline=overlay.accent, width=2, state="hidden")
        self.label_bg = self.canvas.create_rectangle(0, 0, 0, 0, fill=overlay.accent, outline="", state="hidden")
        self.label = self.canvas.create_text(0, 0, text="", fill="white", anchor="w",
                                             font=("Segoe UI", 10, "bold"), state="hidden")
        self._hint()
        self.start: tuple[int, int] | None = None
        self.box: tuple[int, int, int, int] | None = None
        self._crop_pending = False
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonPress-3>", lambda _e: overlay.finish(None, None))

    def _hint(self) -> None:
        cx = self.mon["width"] // 2
        text = self.canvas.create_text(cx, 60, text=HINT, fill="white", font=("Segoe UI", 13), tags="hint")
        x1, y1, x2, y2 = self.canvas.bbox(text)
        pad = 18
        self.canvas.create_rectangle(x1 - pad, y1 - 9, x2 + pad, y2 + 9, fill="#1a1a1a", outline="", tags="hint")
        self.canvas.tag_raise(text)

    def contains(self, x: int, y: int) -> bool:
        m = self.mon
        return m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]

    def focus(self) -> None:
        self.win.focus_force()
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except OSError:
            pass

    def _press(self, e) -> None:
        self.start = (e.x, e.y)
        self.box = (e.x, e.y, e.x, e.y)
        self.canvas.itemconfigure("hint", state="hidden")

    def _drag(self, e) -> None:
        if not self.start:
            return
        x0, y0 = self.start
        x1 = max(0, min(e.x, self.mon["width"]))
        y1 = max(0, min(e.y, self.mon["height"]))
        self.box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        l, t, r, b = self.box
        self.canvas.coords(self.rect_item, l, t, r, b)
        self.canvas.itemconfigure(self.rect_item, state="normal")
        label = f"{r - l} × {b - t}"
        ly = t - 16 if t > 34 else b + 18
        self.canvas.itemconfigure(self.label, text=label, state="normal")
        self.canvas.coords(self.label, l + 8, ly)
        x1b, y1b, x2b, y2b = self.canvas.bbox(self.label)
        self.canvas.coords(self.label_bg, l, y1b - 3, x2b + 8, y2b + 3)
        self.canvas.itemconfigure(self.label_bg, state="normal")
        self.canvas.tag_raise(self.label_bg)
        self.canvas.tag_raise(self.label)
        if not self._crop_pending:  # el trozo sin oscurecer se rehace como mucho ~60 veces por segundo
            self._crop_pending = True
            self.win.after(16, self._update_bright)

    def _update_bright(self) -> None:
        self._crop_pending = False
        if not self.box:
            return
        l, t, r, b = self.box
        if r - l < 1 or b - t < 1:
            return
        self.bright = ImageTk.PhotoImage(self.image.crop(self.box))
        self.canvas.itemconfigure(self.bright_item, image=self.bright)
        self.canvas.coords(self.bright_item, l, t)
        self.canvas.tag_raise(self.rect_item)
        self.canvas.tag_raise(self.label_bg)
        self.canvas.tag_raise(self.label)

    def _release(self, e) -> None:
        self._drag(e)
        box, self.start = self.box, None
        if not box or box[2] - box[0] < 8 or box[3] - box[1] < 8:  # un clic suelto: no vale como selección
            self.box = None
            for item in (self.rect_item, self.label, self.label_bg):
                self.canvas.itemconfigure(item, state="hidden")
            self.canvas.itemconfigure(self.bright_item, image="")
            self.canvas.itemconfigure("hint", state="normal")
            return
        self.overlay.finish(self, box)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    dpi_aware()
    return Overlay(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "#d97757").run()


if __name__ == "__main__":
    sys.exit(main())
