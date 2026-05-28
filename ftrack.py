"""文件追踪 - 用 NTFS ADS + File ID + 内容哈希在文件被改名/移动后仍能定位"""
import ctypes
import hashlib
import os
import shutil
import string
import subprocess
import sys
from ctypes import byref, wintypes
from pathlib import Path

try:
    import everything_ipc
except Exception:
    everything_ipc = None

ADS_STREAM = 'fresh_id'

_IS_WIN = sys.platform == 'win32'

if _IS_WIN:
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    FILE_SHARE_READ = 0x01
    FILE_SHARE_WRITE = 0x02
    FILE_SHARE_DELETE = 0x04
    OPEN_EXISTING = 3
    FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    FILE_ATTRIBUTE_DIRECTORY = 0x10

    class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ('dwFileAttributes', wintypes.DWORD),
            ('ftCreationTime', wintypes.FILETIME),
            ('ftLastAccessTime', wintypes.FILETIME),
            ('ftLastWriteTime', wintypes.FILETIME),
            ('dwVolumeSerialNumber', wintypes.DWORD),
            ('nFileSizeHigh', wintypes.DWORD),
            ('nFileSizeLow', wintypes.DWORD),
            ('nNumberOfLinks', wintypes.DWORD),
            ('nFileIndexHigh', wintypes.DWORD),
            ('nFileIndexLow', wintypes.DWORD),
        ]

    class _FILE_ID_UNION(ctypes.Union):
        _fields_ = [('FileId', ctypes.c_int64), ('_pad', ctypes.c_byte * 16)]

    class _FILE_ID_DESCRIPTOR(ctypes.Structure):
        _anonymous_ = ('u',)
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('Type', wintypes.DWORD),
            ('u', _FILE_ID_UNION),
        ]

    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetFileInformationByHandle.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    ]
    _kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
    _kernel32.OpenFileById.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_FILE_ID_DESCRIPTOR),
        wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    _kernel32.OpenFileById.restype = wintypes.HANDLE
    _kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    ]
    _kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _kernel32.GetVolumeInformationW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD,
    ]
    _kernel32.GetVolumeInformationW.restype = wintypes.BOOL
    _kernel32.GetLogicalDrives.restype = wintypes.DWORD
    _kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetDriveTypeW.restype = wintypes.UINT


# ============ NTFS Alternate Data Stream ============

def write_tag(path, tag, stream=ADS_STREAM):
    """在文件/文件夹上写一个 ADS 标记。返回是否成功。"""
    ads = f"{path}:{stream}"
    try:
        with open(ads, 'w', encoding='utf-8') as f:
            f.write(tag)
        return True
    except OSError:
        return False


def read_tag(path, stream=ADS_STREAM):
    """读取 ADS 标记。文件不存在或非 NTFS 返回 None。"""
    ads = f"{path}:{stream}"
    try:
        with open(ads, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except OSError:
        return None


def remove_tag(path, stream=ADS_STREAM):
    """删除 ADS 标记。"""
    ads = f"{path}:{stream}"
    try:
        os.remove(ads)
        return True
    except OSError:
        return False


# ============ NTFS File ID ============

def get_file_info(path):
    """获取 NTFS 文件 ID 信息 (volume serial + file id)。失败返回 None。"""
    if not _IS_WIN:
        return None
    handle = _kernel32.CreateFileW(
        str(path),
        0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not _kernel32.GetFileInformationByHandle(handle, byref(info)):
            return None
        return {
            'volume_serial': info.dwVolumeSerialNumber,
            'file_id_high': info.nFileIndexHigh,
            'file_id_low': info.nFileIndexLow,
            'is_dir': bool(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY),
        }
    finally:
        _kernel32.CloseHandle(handle)


def _volume_serial_for_drive(letter):
    if not _IS_WIN:
        return None
    serial = wintypes.DWORD(0)
    max_comp = wintypes.DWORD(0)
    flags = wintypes.DWORD(0)
    ok = _kernel32.GetVolumeInformationW(
        f"{letter}:\\", None, 0, byref(serial), byref(max_comp), byref(flags), None, 0
    )
    if not ok:
        return None
    return serial.value


def _drive_for_volume_serial(volume_serial):
    if not _IS_WIN or volume_serial is None:
        return None
    for letter in _local_drive_letters():
        if _volume_serial_for_drive(letter) == volume_serial:
            return letter
    return None


def find_by_file_id(volume_serial, file_id_high, file_id_low, drive_hint=None):
    """通过 NTFS File ID 查找文件当前路径。"""
    if not _IS_WIN:
        return None
    letter = None
    if drive_hint and _volume_serial_for_drive(drive_hint) == volume_serial:
        letter = drive_hint
    if not letter:
        letter = _drive_for_volume_serial(volume_serial)
    if not letter:
        return None

    vol_handle = _kernel32.CreateFileW(
        f"\\\\.\\{letter}:",
        0,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if not vol_handle or vol_handle == INVALID_HANDLE_VALUE:
        return None
    try:
        desc = _FILE_ID_DESCRIPTOR()
        desc.dwSize = ctypes.sizeof(_FILE_ID_DESCRIPTOR)
        desc.Type = 0  # FileIdType
        desc.FileId = (file_id_high << 32) | file_id_low

        file_handle = _kernel32.OpenFileById(
            vol_handle, byref(desc),
            0,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            FILE_FLAG_BACKUP_SEMANTICS,
        )
        if not file_handle or file_handle == INVALID_HANDLE_VALUE:
            return None
        try:
            buf = ctypes.create_unicode_buffer(32768)
            n = _kernel32.GetFinalPathNameByHandleW(file_handle, buf, 32768, 0)
            if n == 0:
                return None
            path = buf.value
            if path.startswith('\\\\?\\'):
                path = path[4:]
            if path.startswith('UNC\\'):
                path = '\\\\' + path[4:]
            return path
        finally:
            _kernel32.CloseHandle(file_handle)
    finally:
        _kernel32.CloseHandle(vol_handle)


# ============ 内容哈希 ============

def compute_hash(path, max_bytes=None):
    """计算 SHA-256 内容哈希。max_bytes 限制读取大小，None 表示读完整个文件。"""
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            if max_bytes is None:
                for chunk in iter(lambda: f.read(65536), b''):
                    h.update(chunk)
            else:
                read = 0
                while read < max_bytes:
                    chunk = f.read(min(65536, max_bytes - read))
                    if not chunk:
                        break
                    h.update(chunk)
                    read += len(chunk)
        return h.hexdigest()
    except OSError:
        return None


HASH_PARTIAL_BYTES = 64 * 1024 * 1024


def _hash_max_bytes_for_tracking(tracking):
    if tracking.get('content_hash_partial'):
        return HASH_PARTIAL_BYTES
    return None


def _size_from_tracking(tracking):
    try:
        size = tracking.get('size_snapshot')
        if size is None:
            return None
        return int(size)
    except (TypeError, ValueError):
        return None


def path_matches_hash(path, tracking):
    """用 tracking 里的 size + content_hash 验证 path。仅适用于文件。"""
    digest = (tracking or {}).get('content_hash')
    if not digest:
        return False
    try:
        if not os.path.isfile(path):
            return False
        size = _size_from_tracking(tracking)
        if size is not None and os.path.getsize(path) != size:
            return False
        actual = compute_hash(path, max_bytes=_hash_max_bytes_for_tracking(tracking))
        return actual == digest
    except OSError:
        return False


# ============ 磁盘扫描 ============

DRIVE_FIXED = 3
DRIVE_REMOVABLE = 2

# 系统/缓存目录黑名单（小写匹配），扫了也不可能有用户附件
_SKIP_DIR_NAMES_LOWER = {
    'windows', 'program files', 'program files (x86)', 'programdata',
    '$recycle.bin', 'system volume information', 'recovery',
    'msocache', 'config.msi', '$winreagent', '$getcurrent',
    'node_modules', '__pycache__', '.git', '.svn', '.hg',
    '.idea', '.vs', '.vscode', '.gradle', '.cache',
    'venv', '.venv', 'env', '.env',
    'target', 'dist-newstyle', '.next', '.nuxt', '.parcel-cache',
    'appdata',  # 用户的 AppData 一般也都是程序缓存，跳掉
}


def _should_skip_dir(name):
    lower = name.lower()
    if lower in _SKIP_DIR_NAMES_LOWER:
        return True
    # 以 $ 开头的多半是 NTFS 元数据 / 隐藏系统目录
    if lower.startswith('$'):
        return True
    return False


def _drive_is_ntfs(letter):
    if not _IS_WIN:
        return False
    buf = ctypes.create_unicode_buffer(64)
    flags = wintypes.DWORD(0)
    max_comp = wintypes.DWORD(0)
    serial = wintypes.DWORD(0)
    ok = _kernel32.GetVolumeInformationW(
        f"{letter}:\\", None, 0, byref(serial), byref(max_comp), byref(flags), buf, 64
    )
    if not ok:
        return False
    return buf.value.upper() == 'NTFS'


def _local_drive_letters():
    if not _IS_WIN:
        return []
    mask = _kernel32.GetLogicalDrives()
    out = []
    for i, ch in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            t = _kernel32.GetDriveTypeW(f"{ch}:\\")
            if t in (DRIVE_FIXED, DRIVE_REMOVABLE):
                out.append(ch)
    return out


def local_drive_roots(ntfs_only=False):
    out = []
    for letter in _local_drive_letters():
        if ntfs_only and not _drive_is_ntfs(letter):
            continue
        out.append(f"{letter}:\\")
    return out


def _ordered_roots(roots, drive_hints, ntfs_only):
    """按 drive_hints 给定的优先级排好的扫描根目录列表。"""
    if roots is not None:
        return list(roots)
    all_roots = local_drive_roots(ntfs_only=ntfs_only)
    if not drive_hints:
        return all_roots
    hint_roots = []
    seen = set()
    for h in drive_hints:
        if not h:
            continue
        target = f"{h}:\\".upper()
        for r in all_roots:
            if r.upper() == target and r not in seen:
                hint_roots.append(r)
                seen.add(r)
                break
    rest = [r for r in all_roots if r not in seen]
    return hint_roots + rest


def _iter_disk(roots=None, drive_hints=None, progress=None, cancel=None, ntfs_only=False):
    """统一磁盘遍历入口。自动跳过系统/缓存目录，drive_hints 优先。
    生成 (full_path, is_dir) 序列。
    """
    ordered = _ordered_roots(roots, drive_hints, ntfs_only)
    for root in ordered:
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if cancel and cancel():
                return
            # 原地裁掉黑名单子目录
            dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
            if progress:
                try:
                    progress(dirpath)
                except Exception:
                    pass
            for name in filenames:
                yield os.path.join(dirpath, name), False
            for name in dirnames:
                yield os.path.join(dirpath, name), True


def scan_for_tag(tag, roots=None, progress=None, cancel=None, stream=ADS_STREAM, drive_hints=None):
    """扫描磁盘查找带指定 ADS 标记的文件/文件夹。"""
    for path, _is_dir in _iter_disk(roots, drive_hints, progress, cancel, ntfs_only=True):
        if read_tag(path, stream) == tag:
            return path
    return None


def scan_for_tags(tags, roots=None, progress=None, cancel=None, on_found=None, stream=ADS_STREAM, drive_hints=None):
    """一次遍历磁盘，查找带 tags 集合中任意 ADS 标记的文件/文件夹。

    tags:        待查 tracking_id 集合
    drive_hints: ['C', 'D'] 这些盘优先扫
    on_found:    每发现一个就回调 (tag, path) -> None
    返回 dict {tag: path}。
    """
    if not tags:
        return {}
    remaining = set(tags)
    found = {}
    for path, _is_dir in _iter_disk(roots, drive_hints, progress, cancel, ntfs_only=True):
        if not remaining:
            break
        t = read_tag(path, stream)
        if t and t in remaining:
            found[t] = path
            remaining.discard(t)
            if on_found:
                try:
                    on_found(t, path)
                except Exception:
                    pass
    return found


def scan_for_name(name, roots=None, progress=None, cancel=None, limit=50, drive_hints=None):
    """按文件/文件夹名扫描，返回匹配的路径列表。"""
    matches = []
    target = name.lower()
    for path, _is_dir in _iter_disk(roots, drive_hints, progress, cancel, ntfs_only=False):
        if os.path.basename(path).lower() == target:
            matches.append(path)
            if len(matches) >= limit:
                return matches
    return matches


def find_nearby_name_candidates(name, original_path=None, roots=None, limit=50, max_depth=3):
    """Small-scope name lookup used before slow disk scans.

    This intentionally avoids walking whole drive roots. It checks likely
    places: the recorded path's parent and configured roots, plus direct files
    in all current drive roots. That covers stale records like Desktop/file.pdf
    when the file is actually under Desktop/project/file.pdf, and cross-drive
    cuts to F:\file.pdf, without showing a long "search disk" workflow.
    """
    if not name:
        return []

    target = name.lower()
    matches = []
    seen_paths = set()
    seen_roots = set()

    def add_candidate(path):
        if len(matches) >= limit:
            return
        try:
            p = Path(path)
            key = os.path.normcase(os.path.normpath(str(p)))
            if key in seen_paths:
                return
            if p.exists() and p.name.lower() == target:
                seen_paths.add(key)
                matches.append(str(p))
        except OSError:
            return

    def add_root(root, recursive=True):
        if len(matches) >= limit or not root:
            return
        try:
            root_path = Path(root)
            key = os.path.normcase(os.path.normpath(str(root_path)))
            if key in seen_roots:
                return
            seen_roots.add(key)
            if not root_path.exists() or not root_path.is_dir():
                return

            add_candidate(root_path / name)
            if len(matches) >= limit or not recursive:
                return

            base_depth = len(root_path.parts)
            for dirpath, dirnames, filenames in os.walk(root_path, onerror=lambda e: None):
                if len(matches) >= limit:
                    return
                depth = len(Path(dirpath).parts) - base_depth
                if depth >= max_depth:
                    dirnames[:] = []
                else:
                    dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
                if name in filenames:
                    add_candidate(Path(dirpath) / name)
        except OSError:
            return

    if original_path:
        try:
            original = Path(original_path)
            add_candidate(original)
            add_root(original.parent, recursive=True)
        except Exception:
            pass

    for root in roots or []:
        add_root(root, recursive=True)

    # Drive roots are cheap to check directly and cover cut/paste to F:\name.
    for root in local_drive_roots(ntfs_only=False):
        add_root(root, recursive=False)

    return matches


def scan_for_hash(tracking, roots=None, progress=None, cancel=None, limit=20, drive_hints=None):
    """按内容 hash 扫描文件。先用 size_snapshot 过滤，再计算 SHA-256。"""
    digest = (tracking or {}).get('content_hash')
    size = _size_from_tracking(tracking or {})
    if not digest or size is None:
        return []

    matches = []
    max_bytes = _hash_max_bytes_for_tracking(tracking)
    for path, is_dir in _iter_disk(roots, drive_hints, progress, cancel, ntfs_only=False):
        if cancel and cancel():
            break
        if is_dir:
            continue
        try:
            if os.path.getsize(path) != size:
                continue
        except OSError:
            continue
        if compute_hash(path, max_bytes=max_bytes) == digest:
            matches.append(path)
            if len(matches) >= limit:
                break
    return matches


def scan_for_hashes(tag_to_tracking, roots=None, progress=None, cancel=None, on_found=None,
                    drive_hints=None, unique_only=False):
    """一次遍历磁盘，按 size + content_hash 找回多个文件。返回 {tag: path}。"""
    groups = {}
    for tag, tracking in (tag_to_tracking or {}).items():
        digest = (tracking or {}).get('content_hash')
        size = _size_from_tracking(tracking or {})
        if not tag or not digest or size is None:
            continue
        partial = bool((tracking or {}).get('content_hash_partial'))
        groups.setdefault(size, {}).setdefault((digest, partial), set()).add(tag)
    if not groups:
        return {}

    if unique_only:
        matches_by_key = {}
        for path, is_dir in _iter_disk(roots, drive_hints, progress, cancel, ntfs_only=False):
            if cancel and cancel():
                break
            if is_dir:
                continue
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            by_hash = groups.get(size)
            if not by_hash:
                continue

            hash_cache = {}
            for digest, partial in by_hash.keys():
                key = (size, digest, partial)
                if len(matches_by_key.get(key, [])) >= 2:
                    continue
                max_bytes = HASH_PARTIAL_BYTES if partial else None
                if max_bytes not in hash_cache:
                    hash_cache[max_bytes] = compute_hash(path, max_bytes=max_bytes)
                if hash_cache[max_bytes] == digest:
                    matches_by_key.setdefault(key, []).append(path)

        found = {}
        for size, by_hash in groups.items():
            for (digest, partial), tags in by_hash.items():
                key = (size, digest, partial)
                paths = matches_by_key.get(key, [])
                if len(paths) != 1 or len(tags) != 1:
                    continue
                tag = next(iter(tags))
                found[tag] = paths[0]
                if on_found:
                    try:
                        on_found(tag, paths[0])
                    except Exception:
                        pass
        return found

    remaining = {tag for by_hash in groups.values() for tags in by_hash.values() for tag in tags}
    found = {}
    for path, is_dir in _iter_disk(roots, drive_hints, progress, cancel, ntfs_only=False):
        if not remaining:
            break
        if cancel and cancel():
            break
        if is_dir:
            continue
        try:
            size = os.path.getsize(path)
        except OSError:
            continue
        by_hash = groups.get(size)
        if not by_hash:
            continue

        hash_cache = {}
        for (digest, partial), tags in list(by_hash.items()):
            active_tags = tags & remaining
            if not active_tags:
                continue
            max_bytes = HASH_PARTIAL_BYTES if partial else None
            if max_bytes not in hash_cache:
                hash_cache[max_bytes] = compute_hash(path, max_bytes=max_bytes)
            if hash_cache[max_bytes] != digest:
                continue
            for tag in list(active_tags):
                found[tag] = path
                remaining.discard(tag)
                if on_found:
                    try:
                        on_found(tag, path)
                    except Exception:
                        pass
    return found


# ============ Everything CLI (es.exe) 集成 ============

EVERYTHING_DOWNLOAD_URL = 'https://www.voidtools.com/downloads/#cli'

_ES_EXE_CACHE = None  # None = 未探测; '' = 探测过但不存在; 路径字符串 = 已找到


def _find_running_everything_dir():
    """通过 wmic 找运行中的 Everything.exe 的目录。"""
    if not _IS_WIN:
        return None
    try:
        out = subprocess.run(
            ['wmic', 'process', 'where', "name='Everything.exe'", 'get', 'ExecutablePath'],
            capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        for line in (out.stdout or '').splitlines():
            line = line.strip()
            if line.lower().endswith('everything.exe') and os.path.isfile(line):
                return os.path.dirname(line)
    except Exception:
        pass
    return None


def find_es_exe(prefer_path=None):
    """查找 es.exe (Everything CLI)。返回路径或 None。

    prefer_path: 用户在设置里指定的路径，优先采用。
    """
    global _ES_EXE_CACHE
    if prefer_path and os.path.isfile(prefer_path):
        return prefer_path

    if _ES_EXE_CACHE is not None:
        return _ES_EXE_CACHE or None

    # 1. PATH
    p = shutil.which('es')
    if p:
        _ES_EXE_CACHE = p
        return p

    # 2. 跟 Everything.exe 同目录
    everything_dir = _find_running_everything_dir()
    candidates = []
    if everything_dir:
        candidates.append(os.path.join(everything_dir, 'es.exe'))

    # 3. 常见安装位置
    candidates += [
        r'C:\Program Files\Everything\es.exe',
        r'C:\Program Files (x86)\Everything\es.exe',
    ]
    for c in candidates:
        if os.path.isfile(c):
            _ES_EXE_CACHE = c
            return c

    _ES_EXE_CACHE = ''
    return None


def everything_available(prefer_path=None):
    """Everything 是否可用（IPC 或 es.exe）。"""
    if everything_ipc and everything_ipc.is_everything_running():
        return True
    return find_es_exe(prefer_path) is not None


def everything_mode(prefer_path=None):
    """返回当前 Everything 集成模式: 'ipc' / 'es' / None"""
    if everything_ipc and everything_ipc.is_everything_running():
        return 'ipc'
    if find_es_exe(prefer_path):
        return 'es'
    return None


def everything_search(query, exact_name=False, drive_hint=None, limit=200, es_path=None, timeout=10):
    """通过 Everything 搜索：优先 IPC，回退 es.exe。"""
    # 1. IPC 优先（无需任何工具）
    if everything_ipc and everything_ipc.is_everything_running():
        try:
            if exact_name:
                paths = everything_ipc.query_by_name(query, drive_hint=drive_hint, max_results=limit, timeout_ms=int(timeout * 1000))
            else:
                q = query
                if drive_hint:
                    q = f'"{drive_hint}:\\" {q}'
                paths = everything_ipc.query(q, max_results=limit, timeout_ms=int(timeout * 1000))
            if paths is not None:
                return paths
        except Exception:
            pass

    # 2. es.exe 备选
    es = find_es_exe(es_path)
    if not es:
        return None

    if exact_name:
        q = f'wfn:"{query}"'
    else:
        q = query
    if drive_hint:
        q = f'"{drive_hint}:\\" {q}'

    args = [es, '-utf8', '-no-header', '-n', str(limit), q]
    try:
        out = subprocess.run(
            args, capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        if out.returncode != 0:
            return []
        text = out.stdout.decode('utf-8', errors='replace')
        return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception:
        return None


def scan_for_tags_smart(tag_to_name, drive_hints=None, on_found=None, cancel=None,
                        progress=None, phase=None, stream=ADS_STREAM,
                        es_path=None, scan_roots=None):
    """优先用 Everything（IPC 或 es.exe）查名定位候选 → 读 ADS 验证。
    Everything 没命中的项继续回退 scan_for_tags (os.walk)。

    tag_to_name: {tracking_id: original_name}
    返回 {tag: path}
    """
    if not tag_to_name:
        return {}

    mode = everything_mode(es_path)
    if mode:
        if phase:
            phase(f'用 Everything ({mode}) 加速查找')
        found = _scan_via_everything(
            tag_to_name, drive_hints=drive_hints, on_found=on_found,
            cancel=cancel, progress=progress, phase=phase, stream=stream, es_path=es_path,
        )
        remaining = set(tag_to_name.keys()) - set(found.keys())
        if not remaining or (cancel and cancel()):
            return found
        if phase:
            phase('Everything 未全部命中，按追踪标记扫描剩余项')
        fallback = scan_for_tags(
            remaining,
            roots=scan_roots, drive_hints=drive_hints, on_found=on_found,
            cancel=cancel, progress=progress, stream=stream,
        )
        found.update(fallback)
        return found

    if phase:
        phase('Everything 不可用，使用全盘扫描')
    return scan_for_tags(
        set(tag_to_name.keys()),
        roots=scan_roots, drive_hints=drive_hints, on_found=on_found,
        cancel=cancel, progress=progress, stream=stream,
    )


def _scan_via_everything(tag_to_name, drive_hints, on_found, cancel, progress, phase, stream, es_path):
    if phase:
        phase('用 Everything 查找候选')
    found = {}
    name_to_tags = {}
    for tag, name in tag_to_name.items():
        if not name:
            continue
        name_to_tags.setdefault(name, set()).add(tag)

    drive = (drive_hints or [None])[0]

    def query_once(name, drive):
        # 先按 drive_hint 精确名搜，找不到再放开全盘搜
        paths = everything_search(name, exact_name=True, drive_hint=drive, limit=500, es_path=es_path)
        if not paths and drive:
            paths = everything_search(name, exact_name=True, drive_hint=None, limit=500, es_path=es_path)
        return paths or []

    for name, tags in list(name_to_tags.items()):
        if cancel and cancel():
            break
        if progress:
            progress(f'Everything: {name}')
        paths = query_once(name, drive)
        for path in paths:
            if cancel and cancel():
                break
            t = read_tag(path, stream)
            if t and t in tags:
                found[t] = path
                tags.discard(t)
                if on_found:
                    try:
                        on_found(t, path)
                    except Exception:
                        pass
                if not tags:
                    break
    return found


def find_candidates_by_name(name, drive_hint=None, size_hint=None, es_path=None, fallback_walk=True, cancel=None, progress=None):
    """按文件名找候选路径。优先 Everything (IPC / es.exe)；不行就 os.walk。
    size_hint 不为空时，把大小相同的项排到前面。
    """
    paths = None
    if everything_mode(es_path):
        paths = everything_search(name, exact_name=True, drive_hint=drive_hint, limit=200, es_path=es_path) or []
    if not paths and fallback_walk:
        paths = scan_for_name(
            name,
            drive_hints=[drive_hint] if drive_hint else None,
            cancel=cancel, progress=progress, limit=200,
        )
    paths = paths or []

    if size_hint and paths:
        def key(p):
            try:
                return (0 if os.path.getsize(p) == size_hint else 1, p.lower())
            except OSError:
                return (1, p.lower())
        paths.sort(key=key)
    return paths


# ============ 一站式工具 ============

def build_tracking(path):
    """为新加入的文件/文件夹生成完整的跟踪信息。返回 dict (可能为空)。"""
    info = {}
    p = Path(path)
    if not p.exists():
        return info

    import uuid
    tag = uuid.uuid4().hex
    if write_tag(str(p), tag):
        info['tracking_id'] = tag

    fi = get_file_info(str(p))
    if fi:
        info['volume_serial'] = fi['volume_serial']
        info['file_id_high'] = fi['file_id_high']
        info['file_id_low'] = fi['file_id_low']

    try:
        info['drive_hint'] = str(p.resolve()).split(':', 1)[0]
    except Exception:
        pass

    if p.is_file():
        try:
            size = p.stat().st_size
            info['size_snapshot'] = size
            # 小文件（<=64MB）整体哈希；大文件只哈希前 64MB，避免太慢
            h = compute_hash(str(p), max_bytes=None if size <= 64 * 1024 * 1024 else 64 * 1024 * 1024)
            if h:
                info['content_hash'] = h
                if size > 64 * 1024 * 1024:
                    info['content_hash_partial'] = True
        except OSError:
            pass
    return info


def try_recover(tracking, scan=False, progress=None, cancel=None):
    """根据 tracking 信息尝试恢复路径。

    tracking: dict，包含 tracking_id / volume_serial / file_id_high / file_id_low / drive_hint
    scan:     是否启用慢速全盘扫描（按 ADS 标签）
    返回找到的路径，或 None。
    """
    if not tracking:
        return None

    vs = tracking.get('volume_serial')
    fh = tracking.get('file_id_high')
    fl = tracking.get('file_id_low')
    hint = tracking.get('drive_hint')
    if vs is not None and fh is not None and fl is not None:
        try:
            p = find_by_file_id(vs, fh, fl, drive_hint=hint)
            if p and os.path.exists(p):
                return p
        except Exception:
            pass

    if scan:
        tag = tracking.get('tracking_id')
        if tag:
            try:
                drive_hints = [hint] if hint else None
                p = scan_for_tag(tag, progress=progress, cancel=cancel, drive_hints=drive_hints)
                if p:
                    return p
            except Exception:
                pass
    return None
