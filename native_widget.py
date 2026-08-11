import ctypes
import os
import subprocess
import sys
import threading
import queue
import traceback
import time
from datetime import datetime
from ctypes import wintypes
from pathlib import Path

from bambu_core import APP_DIR, CONFIG_PATH, BambuMqttClient, ConfigError, load_config, update_config


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

if not hasattr(wintypes, "LRESULT"):
    wintypes.LRESULT = ctypes.c_ssize_t
if not hasattr(wintypes, "HCURSOR"):
    wintypes.HCURSOR = wintypes.HANDLE
if not hasattr(wintypes, "COLORREF"):
    wintypes.COLORREF = ctypes.c_uint32
if not hasattr(wintypes, "UINT_PTR"):
    wintypes.UINT_PTR = ctypes.c_size_t
if not hasattr(wintypes, "HGDIOBJ"):
    wintypes.HGDIOBJ = wintypes.HANDLE
if not hasattr(wintypes, "HFONT"):
    wintypes.HFONT = wintypes.HANDLE


WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_ERASEBKGND = 0x0014
WM_QUIT = 0x0012
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200
WM_RBUTTONUP = 0x0205
WM_COMMAND = 0x0111
WM_TIMER = 0x0113
WM_DISPLAYCHANGE = 0x007E
PM_REMOVE = 0x0001

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_CLIPCHILDREN = 0x02000000
WS_CLIPSIBLINGS = 0x04000000

WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOPMOST = 0x00000008

GWL_STYLE = -16
GWL_EXSTYLE = -20

SW_SHOW = 5
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

MB_OK = 0x00000000
MB_ICONINFORMATION = 0x00000040
MB_SETFOREGROUND = 0x00010000

HWND_TOP = 0
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Local\\BambuNativeWidget-6E318C1D-4BDB-4CC3-9D48-6FDC3B856E94"

MF_STRING = 0x0000
TPM_RIGHTBUTTON = 0x0002

TRANSPARENT = 1
DT_LEFT = 0x0000
DT_CENTER = 0x0001
DT_VCENTER = 0x0004
DT_SINGLELINE = 0x0020
DT_END_ELLIPSIS = 0x8000

EDGE = 8
MIN_WIDTH = 170
MIN_HEIGHT = 72
TIMER_MAIN = 1

ID_MENU_SETTINGS = 1001
ID_MENU_RECONNECT = 1002
ID_MENU_EXIT = 1003
LOG_PATH = APP_DIR / "startup.log"

WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
ENUMWINDOWSPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def configure_ctypes():
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = wintypes.LRESULT
    user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.BeginPaint.restype = wintypes.HDC
    user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
    user32.EndPaint.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = wintypes.LRESULT
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.SetCapture.argtypes = [wintypes.HWND]
    user32.SetCapture.restype = wintypes.HWND
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.SetCursor.argtypes = [wintypes.HCURSOR]
    user32.SetCursor.restype = wintypes.HCURSOR
    user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadCursorW.restype = wintypes.HCURSOR
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wintypes.HICON
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.EnumChildWindows.argtypes = [wintypes.HWND, ENUMWINDOWSPROC, wintypes.LPARAM]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT
    user32.EnumWindows.argtypes = [ENUMWINDOWSPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetDesktopWindow.argtypes = []
    user32.GetDesktopWindow.restype = wintypes.HWND
    user32.SetTimer.argtypes = [wintypes.HWND, wintypes.UINT_PTR, wintypes.UINT_PTR, wintypes.LPVOID]
    user32.SetTimer.restype = wintypes.UINT_PTR
    user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT), wintypes.BOOL]
    user32.InvalidateRect.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.MonitorFromRect.argtypes = [ctypes.POINTER(RECT), wintypes.DWORD]
    user32.MonitorFromRect.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT_PTR, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = wintypes.BOOL
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
    user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), wintypes.HBRUSH]
    user32.FillRect.restype = ctypes.c_int

    gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.SetBkMode.restype = ctypes.c_int
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    gdi32.SetTextColor.restype = wintypes.COLORREF
    user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(RECT), wintypes.UINT]
    user32.DrawTextW.restype = ctypes.c_int
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
    gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, wintypes.LPCWSTR]
    gdi32.CreateFontW.restype = wintypes.HFONT


def rgb(r, g, b):
    return r | (g << 8) | (b << 16)


def rgb_hex(color):
    color = color.lstrip("#")
    return int(color[4:6], 16) | (int(color[2:4], 16) << 8) | (int(color[0:2], 16) << 16)


def log_event(message):
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except Exception:
        pass


def loword(value):
    return value & 0xFFFF


def make_int_resource(value):
    return ctypes.c_void_p(value & 0xFFFF)


def get_x_lparam(lparam):
    return ctypes.c_short(lparam & 0xFFFF).value


def get_y_lparam(lparam):
    return ctypes.c_short((lparam >> 16) & 0xFFFF).value


def normalized_font_size(config):
    try:
        value = int(config.get("font_size", 14))
    except (TypeError, ValueError):
        value = 14
    return max(5, min(30, value))


def layout_mode(width, height, font_size=14):
    if height < max(112, 5 * font_size + 70):
        return "mini"
    if height < max(158, 6 * font_size + 85) or width < 285:
        return "compact"
    return "full"


def clamp_window_rect(x, y, width, height):
    rect = RECT(x, y, x + width, y + height)
    monitor = user32.MonitorFromRect(ctypes.byref(rect), 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        work = info.rcWork
        min_width = min(width, work.right - work.left)
        min_height = min(height, work.bottom - work.top)
        max_x = work.right - min_width
        max_y = work.bottom - min_height
        x = max(work.left, min(x, max_x))
        y = max(work.top, min(y, max_y))
        width = max(120, min(width, work.right - work.left))
        height = max(72, min(height, work.bottom - work.top))
        return x, y, width, height
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    if screen_w > 0 and screen_h > 0:
        width = min(width, screen_w)
        height = min(height, screen_h)
        x = max(0, min(x, screen_w - width))
        y = max(0, min(y, screen_h - height))
    return x, y, width, height


def configured_window_rect(config):
    window = config.get("window", {})
    x = int(window.get("x", 80))
    y = int(window.get("y", 80))
    width = int(window.get("width", 330))
    height = int(window.get("height", 172))
    return clamp_window_rect(x, y, width, height)


def find_desktop_host():
    desktop = user32.GetDesktopWindow()
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        log_event("find_desktop_host fallback to desktop window")
        return desktop

    result = wintypes.DWORD()
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, ctypes.byref(result))

    deadline = time.time() + 2.0

    while True:
        found = {"host": None}

        def callback(hwnd, _lparam):
            shell_view = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
            if shell_view:
                found["host"] = hwnd
                return False
            return True

        user32.EnumWindows(ENUMWINDOWSPROC(callback), 0)
        if found["host"]:
            log_event(f"find_desktop_host host={int(found['host'])}")
            return found["host"]
        if time.time() >= deadline:
            log_event("find_desktop_host fallback to Progman")
            return progman or desktop
        time.sleep(0.1)

    log_event("find_desktop_host fallback to desktop window")
    return desktop


def attach_hwnd_to_desktop(hwnd, x, y, width, height):
    host = find_desktop_host()
    if not host:
        return None

    point = POINT(x, y)
    user32.ScreenToClient(host, ctypes.byref(point))

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style = (style & ~WS_POPUP) | WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)

    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex_style = ex_style & ~(WS_EX_APPWINDOW | WS_EX_TOPMOST)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

    user32.SetParent(hwnd, host)
    user32.SetWindowPos(
        hwnd,
        HWND_TOP,
        point.x,
        point.y,
        width,
        height,
        SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
    )
    user32.ShowWindow(hwnd, SW_SHOW)
    user32.UpdateWindow(hwnd)
    log_event(f"attached hwnd={int(hwnd)} to desktop host={int(host)}")
    return host


def acquire_single_instance():
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        existing = find_existing_widget_window()
        if existing:
            restore_existing_widget_window(existing)
            kernel32.CloseHandle(handle)
            return None
        log_event("stale widget mutex found; starting a replacement instance")
    return handle


def find_existing_widget_window():
    found = None

    def check_window(hwnd, _lparam):
        nonlocal found
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if class_name.value == "BambuNativeWidget":
            found = hwnd
            return False
        return True

    check_callback = ENUMWINDOWSPROC(check_window)

    def check_top_level(hwnd, _lparam):
        if not check_window(hwnd, 0):
            return False
        user32.EnumChildWindows(hwnd, check_callback, 0)
        return found is None

    user32.EnumWindows(ENUMWINDOWSPROC(check_top_level), 0)
    return found


def restore_existing_widget_window(hwnd):
    try:
        config = load_config()
    except ConfigError:
        config = {}
    x, y, width, height = configured_window_rect(config)
    attached = attach_hwnd_to_desktop(hwnd, x, y, width, height)
    if attached:
        log_event(f"restored existing desktop widget hwnd={int(hwnd)}")
    else:
        log_event(f"failed to restore existing desktop widget hwnd={int(hwnd)}")


class NativeWidget:
    def __init__(self):
        log_event("init")
        self.config = load_config()
        log_event(f"config window={self.config.get('window', {})}")
        self.event_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.client_thread = None
        self.client = None
        self.next_desktop_check = 0
        self.taskbar_created_msg = user32.RegisterWindowMessageW("TaskbarCreated")
        self.last_mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else 0
        self.status = {
            "state": "UNKNOWN",
            "state_label": "未知",
            "state_color": "#8a929d",
            "percent": None,
            "remaining_text": "--",
            "eta_text": "--:--",
            "layers_text": "--",
            "job_name": self.config.get("printer_name", "Bambu"),
        }
        self.connection_text = "未连接"
        self.seen_printer_status = False
        self.last_print_state = None
        self.hwnd = None
        self.drag_mode = None
        self.drag_origin = None
        self.drag_rect = None
        self.class_name = "BambuNativeWidget"
        self.wndproc_ref = WNDPROC(self._wndproc)
        self.hinst = kernel32.GetModuleHandleW(None)
        self.fonts = {}
        self.font_heights = {}
        self.current_font_size = None
        self.brushes = {}

    def run(self):
        log_event("run start")
        self.start_client()
        self.register_class()
        self.create_window()
        self.message_loop()

    def register_class(self):
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self.wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = self.hinst
        wc.hIcon = user32.LoadIconW(None, make_int_resource(32512))
        wc.hCursor = user32.LoadCursorW(None, make_int_resource(32512))
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self.class_name
        if not user32.RegisterClassW(ctypes.byref(wc)):
            err = ctypes.get_last_error()
            if err != 1410:
                raise ctypes.WinError(err)
        log_event("register_class ok")

    def create_window(self):
        x, y, width, height = configured_window_rect(self.config)

        ex_style = WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE
        style = WS_POPUP | WS_CLIPCHILDREN | WS_CLIPSIBLINGS

        self.hwnd = user32.CreateWindowExW(
            ex_style,
            self.class_name,
            self.config.get("printer_name", "Bambu"),
            style,
            x,
            y,
            width,
            height,
            None,
            None,
            self.hinst,
            None,
        )
        if not self.hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        rect = self.get_window_rect()
        log_event(
            "create_window hwnd=%s rect=(%s,%s,%s,%s)"
            % (
                int(self.hwnd),
                rect.left,
                rect.top,
                rect.right,
                rect.bottom,
            )
        )

        if not self.brushes:
            self.create_resources()
        else:
            self.create_fonts()
        attached = self.attach_to_desktop()
        log_event(f"attach_to_desktop {'ok' if attached else 'failed'}")
        self.apply_visual_config()

        user32.SetTimer(self.hwnd, TIMER_MAIN, 250, None)
        user32.ShowWindow(self.hwnd, SW_SHOW)
        user32.UpdateWindow(self.hwnd)

    def create_resources(self):
        self.create_fonts()
        self.brushes["bg"] = gdi32.CreateSolidBrush(rgb(12, 17, 27))
        self.brushes["line"] = gdi32.CreateSolidBrush(rgb(37, 48, 65))
        self.brushes["green"] = gdi32.CreateSolidBrush(rgb(18, 183, 100))

    def create_fonts(self):
        font_size = normalized_font_size(self.config)
        if font_size == self.current_font_size and self.fonts:
            return
        for font in self.fonts.values():
            if font:
                gdi32.DeleteObject(font)
        self.fonts.clear()
        self.font_heights = {
            "title": font_size + 7,
            "state": font_size + 5,
            "body": font_size,
            "small": max(8, font_size - 2),
        }
        self.fonts["title"] = gdi32.CreateFontW(self.font_heights["title"], 0, 0, 0, 700, 0, 0, 0, 134, 0, 0, 0, 0, "Microsoft YaHei UI")
        self.fonts["state"] = gdi32.CreateFontW(self.font_heights["state"], 0, 0, 0, 700, 0, 0, 0, 134, 0, 0, 0, 0, "Microsoft YaHei UI")
        self.fonts["body"] = gdi32.CreateFontW(self.font_heights["body"], 0, 0, 0, 400, 0, 0, 0, 134, 0, 0, 0, 0, "Microsoft YaHei UI")
        self.fonts["small"] = gdi32.CreateFontW(self.font_heights["small"], 0, 0, 0, 400, 0, 0, 0, 134, 0, 0, 0, 0, "Microsoft YaHei UI")
        self.current_font_size = font_size

    def apply_visual_config(self):
        self.create_fonts()
        alpha = int(max(0.3, min(1.0, float(self.config.get("opacity", 0.94)))) * 255)
        user32.SetLayeredWindowAttributes(self.hwnd, 0, alpha, 0x00000002)

    def attach_to_desktop(self):
        rect = self.get_window_rect()
        x, y, width, height = clamp_window_rect(
            rect.left,
            rect.top,
            rect.right - rect.left,
            rect.bottom - rect.top,
        )
        host = attach_hwnd_to_desktop(self.hwnd, x, y, width, height)
        if not host:
            log_event("attach_to_desktop host not found")
            return False

        self.next_desktop_check = time.monotonic() + 2.0
        log_event(f"attach_to_desktop parent={int(host)}")
        return True

    def ensure_desktop_parent(self):
        parent = user32.GetParent(self.hwnd)
        if parent and user32.IsWindow(parent):
            user32.SetWindowPos(
                self.hwnd,
                HWND_TOP,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
            return True
        log_event("desktop parent missing; reattaching")
        return self.attach_to_desktop()

    def start_client(self):
        self.stop_event.set()
        if self.client:
            self.client.close()
        if self.client_thread and self.client_thread.is_alive():
            self.client_thread.join(timeout=2.0)
        self.stop_event = threading.Event()
        self.event_queue = queue.Queue()
        self.client = BambuMqttClient(self.config, self.event_queue, self.stop_event)
        self.client_thread = threading.Thread(target=self.client.run_forever, daemon=True)
        self.client_thread.start()

    def reconnect(self):
        try:
            self.config = load_config()
        except ConfigError as exc:
            self.connection_text = f"配置错误：{exc}"
            return
        self.start_client()
        self.apply_visual_config()
        self.connection_text = "已重连"

    def reload_if_config_changed(self):
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime != self.last_mtime:
            try:
                config = load_config()
            except ConfigError as exc:
                self.last_mtime = mtime
                self.connection_text = f"配置错误：{exc}"
                user32.InvalidateRect(self.hwnd, None, True)
                return
            self.last_mtime = mtime
            self.config = config
            self.start_client()
            self.apply_visual_config()
            user32.InvalidateRect(self.hwnd, None, True)

    def show_completion_popup(self, status):
        job_name = str(status.get("job_name") or self.config.get("printer_name", "Bambu")).strip()
        if not job_name:
            job_name = self.config.get("printer_name", "Bambu")
        message = f"{job_name}\n\n打印已完成。"
        title = "打印完成"

        def worker():
            user32.MessageBoxW(None, message, title, MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND)

        threading.Thread(target=worker, daemon=True).start()

    def handle_status_update(self, payload):
        current_state = str(payload.get("state") or "").upper()
        previous_state = self.last_print_state

        if self.seen_printer_status and current_state == "FINISH" and previous_state != "FINISH":
            self.show_completion_popup(payload)

        self.seen_printer_status = True
        self.last_print_state = current_state
        self.status = payload

    def pump_events(self):
        changed = False
        while True:
            try:
                kind, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "connection":
                self.connection_text = payload
                changed = True
            elif kind == "offline":
                self.connection_text = payload
                self.status = {
                    "state": "UNKNOWN",
                    "state_label": "离线",
                    "state_color": "#ef4444",
                    "percent": None,
                    "remaining_text": "--",
                    "eta_text": "--:--",
                    "layers_text": "--",
                    "job_name": self.config.get("printer_name", "Bambu"),
                }
                changed = True
            elif kind == "status":
                self.handle_status_update(payload)
                changed = True
        return changed

    def message_loop(self):
        msg = wintypes.MSG()
        while True:
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                if msg.message == WM_QUIT:
                    return
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            if self.hwnd and not user32.IsWindow(self.hwnd):
                log_event(f"widget window lost hwnd={int(self.hwnd)}; recreating")
                self.hwnd = None
                self.create_window()
                log_event(f"widget window recreated hwnd={int(self.hwnd)}")
            time.sleep(0.05)

    def stop(self):
        self.stop_event.set()
        if self.client:
            self.client.close()
        if self.client_thread and self.client_thread.is_alive():
            self.client_thread.join(timeout=2.0)
        self.client = None
        for font in self.fonts.values():
            if font:
                gdi32.DeleteObject(font)
        for brush in self.brushes.values():
            if brush:
                gdi32.DeleteObject(brush)
        self.fonts.clear()
        self.brushes.clear()

    def get_window_rect(self):
        rect = RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        return rect

    def get_client_rect(self):
        rect = RECT()
        user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        return rect

    def client_point_to_screen(self, x, y):
        point = POINT(x, y)
        user32.ClientToScreen(self.hwnd, ctypes.byref(point))
        return point.x, point.y

    def set_window_rect_from_screen(self, left, top, width, height, flags):
        x, y = left, top
        parent = user32.GetParent(self.hwnd)
        if parent:
            point = POINT(left, top)
            user32.ScreenToClient(parent, ctypes.byref(point))
            x, y = point.x, point.y
        user32.SetWindowPos(self.hwnd, 0, x, y, width, height, flags)

    def hit_region(self, x, y):
        rect = self.get_client_rect()
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        left = x <= EDGE
        right = x >= width - EDGE
        top = y <= EDGE
        bottom = y >= height - EDGE
        if top and left:
            return "nw"
        if top and right:
            return "ne"
        if bottom and left:
            return "sw"
        if bottom and right:
            return "se"
        if left:
            return "w"
        if right:
            return "e"
        if top:
            return "n"
        if bottom:
            return "s"
        return ""

    def begin_drag(self, x, y, mode):
        self.drag_mode = mode
        self.drag_origin = self.client_point_to_screen(x, y)
        self.drag_rect = self.get_window_rect()
        user32.SetCapture(self.hwnd)

    def build_drag_target(self, x, y):
        if not self.drag_mode or not self.drag_origin or not self.drag_rect:
            return None
        ox, oy = self.drag_origin
        screen_x, screen_y = self.client_point_to_screen(x, y)
        dx = screen_x - ox
        dy = screen_y - oy
        left = self.drag_rect.left
        top = self.drag_rect.top
        right = self.drag_rect.right
        bottom = self.drag_rect.bottom

        if self.drag_mode == "move":
            return (
                left + dx,
                top + dy,
                0,
                0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )

        new_left, new_top, new_right, new_bottom = left, top, right, bottom
        if "w" in self.drag_mode:
            new_left = min(left + dx, right - MIN_WIDTH)
        if "e" in self.drag_mode:
            new_right = max(right + dx, left + MIN_WIDTH)
        if "n" in self.drag_mode:
            new_top = min(top + dy, bottom - MIN_HEIGHT)
        if "s" in self.drag_mode:
            new_bottom = max(bottom + dy, top + MIN_HEIGHT)

        new_width = max(MIN_WIDTH, new_right - new_left)
        new_height = max(MIN_HEIGHT, new_bottom - new_top)
        return (
            new_left,
            new_top,
            new_width,
            new_height,
            SWP_NOZORDER | SWP_NOACTIVATE,
        )

    def update_drag(self, x, y):
        target = self.build_drag_target(x, y)
        if not target:
            return
        self.set_window_rect_from_screen(*target)

    def end_drag(self):
        if self.drag_mode:
            rect = self.get_window_rect()
            geometry = {
                "x": rect.left,
                "y": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            }

            def save_geometry(config):
                config["window"] = {**config.get("window", {}), **geometry}

            try:
                self.config = update_config(save_geometry)
                self.last_mtime = CONFIG_PATH.stat().st_mtime
            except ConfigError as exc:
                self.connection_text = f"无法保存位置：{exc}"
        self.drag_mode = None
        self.drag_origin = None
        self.drag_rect = None
        user32.ReleaseCapture()

    def open_settings(self):
        script = APP_DIR / "settings_dialog.py"
        subprocess.Popen([sys.executable, str(script)], cwd=str(APP_DIR))

    def show_menu(self, x, y):
        user32.SetForegroundWindow(self.hwnd)
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, ID_MENU_SETTINGS, "打开配置")
        user32.AppendMenuW(menu, MF_STRING, ID_MENU_RECONNECT, "重新连接")
        user32.AppendMenuW(menu, MF_STRING, ID_MENU_EXIT, "退出")
        user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON, x, y, 0, self.hwnd, None)
        user32.DestroyMenu(menu)

    def draw(self, hdc):
        rect = self.get_client_rect()
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        mode = layout_mode(width, height, normalized_font_size(self.config))

        gdi32.SetBkMode(hdc, TRANSPARENT)
        user32.FillRect(hdc, ctypes.byref(rect), self.brushes["bg"])

        self.draw_top_bar(hdc, rect)
        self.draw_state(hdc, rect, mode)
        self.draw_progress(hdc, rect, mode)
        self.draw_details(hdc, rect, mode)
        if mode != "mini":
            self.draw_connection(hdc, rect)

    def draw_top_bar(self, hdc, rect):
        title_top = 6
        title_bottom = title_top + self.font_heights["title"] + 6
        dot_top = title_top + max(0, (title_bottom - title_top - 8) // 2)
        dot = RECT(12, dot_top, 20, dot_top + 8)
        brush = gdi32.CreateSolidBrush(rgb_hex(self.status["state_color"]))
        user32.FillRect(hdc, ctypes.byref(dot), brush)
        gdi32.DeleteObject(brush)
        self.draw_text(hdc, self.config.get("printer_name", "Bambu"), RECT(28, title_top, rect.right - 32, title_bottom), self.fonts["title"], "#f8fafc")
        self.draw_text(hdc, "×", RECT(rect.right - 24, title_top, rect.right - 8, title_bottom), self.fonts["body"], "#94a3b8", DT_CENTER)

    def content_layout(self, mode):
        title_bottom = 6 + self.font_heights["title"] + 6
        state_top = title_bottom + 2
        state_bottom = state_top + self.font_heights["state"] + 8
        if mode == "mini":
            return state_top, state_bottom, None, None, state_bottom + 4, state_bottom + 12
        job_top = state_bottom
        job_bottom = job_top + self.font_heights["body"] + 8
        bar_top = job_bottom + 5
        bar_height = 8 if mode == "compact" else 10
        return state_top, state_bottom, job_top, job_bottom, bar_top, bar_top + bar_height

    def draw_state(self, hdc, rect, mode):
        state_top, state_bottom, job_top, job_bottom, _bar_top, _bar_bottom = self.content_layout(mode)
        if mode == "mini":
            text = f"{self.status['state_label']}  剩 {self.status['remaining_text']}  完 {self.status['eta_text']}"
            area = RECT(12, state_top, rect.right - 12, state_bottom)
        else:
            text = self.status["state_label"]
            area = RECT(12, state_top, rect.right - 12, state_bottom)
        self.draw_text(hdc, text, area, self.fonts["state"], self.status["state_color"])
        if mode != "mini":
            self.draw_text(hdc, self.status["job_name"], RECT(12, job_top, rect.right - 12, job_bottom), self.fonts["body"], "#94a3b8")

    def draw_progress(self, hdc, rect, mode):
        _state_top, _state_bottom, _job_top, _job_bottom, top, bottom = self.content_layout(mode)
        left = 12
        right = rect.right - 12
        bar_bg = RECT(left, top, right, bottom)
        user32.FillRect(hdc, ctypes.byref(bar_bg), self.brushes["line"])
        percent = self.status.get("percent")
        if percent is not None:
            percent = max(0, min(100, float(percent)))
            bar = RECT(left, top, left + int((right - left) * percent / 100.0), bottom)
            user32.FillRect(hdc, ctypes.byref(bar), self.brushes["green"])

    def draw_details(self, hdc, rect, mode):
        _state_top, _state_bottom, _job_top, _job_bottom, _bar_top, bar_bottom = self.content_layout(mode)
        y = bar_bottom + 8
        if mode == "full":
            col_w = (rect.right - 24) // 3
            self.draw_metric(hdc, 12, y, col_w, "剩余", self.status["remaining_text"])
            self.draw_metric(hdc, 12 + col_w, y, col_w, "完成", self.status["eta_text"])
            self.draw_metric(hdc, 12 + col_w * 2, y, rect.right - 12 - col_w * 2, "层", self.status["layers_text"])
        elif mode == "compact":
            text = f"剩余 {self.status['remaining_text']}   完成 {self.status['eta_text']}   层 {self.status['layers_text']}"
            self.draw_text(hdc, text, RECT(12, bar_bottom + 4, rect.right - 12, rect.bottom - self.font_heights["small"] - 9), self.fonts["small"], "#dbeafe")

    def draw_metric(self, hdc, x, y, w, label, value):
        label_bottom = y + self.font_heights["small"] + 5
        self.draw_text(hdc, label, RECT(x, y, x + w, label_bottom), self.fonts["small"], "#64748b")
        self.draw_text(hdc, value, RECT(x, label_bottom, x + w, label_bottom + self.font_heights["body"] + 8), self.fonts["body"], "#f8fafc")

    def draw_connection(self, hdc, rect):
        self.draw_text(hdc, self.connection_text, RECT(12, rect.bottom - self.font_heights["small"] - 7, rect.right - 12, rect.bottom - 3), self.fonts["small"], "#94a3b8")

    def draw_text(self, hdc, text, rect, font, color, flags=DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS):
        gdi32.SelectObject(hdc, font)
        gdi32.SetBkMode(hdc, TRANSPARENT)
        gdi32.SetTextColor(hdc, rgb_hex(color))
        user32.DrawTextW(hdc, text, -1, ctypes.byref(rect), flags | DT_VCENTER)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TIMER:
            changed = self.pump_events()
            self.reload_if_config_changed()
            if time.monotonic() >= self.next_desktop_check:
                self.ensure_desktop_parent()
                self.next_desktop_check = time.monotonic() + 2.0
            if changed:
                user32.InvalidateRect(hwnd, None, True)
            return 0

        if msg == WM_DISPLAYCHANGE or msg == self.taskbar_created_msg:
            self.attach_to_desktop()
            user32.InvalidateRect(hwnd, None, True)
            return 0

        if msg == WM_ERASEBKGND:
            return 1

        if msg == WM_PAINT:
            ps = PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            self.draw(hdc)
            user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0

        if msg == WM_LBUTTONDOWN:
            x = get_x_lparam(lparam)
            y = get_y_lparam(lparam)
            if x >= self.get_client_rect().right - 28 and y <= 26:
                self.close()
                user32.DestroyWindow(hwnd)
                return 0
            region = self.hit_region(x, y)
            self.begin_drag(x, y, region if region else "move")
            return 0

        if msg == WM_MOUSEMOVE:
            if self.drag_mode:
                self.update_drag(get_x_lparam(lparam), get_y_lparam(lparam))
                return 0
            region = self.hit_region(get_x_lparam(lparam), get_y_lparam(lparam))
            self.set_cursor(region)
            return 0

        if msg == WM_LBUTTONUP:
            if self.drag_mode:
                self.end_drag()
                user32.InvalidateRect(hwnd, None, True)
            return 0

        if msg == WM_RBUTTONUP:
            pt = POINT()
            pt.x = get_x_lparam(lparam)
            pt.y = get_y_lparam(lparam)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            self.show_menu(pt.x, pt.y)
            return 0

        if msg == WM_COMMAND:
            cmd = loword(wparam)
            if cmd == ID_MENU_SETTINGS:
                self.open_settings()
            elif cmd == ID_MENU_RECONNECT:
                self.reconnect()
                user32.InvalidateRect(hwnd, None, True)
            elif cmd == ID_MENU_EXIT:
                self.close()
                user32.DestroyWindow(hwnd)
            return 0

        if msg == WM_CLOSE:
            self.close()
            user32.DestroyWindow(hwnd)
            return 0

        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def close(self):
        self.stop()

    def set_cursor(self, region):
        cursor_ids = {
            "": 32512,
            "move": 32646,
            "n": 32645,
            "s": 32645,
            "e": 32644,
            "w": 32644,
            "ne": 32643,
            "sw": 32643,
            "nw": 32642,
            "se": 32642,
        }
        user32.SetCursor(user32.LoadCursorW(None, make_int_resource(cursor_ids.get(region, 32512))))

def main():
    configure_ctypes()
    mutex = acquire_single_instance()
    if not mutex:
        log_event("another instance is already running")
        return
    app = None
    try:
        app = NativeWidget()
        app.run()
    except Exception:
        log_event("exception\n" + traceback.format_exc())
        raise
    finally:
        if app:
            app.stop()
        kernel32.CloseHandle(mutex)


if __name__ == "__main__":
    main()
