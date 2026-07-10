"""无边框窗口的原生窗口框架辅助 —— 与 win_shell.py 同理，把 ctypes/Win32
调用集中在独立模块，避免 main.py 字节码里出现杀软启发式敏感的组合。

Qt.FramelessWindowHint 会把 WS_THICKFRAME/WS_CAPTION 一并去掉，导致：
  - 窗口边缘无法拉伸；
  - 拖动标题栏没有 Aero Snap（贴边分屏 / Win+方向键）；
  - Win11 的圆角和窗口阴影消失。

标准补救（Windows Terminal 等同款做法）：
  1. 给窗口补回 WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX；
  2. WM_NCCALCSIZE 返回 0，把非客户区面积吞掉（原生标题栏不再显示，
     但 resize 边框、Snap、动画、圆角、阴影全部保留）；
  3. WM_NCHITTEST 自行汇报边缘（HTLEFT..HTBOTTOMRIGHT）与标题栏（HTCAPTION），
     让系统接管拉伸与拖动。
全部调用都包在 try/except 里：任何一步失败就退回纯 Qt 行为，不影响启动。
"""
import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform == 'win32'

if IS_WIN:
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _dwmapi = None
    try:
        _dwmapi = ctypes.WinDLL('dwmapi')
    except Exception:
        _dwmapi = None
    _shell32 = None
    try:
        _shell32 = ctypes.WinDLL('shell32')
    except Exception:
        _shell32 = None

GWL_STYLE = -16
WS_MAXIMIZEBOX = 0x00010000
WS_MINIMIZEBOX = 0x00020000
WS_THICKFRAME = 0x00040000
WS_CAPTION = 0x00C00000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

SM_CXSIZEFRAME = 32
SM_CXPADDEDBORDER = 92


class _MSG(ctypes.Structure):
    _fields_ = [
        ('hwnd', wintypes.HWND),
        ('message', wintypes.UINT),
        ('wParam', wintypes.WPARAM),
        ('lParam', wintypes.LPARAM),
        ('time', wintypes.DWORD),
        ('pt', wintypes.POINT),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [
        ('left', ctypes.c_long),
        ('top', ctypes.c_long),
        ('right', ctypes.c_long),
        ('bottom', ctypes.c_long),
    ]


# ---- 自动隐藏任务栏探测（SHAppBarMessage） ----
ABM_GETSTATE = 0x0004
ABM_GETAUTOHIDEBAREX = 0x000B
ABS_AUTOHIDE = 0x0001
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3
MONITOR_DEFAULTTONEAREST = 2
# Chromium(kAutoHideTaskbarThicknessPx) 与 Windows Terminal 同款取值
AUTOHIDE_TASKBAR_GAP_PX = 2


class _APPBARDATA(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uCallbackMessage', wintypes.UINT),
        ('uEdge', wintypes.UINT),
        ('rc', _RECT),
        ('lParam', wintypes.LPARAM),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', _RECT),
        ('rcWork', _RECT),
        ('dwFlags', wintypes.DWORD),
    ]


def _autohide_taskbar_edges(hwnd):
    """窗口所在显示器上有自动隐藏 AppBar 的边集合（ABE_* 常量）。

    每次 WM_NCCALCSIZE 现查、不缓存：用户运行中切换"自动隐藏任务栏"会促使
    系统对最大化窗口重发 WM_NCCALCSIZE，现查才能自愈。
    ABM_GETAUTOHIDEBAREX 必须带当前显示器矩形，用 MONITOR_DEFAULTTONEAREST
    才能在从最小化恢复等场景取到正确显示器。
    """
    edges = set()
    if _shell32 is None:
        return edges
    try:
        _shell32.SHAppBarMessage.restype = ctypes.c_size_t
        abd = _APPBARDATA()
        abd.cbSize = ctypes.sizeof(_APPBARDATA)
        state = int(_shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd)))
        if not (state & ABS_AUTOHIDE):
            return edges
        monitor = _user32.MonitorFromWindow(
            wintypes.HWND(hwnd), wintypes.DWORD(MONITOR_DEFAULTTONEAREST))
        if not monitor:
            return edges
        mi = _MONITORINFO()
        mi.cbSize = ctypes.sizeof(_MONITORINFO)
        if not _user32.GetMonitorInfoW(monitor, ctypes.byref(mi)):
            return edges
        for edge in (ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM):
            abd = _APPBARDATA()
            abd.cbSize = ctypes.sizeof(_APPBARDATA)
            abd.uEdge = edge
            abd.rc = mi.rcMonitor
            if _shell32.SHAppBarMessage(ABM_GETAUTOHIDEBAREX, ctypes.byref(abd)):
                edges.add(edge)
    except Exception:
        return set()
    return edges


def _get_window_long(hwnd, index):
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _user32.GetWindowLongPtrW.restype = ctypes.c_longlong
        _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        return _user32.GetWindowLongPtrW(hwnd, index)
    return _user32.GetWindowLongW(hwnd, index)


def _set_window_long(hwnd, index, value):
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _user32.SetWindowLongPtrW.restype = ctypes.c_longlong
        _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
        return _user32.SetWindowLongPtrW(hwnd, index, value)
    return _user32.SetWindowLongW(hwnd, index, value)


def apply_native_frame(hwnd):
    """给无边框窗口补回可拉伸的原生窗口样式。失败返回 False。"""
    if not IS_WIN or not hwnd:
        return False
    try:
        hwnd = int(hwnd)
        style = _get_window_long(hwnd, GWL_STYLE)
        style |= WS_THICKFRAME | WS_CAPTION | WS_MAXIMIZEBOX | WS_MINIMIZEBOX
        _set_window_long(hwnd, GWL_STYLE, style)
        _user32.SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )
        return True
    except Exception:
        return False


def _dpi_for_window(hwnd):
    try:
        dpi = int(_user32.GetDpiForWindow(wintypes.HWND(hwnd)))
        if dpi > 0:
            return dpi
    except Exception:
        pass
    return 96


def resize_border_thickness(hwnd):
    """当前 DPI 下系统 resize 边框的物理像素厚度。"""
    dpi = _dpi_for_window(hwnd)
    try:
        frame = int(_user32.GetSystemMetricsForDpi(SM_CXSIZEFRAME, dpi))
        padded = int(_user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi))
        if frame + padded > 0:
            return frame + padded
    except Exception:
        pass
    try:
        frame = int(_user32.GetSystemMetrics(SM_CXSIZEFRAME))
        padded = int(_user32.GetSystemMetrics(SM_CXPADDEDBORDER))
        if frame + padded > 0:
            return frame + padded
    except Exception:
        pass
    return 8


def _is_zoomed(hwnd):
    try:
        return bool(_user32.IsZoomed(wintypes.HWND(hwnd)))
    except Exception:
        return False


def is_zoomed(hwnd):
    """窗口当前是否处于原生最大化(zoomed)状态。

    Qt6 对 FramelessWindowHint 窗口的 showMaximized()/showNormal() 走几何仿真，
    不会置/清原生 zoomed 位；而 HTCAPTION 触发的贴边/Win+Up/双击走的是
    DefWindowProc 的原生 SC_MAXIMIZE。两套状态机会互相脱钩（isMaximized 与
    IsZoomed 不一致），判断真实状态一律以本函数为准。
    """
    if not IS_WIN or not hwnd:
        return False
    return _is_zoomed(int(hwnd))


SW_MAXIMIZE = 3
SW_RESTORE = 9


def maximize_window(hwnd):
    """原生最大化（置 zoomed 位）。失败返回 False，调用方回落 Qt 路径。

    必须用 ShowWindow 而不是 Qt 的 showMaximized()：后者对 frameless 窗口是
    setGeometry 仿真，IsZoomed 保持 False，WM_NCHITTEST/WM_NCCALCSIZE 会把
    "最大化"窗口继续当普通窗口处理（边缘可拉伸、双击再最大化一次）。
    """
    if not IS_WIN or not hwnd:
        return False
    try:
        _user32.ShowWindow(wintypes.HWND(int(hwnd)), SW_MAXIMIZE)
        return True
    except Exception:
        return False


def restore_window(hwnd):
    """原生还原（解除 zoomed 位）。失败返回 False，调用方回落 Qt 路径。

    原生 zoomed 状态只能用 SW_RESTORE/SC_RESTORE 解除；Qt 的 showNormal()
    对该状态实测是彻底 no-op（Qt 仿真还原只回放自己记录的几何账本）。
    """
    if not IS_WIN or not hwnd:
        return False
    try:
        _user32.ShowWindow(wintypes.HWND(int(hwnd)), SW_RESTORE)
        return True
    except Exception:
        return False


def handle_native_message(message_ptr, caption_height_px, caption_hit_test):
    """在 QWidget.nativeEvent 里调用。

    message_ptr:        nativeEvent 收到的 message 指针（int）
    caption_height_px:  标题栏高度（物理像素）
    caption_hit_test:   回调 (x_px, y_px) -> True 表示这一点算标题栏空白区
                        （x/y 为相对窗口左上角的物理像素坐标；用于排除
                        标题栏上的按钮，按钮区域返回 False 走 HTCLIENT）

    返回 (handled: bool, result: int)。
    """
    if not IS_WIN:
        return False, 0
    try:
        msg = _MSG.from_address(int(message_ptr))
    except Exception:
        return False, 0

    if msg.message == WM_NCCALCSIZE and msg.wParam:
        # 吞掉整个非客户区。最大化时窗口会比屏幕大出一圈边框，
        # 需要把客户区往里缩回边框厚度，否则四边内容被裁掉。
        if _is_zoomed(msg.hwnd):
            try:
                rect = _RECT.from_address(int(msg.lParam))
                border = resize_border_thickness(int(msg.hwnd))
                rect.left += border
                rect.top += border
                rect.right -= border
                rect.bottom -= border
                # 任务栏设为"自动隐藏"时工作区等于整屏，客户区盖满每一个像素
                # 会被 shell 当成全屏应用而不再弹出任务栏（Chromium/Terminal
                # 都在对应边缩 2px 处理）。
                for edge in _autohide_taskbar_edges(int(msg.hwnd)):
                    if edge == ABE_LEFT:
                        rect.left += AUTOHIDE_TASKBAR_GAP_PX
                    elif edge == ABE_TOP:
                        rect.top += AUTOHIDE_TASKBAR_GAP_PX
                    elif edge == ABE_RIGHT:
                        rect.right -= AUTOHIDE_TASKBAR_GAP_PX
                    elif edge == ABE_BOTTOM:
                        rect.bottom -= AUTOHIDE_TASKBAR_GAP_PX
            except Exception:
                pass
        return True, 0

    if msg.message == WM_NCHITTEST:
        try:
            hwnd = int(msg.hwnd)
            # lParam: 屏幕物理坐标（有符号 16 位打包）
            x = ctypes.c_short(msg.lParam & 0xFFFF).value
            y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            rect = _RECT()
            if not _user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                return False, 0
            border = resize_border_thickness(hwnd)
            maximized = _is_zoomed(hwnd)

            on_left = x < rect.left + border
            on_right = x >= rect.right - border
            on_top = y < rect.top + border
            on_bottom = y >= rect.bottom - border

            if not maximized:
                if on_top and on_left:
                    return True, HTTOPLEFT
                if on_top and on_right:
                    return True, HTTOPRIGHT
                if on_bottom and on_left:
                    return True, HTBOTTOMLEFT
                if on_bottom and on_right:
                    return True, HTBOTTOMRIGHT
                if on_left:
                    return True, HTLEFT
                if on_right:
                    return True, HTRIGHT
                if on_top:
                    return True, HTTOP
                if on_bottom:
                    return True, HTBOTTOM

            rel_x = x - rect.left
            rel_y = y - rect.top
            if maximized:
                # 最大化时客户区被缩了一圈，标题栏相对坐标同步平移
                rel_x -= border
                rel_y -= border
            if 0 <= rel_y < caption_height_px:
                try:
                    if caption_hit_test(rel_x, rel_y):
                        return True, HTCAPTION
                except Exception:
                    return True, HTCAPTION
                return True, HTCLIENT
            return True, HTCLIENT
        except Exception:
            return False, 0

    return False, 0
