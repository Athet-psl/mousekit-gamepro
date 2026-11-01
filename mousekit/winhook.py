"""Windows input: low-level hooks, raw input and SendInput, in evdev terms.

Windows has no exclusive grab and no virtual devices. Instead a low-level
mouse hook sees every button and wheel event before the system acts on it
and may swallow it, and SendInput injects new events. Raw input says which
mouse moved last (hooks don't know the device) and delivers its relative
motion, which hooks only show as cursor positions that stop at screen edges.

Events Mousekit injects carry INJECTED_TAG in their extra info; the hook
leaves those, and anything injected by other software, alone.
"""

import ctypes
import logging
import threading
from ctypes import wintypes

from .codes import ecodes as e

log = logging.getLogger("mousekit")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

INJECTED_TAG = 0x4D4B4954  # "MKIT"
ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_QUIT, WM_INPUT = 0x0012, 0x00FF
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP = 0x204, 0x205, 0x207, 0x208
WM_MOUSEWHEEL, WM_XBUTTONDOWN, WM_XBUTTONUP, WM_MOUSEHWHEEL = 0x20A, 0x20B, 0x20C, 0x20E
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
LLMHF_INJECTED, LLMHF_LOWER_IL_INJECTED = 0x1, 0x2
LLKHF_INJECTED = 0x10
WHEEL_DELTA = 120

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x8, 0x10
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x20, 0x40
MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP = 0x80, 0x100
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
XBUTTON1, XBUTTON2 = 1, 2

RIDEV_INPUTSINK = 0x100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIDI_DEVICENAME = 0x20000007
MOUSE_MOVE_ABSOLUTE = 0x1
SPI_GETMOUSESPEED, SPI_SETMOUSESPEED = 0x70, 0x71
HWND_MESSAGE = wintypes.HWND(-3)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT), ("dwFlags", wintypes.DWORD),
                ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD), ("hDevice", wintypes.HANDLE),
                ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    _fields_ = [("usFlags", wintypes.USHORT), ("usButtonFlags", wintypes.USHORT),
                ("usButtonData", wintypes.USHORT), ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG), ("lLastY", wintypes.LONG), ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(wintypes.UINT),
                                   wintypes.UINT]
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
                                          ctypes.POINTER(wintypes.UINT)]
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

# Linux key code -> (virtual key, extended)
_EXT = True
VK = {
    e.KEY_ESC: (0x1B, False), e.KEY_TAB: (0x09, False), e.KEY_BACKSPACE: (0x08, False),
    e.KEY_ENTER: (0x0D, False), e.KEY_KPENTER: (0x0D, _EXT), e.KEY_SPACE: (0x20, False),
    e.KEY_LEFTCTRL: (0xA2, False), e.KEY_LEFTSHIFT: (0xA0, False), e.KEY_LEFTALT: (0xA4, False),
    e.KEY_LEFTMETA: (0x5B, _EXT), e.KEY_RIGHTCTRL: (0xA3, _EXT), e.KEY_RIGHTSHIFT: (0xA1, False),
    e.KEY_RIGHTALT: (0xA5, _EXT), e.KEY_RIGHTMETA: (0x5C, _EXT),
    e.KEY_INSERT: (0x2D, _EXT), e.KEY_DELETE: (0x2E, _EXT), e.KEY_HOME: (0x24, _EXT), e.KEY_END: (0x23, _EXT),
    e.KEY_PAGEUP: (0x21, _EXT), e.KEY_PAGEDOWN: (0x22, _EXT), e.KEY_LEFT: (0x25, _EXT), e.KEY_UP: (0x26, _EXT),
    e.KEY_RIGHT: (0x27, _EXT), e.KEY_DOWN: (0x28, _EXT),
    e.KEY_CAPSLOCK: (0x14, False), e.KEY_NUMLOCK: (0x90, _EXT), e.KEY_SCROLLLOCK: (0x91, False),
    e.KEY_PAUSE: (0x13, False), e.KEY_SYSRQ: (0x2C, _EXT), e.KEY_COMPOSE: (0x5D, _EXT),
    e.KEY_MINUS: (0xBD, False), e.KEY_EQUAL: (0xBB, False), e.KEY_LEFTBRACE: (0xDB, False),
    e.KEY_RIGHTBRACE: (0xDD, False), e.KEY_SEMICOLON: (0xBA, False), e.KEY_APOSTROPHE: (0xDE, False),
    e.KEY_GRAVE: (0xC0, False), e.KEY_BACKSLASH: (0xDC, False), e.KEY_COMMA: (0xBC, False),
    e.KEY_DOT: (0xBE, False), e.KEY_SLASH: (0xBF, False),
    e.KEY_PLAYPAUSE: (0xB3, _EXT), e.KEY_PAUSECD: (0xB3, _EXT), e.KEY_STOPCD: (0xB2, _EXT),
    e.KEY_NEXTSONG: (0xB0, _EXT), e.KEY_PREVIOUSSONG: (0xB1, _EXT),
    e.KEY_VOLUMEUP: (0xAF, _EXT), e.KEY_VOLUMEDOWN: (0xAE, _EXT), e.KEY_MUTE: (0xAD, _EXT),
    e.KEY_BACK: (0xA6, _EXT), e.KEY_FORWARD: (0xA7, _EXT), e.KEY_REFRESH: (0xA8, _EXT),
    e.KEY_CALC: (0xB7, _EXT), e.KEY_SLEEP: (0x5F, False),
}
for _i, _c in enumerate("1234567890"):
    VK[2 + _i] = (ord(_c), False)
for _row, _start in (("QWERTYUIOP", 16), ("ASDFGHJKL", 30), ("ZXCVBNM", 44)):
    for _i, _c in enumerate(_row):
        VK[_start + _i] = (ord(_c), False)
for _i in range(10):
    VK[59 + _i] = (0x70 + _i, False)    # F1-F10
VK[e.KEY_F11], VK[e.KEY_F12] = (0x7A, False), (0x7B, False)
for _i in range(12):
    VK[183 + _i] = (0x7C + _i, False)   # F13-F24

# Mouse buttons: evdev code -> (down flag, up flag, mouseData)
BUTTON_FLAGS = {
    e.BTN_LEFT: (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 0),
    e.BTN_RIGHT: (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, 0),
    e.BTN_MIDDLE: (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP, 0),
    e.BTN_SIDE: (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    e.BTN_EXTRA: (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
    e.BTN_BACK: (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON1),
    e.BTN_FORWARD: (MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP, XBUTTON2),
}


def _send(inputs):
    array = (INPUT * len(inputs))(*inputs)
    if user32.SendInput(len(inputs), array, ctypes.sizeof(INPUT)) != len(inputs):
        log.warning("SendInput failed: %s", ctypes.WinError(ctypes.get_last_error()))


def key_input(code, down):
    vk, extended = VK[code]
    flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (0 if down else KEYEVENTF_KEYUP)
    scan = user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=INJECTED_TAG)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=ki))


def vk_input(vk, down, extended=True):
    flags = (KEYEVENTF_EXTENDEDKEY if extended else 0) | (0 if down else KEYEVENTF_KEYUP)
    ki = KEYBDINPUT(wVk=vk, wScan=user32.MapVirtualKeyW(vk, 0), dwFlags=flags, time=0, dwExtraInfo=INJECTED_TAG)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=ki))


def mouse_input(flags, data=0):
    mi = MOUSEINPUT(dx=0, dy=0, mouseData=data & 0xFFFFFFFF, dwFlags=flags, time=0, dwExtraInfo=INJECTED_TAG)
    return INPUT(type=INPUT_MOUSE, u=_INPUTUNION(mi=mi))


def send_keys(codes, down):
    """Press (down) or release a combination of evdev key codes, in order (released in reverse)."""
    known = [code for code in codes if code in VK]
    _send([key_input(code, down) for code in (known if down else reversed(known))])


def send_vk(vk, down, extended=True):
    _send([vk_input(vk, down, extended)])


def send_button(code, down):
    if code not in BUTTON_FLAGS:
        return
    press, release, data = BUTTON_FLAGS[code]
    _send([mouse_input(press if down else release, data)])


def send_wheel(delta, horizontal=False):
    _send([mouse_input(MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, delta)])


def mouse_speed():
    speed = ctypes.c_int()
    user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(speed), 0)
    return speed.value


def set_mouse_speed(speed):
    """Pointer speed 1-20 for this session only (not written to the user's profile)."""
    user32.SystemParametersInfoW(SPI_SETMOUSESPEED, 0, ctypes.c_void_p(max(1, min(20, int(speed)))), 0)


def _signed16(value):
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


class Hooks:
    """Runs the hooks and raw input on one thread with its own message loop.

    on_mouse(message, data, device) and on_key(vk, scan, down) are called on
    that thread and return True to swallow the event; on_motion(device, dx, dy)
    gets raw relative motion. `device` is the raw input device path of the
    mouse that moved last (or None). Callbacks must be quick: Windows drops a
    hook that keeps it waiting.
    """

    def __init__(self, on_mouse, on_key, on_motion):
        self.on_mouse = on_mouse
        self.on_key = on_key
        self.on_motion = on_motion
        self.device = None
        self._names = {}
        self._thread_id = None
        self._ready = threading.Event()
        self._error = None
        # Keep references: ctypes callbacks must outlive the hooks.
        self._mouse_proc = HOOKPROC(self._mouse_hook)
        self._key_proc = HOOKPROC(self._key_hook)
        self._wnd_proc = WNDPROC(self._window_proc)

    def run(self):
        """The message loop; returns after stop()."""
        self._thread_id = kernel32.GetCurrentThreadId()
        module = kernel32.GetModuleHandleW(None)
        hwnd = None
        hooks = []
        try:
            cls = WNDCLASSW(lpfnWndProc=self._wnd_proc, hInstance=module, lpszClassName="MousekitRawInput")
            user32.RegisterClassW(ctypes.byref(cls))
            hwnd = user32.CreateWindowExW(0, "MousekitRawInput", "Mousekit", 0, 0, 0, 0, 0, HWND_MESSAGE,
                                          None, module, None)
            if hwnd:
                device = RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, hwnd)
                if not user32.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(RAWINPUTDEVICE)):
                    log.warning("raw input unavailable: %s", ctypes.WinError(ctypes.get_last_error()))
            for kind, proc in ((WH_MOUSE_LL, self._mouse_proc), (WH_KEYBOARD_LL, self._key_proc)):
                hook = user32.SetWindowsHookExW(kind, proc, module, 0)
                if not hook:
                    raise ctypes.WinError(ctypes.get_last_error())
                hooks.append(hook)
        except OSError as err:
            self._error = err
            self._ready.set()
            for hook in hooks:
                user32.UnhookWindowsHookEx(hook)
            raise
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            for hook in hooks:
                user32.UnhookWindowsHookEx(hook)
            if hwnd:
                user32.DestroyWindow(hwnd)

    def stop(self):
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def wait_ready(self, timeout=5):
        self._ready.wait(timeout)
        if self._error:
            raise self._error

    def _device_name(self, handle):
        if handle not in self._names:
            size = wintypes.UINT(0)
            user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(size))
            buf = ctypes.create_unicode_buffer(size.value + 1)
            got = user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf, ctypes.byref(size))
            self._names[handle] = buf.value.lower() if got not in (0, 0xFFFFFFFF) else None
        return self._names[handle]

    def _window_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            raw = RAWINPUT()
            size = wintypes.UINT(ctypes.sizeof(raw))
            got = user32.GetRawInputData(lparam, RID_INPUT, ctypes.byref(raw), ctypes.byref(size),
                                         ctypes.sizeof(RAWINPUTHEADER))
            if got != 0xFFFFFFFF and raw.header.dwType == RIM_TYPEMOUSE and raw.header.hDevice:
                self.device = self._device_name(raw.header.hDevice)
                if not raw.mouse.usFlags & MOUSE_MOVE_ABSOLUTE and (raw.mouse.lLastX or raw.mouse.lLastY):
                    try:
                        self.on_motion(self.device, raw.mouse.lLastX, raw.mouse.lLastY)
                    except Exception:  # noqa: BLE001 - never let a bug take the message loop down
                        log.exception("motion handler failed")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _mouse_hook(self, code, wparam, lparam):
        if code == 0 and wparam != WM_MOUSEMOVE:
            info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not info.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED):
                try:
                    if self.on_mouse(wparam, info.mouseData, self.device):
                        return 1
                except Exception:  # noqa: BLE001
                    log.exception("mouse handler failed")
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _key_hook(self, code, wparam, lparam):
        if code == 0:
            info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not info.flags & LLKHF_INJECTED:
                down = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                try:
                    if self.on_key(info.vkCode, info.scanCode, down):
                        return 1
                except Exception:  # noqa: BLE001
                    log.exception("key handler failed")
        return user32.CallNextHookEx(None, code, wparam, lparam)


def mouse_event(message, data):
    """A hooked mouse message as evdev events [(type, code, value)], or None for what Mousekit leaves alone."""
    buttons = {
        WM_LBUTTONDOWN: (e.BTN_LEFT, 1), WM_LBUTTONUP: (e.BTN_LEFT, 0),
        WM_RBUTTONDOWN: (e.BTN_RIGHT, 1), WM_RBUTTONUP: (e.BTN_RIGHT, 0),
        WM_MBUTTONDOWN: (e.BTN_MIDDLE, 1), WM_MBUTTONUP: (e.BTN_MIDDLE, 0),
    }
    if message in buttons:
        code, value = buttons[message]
        return [(e.EV_KEY, code, value)]
    if message in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        which = (data >> 16) & 0xFFFF
        code = {XBUTTON1: e.BTN_SIDE, XBUTTON2: e.BTN_EXTRA}.get(which)
        return [(e.EV_KEY, code, int(message == WM_XBUTTONDOWN))] if code else None
    if message == WM_MOUSEWHEEL:
        delta = _signed16(data >> 16)
        events = []
        notches = int(delta / WHEEL_DELTA)
        if notches:
            events.append((e.EV_REL, e.REL_WHEEL, notches))
        events.append((e.EV_REL, e.REL_WHEEL_HI_RES, delta))
        return events
    return None  # horizontal wheel and anything else pass untouched


def inject(events):
    """Send evdev events produced by the engine for a swallowed input."""
    hi_res = any(code == e.REL_WHEEL_HI_RES for type_, code, _ in events if type_ == e.EV_REL)
    for type_, code, value in events:
        if type_ == e.EV_KEY:
            send_button(code, value == 1)
        elif type_ == e.EV_REL and code == e.REL_WHEEL_HI_RES:
            send_wheel(value)
        elif type_ == e.EV_REL and code == e.REL_WHEEL and not hi_res:
            send_wheel(value * WHEEL_DELTA)
        elif type_ == e.EV_REL and code == e.REL_HWHEEL:
            send_wheel(value * WHEEL_DELTA, horizontal=True)
