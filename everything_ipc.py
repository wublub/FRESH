"""everything_ipc.py - 直接通过 WM_COPYDATA 与 Everything 进程通信。

Everything 主程序运行时会暴露一个隐藏窗口 (class "EVERYTHING_TASKBAR_NOTIFICATION")
接收 IPC 查询。我们用 ctypes 实现客户端，发送查询并接收结果，不需要 es.exe。
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import byref, wintypes

_IS_WIN = sys.platform == 'win32'

# ============ Win32 类型 ============

if _IS_WIN:
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ('style', wintypes.UINT),
            ('lpfnWndProc', WNDPROC),
            ('cbClsExtra', ctypes.c_int),
            ('cbWndExtra', ctypes.c_int),
            ('hInstance', wintypes.HINSTANCE),
            ('hIcon', wintypes.HANDLE),
            ('hCursor', wintypes.HANDLE),
            ('hbrBackground', wintypes.HANDLE),
            ('lpszMenuName', wintypes.LPCWSTR),
            ('lpszClassName', wintypes.LPCWSTR),
        ]

    class MSG(ctypes.Structure):
        _fields_ = [
            ('hwnd', wintypes.HWND),
            ('message', wintypes.UINT),
            ('wParam', wintypes.WPARAM),
            ('lParam', wintypes.LPARAM),
            ('time', wintypes.DWORD),
            ('pt', wintypes.POINT),
        ]

    class COPYDATASTRUCT(ctypes.Structure):
        _fields_ = [
            ('dwData', ctypes.c_ssize_t),
            ('cbData', wintypes.DWORD),
            ('lpData', ctypes.c_void_p),
        ]

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = LRESULT
    # wintypes 没有 DWORD_PTR，结果出参用 POINTER(c_size_t) 等价表示
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = LRESULT
    user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = LRESULT

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

# ============ 常量 ============

WM_COPYDATA = 0x004A
HWND_MESSAGE = wintypes.HWND(-3)
PM_REMOVE = 0x0001
# SendMessageTimeoutW 标志：目标挂死(无响应)时直接放弃。
# 注意不要用 SMTO_BLOCK——我们依赖发送等待期间同步处理 Everything 回传的 WM_COPYDATA。
SMTO_ABORTIFHUNG = 0x0002

EVERYTHING_IPC_WNDCLASS = 'EVERYTHING_TASKBAR_NOTIFICATION'

# IPC 协议常量 (来自 Everything SDK ipc.h)
EVERYTHING_IPC_COPYDATAQUERYW = 2
EVERYTHING_IPC_COPYDATA_QUERYREPLY = 0  # 我们任选一个值作为回复消息标识

# 搜索 flags
EVERYTHING_IPC_MATCHCASE = 0x01
EVERYTHING_IPC_MATCHWHOLEWORD = 0x02
EVERYTHING_IPC_MATCHPATH = 0x04
EVERYTHING_IPC_REGEX = 0x08


# ============ 查询/回复结构 ============
# EVERYTHING_IPC_QUERYW = header + search_string (WCHARs, null-terminated)
class EVERYTHING_IPC_QUERYW_HEADER(ctypes.Structure):
    _fields_ = [
        ('reply_hwnd', ctypes.c_uint32),
        ('reply_copydata_message', ctypes.c_uint32),
        ('search_flags', ctypes.c_uint32),
        ('offset', ctypes.c_uint32),
        ('max_results', ctypes.c_uint32),
    ]


# EVERYTHING_IPC_LISTW = header + items[N] + strings
class EVERYTHING_IPC_LISTW_HEADER(ctypes.Structure):
    _fields_ = [
        ('totfolders', ctypes.c_uint32),
        ('totfiles', ctypes.c_uint32),
        ('totitems', ctypes.c_uint32),
        ('numfolders', ctypes.c_uint32),
        ('numfiles', ctypes.c_uint32),
        ('numitems', ctypes.c_uint32),
        ('offset', ctypes.c_uint32),
    ]


class EVERYTHING_IPC_ITEMW(ctypes.Structure):
    _fields_ = [
        ('flags', ctypes.c_uint32),
        ('filename_offset', ctypes.c_uint32),
        ('path_offset', ctypes.c_uint32),
    ]


# ============ 模块状态 ============

_class_registered = False
_class_name = None
_class_lock = threading.Lock()
_wnd_proc_ref = None  # 必须保持引用，否则 ctypes 回调会被 GC


def _ensure_class_registered():
    """注册一次窗口类（线程安全）。返回 class_name 或 None。"""
    global _class_registered, _class_name, _wnd_proc_ref
    if not _IS_WIN:
        return None
    with _class_lock:
        if _class_registered:
            return _class_name

        @WNDPROC
        def wnd_proc(hwnd, msg, wparam, lparam):
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        _wnd_proc_ref = wnd_proc

        name = f'FRESH_EverythingIPC_{os.getpid()}'
        hinstance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = wnd_proc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinstance
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = name
        atom = user32.RegisterClassW(byref(wc))
        if not atom:
            return None
        _class_registered = True
        _class_name = name
        return name


def is_everything_running():
    """Everything 主程序是否在跑（看 IPC 窗口是否存在）。"""
    if not _IS_WIN:
        return False
    try:
        hwnd = user32.FindWindowW(EVERYTHING_IPC_WNDCLASS, None)
        return bool(hwnd)
    except Exception:
        return False


def _read_wstr_bounded(buf_addr, cb_data, offset):
    """在回复缓冲区 [buf_addr, buf_addr+cb_data) 内安全读取 NUL 结尾的 WCHAR 字符串。

    偏移越界（畸形回复）返回 None；字符串未在缓冲区内终止则截断到缓冲区末尾，
    避免 wstring_at 无限定长度读越界导致崩溃。
    """
    try:
        off = int(offset)
    except (TypeError, ValueError):
        return None
    # 至少要容得下 1 个 WCHAR
    if off < 0 or off + 2 > cb_data:
        return None
    max_chars = (cb_data - off) // 2
    try:
        s = ctypes.wstring_at(buf_addr + off, max_chars)
    except Exception:
        return None
    # 带 size 的 wstring_at 不会在 NUL 处停下，手动截断到首个 NUL
    nul = s.find('\x00')
    if nul != -1:
        s = s[:nul]
    return s


def _parse_list_reply(buf_addr, cb_data):
    """解析 EVERYTHING_IPC_LISTW 回复，返回完整路径列表。"""
    if cb_data < ctypes.sizeof(EVERYTHING_IPC_LISTW_HEADER):
        return []
    raw = (ctypes.c_byte * cb_data).from_address(buf_addr)
    buf = bytes(raw)
    header = EVERYTHING_IPC_LISTW_HEADER.from_buffer_copy(buf[:ctypes.sizeof(EVERYTHING_IPC_LISTW_HEADER)])

    item_size = ctypes.sizeof(EVERYTHING_IPC_ITEMW)
    header_size = ctypes.sizeof(EVERYTHING_IPC_LISTW_HEADER)
    paths = []
    for i in range(header.numitems):
        item_off = header_size + i * item_size
        if item_off + item_size > cb_data:
            break
        item = EVERYTHING_IPC_ITEMW.from_buffer_copy(buf[item_off:item_off + item_size])
        # 字符串以 WCHAR 数组形式存在 buffer 内偏移处，null 结尾；读取严格限制在回复缓冲区内
        filename = _read_wstr_bounded(buf_addr, cb_data, item.filename_offset)
        path = _read_wstr_bounded(buf_addr, cb_data, item.path_offset)
        if filename is None or path is None:
            # 偏移越界的畸形条目：跳过，不要崩溃
            continue
        if path and filename:
            paths.append(os.path.join(path, filename))
        elif filename:
            paths.append(filename)
    return paths


def query(search_text, max_results=200, search_flags=0, timeout_ms=5000):
    """同步向 Everything 发送查询。返回路径列表，失败返回 None。

    search_text:  Everything 查询语法 (如 'wfn:"name.ext"' 表示精确文件名匹配)
    max_results:  最多返回多少结果
    search_flags: EVERYTHING_IPC_MATCH* 组合，0 = 默认匹配
    timeout_ms:   等待回复的总超时
    """
    if not _IS_WIN:
        return None
    hwnd_everything = user32.FindWindowW(EVERYTHING_IPC_WNDCLASS, None)
    if not hwnd_everything:
        return None

    class_name = _ensure_class_registered()
    if not class_name:
        return None

    hinstance = kernel32.GetModuleHandleW(None)
    hwnd = user32.CreateWindowExW(
        0, class_name, 'FRESHEverythingRecv', 0, 0, 0, 0, 0,
        HWND_MESSAGE, None, hinstance, None,
    )
    if not hwnd:
        return None

    results = []
    received = [False]
    parse_failed = [False]
    reply_msg = EVERYTHING_IPC_COPYDATAQUERYW + 100  # 任选

    # 自定义 WindowProc，临时替换以接收回复
    @WNDPROC
    def recv_proc(h, msg, wparam, lparam):
        if msg == WM_COPYDATA:
            try:
                cds_ptr = ctypes.cast(lparam, ctypes.POINTER(COPYDATASTRUCT))
                cds = cds_ptr.contents
                # Everything 回复的 dwData == 查询头里的 reply_copydata_message。
                # 只接受匹配的回复，其余 WM_COPYDATA 一律交给 DefWindowProc。
                if int(cds.dwData) == reply_msg:
                    paths = _parse_list_reply(cds.lpData, cds.cbData)
                    results.extend(paths)
                    received[0] = True
                    return 1
            except Exception:
                # 解析崩了要报告成"查询失败"(None)而不是"没有结果"([])，
                # 否则调用方会把它当权威空结果、跳过 es.exe / 全盘扫描兜底
                parse_failed[0] = True
                received[0] = True
                return 1
        return user32.DefWindowProcW(h, msg, wparam, lparam)

    # 把窗口的 WindowProc 替换为我们的
    GWLP_WNDPROC = -4
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.SetWindowLongPtrW.restype = ctypes.c_void_p
        old_proc = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(recv_proc, ctypes.c_void_p))
    else:
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        user32.SetWindowLongW.restype = ctypes.c_void_p
        old_proc = user32.SetWindowLongW(hwnd, GWLP_WNDPROC, ctypes.cast(recv_proc, ctypes.c_void_p))

    try:
        # 构造查询：header + search_string(WCHARs+\0)
        search_bytes = (search_text + '\0').encode('utf-16-le')
        header = EVERYTHING_IPC_QUERYW_HEADER(
            reply_hwnd=int(hwnd) & 0xFFFFFFFF,
            reply_copydata_message=reply_msg,
            search_flags=search_flags,
            offset=0,
            max_results=max_results,
        )
        total = ctypes.sizeof(header) + len(search_bytes)
        buf = ctypes.create_string_buffer(total)
        ctypes.memmove(buf, byref(header), ctypes.sizeof(header))
        ctypes.memmove(ctypes.addressof(buf) + ctypes.sizeof(header), search_bytes, len(search_bytes))

        cds = COPYDATASTRUCT(
            dwData=EVERYTHING_IPC_COPYDATAQUERYW,
            cbData=total,
            lpData=ctypes.cast(buf, ctypes.c_void_p),
        )

        # 发送查询；这一步可能会同步走 WindowProc，所以 received 可能立刻就 True
        # 用 SendMessageTimeoutW 替代 SendMessageW：Everything 消息循环卡死时不会把我们永久挂起。
        # 只用 SMTO_ABORTIFHUNG，不加 SMTO_BLOCK（否则回传消息无法在等待期间被同步处理，必然互等超时）。
        smto_result = ctypes.c_size_t(0)
        sent = user32.SendMessageTimeoutW(
            hwnd_everything, WM_COPYDATA,
            wintypes.WPARAM(int(hwnd)),
            ctypes.addressof(cds),
            SMTO_ABORTIFHUNG,
            min(int(timeout_ms), 3000),
            byref(smto_result),
        )
        if not sent:
            # 失败/超时（目标挂死等）。窗口由 finally 统一 DestroyWindow，这里直接放弃。
            return None

        # 抽取消息直到收到回复或超时
        start = time.time()
        msg = MSG()
        while not received[0] and (time.time() - start) * 1000 < timeout_ms:
            if user32.PeekMessageW(byref(msg), None, 0, 0, PM_REMOVE):
                user32.TranslateMessage(byref(msg))
                user32.DispatchMessageW(byref(msg))
            else:
                time.sleep(0.001)
        if not received[0] or parse_failed[0]:
            return None
        return results
    finally:
        user32.DestroyWindow(hwnd)


def query_by_name(name, drive_hint=None, max_results=200, timeout_ms=5000):
    """通过文件名精确查找。drive_hint 形如 'C'。返回路径列表或 None。"""
    if drive_hint:
        q = f'"{drive_hint}:\\" wfn:"{name}"'
    else:
        q = f'wfn:"{name}"'
    return query(q, max_results=max_results, timeout_ms=timeout_ms)
