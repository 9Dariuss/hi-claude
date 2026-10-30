"""Pequeñas llamadas a la API de Windows (ctypes): icono, barra de título, primer plano, portapapeles."""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import winreg

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

APP_USER_MODEL_ID = "9Dariuss.HiClaude"

WM_SETICON = 0x0080
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 20, 35, 36
SW_RESTORE = 9
FLASHW_ALL, FLASHW_TIMERNOFG = 3, 12
ASFW_ANY = -1


class FLASHWINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("hwnd", wt.HWND), ("dwFlags", wt.DWORD),
                ("uCount", wt.UINT), ("dwTimeout", wt.DWORD)]


def set_app_id() -> None:
    """Que la barra de tareas agrupe y muestre las ventanas como «Hi Claude!» y no como Python."""
    try:
        shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def set_icon(hwnd: int, ico_path: str) -> None:
    if not hwnd or not os.path.exists(ico_path):
        return
    load = user32.LoadImageW
    load.restype = wt.HANDLE
    for size, which in ((16, 0), (32, 1)):  # ICON_SMALL, ICON_BIG
        handle = load(None, ico_path, IMAGE_ICON, size if which == 0 else 0, size if which == 0 else 0,
                      LR_LOADFROMFILE | (0 if which == 0 else LR_DEFAULTSIZE))
        if handle:
            user32.SendMessageW(wt.HWND(hwnd), WM_SETICON, which, handle)


def _colorref(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def set_caption(hwnd: int, dark: bool, bg: str, fg: str) -> None:
    """Barra de título del mismo color que la app (Windows 11) y en modo oscuro si toca (Windows 10)."""
    if not hwnd:
        return
    for attr, value in ((DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark)),
                        (DWMWA_CAPTION_COLOR, _colorref(bg)), (DWMWA_TEXT_COLOR, _colorref(fg))):
        v = ctypes.c_int(value)
        dwmapi.DwmSetWindowAttribute(wt.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))


def is_foreground(hwnd: int) -> bool:
    return bool(hwnd) and user32.GetForegroundWindow() == hwnd


def bring_to_front(hwnd: int) -> None:
    if not hwnd:
        return
    if user32.IsIconic(wt.HWND(hwnd)):
        user32.ShowWindow(wt.HWND(hwnd), SW_RESTORE)
    user32.SetForegroundWindow(wt.HWND(hwnd))


def allow_foreground() -> None:
    """La ventana que abramos (o a la que avisemos) podrá ponerse delante."""
    user32.AllowSetForegroundWindow(ASFW_ANY)


def flash(hwnd: int) -> None:
    """Hace parpadear el botón de la barra de tareas hasta que vuelvas a la ventana."""
    if hwnd:
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), wt.HWND(hwnd), FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0)
        user32.FlashWindowEx(ctypes.byref(info))


def system_dark() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        return False


def copy_text(text: str) -> None:
    import win32clipboard

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


class NamedMutex:
    """Mutex con nombre: sirve para saber si ya hay otra instancia abierta."""

    def __init__(self, name: str):
        kernel32.CreateMutexW.restype = wt.HANDLE
        self.handle = kernel32.CreateMutexW(None, False, name)
        self.already_existed = kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
