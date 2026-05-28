"""订阅 Windows Shell 文件移动通知。

Windows Shell 在文件被剪切/粘贴、改名、移动时会广播事件（SHCNE_RENAMEITEM 等），
事件本身就包含 (旧路径, 新路径)，比扫盘要快得多 —— 用户剪完粘贴的瞬间就能拿到结果。
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter

_IS_WIN = sys.platform == 'win32'


SHCNE_RENAMEITEM   = 0x00000001
SHCNE_CREATE       = 0x00000002
SHCNE_DELETE       = 0x00000004
SHCNE_MKDIR        = 0x00000008
SHCNE_RMDIR        = 0x00000010
SHCNE_UPDATEDIR    = 0x00001000
SHCNE_UPDATEITEM   = 0x00002000
SHCNE_RENAMEFOLDER = 0x00020000

SHCNRF_InterruptLevel = 0x0001
SHCNRF_ShellLevel     = 0x0002
SHCNRF_RecursiveInterrupt = 0x1000
SHCNRF_NewDelivery    = 0x8000

CSIDL_DESKTOP = 0x0000

WM_USER = 0x0400
WM_SHELL_NOTIFY = WM_USER + 1234   # 自定义消息，落在 WM_USER 以上即可

_INTEREST_MASK = (
    SHCNE_RENAMEITEM
    | SHCNE_RENAMEFOLDER
    | SHCNE_CREATE
    | SHCNE_DELETE
    | SHCNE_MKDIR
    | SHCNE_RMDIR
    | SHCNE_UPDATEDIR
    | SHCNE_UPDATEITEM
)


if _IS_WIN:
    _shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    _user32 = ctypes.WinDLL('user32', use_last_error=True)

    class _SHChangeNotifyEntry(ctypes.Structure):
        _fields_ = [
            ('pidl', ctypes.c_void_p),
            ('fRecursive', wintypes.BOOL),
        ]

    class _MSG(ctypes.Structure):
        _fields_ = [
            ('hwnd',    wintypes.HWND),
            ('message', wintypes.UINT),
            ('wParam',  wintypes.WPARAM),
            ('lParam',  wintypes.LPARAM),
            ('time',    wintypes.DWORD),
            ('pt_x',    wintypes.LONG),
            ('pt_y',    wintypes.LONG),
        ]

    _shell32.SHGetSpecialFolderLocation.argtypes = [
        wintypes.HWND, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
    ]
    _shell32.SHGetSpecialFolderLocation.restype = ctypes.c_long  # HRESULT

    _shell32.SHChangeNotifyRegister.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.LONG, wintypes.UINT, ctypes.c_int,
        ctypes.POINTER(_SHChangeNotifyEntry),
    ]
    _shell32.SHChangeNotifyRegister.restype = wintypes.ULONG

    _shell32.SHChangeNotifyDeregister.argtypes = [wintypes.ULONG]
    _shell32.SHChangeNotifyDeregister.restype = wintypes.BOOL

    _shell32.SHChangeNotification_Lock.argtypes = [
        wintypes.HANDLE, wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ctypes.POINTER(wintypes.LONG),
    ]
    _shell32.SHChangeNotification_Lock.restype = wintypes.HANDLE

    _shell32.SHChangeNotification_Unlock.argtypes = [wintypes.HANDLE]
    _shell32.SHChangeNotification_Unlock.restype = wintypes.BOOL

    _shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    _shell32.SHGetPathFromIDListW.restype = wintypes.BOOL

    _ole32 = ctypes.WinDLL('ole32', use_last_error=True)
    _ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    _ole32.CoTaskMemFree.restype = None


def _pidl_to_path(pidl):
    if not pidl:
        return ''
    # 路径上限 32K，避开 MAX_PATH 短路径限制
    buf = ctypes.create_unicode_buffer(32768)
    if _shell32.SHGetPathFromIDListW(pidl, buf):
        return buf.value
    return ''


class ShellChangeFilter(QAbstractNativeEventFilter):
    """订阅整个 Shell 命名空间的变更事件，回调形式 callback(event_code, path1, path2)。"""

    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self._reg_id = 0
        self._target_hwnd = 0

    def install(self, hwnd):
        if not _IS_WIN:
            return False
        if self._reg_id:
            return True
        # 拿到 Desktop 的 PIDL，配合 SHCNRF_RecursiveInterrupt 监听所有盘符
        desktop_pidl = ctypes.c_void_p()
        hr = _shell32.SHGetSpecialFolderLocation(0, CSIDL_DESKTOP, ctypes.byref(desktop_pidl))
        if hr != 0 or not desktop_pidl:
            return False
        try:
            entry = _SHChangeNotifyEntry()
            entry.pidl = desktop_pidl.value
            entry.fRecursive = True
            sources = SHCNRF_ShellLevel | SHCNRF_InterruptLevel | SHCNRF_RecursiveInterrupt | SHCNRF_NewDelivery
            reg = _shell32.SHChangeNotifyRegister(
                hwnd, sources, _INTEREST_MASK, WM_SHELL_NOTIFY, 1, ctypes.byref(entry),
            )
            self._reg_id = reg
            self._target_hwnd = hwnd
            return bool(reg)
        finally:
            _ole32.CoTaskMemFree(desktop_pidl)

    def uninstall(self):
        if not _IS_WIN or not self._reg_id:
            return
        try:
            _shell32.SHChangeNotifyDeregister(self._reg_id)
        finally:
            self._reg_id = 0

    def nativeEventFilter(self, eventType, message):
        if not _IS_WIN:
            return False, 0
        try:
            if eventType not in (b'windows_generic_MSG', 'windows_generic_MSG'):
                return False, 0
            msg = _MSG.from_address(int(message))
            if msg.message != WM_SHELL_NOTIFY:
                return False, 0
            if self._target_hwnd and msg.hwnd and msg.hwnd != self._target_hwnd:
                return False, 0

            ppidl = ctypes.POINTER(ctypes.c_void_p)()
            event_code = wintypes.LONG()
            lock = _shell32.SHChangeNotification_Lock(
                wintypes.HANDLE(msg.wParam),
                wintypes.DWORD(msg.lParam),
                ctypes.byref(ppidl),
                ctypes.byref(event_code),
            )
            if not lock:
                return False, 0
            try:
                path1 = ''
                path2 = ''
                if ppidl:
                    try:
                        if ppidl[0]:
                            path1 = _pidl_to_path(ppidl[0])
                    except Exception:
                        pass
                    try:
                        if ppidl[1]:
                            path2 = _pidl_to_path(ppidl[1])
                    except Exception:
                        pass
                try:
                    self.callback(int(event_code.value), path1, path2)
                except Exception:
                    pass
            finally:
                _shell32.SHChangeNotification_Unlock(lock)
        except Exception:
            return False, 0
        return False, 0
