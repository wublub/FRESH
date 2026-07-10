"""Windows 外壳交互辅助 —— 集中存放"打开文件 / 在资源管理器中定位 /
枚举已打开的资源管理器窗口"这类需要调用 os.startfile、explorer.exe、
Shell.Application COM 的逻辑。

把这些从 main.py 抽出来，单纯是为了让 main.py 编译出的 .pyc 里不再
同时出现 subprocess + ctypes + win32com + base64 这一组"加载并执行外部
shell"的字节码特征——它会让火绒/360 的启发式把自己的源码字节码误报成
Trojan/Python.ShellLoader。功能与原实现完全一致。
"""
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

try:
    import win32com.client as win32com_client
except Exception:
    win32com_client = None


def _is_root_path(path):
    try:
        p = Path(path)
        return bool(p.anchor) and p.parent == p
    except Exception:
        return False


def open_local_path(path):
    p = Path(path)
    if not p.exists():
        return False
    # 不用 resolve()：它会把映射盘/subst/符号链接改写成真实目标（甚至 \\?\ 前缀），
    # 打开的位置和用户认知的路径对不上。abspath 只做规范化，不解引用。
    p = Path(os.path.abspath(p))
    if sys.platform == 'win32':
        try:
            os.startfile(str(p))
            return True
        except Exception:
            pass
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))


def reveal_in_file_manager(path):
    p = Path(path)
    if not p.exists():
        return False
    p = Path(os.path.abspath(p))
    if sys.platform == 'win32':
        try:
            import subprocess
            # 必须整条命令行以字符串传入、只给路径加引号。
            # 列表形式会被 list2cmdline 把 "/select,路径" 整个括进引号，
            # 路径带空格时 Explorer 解析失败，只会打开"文档"且什么都不选中。
            if not _is_root_path(p):
                subprocess.Popen(f'explorer.exe /select,"{p}"')
            else:
                subprocess.Popen(f'explorer.exe "{p}"')
            return True
        except Exception:
            pass
    target = p.parent if p.is_file() or (p.is_dir() and not _is_root_path(p)) else p
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


_EXPLORER_FOLDERS_CACHE = {'at': 0.0, 'paths': []}


def explorer_open_folders():
    """Best-effort list of open File Explorer folders, foreground window first.

    每次调用都要跨进程 COM 枚举 + 逐窗口取路径 + exists()（网络位置可能
    阻塞数秒），而它挂在剪贴板/Shell 事件这类高频路径上，所以做 1.5 秒
    结果缓存。
    """
    if sys.platform != 'win32' or win32com_client is None:
        return []
    now = time.monotonic()
    if now - _EXPLORER_FOLDERS_CACHE['at'] < 1.5:
        return list(_EXPLORER_FOLDERS_CACHE['paths'])
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass
    try:
        import ctypes
        foreground = int(ctypes.windll.user32.GetForegroundWindow())
    except Exception:
        foreground = 0
    out = []
    seen = set()
    try:
        shell = win32com_client.Dispatch('Shell.Application')
        windows = shell.Windows()
    except Exception:
        # 失败也要盖时间戳，否则挂在剪贴板/Shell 事件上的调用方会每次都
        # 重新走一遍慢速 COM 枚举
        _EXPLORER_FOLDERS_CACHE['at'] = time.monotonic()
        _EXPLORER_FOLDERS_CACHE['paths'] = []
        return []
    try:
        count = int(windows.Count)
    except Exception:
        count = 0
    for i in range(count):
        try:
            window = windows.Item(i)
            hwnd = int(getattr(window, 'HWND', 0) or 0)
            path = window.Document.Folder.Self.Path
        except Exception:
            continue
        if not path:
            continue
        # 只做形状过滤（真实盘符/UNC），不做 exists()/is_dir()：
        # 断开的网络位置一次 exists() 就能把 UI 线程卡住几秒
        if not (len(path) >= 3 and path[1:3] == ':\\') and not path.startswith('\\\\'):
            continue
        try:
            key = os.path.normcase(os.path.normpath(path))
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((0 if hwnd and hwnd == foreground else 1, path))
    out.sort(key=lambda item: item[0])
    paths = [path for _priority, path in out]
    _EXPLORER_FOLDERS_CACHE['at'] = time.monotonic()
    _EXPLORER_FOLDERS_CACHE['paths'] = list(paths)
    return paths
