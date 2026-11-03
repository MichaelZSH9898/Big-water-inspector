# -*- coding: utf-8 -*-
"""Win32 的 ctypes 声明（哨兵、设置进程、验证脚本共用）。

所有函数都显式声明 argtypes / restype：64 位下句柄是 8 字节，不声明会被截成 32 位整数。
非 Windows 平台上本模块也能 import（IS_WINDOWS = False，各 DLL 为 None），方便在 Linux 上跑逻辑测试。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import POINTER, Structure, Union, byref, c_float, c_int, c_long, c_ssize_t, c_size_t, c_uint, \
    c_ulong, c_ushort, c_void_p, c_wchar, c_wchar_p, sizeof  # noqa: F401
from ctypes import wintypes as W

IS_WINDOWS = os.name == "nt" and hasattr(ctypes, "WinDLL")

if IS_WINDOWS:
    WINFUNCTYPE = ctypes.WINFUNCTYPE
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    try:
        wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    except OSError:  # pragma: no cover
        wtsapi32 = None
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
    except OSError:  # pragma: no cover - Windows 7
        shcore = None
    try:
        ntdll = ctypes.WinDLL("ntdll")
    except OSError:  # pragma: no cover
        ntdll = None
else:
    WINFUNCTYPE = ctypes.CFUNCTYPE
    user32 = kernel32 = gdi32 = shell32 = ole32 = advapi32 = wtsapi32 = shcore = ntdll = None

# ── 基本类型 ─────────────────────────────────────────────────────────────────
HWND = HANDLE = HMONITOR = HDC = HICON = HMENU = HINSTANCE = HBITMAP = HGDIOBJ = HCURSOR = HBRUSH = c_void_p
WPARAM = c_size_t
LPARAM = c_ssize_t
LRESULT = c_ssize_t
UINT, DWORD, BOOL, LONG, BYTE, WORD = c_uint, W.DWORD, W.BOOL, c_long, ctypes.c_ubyte, c_ushort
HRESULT = c_long

WNDPROC = WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)
WINEVENTPROC = WINFUNCTYPE(None, HANDLE, DWORD, HWND, LONG, LONG, DWORD, DWORD)
MONITORENUMPROC = WINFUNCTYPE(BOOL, HMONITOR, HDC, c_void_p, LPARAM)

# ── 常量 ─────────────────────────────────────────────────────────────────────
WM_NULL, WM_DESTROY, WM_CLOSE, WM_QUIT, WM_TIMER, WM_COMMAND = 0x0000, 0x0002, 0x0010, 0x0012, 0x0113, 0x0111
WM_QUERYENDSESSION, WM_ENDSESSION = 0x0011, 0x0016
WM_DISPLAYCHANGE, WM_DPICHANGED, WM_SETTINGCHANGE = 0x007E, 0x02E0, 0x001A
WM_POWERBROADCAST, WM_WTSSESSION_CHANGE = 0x0218, 0x02B1
WM_CONTEXTMENU, WM_LBUTTONUP, WM_RBUTTONUP, WM_LBUTTONDBLCLK = 0x007B, 0x0202, 0x0205, 0x0203
WM_APP = 0x8000
PBT_APMSUSPEND, PBT_APMRESUMESUSPEND, PBT_APMRESUMEAUTOMATIC = 0x0004, 0x0007, 0x0012
WTS_SESSION_LOCK, WTS_SESSION_UNLOCK = 0x7, 0x8
NOTIFY_FOR_THIS_SESSION = 0

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x00000008, 0x00000020, 0x00000080
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x00080000, 0x08000000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = c_void_p(-1)
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0010, 0x0040
ULW_ALPHA = 0x00000002
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
BI_RGB, DIB_RGB_COLORS = 0, 0

EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS = 0x0000, 0x0002

MONITOR_DEFAULTTONULL, MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 0, 1, 2
MDT_EFFECTIVE_DPI = 0
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = c_void_p(-4)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ALREADY_EXISTS = 183

MF_STRING, MF_SEPARATOR, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_DISABLED = 0x0, 0x800, 0x1, 0x8, 0x10, 0x2
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY, TPM_BOTTOMALIGN = 0x0002, 0x0100, 0x0080, 0x0020

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x80
NOTIFYICON_VERSION_4 = 4
NIN_SELECT, NIN_KEYSELECT = 0x0400, 0x0401

IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
CLSCTX_ALL = 0x17
COINIT_APARTMENTTHREADED = 0x2


# ── 结构体 ───────────────────────────────────────────────────────────────────
class POINT(Structure):
    _fields_ = [("x", LONG), ("y", LONG)]


class SIZE(Structure):
    _fields_ = [("cx", LONG), ("cy", LONG)]


class RECT(Structure):
    _fields_ = [("left", LONG), ("top", LONG), ("right", LONG), ("bottom", LONG)]

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top


class MONITORINFOEXW(Structure):
    _fields_ = [("cbSize", DWORD), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", DWORD),
                ("szDevice", c_wchar * 32)]


class LASTINPUTINFO(Structure):
    _fields_ = [("cbSize", UINT), ("dwTime", DWORD)]


class MSG(Structure):
    _fields_ = [("hwnd", HWND), ("message", UINT), ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", DWORD), ("pt", POINT), ("lPrivate", DWORD)]


class WNDCLASSEXW(Structure):
    _fields_ = [("cbSize", UINT), ("style", UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", c_int),
                ("cbWndExtra", c_int), ("hInstance", HINSTANCE), ("hIcon", HICON), ("hCursor", HCURSOR),
                ("hbrBackground", HBRUSH), ("lpszMenuName", c_wchar_p), ("lpszClassName", c_wchar_p),
                ("hIconSm", HICON)]


class BLENDFUNCTION(Structure):
    _fields_ = [("BlendOp", BYTE), ("BlendFlags", BYTE), ("SourceConstantAlpha", BYTE), ("AlphaFormat", BYTE)]


class BITMAPINFOHEADER(Structure):
    _fields_ = [("biSize", DWORD), ("biWidth", LONG), ("biHeight", LONG), ("biPlanes", WORD),
                ("biBitCount", WORD), ("biCompression", DWORD), ("biSizeImage", DWORD),
                ("biXPelsPerMeter", LONG), ("biYPelsPerMeter", LONG), ("biClrUsed", DWORD),
                ("biClrImportant", DWORD)]


class BITMAPINFO(Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", DWORD * 3)]


class GUID(Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD), ("Data4", BYTE * 8)]

    @classmethod
    def parse(cls, s: str) -> "GUID":
        s = s.strip("{}")
        a, b, c, d, e = s.split("-")
        g = cls()
        g.Data1, g.Data2, g.Data3 = int(a, 16), int(b, 16), int(c, 16)
        tail = bytes.fromhex(d + e)
        for i in range(8):
            g.Data4[i] = tail[i]
        return g


class _NIDUnion(Union):
    _fields_ = [("uTimeout", UINT), ("uVersion", UINT)]


class NOTIFYICONDATAW(Structure):
    _anonymous_ = ("u",)
    _fields_ = [("cbSize", DWORD), ("hWnd", HWND), ("uID", UINT), ("uFlags", UINT),
                ("uCallbackMessage", UINT), ("hIcon", HICON), ("szTip", c_wchar * 128),
                ("dwState", DWORD), ("dwStateMask", DWORD), ("szInfo", c_wchar * 256), ("u", _NIDUnion),
                ("szInfoTitle", c_wchar * 64), ("dwInfoFlags", DWORD), ("guidItem", GUID),
                ("hBalloonIcon", HICON)]


# ── 函数原型 ─────────────────────────────────────────────────────────────────
def _proto(dll, name, restype, *argtypes):
    if dll is None:
        return
    try:
        fn = getattr(dll, name)
    except AttributeError:
        return
    fn.restype = restype
    fn.argtypes = list(argtypes)


if IS_WINDOWS:
    _proto(user32, "GetLastInputInfo", BOOL, POINTER(LASTINPUTINFO))
    _proto(user32, "GetForegroundWindow", HWND)
    _proto(user32, "GetWindowThreadProcessId", DWORD, HWND, POINTER(DWORD))
    _proto(user32, "GetClassNameW", c_int, HWND, c_wchar_p, c_int)
    _proto(user32, "InternalGetWindowText", c_int, HWND, c_wchar_p, c_int)
    _proto(user32, "IsWindow", BOOL, HWND)
    _proto(user32, "IsWindowVisible", BOOL, HWND)
    _proto(user32, "GetWindowRect", BOOL, HWND, POINTER(RECT))
    _proto(user32, "GetAncestor", HWND, HWND, UINT)
    _proto(user32, "MonitorFromWindow", HMONITOR, HWND, DWORD)
    _proto(user32, "MonitorFromPoint", HMONITOR, POINT, DWORD)
    _proto(user32, "GetMonitorInfoW", BOOL, HMONITOR, POINTER(MONITORINFOEXW))
    _proto(user32, "EnumDisplayMonitors", BOOL, HDC, c_void_p, MONITORENUMPROC, LPARAM)
    _proto(user32, "SetWinEventHook", HANDLE, DWORD, DWORD, HINSTANCE, WINEVENTPROC, DWORD, DWORD, DWORD)
    _proto(user32, "UnhookWinEvent", BOOL, HANDLE)
    _proto(user32, "RegisterClassExW", W.ATOM, POINTER(WNDCLASSEXW))
    _proto(user32, "UnregisterClassW", BOOL, c_wchar_p, HINSTANCE)
    _proto(user32, "CreateWindowExW", HWND, DWORD, c_wchar_p, c_wchar_p, DWORD, c_int, c_int, c_int, c_int,
           HWND, HMENU, HINSTANCE, c_void_p)
    _proto(user32, "DestroyWindow", BOOL, HWND)
    _proto(user32, "DefWindowProcW", LRESULT, HWND, UINT, WPARAM, LPARAM)
    _proto(user32, "GetMessageW", BOOL, POINTER(MSG), HWND, UINT, UINT)
    _proto(user32, "PeekMessageW", BOOL, POINTER(MSG), HWND, UINT, UINT, UINT)
    _proto(user32, "TranslateMessage", BOOL, POINTER(MSG))
    _proto(user32, "DispatchMessageW", LRESULT, POINTER(MSG))
    _proto(user32, "PostMessageW", BOOL, HWND, UINT, WPARAM, LPARAM)
    _proto(user32, "PostQuitMessage", None, c_int)
    _proto(user32, "SetTimer", c_size_t, HWND, c_size_t, UINT, c_void_p)
    _proto(user32, "KillTimer", BOOL, HWND, c_size_t)
    _proto(user32, "RegisterWindowMessageW", UINT, c_wchar_p)
    _proto(user32, "FindWindowW", HWND, c_wchar_p, c_wchar_p)
    _proto(user32, "ShowWindow", BOOL, HWND, c_int)
    _proto(user32, "SetWindowPos", BOOL, HWND, HWND, c_int, c_int, c_int, c_int, UINT)
    _proto(user32, "UpdateLayeredWindow", BOOL, HWND, HDC, POINTER(POINT), POINTER(SIZE), HDC, POINTER(POINT),
           DWORD, POINTER(BLENDFUNCTION), DWORD)
    _proto(user32, "GetDC", HDC, HWND)
    _proto(user32, "ReleaseDC", c_int, HWND, HDC)
    _proto(user32, "CreatePopupMenu", HMENU)
    _proto(user32, "AppendMenuW", BOOL, HMENU, UINT, c_size_t, c_wchar_p)
    _proto(user32, "TrackPopupMenu", BOOL, HMENU, UINT, c_int, c_int, c_int, HWND, c_void_p)
    _proto(user32, "DestroyMenu", BOOL, HMENU)
    _proto(user32, "SetForegroundWindow", BOOL, HWND)
    _proto(user32, "GetCursorPos", BOOL, POINTER(POINT))
    _proto(user32, "LoadImageW", HANDLE, HINSTANCE, c_wchar_p, UINT, c_int, c_int, UINT)
    _proto(user32, "DestroyIcon", BOOL, HICON)
    _proto(user32, "GetSystemMetrics", c_int, c_int)
    _proto(user32, "SetProcessDpiAwarenessContext", BOOL, c_void_p)
    _proto(user32, "SetProcessDPIAware", BOOL)
    _proto(user32, "GetDpiForWindow", UINT, HWND)
    _proto(user32, "MessageBoxW", c_int, HWND, c_wchar_p, c_wchar_p, UINT)
    _proto(user32, "GetWindowLongPtrW", c_ssize_t, HWND, c_int)
    _proto(user32, "GetFocus", HWND)
    _proto(kernel32, "GetModuleHandleW", HINSTANCE, c_wchar_p)
    _proto(kernel32, "GetTickCount", DWORD)
    _proto(kernel32, "OpenProcess", HANDLE, DWORD, BOOL, DWORD)
    _proto(kernel32, "QueryFullProcessImageNameW", BOOL, HANDLE, DWORD, c_wchar_p, POINTER(DWORD))
    _proto(kernel32, "CloseHandle", BOOL, HANDLE)
    _proto(kernel32, "CreateMutexW", HANDLE, c_void_p, BOOL, c_wchar_p)
    _proto(kernel32, "GetCurrentProcessId", DWORD)
    _proto(kernel32, "SetProcessWorkingSetSize", BOOL, HANDLE, c_ssize_t, c_ssize_t)
    _proto(kernel32, "GetCurrentProcess", HANDLE)
    _proto(gdi32, "CreateCompatibleDC", HDC, HDC)
    _proto(gdi32, "CreateDIBSection", HBITMAP, HDC, POINTER(BITMAPINFO), UINT, POINTER(c_void_p), HANDLE, DWORD)
    _proto(gdi32, "SelectObject", HGDIOBJ, HDC, HGDIOBJ)
    _proto(gdi32, "DeleteObject", BOOL, HGDIOBJ)
    _proto(gdi32, "DeleteDC", BOOL, HDC)
    _proto(shell32, "SHQueryUserNotificationState", HRESULT, POINTER(c_int))
    _proto(shell32, "Shell_NotifyIconW", BOOL, DWORD, POINTER(NOTIFYICONDATAW))
    _proto(ole32, "CoInitializeEx", HRESULT, c_void_p, DWORD)
    _proto(ole32, "CoCreateInstance", HRESULT, POINTER(GUID), c_void_p, DWORD, POINTER(GUID), POINTER(c_void_p))
    _proto(wtsapi32, "WTSRegisterSessionNotification", BOOL, HWND, DWORD)
    _proto(wtsapi32, "WTSUnRegisterSessionNotification", BOOL, HWND)
    _proto(shcore, "GetDpiForMonitor", HRESULT, HMONITOR, c_int, POINTER(UINT), POINTER(UINT))
    _proto(shcore, "SetProcessDpiAwareness", HRESULT, c_int)


def last_error() -> int:
    return ctypes.get_last_error() if IS_WINDOWS else 0


def defwindowproc_ptr():
    """DefWindowProcW 的函数地址，作为闪现窗口的窗口过程：不经过任何 Python 回调。"""
    addr = ctypes.cast(user32.DefWindowProcW, c_void_p).value
    return WNDPROC(addr)


def set_dpi_awareness() -> str:
    """声明 Per-Monitor V2 DPI 感知；旧系统依次回退。返回实际生效的级别。"""
    if not IS_WINDOWS:
        return "n/a"
    try:
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return "per-monitor-v2"
    except AttributeError:
        pass
    try:
        if shcore is not None and shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except AttributeError:
        return "unaware"


def single_instance(name: str):
    """命名互斥量；已有实例时返回 None。返回的句柄要一直持有到进程退出。"""
    if not IS_WINDOWS:
        return object()
    h = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        return None
    return h
