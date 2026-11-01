"""A Windows notification (a tray balloon) with a click action, without a GUI toolkit."""

import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger("mousekit")

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WM_USER, WM_TIMER, WM_CLOSE, WM_DESTROY, WM_LBUTTONUP = 0x400, 0x113, 0x10, 0x2, 0x202
CALLBACK = WM_USER + 1
NIN_BALLOONTIMEOUT, NIN_BALLOONUSERCLICK = WM_USER + 4, WM_USER + 5
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
NIIF_INFO = 0x1
IDI_APPLICATION = 32512


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HICON)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.LoadIconW.restype = wintypes.HICON
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]


def _icon(module):
    icon = user32.LoadIconW(module, ctypes.c_void_p(1))  # the exe's own icon in the installed build
    return icon or user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))


def _show(title, text, on_click, seconds):
    module = kernel32.GetModuleHandleW(None)
    data = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), uID=1)
    clicked = []

    def proc(hwnd, msg, wparam, lparam):
        if msg == CALLBACK and (lparam & 0xFFFF) in (NIN_BALLOONUSERCLICK, WM_LBUTTONUP):
            clicked.append(True)
            user32.DestroyWindow(hwnd)
        elif msg == CALLBACK and (lparam & 0xFFFF) == NIN_BALLOONTIMEOUT or msg in (WM_TIMER, WM_CLOSE):
            user32.DestroyWindow(hwnd)
        elif msg == WM_DESTROY:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(data))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc = WNDPROC(proc)
    cls = WNDCLASSW(lpfnWndProc=wndproc, hInstance=module, lpszClassName="MousekitNotify")
    user32.RegisterClassW(ctypes.byref(cls))
    hwnd = user32.CreateWindowExW(0, "MousekitNotify", "Mousekit", 0, 0, 0, 0, 0, None, None, module, None)
    if not hwnd:
        return
    data.hWnd = hwnd
    data.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_INFO
    data.uCallbackMessage = CALLBACK
    data.hIcon = _icon(module)
    data.szTip = "Mousekit"
    data.szInfoTitle = title[:63]
    data.szInfo = text[:255]
    data.dwInfoFlags = NIIF_INFO
    if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(data)):
        user32.DestroyWindow(hwnd)
        return
    user32.SetTimer(hwnd, 1, int(seconds * 1000), None)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.DispatchMessageW(ctypes.byref(msg))
    if clicked and on_click:
        on_click()


def notify(title, text, on_click=None, seconds=60):
    """Show a notification on its own thread; on_click runs if the user clicks it."""
    def run():
        try:
            _show(title, text, on_click, seconds)
        except Exception:  # noqa: BLE001
            log.exception("notification failed")

    threading.Thread(target=run, daemon=True, name="notify").start()


def open_about():
    from . import winservice

    winservice.launch_app("--about")
