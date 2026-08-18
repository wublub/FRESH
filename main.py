"""FRESH - 苹果风格便签"""
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from collections import OrderedDict, defaultdict
from datetime import datetime, timedelta
from html import escape as html_escape
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import (
    Qt, QSize, Signal, QTimer, QRect, QRectF, QUrl, QPoint, QPointF, QThread,
    QFileSystemWatcher, QEvent, QEventLoop, QSettings, QLockFile, QStandardPaths, QDate,
    QVariantAnimation, QEasingCurve
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (
    QPixmap, QImage, QImageReader, QFont, QColor, QPainter, QPolygonF,
    QDesktopServices, QFontMetrics, QKeySequence, QIcon, QShortcut, QGuiApplication,
    QPen, QCursor, QPainterPath, QLinearGradient, QBrush,
    QTextCharFormat, QTextCursor, QTextListFormat
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QLabel, QScrollArea, QFrame, QFileDialog, QMessageBox,
    QMenu, QStyledItemDelegate, QStyle, QStackedWidget, QGridLayout,
    QDialog, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QComboBox, QSizePolicy, QProgressDialog,
    QGroupBox, QFormLayout, QCheckBox, QInputDialog,
    QSystemTrayIcon, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QPlainTextEdit, QKeySequenceEdit, QGraphicsOpacityEffect,
    QToolTip, QDateEdit
)

from accounts import AccountError, AccountManager, MIN_PASSWORD_LENGTH
from app_paths import DATA_ROOT_ENV, portable_data_root, set_data_root
from crypter import PASSWORD_KDF_ITERATIONS, PasswordCrypter, SaltFileError
from storage import (
    IMAGE_EXTS,
    SCREENSHOT_BOARD_ID,
    Storage,
    is_attachment_image as is_image_attachment,
)
from styles import COLORS, STYLE
from customization import (
    DEFAULT_TEXTS,
    apply_text_overrides,
    custom_qss_path,
    customized_stylesheet,
    ensure_custom_files,
    install_text_overrides,
    load_custom_qss_text,
    load_text_config_values,
    reload_customization,
    save_custom_qss_text,
    save_text_config_values,
    text_config_path,
    tr,
    validate_qss_text,
)
import ftrack
import win_frame
from win_shell import open_local_path, reveal_in_file_manager, explorer_open_folders
from shell_notify import (
    ShellChangeFilter,
    SHCNE_RENAMEITEM, SHCNE_RENAMEFOLDER,
    SHCNE_CREATE, SHCNE_DELETE, SHCNE_MKDIR, SHCNE_RMDIR,
    SHCNE_UPDATEDIR, SHCNE_UPDATEITEM,
)


DATA_ROOT_SETTINGS = 'data/root_dir'
DATA_ROOT_ARG = '--data-root'
AUTOSTART_NAME = 'FRESH'
AUTOSTART_REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'

logger = logging.getLogger('fresh')


def configure_application_font(app):
    """Use a Windows-native font stack with reliable Chinese fallback.

    QSS font-family fallback is inconsistent across Qt platform plugins.  In
    particular, naming an unavailable macOS-only family first can leave CJK
    glyphs rendered as tofu boxes.  QFont's family list delegates fallback to
    Qt/DirectWrite and keeps the typography crisp on Windows 10/11.
    """
    font = QFont()
    font.setFamilies([
        'Segoe UI Variable Text',
        'Microsoft YaHei UI',
        'Segoe UI',
    ])
    font.setPointSize(10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)


def _ui_icon_pixmap(name, color, size=64):
    """Render a small font-independent line icon on a high-resolution canvas."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(QColor(color), max(3.5, size * 0.075))
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    s = float(size)

    if name == 'plus':
        painter.drawLine(QPointF(s * .25, s * .5), QPointF(s * .75, s * .5))
        painter.drawLine(QPointF(s * .5, s * .25), QPointF(s * .5, s * .75))
    elif name == 'more':
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        radius = s * .065
        for x in (.25, .5, .75):
            painter.drawEllipse(QPointF(s * x, s * .5), radius, radius)
    elif name == 'timeline':
        painter.drawEllipse(QRectF(s * .16, s * .16, s * .68, s * .68))
        painter.drawLine(QPointF(s * .5, s * .5), QPointF(s * .5, s * .29))
        painter.drawLine(QPointF(s * .5, s * .5), QPointF(s * .67, s * .59))
    elif name == 'minus':
        painter.drawLine(QPointF(s * .27, s * .55), QPointF(s * .73, s * .55))
    elif name == 'maximize':
        painter.drawRoundedRect(QRectF(s * .22, s * .22, s * .56, s * .56), s * .05, s * .05)
    elif name == 'restore':
        painter.drawRoundedRect(QRectF(s * .29, s * .19, s * .48, s * .48), s * .04, s * .04)
        painter.drawRoundedRect(QRectF(s * .19, s * .31, s * .48, s * .48), s * .04, s * .04)
    elif name == 'close':
        painter.drawLine(QPointF(s * .29, s * .29), QPointF(s * .71, s * .71))
        painter.drawLine(QPointF(s * .71, s * .29), QPointF(s * .29, s * .71))
    elif name == 'check':
        painter.drawLine(QPointF(s * .22, s * .52), QPointF(s * .43, s * .71))
        painter.drawLine(QPointF(s * .43, s * .71), QPointF(s * .79, s * .30))
    elif name == 'search':
        painter.drawEllipse(QRectF(s * .18, s * .17, s * .46, s * .46))
        painter.drawLine(QPointF(s * .57, s * .57), QPointF(s * .79, s * .79))
    elif name == 'reset':
        painter.drawArc(QRectF(s * .18, s * .18, s * .62, s * .62), 35 * 16, 285 * 16)
        painter.drawLine(QPointF(s * .18, s * .38), QPointF(s * .18, s * .18))
        painter.drawLine(QPointF(s * .18, s * .18), QPointF(s * .38, s * .18))
    elif name == 'document':
        painter.drawRoundedRect(QRectF(s * .23, s * .13, s * .54, s * .74), s * .06, s * .06)
        for y, right in ((.39, .66), (.53, .66), (.67, .56)):
            painter.drawLine(QPointF(s * .34, s * y), QPointF(s * right, s * y))
    painter.end()
    return pix


def build_ui_icon(name, color='#636366', active_color=None):
    """Create Normal/Active/Disabled icon states without Unicode glyphs."""
    active_color = active_color or color
    icon = QIcon()
    icon.addPixmap(_ui_icon_pixmap(name, color), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_ui_icon_pixmap(name, active_color), QIcon.Active, QIcon.Off)
    disabled = QColor(color)
    disabled.setAlpha(90)
    icon.addPixmap(_ui_icon_pixmap(name, disabled.name(QColor.HexArgb)), QIcon.Disabled, QIcon.Off)
    return icon


def _path_identity_snapshot(path):
    """Cheap object/version token used to guard asynchronous tracking work."""
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError:
        return None
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_ctime_ns),
        int(stat.st_mtime_ns),
        int(stat.st_size),
        int(stat.st_mode & 0o170000),
    )


def _finalize_tracking_identity(path, tracking, old_tracking_id=''):
    """Write a guarded ADS/folder marker after background inspection."""
    data = dict(tracking or {})
    proposed = old_tracking_id or data.get('tracking_id', '')
    if not proposed:
        return data
    if ftrack.write_tracking_tag(str(path), proposed):
        data['tracking_id'] = proposed
    elif old_tracking_id:
        # Preserve an existing logical ID even when the destination filesystem
        # cannot store ADS; hash/File-ID recovery can still use the rest.
        data['tracking_id'] = old_tracking_id
    else:
        # A freshly generated ID that was never written is not a real tag.
        data.pop('tracking_id', None)
    return data


def _build_tracking_snapshot(path, old_tracking_id='', expected_identity=None):
    """Collect tracking metadata without writes and return its object token.

    ``expected_identity`` is captured when work is scheduled.  Checking it
    before and after hashing prevents a queued worker from silently switching
    to a replacement that later appeared at the same path.
    """
    before = _path_identity_snapshot(path)
    if before is None or (expected_identity is not None and before != expected_identity):
        return None
    tracking = ftrack.build_tracking(
        path,
        tracking_id=old_tracking_id or None,
        write_identity=False,
    )
    after = _path_identity_snapshot(path)
    if not tracking or after is None or before != after:
        return None
    return tracking, after


def _attachment_recovery_key(attachment):
    """Return a worker key for recoverable external attachments.

    Real tracking IDs are used unchanged. Files on FAT/exFAT may fail ADS tag
    creation but still keep size + content_hash; those get a synthetic key so
    batch recovery can find them by hash without pretending they have an ADS tag.
    """
    tracking = (attachment or {}).get('tracking') or {}
    tag = tracking.get('tracking_id')
    if tag:
        return tag, True
    if (
        (attachment or {}).get('type') == 'file_ref'
        and tracking.get('content_hash')
        and tracking.get('size_snapshot') is not None
        and (attachment or {}).get('id')
    ):
        return f"hash:{attachment.get('id')}", False
    return '', False


def _clear_recovery_failure(attachment):
    if not attachment:
        return False
    changed = False
    for key in ('recovery_failed_at', 'recovery_failed_count'):
        if key in attachment:
            attachment.pop(key, None)
            changed = True
    return changed


def setup_logging(data_root: Path):
    """把日志写到数据目录下的 fresh.log（轮转 1MB×2）。

    之前全项目近 200 处 except Exception: pass，线上问题完全不可诊断；
    关键路径的吞错现在至少会留下日志。
    """
    try:
        data_root = Path(data_root)
        data_root.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            data_root / 'fresh.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8'
        )
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        logging.captureWarnings(True)

        def _hook(exc_type, exc, tb):
            logger.critical('未捕获异常', exc_info=(exc_type, exc, tb))
            sys.__excepthook__(exc_type, exc, tb)

        sys.excepthook = _hook
    except Exception:
        pass


def legacy_appdata_root() -> Path:
    appdata = os.getenv('APPDATA') or str(Path.home())
    return Path(appdata) / 'FRESH'


def _root_has_fresh_data(root: Path) -> bool:
    return any((root / name).exists() for name in ('accounts.json', 'accounts', 'data.json', 'ui_text.json', 'custom.qss'))


def _copy_initial_data_root(src: Path, dst: Path):
    if not src.exists() or _root_has_fresh_data(dst):
        return
    try:
        shutil.copytree(src, dst, dirs_exist_ok=True)
    except Exception:
        logger.exception('迁移旧数据目录失败: %s -> %s', src, dst)


def parse_startup_args(argv):
    """Extract FRESH arguments before QApplication sees argv."""
    data_root = None
    cleaned = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == DATA_ROOT_ARG:
            if i + 1 < len(argv):
                data_root = Path(argv[i + 1]).expanduser()
                i += 2
                continue
            i += 1
            continue
        prefix = DATA_ROOT_ARG + '='
        if arg.startswith(prefix):
            data_root = Path(arg[len(prefix):]).expanduser()
            i += 1
            continue
        cleaned.append(arg)
        i += 1
    return data_root, cleaned


def configured_data_root(settings: QSettings | None = None, override: Path | str | None = None) -> Path:
    if settings is None:
        settings = QSettings('FRESH', 'FRESH')
    configured = ''
    try:
        configured = settings.value(DATA_ROOT_SETTINGS, '', str) or ''
    except Exception:
        configured = ''
    if override:
        root = Path(override).expanduser()
        try:
            settings.setValue(DATA_ROOT_SETTINGS, str(root))
        except Exception:
            pass
    else:
        root = Path(configured).expanduser() if configured else portable_data_root()
    if not configured and not override:
        _copy_initial_data_root(legacy_appdata_root(), root)
    set_data_root(root)
    return root


def copy_data_root(src: Path, dst: Path):
    """复制数据根目录。返回失败清单 [(路径, 错误)]，空列表表示全部成功。

    之前逐项静默吞错：文件被占用/权限不足/磁盘满都会被跳过，调用方却
    提示"已切换"，用户实际切到一个缺数据的目录。
    """
    src = Path(src)
    dst = Path(dst)
    failures = []
    if not src.exists() or src.resolve() == dst.resolve():
        return failures
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        failures.append((str(dst), str(exc)))
        return failures
    for child in src.iterdir():
        target = dst / child.name
        try:
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, target)
        except shutil.Error as exc:
            # copytree 部分失败时抛出聚合错误，解包列出具体文件
            try:
                for item_src, _item_dst, why in exc.args[0]:
                    failures.append((str(item_src), str(why)))
            except Exception:
                failures.append((str(child), str(exc)))
            logger.warning('复制数据目录部分失败: %s', exc)
        except Exception as exc:
            failures.append((str(child), str(exc)))
            logger.warning('复制数据目录失败 %s: %s', child, exc)
    return failures


def is_path_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


# ============ 工具函数 ============

def html_to_preview(html: str) -> str:
    if not html:
        return ''
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.S | re.I)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = (text.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>')
                .replace('&amp;', '&').replace('&quot;', '"').replace('&#39;', "'"))
    return re.sub(r'\s+', ' ', text).strip()


def markdown_to_preview(text: str) -> str:
    if not text:
        return ''
    text = re.sub(r'```.*?```', ' ', text, flags=re.S)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'^\s{0,3}#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'^\s{0,3}>\s?', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.M)
    text = re.sub(r'[*_~#>`]', '', text)
    return re.sub(r'\s+', ' ', text).strip()


_THUMB_CACHE = OrderedDict()
_THUMB_CACHE_MAX = 600


def _screen_dpr():
    """主屏 devicePixelRatio，供离屏 QPixmap 绘制用（下限 1.0）。"""
    try:
        screen = QGuiApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
    except Exception:
        dpr = 1.0
    return max(1.0, float(dpr))


def load_scaled_pixmap(path, max_w, max_h, dpr=None):
    """按目标尺寸解码图片并做 LRU 缓存。返回 None 表示不存在或解码失败。

    QPixmap(path) 会把原图全分辨率解码进内存（4K 截图几十毫秒/几十 MB），
    网格、时间线每次重建都重复解码是最大的卡顿源。QImageReader 按
    缩略图尺寸解码 + (路径, mtime, 尺寸, dpr) 缓存基本消掉这部分成本；
    按 devicePixelRatio 放大解码再标记，高分屏不再发虚。
    """
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    if dpr is None:
        try:
            screen = QGuiApplication.primaryScreen()
            dpr = screen.devicePixelRatio() if screen else 1.0
        except Exception:
            dpr = 1.0
    dpr = max(1.0, float(dpr))
    key = (str(p), mtime, int(max_w), int(max_h), round(dpr, 2))
    cached = _THUMB_CACHE.get(key)
    if cached is not None:
        _THUMB_CACHE.move_to_end(key)
        return cached
    reader = QImageReader(str(p))
    reader.setAutoTransform(True)
    size = reader.size()
    target_w = max(1, int(max_w * dpr))
    target_h = max(1, int(max_h * dpr))
    scaled = False
    if size.isValid() and size.width() > 0 and size.height() > 0:
        if size.width() > target_w or size.height() > target_h:
            reader.setScaledSize(size.scaled(target_w, target_h, Qt.KeepAspectRatio))
            scaled = True
    image = reader.read()
    if image.isNull():
        return None
    pixmap = QPixmap.fromImage(image)
    if scaled:
        pixmap.setDevicePixelRatio(dpr)
    elif pixmap.width() > target_w or pixmap.height() > target_h:
        # 读取前探不到尺寸的格式：解码后再缩一次
        pixmap = pixmap.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap.setDevicePixelRatio(dpr)
    # else: 源图本身比目标还小——保持 1x 按天然逻辑尺寸显示。
    # 以前这里无条件打 dpr 标记，小图在高分屏会被缩小到 1/dpr 显示。
    _THUMB_CACHE[key] = pixmap
    while len(_THUMB_CACHE) > _THUMB_CACHE_MAX:
        _THUMB_CACHE.popitem(last=False)
    return pixmap


def looks_like_qt_html(text: str) -> bool:
    stripped = (text or '').lstrip().lower()
    return (
        stripped.startswith('<!doctype html')
        or stripped.startswith('<html')
        or 'meta name="qrichtext"' in stripped[:500]
    )


_PREVIEW_CACHE = OrderedDict()
_SEARCH_TEXT_CACHE = OrderedDict()
_NOTE_CACHE_MAX = 4096


def _note_cache_key(note: dict):
    # update_note 改动任何字段都会刷新 updated_at，可作为内容版本号
    return (note.get('id') or id(note), note.get('updated_at', ''), note.get('content_format', ''))


def note_content_preview(note: dict) -> str:
    """生成列表预览文本（带缓存）。

    delegate 每次重绘都会调用；不缓存的话，鼠标划过/滚动列表时每行
    每帧都对全文 HTML 跑一遍正则，长富文本下明显掉帧。
    """
    key = _note_cache_key(note)
    hit = _PREVIEW_CACHE.get(key)
    if hit is not None:
        _PREVIEW_CACHE.move_to_end(key)
        return hit
    content = note.get('content', '') or ''
    if note.get('content_format') == 'markdown':
        result = markdown_to_preview(content)
    else:
        result = html_to_preview(content)
    _PREVIEW_CACHE[key] = result
    while len(_PREVIEW_CACHE) > _NOTE_CACHE_MAX:
        _PREVIEW_CACHE.popitem(last=False)
    return result


def note_display_title(note: dict) -> str:
    title = (note.get('title') or '').strip()
    if title:
        return title
    preview = note_content_preview(note)
    return preview[:28] if preview else tr('未命名备忘录')


def note_search_text(note: dict) -> str:
    """搜索匹配文本（带缓存）——搜索框每个按键都会对全部笔记调用一遍。"""
    key = _note_cache_key(note)
    hit = _SEARCH_TEXT_CACHE.get(key)
    if hit is not None:
        _SEARCH_TEXT_CACHE.move_to_end(key)
        return hit
    parts = [
        note.get('title', ''),
        note_content_preview(note),
        note.get('category', ''),
        note.get('archive_category', ''),
        note.get('created_at', ''),
        note.get('updated_at', ''),
        note.get('archived_at', ''),
    ]
    for att in iter_attachment_tree(note.get('attachments', []) or []):
        if att.get('deleted'):
            continue
        parts.extend([
            att.get('original_name', ''),
            att.get('category', ''),
            att.get('memo', ''),
            att.get('archive_content', ''),
            att.get('archive_category', ''),
            att.get('original_path', ''),
            att.get('stored_name', ''),
            att.get('added_at', ''),
            att.get('archived_at', ''),
        ])
    result = ' '.join(str(part) for part in parts if part).lower()
    _SEARCH_TEXT_CACHE[key] = result
    while len(_SEARCH_TEXT_CACHE) > _NOTE_CACHE_MAX:
        _SEARCH_TEXT_CACHE.popitem(last=False)
    return result


def iter_attachment_tree(attachments):
    for att in attachments or []:
        yield att
        yield from iter_attachment_tree(att.get('attachments', []) or [])


def note_belongs_to_screenshot_workspace(note):
    return (
        (note or {}).get('id') == SCREENSHOT_BOARD_ID
        or (note or {}).get('mode') == 'screenshot'
    )


def archive_item_key(item: dict) -> str:
    if not item:
        return ''
    if item.get('kind') == 'note':
        note = item.get('note') or {}
        return f"note:{note.get('id', '')}"
    att = item.get('attachment') or {}
    return f"attachment:{att.get('id', '')}"


def archive_item_search_text(item: dict) -> str:
    if not item:
        return ''
    note = item.get('note') or {}
    if item.get('kind') == 'note':
        return note_search_text(note)
    att = item.get('attachment') or {}
    parts = [
        item.get('time', ''),
        note_display_title(note),
        note.get('category', ''),
        note.get('archive_category', ''),
        att.get('original_name', ''),
        att.get('category', ''),
        att.get('memo', ''),
        att.get('archive_content', ''),
        att.get('archive_category', ''),
        att.get('original_path', ''),
        att.get('stored_name', ''),
    ]
    return ' '.join(str(part) for part in parts if part).lower()


def format_time_short(iso_time: str) -> str:
    if not iso_time:
        return ''
    try:
        dt = datetime.fromisoformat(iso_time)
    except Exception:
        return ''
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime('%H:%M')
    delta = (now.date() - dt.date()).days
    if delta == 1:
        return tr('昨天')
    if 0 < delta < 7:
        weekdays = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
        return tr(weekdays[dt.weekday()])
    if dt.year == now.year:
        return dt.strftime('%m月%d日')
    return dt.strftime('%Y/%m/%d')


def format_time_long(iso_time: str) -> str:
    if not iso_time:
        return ''
    try:
        dt = datetime.fromisoformat(iso_time)
        return dt.strftime('%Y年%m月%d日 %H:%M')
    except Exception:
        return ''


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:.1f} MB"
    return f"{size / 1024 ** 3:.2f} GB"


def recovery_scan_roots(scan_settings, drive_hints=None):
    """Roots for recovery scans.

    User configured roots are searched first, but cross-drive moves need the
    current local/removable drives too; otherwise a custom Desktop-only scope
    can never find a file that was cut to F:.
    """
    roots = []
    seen = set()

    def add(root):
        if not root:
            return
        root = str(root)
        key = os.path.normcase(os.path.normpath(root))
        if key in seen:
            return
        seen.add(key)
        roots.append(root)

    for root in (scan_settings or {}).get('scan_roots', []) or []:
        add(root)

    # 祖先包含的根去重：同时配置 C:\ 和 C:\Users\x 会把后者扫两遍，
    # 重复命中会让"唯一匹配才自动采纳"的判定失效
    pruned = []
    norm_roots = [os.path.normcase(os.path.normpath(r)) for r in roots]
    for i, root in enumerate(roots):
        covered = False
        for j, other in enumerate(norm_roots):
            if i == j:
                continue
            prefix = other.rstrip('\\/') + os.sep
            if norm_roots[i] != other and norm_roots[i].startswith(prefix):
                covered = True
                break
            if norm_roots[i] == other and j < i:
                covered = True
                break
        if not covered:
            pruned.append(root)
    roots = pruned
    seen = {os.path.normcase(os.path.normpath(r)) for r in roots}

    hint_letters = {
        str(h).rstrip(':\\/')
        .upper()
        for h in (drive_hints or [])
        if h
    }
    local_roots = ftrack.local_drive_roots(ntfs_only=False)

    # Same-volume moves are usually handled by File ID before scanning. For
    # hash fallback, prefer other drives first because they are the likely
    # target of a cut/paste from the original drive.
    for root in local_roots:
        letter = root.split(':', 1)[0].upper()
        if letter not in hint_letters:
            add(root)
    for root in local_roots:
        letter = root.split(':', 1)[0].upper()
        if letter in hint_letters:
            add(root)

    return roots or None


# ============ 开机启动 ============

def _current_data_root_for_autostart() -> Path:
    configured = os.getenv(DATA_ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return configured_data_root()


def _launch_argv_for_current_app(
    data_root: Path | str,
    executable: str | None = None,
    script_path: str | Path | None = None,
    frozen: bool | None = None,
):
    executable = executable or sys.executable
    if frozen is None:
        frozen = bool(getattr(sys, 'frozen', False))
    argv = [str(executable)]
    if not frozen:
        argv.append(str(Path(script_path).resolve() if script_path else Path(__file__).resolve()))
    argv.extend([DATA_ROOT_ARG, str(Path(data_root).expanduser())])
    return argv


def _format_windows_command(argv) -> str:
    return subprocess.list2cmdline([str(arg) for arg in argv])


def _autostart_command(data_root: Path | str | None = None) -> str:
    return _format_windows_command(
        _launch_argv_for_current_app(data_root or _current_data_root_for_autostart())
    )


def autostart_supported():
    return sys.platform.startswith('win')


def _read_autostart_command():
    if not autostart_supported():
        return ''
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_PATH, 0, winreg.KEY_QUERY_VALUE) as key:
            value, _kind = winreg.QueryValueEx(key, AUTOSTART_NAME)
            return str(value or '')
    except FileNotFoundError:
        return ''
    except Exception:
        logger.exception('读取开机启动设置失败')
        return ''


def is_autostart_enabled():
    return bool(_read_autostart_command())


def set_autostart(enable):
    if not autostart_supported():
        return False
    try:
        import winreg
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            AUTOSTART_REG_PATH,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            if enable:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        logger.exception('修改开机启动设置失败')
        return False


def refresh_autostart_if_needed():
    current = _read_autostart_command()
    if current and current != _autostart_command():
        set_autostart(True)


# ============ 备忘录列表自定义渲染 ============

LIST_SELECTED_BG = QColor(COLORS['selection_bg'])
LIST_HOVER_BG = QColor('#E8E8ED')
LIST_TITLE = QColor(COLORS['text_primary'])
LIST_SECONDARY = QColor(COLORS['text_secondary'])
LIST_TERTIARY = QColor(COLORS['text_tertiary'])
LIST_ACCENT = QColor(COLORS['accent'])
LIST_SELECTED_SECONDARY = QColor('#4F6F92')
LIST_BADGE_BG = QColor('#E6E6EB')
LIST_BADGE_FG = QColor('#5F636B')

class NoteListDelegate(QStyledItemDelegate):
    ITEM_HEIGHT = 72
    SIDE_MARGIN = 3
    PADDING = 12

    def sizeHint(self, option, index):
        return QSize(0, self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        note = index.data(Qt.UserRole)
        if not note:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(self.SIDE_MARGIN, 3, -self.SIDE_MARGIN, -3)

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setBrush(LIST_SELECTED_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
            c_title = LIST_ACCENT
            c_time = LIST_SELECTED_SECONDARY
            c_preview = LIST_SELECTED_SECONDARY
        elif hovered:
            painter.setBrush(LIST_HOVER_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
            c_title = LIST_TITLE
            c_time = LIST_SECONDARY
            c_preview = LIST_SECONDARY
        else:
            c_title = LIST_TITLE
            c_time = LIST_TERTIARY
            c_preview = LIST_SECONDARY

        title = note_display_title(note)
        time_str = format_time_short(note.get('updated_at', ''))
        preview = note_content_preview(note) or tr('没有附加文本')
        category = (note.get('archive_category') or note.get('category') or '').strip()
        if category:
            preview = f'#{category}  · {preview}'
        att_count = len([att for att in (note.get('attachments', []) or []) if not att.get('deleted')])
        pinned = bool(note.get('pinned'))

        # 附件 badge 宽度
        badge_w = 0
        if att_count > 0:
            bf = QFont(painter.font())
            bf.setPointSize(9)
            bf.setWeight(QFont.Bold)
            painter.setFont(bf)
            num_w = painter.fontMetrics().horizontalAdvance(str(att_count))
            badge_w = max(num_w + 12, 18)

        pin_w = 0
        pin_label = tr('置顶')
        if pinned:
            pf = QFont(painter.font())
            pf.setPointSize(8)
            pf.setWeight(QFont.DemiBold)
            painter.setFont(pf)
            pin_w = max(painter.fontMetrics().horizontalAdvance(pin_label) + 14, 34)

        # 标题
        title_font = QFont(painter.font())
        title_font.setPointSize(11)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(c_title)
        title_right_pad = self.PADDING
        if badge_w > 0:
            title_right_pad += badge_w + 6
        if pin_w > 0:
            title_right_pad += pin_w + 6
        title_rect = rect.adjusted(self.PADDING, 10, -title_right_pad, 0)
        title_rect.setHeight(20)
        elided_title = painter.fontMetrics().elidedText(title, Qt.ElideRight, title_rect.width())
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_title)

        # 附件 badge
        if att_count > 0:
            bf = QFont(painter.font())
            bf.setPointSize(9)
            bf.setWeight(QFont.Bold)
            painter.setFont(bf)
            badge_rect = QRectF(
                rect.right() - self.PADDING - badge_w,
                rect.top() + 12,
                badge_w, 16
            )
            if selected:
                painter.setBrush(QColor(0, 122, 255, 28))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(badge_rect, 8, 8)
                painter.setPen(LIST_ACCENT)
            else:
                painter.setBrush(LIST_BADGE_BG)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(badge_rect, 8, 8)
                painter.setPen(LIST_BADGE_FG)
            painter.drawText(badge_rect, Qt.AlignCenter, str(att_count))

        if pinned:
            pf = QFont(painter.font())
            pf.setPointSize(8)
            pf.setWeight(QFont.DemiBold)
            painter.setFont(pf)
            right_edge = rect.right() - self.PADDING - (badge_w + 6 if badge_w > 0 else 0)
            pin_rect = QRectF(right_edge - pin_w, rect.top() + 12, pin_w, 16)
            if selected:
                painter.setBrush(QColor('#FFF0BF'))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(pin_rect, 8, 8)
                painter.setPen(QColor('#7A5200'))
            else:
                painter.setBrush(QColor("#FFF2CC"))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(pin_rect, 8, 8)
                painter.setPen(QColor("#7A4F00"))
            painter.drawText(pin_rect, Qt.AlignCenter, pin_label)

        # 第二行
        info_font = QFont(painter.font())
        info_font.setPointSize(9)
        info_font.setWeight(QFont.Normal)
        painter.setFont(info_font)
        info_rect = rect.adjusted(self.PADDING, 32, -self.PADDING, 0)
        info_rect.setHeight(16)

        time_w = painter.fontMetrics().horizontalAdvance(time_str)
        painter.setPen(c_time)
        time_rect = QRectF(info_rect.left(), info_rect.top(), time_w, info_rect.height())
        painter.drawText(time_rect, Qt.AlignLeft | Qt.AlignVCenter, time_str)

        preview_x = info_rect.left() + time_w + 8
        preview_w = info_rect.right() - preview_x
        if preview_w > 10:
            preview_rect = QRectF(preview_x, info_rect.top(), preview_w, info_rect.height())
            painter.setPen(c_preview)
            elided_preview = painter.fontMetrics().elidedText(preview, Qt.ElideRight, int(preview_w))
            painter.drawText(preview_rect, Qt.AlignLeft | Qt.AlignVCenter, elided_preview)

        painter.restore()


class ScreenshotListDelegate(QStyledItemDelegate):
    ITEM_HEIGHT = 72
    SIDE_MARGIN = 3
    PADDING = 12

    def sizeHint(self, option, index):
        return QSize(0, self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        att = index.data(Qt.UserRole)
        if not att:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(self.SIDE_MARGIN, 3, -self.SIDE_MARGIN, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setBrush(LIST_SELECTED_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
            title_color = LIST_ACCENT
            sub_color = LIST_SELECTED_SECONDARY
        elif hovered:
            painter.setBrush(LIST_HOVER_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
            title_color = LIST_TITLE
            sub_color = LIST_SECONDARY
        else:
            title_color = LIST_TITLE
            sub_color = LIST_TERTIARY

        title = attachment_display_title(att)
        sub = format_time_short(att.get('archived_at') or att.get('added_at') or '')
        kind = attachment_kind_label(att)
        category = (att.get('archive_category') or att.get('category') or '').strip()
        if category:
            sub = f'{kind} · #{category}  · {sub}' if sub else f'{kind} · #{category}'
        elif sub:
            sub = f'{kind} · {sub}'
        else:
            sub = kind

        title_font = QFont(painter.font())
        title_font.setPointSize(11)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(title_color)
        title_rect = rect.adjusted(self.PADDING, 10, -self.PADDING, 0)
        title_rect.setHeight(20)
        painter.drawText(
            title_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(title, Qt.ElideRight, title_rect.width()),
        )

        sub_font = QFont(painter.font())
        sub_font.setPointSize(9)
        sub_font.setWeight(QFont.Normal)
        painter.setFont(sub_font)
        painter.setPen(sub_color)
        sub_rect = rect.adjusted(self.PADDING, 32, -self.PADDING, 0)
        sub_rect.setHeight(16)
        painter.drawText(
            sub_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(sub or tr('未归档'), Qt.ElideRight, sub_rect.width()),
        )
        painter.restore()


class ArchiveListDelegate(QStyledItemDelegate):
    ITEM_HEIGHT = 72
    SIDE_MARGIN = 3
    PADDING = 12

    def sizeHint(self, option, index):
        return QSize(0, self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        data = index.data(Qt.UserRole)
        if not data:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(self.SIDE_MARGIN, 3, -self.SIDE_MARGIN, -3)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setBrush(LIST_SELECTED_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
            title_color = LIST_ACCENT
            sub_color = LIST_SELECTED_SECONDARY
            badge_bg = QColor(0, 122, 255, 28)
            badge_fg = LIST_ACCENT
        elif hovered:
            painter.setBrush(LIST_HOVER_BG)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 10, 10)
            title_color = LIST_TITLE
            sub_color = LIST_SECONDARY
            badge_bg = LIST_BADGE_BG
            badge_fg = LIST_BADGE_FG
        else:
            title_color = LIST_TITLE
            sub_color = LIST_TERTIARY
            badge_bg = LIST_BADGE_BG
            badge_fg = LIST_BADGE_FG

        note = data.get('note') or {}
        att = data.get('attachment') or {}
        is_note = data.get('kind') == 'note'
        kind_label = tr('文字') if is_note else attachment_kind_label(att)
        if is_note:
            title = note_display_title(note)
            preview = note_content_preview(note) or tr('没有附加文本')
            category = (note.get('archive_category') or note.get('category') or '').strip()
        else:
            title = attachment_display_title(att)
            preview = tr('来自 {title}', title=note_display_title(note))
            category = (att.get('archive_category') or att.get('category') or '').strip()
        time_str = format_time_short(data.get('time') or '')
        if category:
            preview = f'#{category}  · {preview}'

        badge_font = QFont(painter.font())
        badge_font.setPointSize(8)
        badge_font.setWeight(QFont.DemiBold)
        painter.setFont(badge_font)
        badge_w = max(painter.fontMetrics().horizontalAdvance(kind_label) + 14, 34)
        badge_rect = QRectF(
            rect.right() - self.PADDING - badge_w,
            rect.top() + 12,
            badge_w,
            16,
        )
        painter.setBrush(badge_bg)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(badge_rect, 8, 8)
        painter.setPen(badge_fg)
        painter.drawText(badge_rect, Qt.AlignCenter, kind_label)

        title_font = QFont(painter.font())
        title_font.setPointSize(11)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(title_color)
        title_rect = rect.adjusted(self.PADDING, 10, -(self.PADDING + badge_w + 8), 0)
        title_rect.setHeight(20)
        painter.drawText(
            title_rect,
            Qt.AlignLeft | Qt.AlignVCenter,
            painter.fontMetrics().elidedText(title, Qt.ElideRight, title_rect.width()),
        )

        info_font = QFont(painter.font())
        info_font.setPointSize(9)
        info_font.setWeight(QFont.Normal)
        painter.setFont(info_font)
        painter.setPen(sub_color)
        info_rect = rect.adjusted(self.PADDING, 32, -self.PADDING, 0)
        info_rect.setHeight(16)

        time_w = painter.fontMetrics().horizontalAdvance(time_str)
        if time_w:
            time_rect = QRectF(info_rect.left(), info_rect.top(), time_w, info_rect.height())
            painter.drawText(time_rect, Qt.AlignLeft | Qt.AlignVCenter, time_str)
        preview_x = info_rect.left() + time_w + (8 if time_w else 0)
        preview_w = info_rect.right() - preview_x
        if preview_w > 10:
            preview_rect = QRectF(preview_x, info_rect.top(), preview_w, info_rect.height())
            painter.drawText(
                preview_rect,
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(preview, Qt.ElideRight, int(preview_w)),
            )

        painter.restore()


# ============ 截图模式相关 ============

# IMAGE_EXTS / is_image_attachment 统一从 storage 导入：
# 之前两边各写一份，None 防御已经分叉，将来加新后缀也只会改一处
SHELL_CREATE_MATCH_WINDOW_SECONDS = 180.0
SHELL_DELETE_RETRY_WINDOW_SECONDS = 180.0
AUTO_RECOVERY_COOLDOWN_SECONDS = 30.0
AUTO_RECOVERY_BACKOFF_SECONDS = (180.0, 600.0, 1800.0, 3600.0)
WINDOW_ACTIVATE_COOLDOWN_SECONDS = 8.0
CLIPBOARD_MOVE_MATCH_WINDOW_SECONDS = 180.0
DROPEFFECT_COPY = 1
DROPEFFECT_MOVE = 2


def _auto_recovery_backoff_seconds(fail_count):
    try:
        idx = max(0, int(fail_count or 1) - 1)
    except Exception:
        idx = 0
    return AUTO_RECOVERY_BACKOFF_SECONDS[min(idx, len(AUTO_RECOVERY_BACKOFF_SECONDS) - 1)]


def attachment_kind_label(att):
    if is_image_attachment(att):
        return tr('图片')
    if att.get('type') == 'folder':
        return tr('文件夹')
    return tr('文件')


def attachment_display_title(att):
    if att.get('type') in ('folder', 'file_ref'):
        return att.get('original_name') or att.get('archive_content') or att.get('memo') or attachment_kind_label(att)
    return att.get('archive_content') or att.get('memo') or att.get('original_name') or attachment_kind_label(att)


def build_folder_icon(size=36, dpr=None):
    height = max(size, int(size * 44 / 36))
    if dpr is None:
        dpr = _screen_dpr()
    # 先按 dpr 放大画布并打标记再开 QPainter：painter 自动落在逻辑坐标系，
    # 下面的绘制代码保持逻辑尺寸不变，高分屏不再发虚
    pix = QPixmap(int(size * dpr), int(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)

    back_color = QColor("#3F8FE0")
    front_color = QColor("#5AC8FA")
    sx = size / 36
    sy = height / 44

    painter.setBrush(back_color)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(2 * sx, 12 * sy, 32 * sx, 28 * sy), 3 * sx, 3 * sy)
    painter.drawRoundedRect(QRectF(2 * sx, 8 * sy, 16 * sx, 8 * sy), 2 * sx, 2 * sy)

    painter.setBrush(front_color)
    painter.drawRoundedRect(QRectF(2 * sx, 16 * sy, 32 * sx, 24 * sy), 3 * sx, 3 * sy)

    painter.setBrush(QColor(255, 255, 255, 50))
    painter.drawRoundedRect(QRectF(2 * sx, 16 * sy, 32 * sx, 5 * sy), 3 * sx, 3 * sy)
    painter.end()
    return pix


def build_file_icon(path, size=36, colors=None, dpr=None):
    height = max(size, int(size * 44 / 36))
    ext = Path(path).suffix.lower()
    color = QColor((colors or {}).get(ext, '#8E8E93'))

    if dpr is None:
        dpr = _screen_dpr()
    pix = QPixmap(int(size * dpr), int(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)

    sx = size / 36
    sy = height / 44
    painter.setBrush(color)
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(QRectF(0, 0, size, height), 6 * sx, 6 * sy)

    painter.setBrush(QColor(255, 255, 255, 60))
    poly = QPolygonF([QPointF(size - 10 * sx, 0), QPointF(size, 10 * sy), QPointF(size - 10 * sx, 10 * sy)])
    painter.drawPolygon(poly)

    label = ext.lstrip('.').upper() if ext else 'FILE'
    if len(label) > 4:
        label = label[:4]
    painter.setPen(QColor("#FFFFFF"))
    font = QFont(painter.font())
    font.setPointSize(max(8, int(size * 0.22)))
    font.setWeight(QFont.Bold)
    painter.setFont(font)
    painter.drawText(QRectF(0, 8 * sy, size, height - 8 * sy), Qt.AlignCenter, label)
    painter.end()
    return pix


def scale_icon_to_box(pix, box_w, box_h):
    """把图标等比缩进 box_w×box_h 逻辑尺寸的盒子。

    QPixmap.scaled 的目标尺寸是设备像素且结果沿用源 dpr 标记，直接
    .scaled(16,16) 会把高分屏图标缩成 16 设备像素（≈10.7 逻辑像素）显示变小。
    """
    dpr = pix.devicePixelRatio() or 1.0
    return pix.scaled(
        max(1, int(box_w * dpr)), max(1, int(box_h * dpr)),
        Qt.KeepAspectRatio, Qt.SmoothTransformation,
    )


def clipboard_drop_effect(mime):
    """Return Windows DROPEFFECT flags from Explorer clipboard data when present."""
    try:
        formats = mime.formats()
    except Exception:
        return 0
    for fmt in formats:
        if 'Preferred DropEffect' not in fmt:
            continue
        try:
            data = bytes(mime.data(fmt))
        except Exception:
            continue
        if len(data) >= 4:
            return int.from_bytes(data[:4], byteorder='little', signed=False)
    return 0


def grab_clipboard_image_path():
    """如果剪贴板里是图片,保存为临时 PNG 并返回路径,否则返回 None"""
    clipboard = QApplication.clipboard()
    mime = clipboard.mimeData()
    if not mime.hasImage():
        return None
    img = mime.imageData()
    if isinstance(img, QPixmap):
        img = img.toImage()
    if not isinstance(img, QImage) or img.isNull():
        return None
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    tmp_dir = Path(tempfile.gettempdir())
    tmp = tmp_dir / f'截图_{ts}.png'
    idx = 1
    while tmp.exists():
        tmp = tmp_dir / f'截图_{ts}_{idx}.png'
        idx += 1
    if img.save(str(tmp), 'PNG'):
        return str(tmp)
    return None


def save_temp_screenshot_image(image):
    if isinstance(image, QPixmap):
        image = image.toImage()
    if not isinstance(image, QImage) or image.isNull():
        return None
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    tmp_dir = Path(tempfile.gettempdir())
    tmp = tmp_dir / f'截图_{ts}.png'
    idx = 1
    while tmp.exists():
        tmp = tmp_dir / f'截图_{ts}_{idx}.png'
        idx += 1
    if image.save(str(tmp), 'PNG'):
        return str(tmp)
    return None


def grab_virtual_desktop_pixmap():
    screens = QGuiApplication.screens()
    if not screens:
        return None, QRect()
    virtual = screens[0].geometry()
    for screen in screens[1:]:
        virtual = virtual.united(screen.geometry())
    if virtual.isEmpty():
        return None, QRect()

    scale_x = 1.0
    scale_y = 1.0
    probe = None
    for screen in screens:
        pix = screen.grabWindow(0)
        if not pix.isNull():
            probe = (screen, pix)
            break
    if probe:
        screen, pix = probe
        geo = screen.geometry()
        if geo.width() > 0 and geo.height() > 0:
            scale_x = max(1.0, pix.width() / geo.width())
            scale_y = max(1.0, pix.height() / geo.height())

    canvas = QPixmap(
        max(1, int(round(virtual.width() * scale_x))),
        max(1, int(round(virtual.height() * scale_y))),
    )
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    for screen in screens:
        if probe and screen is probe[0]:
            pix = probe[1]
        else:
            pix = screen.grabWindow(0)
        if pix.isNull():
            continue
        geo = screen.geometry()
        target = QRect(
            int(round((geo.left() - virtual.left()) * scale_x)),
            int(round((geo.top() - virtual.top()) * scale_y)),
            max(1, int(round(geo.width() * scale_x))),
            max(1, int(round(geo.height() * scale_y))),
        )
        painter.drawPixmap(target, pix)
    painter.end()
    return canvas, virtual


class RegionCaptureOverlay(QDialog):
    def __init__(self, pixmap, virtual_geometry, parent=None):
        super().__init__(parent)
        self.pixmap = pixmap
        self.virtual_geometry = virtual_geometry
        self.origin = QPoint()
        self.current = QPoint()
        self.selection = QRect()
        self.result_path = None
        self.setWindowTitle('框选截图')
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(virtual_geometry)
        self.setMinimumSize(1, 1)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.pixmap and not self.pixmap.isNull():
            painter.drawPixmap(self.rect(), self.pixmap)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 96))

        if self.selection.isValid() and self.selection.width() > 1 and self.selection.height() > 1:
            sel = self.selection.normalized().intersected(self.rect())
            if self.pixmap and not self.pixmap.isNull():
                sx = self.pixmap.width() / max(1, self.width())
                sy = self.pixmap.height() / max(1, self.height())
                source = QRect(
                    int(sel.x() * sx),
                    int(sel.y() * sy),
                    max(1, int(sel.width() * sx)),
                    max(1, int(sel.height() * sy)),
                )
                # 三参重载直接从源 pixmap 取区域绘制，避免拖拽期间每帧 copy 大图
                painter.drawPixmap(sel, self.pixmap, source)
            painter.setPen(QPen(QColor('#FFFFFF'), 2))
            painter.drawRect(sel.adjusted(0, 0, -1, -1))
        else:
            painter.setPen(QColor(255, 255, 255, 230))
            painter.drawText(self.rect(), Qt.AlignCenter, tr('请拖拽选择要保存的区域。按 Esc 取消。'))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.origin = event.position().toPoint()
        self.current = self.origin
        self.selection = QRect(self.origin, self.current)
        self.update()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        self.current = event.position().toPoint()
        self.selection = QRect(self.origin, self.current).normalized()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        self.current = event.position().toPoint()
        self.selection = QRect(self.origin, self.current).normalized().intersected(self.rect())
        if self.selection.width() < 8 or self.selection.height() < 8:
            self.reject()
            return
        self.result_path = self._save_selection()
        if self.result_path:
            self.accept()
        else:
            self.reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def _save_selection(self):
        if not self.pixmap or self.pixmap.isNull() or self.selection.isEmpty():
            return None
        sx = self.pixmap.width() / max(1, self.width())
        sy = self.pixmap.height() / max(1, self.height())
        source = QRect(
            int(self.selection.x() * sx),
            int(self.selection.y() * sy),
            max(1, int(self.selection.width() * sx)),
            max(1, int(self.selection.height() * sy)),
        ).intersected(QRect(QPoint(0, 0), self.pixmap.size()))
        if source.isEmpty():
            return None
        return save_temp_screenshot_image(self.pixmap.copy(source))


class ModeSwitch(QWidget):
    """文字 / 截图 模式切换"""
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('mode_switch')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._mode = 'text'
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.text_btn = QPushButton('文字')
        self.text_btn.setObjectName('mode_btn_left')
        self.text_btn.setCheckable(True)
        self.text_btn.setChecked(True)
        self.text_btn.setCursor(Qt.PointingHandCursor)
        self.text_btn.setFocusPolicy(Qt.NoFocus)

        self.shot_btn = QPushButton('截图')
        self.shot_btn.setObjectName('mode_btn_right')
        self.shot_btn.setCheckable(True)
        self.shot_btn.setCursor(Qt.PointingHandCursor)
        self.shot_btn.setFocusPolicy(Qt.NoFocus)

        layout.addWidget(self.text_btn, 1)
        layout.addWidget(self.shot_btn, 1)

        self.text_btn.clicked.connect(lambda: self._click('text'))
        self.shot_btn.clicked.connect(lambda: self._click('screenshot'))

    def _click(self, mode):
        if mode == self.current_mode():
            # 重复点击当前已选模式：只复位按钮态，不触发整条刷新链
            self.set_mode(mode, emit=False)
            return
        self.set_mode(mode, emit=True)

    def set_mode(self, mode, emit=False):
        mode = 'screenshot' if mode == 'screenshot' else 'text'
        self._mode = mode
        self.text_btn.blockSignals(True)
        self.shot_btn.blockSignals(True)
        self.text_btn.setChecked(mode == 'text')
        self.shot_btn.setChecked(mode == 'screenshot')
        self.text_btn.blockSignals(False)
        self.shot_btn.blockSignals(False)
        if emit:
            self.changed.emit(mode)

    def current_mode(self):
        return self._mode


class ViewSwitch(QWidget):
    """活跃 / 归档 视图切换"""
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('view_switch')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._view = 'active'
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.active_btn = QPushButton('活跃')
        self.active_btn.setObjectName('view_btn_left')
        self.active_btn.setCheckable(True)
        self.active_btn.setChecked(True)
        self.active_btn.setCursor(Qt.PointingHandCursor)
        self.active_btn.setFocusPolicy(Qt.NoFocus)

        self.archived_btn = QPushButton('归档')
        self.archived_btn.setObjectName('view_btn_right')
        self.archived_btn.setCheckable(True)
        self.archived_btn.setCursor(Qt.PointingHandCursor)
        self.archived_btn.setFocusPolicy(Qt.NoFocus)

        layout.addWidget(self.active_btn, 1)
        layout.addWidget(self.archived_btn, 1)

        self.active_btn.clicked.connect(lambda: self._click('active'))
        self.archived_btn.clicked.connect(lambda: self._click('archived'))

    def _click(self, view):
        if view == self.current_view():
            self.set_view(view, emit=False)
            return
        self.set_view(view, emit=True)

    def set_view(self, view, emit=False):
        view = 'archived' if view == 'archived' else 'active'
        self._view = view
        self.active_btn.blockSignals(True)
        self.archived_btn.blockSignals(True)
        self.active_btn.setChecked(view == 'active')
        self.archived_btn.setChecked(view == 'archived')
        self.active_btn.blockSignals(False)
        self.archived_btn.blockSignals(False)
        if emit:
            self.changed.emit(view)

    def set_counts(self, active_count, archived_count):
        self.active_btn.setText(f'活跃  ·  {active_count}')
        self.archived_btn.setText(f'归档  ·  {archived_count}')

    def current_view(self):
        return self._view


class TextFormatSwitch(QWidget):
    """富文本 / Markdown 格式切换"""
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('text_format_switch')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._format = 'rich'
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.rich_btn = QPushButton('富文本')
        self.rich_btn.setObjectName('mode_btn_left')
        self.rich_btn.setCheckable(True)
        self.rich_btn.setChecked(True)
        self.rich_btn.setCursor(Qt.PointingHandCursor)
        self.rich_btn.setFocusPolicy(Qt.NoFocus)

        self.markdown_btn = QPushButton('Markdown')
        self.markdown_btn.setObjectName('mode_btn_right')
        self.markdown_btn.setCheckable(True)
        self.markdown_btn.setCursor(Qt.PointingHandCursor)
        self.markdown_btn.setFocusPolicy(Qt.NoFocus)

        layout.addWidget(self.rich_btn)
        layout.addWidget(self.markdown_btn)

        self.rich_btn.clicked.connect(lambda: self._click('rich'))
        self.markdown_btn.clicked.connect(lambda: self._click('markdown'))

    def _click(self, fmt):
        if fmt == self.current_format():
            self.set_format(fmt, emit=False)
            return
        self.set_format(fmt, emit=True)

    def set_format(self, fmt, emit=False):
        fmt = 'markdown' if fmt == 'markdown' else 'rich'
        self._format = fmt
        self.rich_btn.blockSignals(True)
        self.markdown_btn.blockSignals(True)
        self.rich_btn.setChecked(fmt == 'rich')
        self.markdown_btn.setChecked(fmt == 'markdown')
        self.rich_btn.blockSignals(False)
        self.markdown_btn.blockSignals(False)
        if emit:
            self.changed.emit(fmt)

    def current_format(self):
        return self._format


class DropHintCard(QFrame):
    def __init__(self, title='', subtitle=''):
        super().__init__()
        self.setObjectName('drop_hint_card')
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setMinimumSize(246, 204)
        self.setMaximumSize(246, 204)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 26, 18, 22)
        layout.setSpacing(10)
        layout.addStretch()

        icon = QLabel('▤')
        icon.setObjectName('drop_hint_icon')
        icon.setAlignment(Qt.AlignCenter)

        title_label = QLabel(title or '点击“新建”或拖拽文件到此处')
        title_label.setObjectName('drop_hint_title')
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setWordWrap(True)

        subtitle_label = QLabel(subtitle or '支持 .txt .md 等文本文件')
        subtitle_label.setObjectName('drop_hint_subtitle')
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setWordWrap(True)

        layout.addWidget(icon, 0, Qt.AlignCenter)
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addStretch()


class ScreenshotThumbnail(QFrame):
    selected_requested = Signal(str)
    delete_requested = Signal(str)
    open_requested = Signal(str)
    archive_toggled = Signal(str)
    memo_changed = Signal(str, str)
    child_delete_requested = Signal(str)
    child_open_requested = Signal(str)
    child_category_change_requested = Signal(str)
    child_file_dropped = Signal(str, str)
    add_child_requested = Signal(str)

    THUMB_W = 220
    THUMB_H = 150
    # QSS 里 #screenshot_thumb 各状态 border+padding 每侧恒为 2px，
    # 子控件必须按内容区宽度排，否则会盖住卡片边框（选中态右侧描边消失）
    CONTENT_W = THUMB_W - 4
    CHILD_ROW_H = 42
    CARD_H = THUMB_H + CHILD_ROW_H + 38

    def __init__(self, attachment, file_path, path_resolver=None):
        super().__init__()
        self.attachment = attachment
        self.file_path = Path(file_path)
        self.path_resolver = path_resolver
        self.is_archived = bool(attachment.get('archived', False))
        self.is_image = is_image_attachment(attachment)
        self.setObjectName('screenshot_thumb')
        self.setProperty('archived', self.is_archived)
        self.setProperty('selected', False)
        self.setFixedSize(self.THUMB_W, self.CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.setToolTip(tr('{name}\n双击打开 · 右键更多', name=attachment['original_name']))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.image_label = QLabel()
        self.image_label.setObjectName('thumb_image')
        self.image_label.setFixedSize(self.CONTENT_W, self.THUMB_H)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setPixmap(self._build_thumbnail())

        # 右上角完成按钮 (浮在图片上)
        self.check_btn = QPushButton('✓', self.image_label)
        self.check_btn.setObjectName('thumb_check')
        self.check_btn.setProperty('done', self.is_archived)
        self.check_btn.setFixedSize(28, 28)
        self.check_btn.move(self.CONTENT_W - 36, 8)
        self.check_btn.setCursor(Qt.PointingHandCursor)
        self.check_btn.setFocusPolicy(Qt.NoFocus)
        self.check_btn.setAttribute(Qt.WA_NoMousePropagation, True)
        self.check_btn.setToolTip('已归档 · 点击取消' if self.is_archived else '归档这个项目')
        self.check_btn.clicked.connect(lambda: self.archive_toggled.emit(self.attachment['id']))

        self.add_child_btn = QPushButton('+', self.image_label)
        self.add_child_btn.setObjectName('thumb_add_attachment')
        self.add_child_btn.setFixedSize(24, 24)
        self.add_child_btn.move(self.CONTENT_W - 66, 10)
        self.add_child_btn.setCursor(Qt.PointingHandCursor)
        self.add_child_btn.setFocusPolicy(Qt.NoFocus)
        self.add_child_btn.setAttribute(Qt.WA_NoMousePropagation, True)
        self.add_child_btn.setToolTip('给这张截图添加文件或文件夹')
        self.add_child_btn.clicked.connect(lambda: self.add_child_requested.emit(self.attachment['id']))

        self.memo_input = QLineEdit()
        self.memo_input.setObjectName('thumb_memo')
        self.memo_input.setPlaceholderText('备注…')
        self.memo_input.setText(attachment.get('memo', '') or '')
        self.memo_input.editingFinished.connect(self._on_memo_committed)

        layout.addWidget(self.image_label)
        layout.addLayout(self._build_child_row())
        layout.addWidget(self.memo_input)

    def set_selected(self, selected):
        self.setProperty('selected', bool(selected))
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _active_child_attachments(self):
        return [
            child for child in (self.attachment.get('attachments', []) or [])
            if not child.get('deleted')
        ]

    def _build_child_row(self):
        row = QHBoxLayout()
        row.setContentsMargins(12, 5, 12, 5)
        row.setSpacing(6)
        children = self._active_child_attachments()
        if not children:
            empty = QLabel('附件')
            empty.setObjectName('thumb_attachment_empty')
            row.addWidget(empty)
            row.addStretch()
            return row
        visible_count = 2 if len(children) > 3 else 3
        for child in children[:visible_count]:
            chip = ScreenshotChildAttachmentChip(child, self._child_path(child))
            chip.open_requested.connect(self.child_open_requested.emit)
            chip.delete_requested.connect(self.child_delete_requested.emit)
            chip.category_change_requested.connect(self.child_category_change_requested.emit)
            row.addWidget(chip)
        if len(children) > visible_count:
            more_text = f'+{len(children) - visible_count}'
            more = QLabel(more_text)
            more.setObjectName('thumb_attachment_more')
            more.setAlignment(Qt.AlignCenter)
            more.setFixedHeight(30)
            more.setMinimumWidth(max(32, QFontMetrics(more.font()).horizontalAdvance(more_text) + 18))
            row.addWidget(more)
        row.addStretch()
        return row

    def _child_path(self, child):
        if self.path_resolver:
            return self.path_resolver(child)
        return Path(child.get('original_path', ''))

    def _build_thumbnail(self):
        if not self.is_image:
            return self._build_attachment_thumbnail()
        if not self.file_path.exists():
            return self._build_placeholder(tr('图片不存在'))
        pixmap = load_scaled_pixmap(self.file_path, self.CONTENT_W, self.THUMB_H)
        if pixmap is None:
            return self._build_placeholder(tr('无法加载'))
        return pixmap

    def _build_placeholder(self, text):
        dpr = _screen_dpr()
        pix = QPixmap(int(self.CONTENT_W * dpr), int(self.THUMB_H * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(QColor("#F5F5F7"))
        painter = QPainter(pix)
        painter.setPen(QColor("#8B98AA"))
        painter.drawText(QRect(0, 0, self.CONTENT_W, self.THUMB_H), Qt.AlignCenter, text)
        painter.end()
        return pix

    def _build_attachment_thumbnail(self):
        dpr = _screen_dpr()
        pix = QPixmap(int(self.CONTENT_W * dpr), int(self.THUMB_H * dpr))
        pix.setDevicePixelRatio(dpr)
        pix.fill(QColor("#F5F5F7"))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if self.attachment.get('type') == 'folder':
            icon = build_folder_icon(46)
        else:
            icon = build_file_icon(self.file_path, 46, AttachmentCard.EXT_COLORS)
        icon_w = int(icon.width() / (icon.devicePixelRatio() or 1.0))
        icon_h = int(icon.height() / (icon.devicePixelRatio() or 1.0))
        icon_rect = QRect((self.CONTENT_W - icon_w) // 2, 36, icon_w, icon_h)
        painter.drawPixmap(icon_rect, icon)

        name = self.attachment.get('original_name', '') or attachment_kind_label(self.attachment)
        font = QFont(painter.font())
        font.setPointSize(10)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#263548"))
        text_rect = QRect(18, 98, self.CONTENT_W - 36, 20)
        painter.drawText(
            text_rect,
            Qt.AlignCenter,
            painter.fontMetrics().elidedText(name, Qt.ElideMiddle, text_rect.width()),
        )

        sub_font = QFont(painter.font())
        sub_font.setPointSize(9)
        sub_font.setWeight(QFont.Normal)
        painter.setFont(sub_font)
        painter.setPen(QColor("#8B98AA"))
        sub = attachment_kind_label(self.attachment)
        if self.attachment.get('type') == 'file_ref':
            sub = format_size(self.attachment.get('size', 0))
        painter.drawText(QRect(18, 120, self.CONTENT_W - 36, 18), Qt.AlignCenter, sub)
        painter.end()
        return pix

    def _on_memo_committed(self):
        text = self.memo_input.text().strip()
        if text != (self.attachment.get('memo', '') or ''):
            self.memo_changed.emit(self.attachment['id'], text)

    def mouseDoubleClickEvent(self, event):
        # 双击在备注输入框上不触发 (因为 LineEdit 自己消费事件)
        # 双击在图片或边缘触发
        self.open_requested.emit(self.attachment['id'])
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected_requested.emit(self.attachment['id'])
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        view = menu.addAction('查看大图' if self.is_image else '打开')
        add_child = menu.addAction('给这张截图添加文件或文件夹...')
        toggle = menu.addAction('取消归档' if self.is_archived else '归档')
        menu.addSeparator()
        save = menu.addAction('保存为...') if self.is_image else None
        reveal = menu.addAction('在文件夹中显示')
        menu.addSeparator()
        delete = menu.addAction('从备忘录中移除')
        action = menu.exec(event.globalPos())
        if action == view:
            self.open_requested.emit(self.attachment['id'])
        elif action == add_child:
            self.add_child_requested.emit(self.attachment['id'])
        elif action == toggle:
            self.archive_toggled.emit(self.attachment['id'])
        elif save is not None and action == save:
            self._save_as()
        elif action == reveal:
            self._reveal()
        elif action == delete:
            self.delete_requested.emit(self.attachment['id'])

    def _save_as(self):
        if not self.file_path.exists():
            QMessageBox.warning(self, '文件不存在', '原始图片已不存在。')
            return
        suggested = self.attachment.get('original_name', 'image.png')
        target, _ = QFileDialog.getSaveFileName(self, '保存为', suggested)
        if target:
            try:
                shutil.copy2(self.file_path, target)
            except Exception as e:
                QMessageBox.critical(self, '保存失败', str(e))

    def _reveal(self):
        if not self.file_path.exists() or not reveal_in_file_manager(self.file_path):
            QMessageBox.warning(
                self, '无法定位',
                tr('文件已被移动或删除，无法在资源管理器中显示：\n{path}',
                   path=str(self.file_path)))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.child_file_dropped.emit(self.attachment['id'], url.toLocalFile())
            event.acceptProposedAction()


class ScreenshotChildAttachmentChip(QFrame):
    open_requested = Signal(str)
    delete_requested = Signal(str)
    category_change_requested = Signal(str)

    def __init__(self, attachment, file_path):
        super().__init__()
        self.attachment = attachment
        self.file_path = Path(file_path)
        self.setObjectName('thumb_attachment_chip')
        self.setProperty('categorized', bool((attachment.get('archive_category') or attachment.get('category') or '').strip()))
        self.setFixedSize(60, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_NoMousePropagation, True)
        category = (attachment.get('archive_category') or attachment.get('category') or '').strip()
        tooltip = tr('{name}\n双击打开 · 右键更多', name=attachment.get('original_name', ''))
        if category:
            tooltip = f'{tooltip}\n#{category}'
        self.setToolTip(tooltip)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        icon = QLabel()
        icon.setObjectName('thumb_attachment_icon')
        icon.setFixedSize(16, 16)
        icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if is_image_attachment(attachment) and self.file_path.exists():
            # 之前整图解码只为做 16x16 图标
            pixmap = load_scaled_pixmap(self.file_path, 16, 16)
            if pixmap is not None:
                icon.setPixmap(pixmap)
            else:
                icon.setPixmap(scale_icon_to_box(build_file_icon(file_path, 16, AttachmentCard.EXT_COLORS), 16, 16))
        elif attachment.get('type') == 'folder':
            icon.setPixmap(scale_icon_to_box(build_folder_icon(16), 16, 16))
        else:
            icon.setPixmap(scale_icon_to_box(build_file_icon(file_path, 16, AttachmentCard.EXT_COLORS), 16, 16))

        name_text = f'#{category}' if category else (attachment.get('original_name', '') or attachment_kind_label(attachment))
        name = QLabel()
        name.setObjectName('thumb_attachment_name')
        name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        name.setFixedWidth(28)
        name.setText(QFontMetrics(name.font()).elidedText(name_text, Qt.ElideRight, 28))

        layout.addWidget(icon)
        layout.addWidget(name, 1)

    def mouseDoubleClickEvent(self, event):
        self.open_requested.emit(self.attachment.get('id', ''))
        event.accept()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = menu.addAction('打开')
        category_action = menu.addAction(tr('修改分类'))
        delete_action = menu.addAction('从当前截图中移除')
        action = menu.exec(event.globalPos())
        if action == open_action:
            self.open_requested.emit(self.attachment.get('id', ''))
        elif action == category_action:
            self.category_change_requested.emit(self.attachment.get('id', ''))
        elif action == delete_action:
            self.delete_requested.emit(self.attachment.get('id', ''))


class ScreenshotGridCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName('screenshot_grid_inner')
        # 自定义 QWidget 子类默认不画 QSS 背景，必须显式启用
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._empty_art = True

    def set_empty_art(self, empty):
        empty = bool(empty)
        if self._empty_art != empty:
            self._empty_art = empty
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect()
        path = QPainterPath()
        path.moveTo(rect.left(), rect.bottom() - 52)
        path.cubicTo(
            rect.left() + rect.width() * 0.35,
            rect.bottom() + 10,
            rect.left() + rect.width() * 0.66,
            rect.bottom() - 76,
            rect.right(),
            rect.top() + rect.height() * 0.58,
        )
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        painter.fillPath(path, QColor(235, 242, 255, 132))

        if self._empty_art:
            painter.setPen(QPen(QColor(205, 218, 242, 90), 4))
            painter.setBrush(Qt.NoBrush)
            paper = QRectF(rect.right() - 132, rect.bottom() - 110, 58, 72)
            painter.drawRoundedRect(paper, 8, 8)
            painter.setPen(QPen(QColor(205, 218, 242, 84), 3))
            for i in range(3):
                y = paper.top() + 20 + i * 14
                painter.drawLine(QPointF(paper.left() + 16, y), QPointF(paper.right() - 12, y))
            painter.setPen(QPen(QColor(205, 218, 242, 100), 6))
            painter.drawLine(QPointF(paper.right() - 2, paper.bottom() - 8), QPointF(paper.right() + 24, paper.bottom() - 38))
        painter.end()


class ScreenshotGrid(QScrollArea):
    selected_requested = Signal(str)
    file_dropped = Signal(str)
    image_pasted = Signal(str)
    child_file_dropped = Signal(str, str)
    add_child_requested = Signal(str)
    delete_requested = Signal(str)
    open_requested = Signal(str)
    category_change_requested = Signal(str)
    archive_toggled = Signal(str)
    memo_changed = Signal(str, str)

    THUMB_SPACING = 16
    PADDING = 20

    def __init__(self):
        super().__init__()
        self.setObjectName('screenshot_grid')
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.container = ScreenshotGridCanvas()
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(self.PADDING, self.PADDING, self.PADDING, self.PADDING)
        self.grid.setSpacing(self.THUMB_SPACING)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.empty_label = DropHintCard(
            '点击“新建记事”或拖拽文件到此处',
            '支持图片、文件和文件夹'
        )

        self.setWidget(self.container)

        self._thumbnails = []
        self._current_images = []
        self._current_resolver = None
        self._current_cols = 0
        self._selected_id = ''

    def set_attachments(self, attachments, path_resolver, selected_id=''):
        self._current_images = [att for att in (attachments or []) if is_image_attachment(att)]
        self._current_resolver = path_resolver
        self._current_cols = 0
        self._selected_id = selected_id or ''
        if self._selected_id and not any(att.get('id') == self._selected_id for att in self._current_images):
            self._selected_id = ''
        self._render()

    def current_attachment_id(self):
        return self._selected_id

    def set_selected_attachment(self, attachment_id):
        self._selected_id = attachment_id or ''
        for thumb in self._thumbnails:
            thumb.set_selected(thumb.attachment.get('id') == self._selected_id)

    def _cols(self):
        avail = max(1, self.viewport().width() - 2 * self.PADDING)
        cell = ScreenshotThumbnail.THUMB_W + self.THUMB_SPACING
        return max(1, (avail + self.THUMB_SPACING) // cell)

    def _render(self):
        # 注意：对“当前可见”的子 widget 调用 setParent(None) 会让它瞬间变成
        # 一个可见的顶层窗口（标题回退为应用名），直到 deleteLater 在下一轮事件
        # 循环真正销毁它——表现为屏幕上不停闪窗。所以 reparent 前必须先 hide()。
        for w in self._thumbnails:
            w.hide()
            w.setParent(None)
            w.deleteLater()
        self._thumbnails = []
        self.empty_label.hide()
        self.empty_label.setParent(None)

        while self.grid.count() > 0:
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().setParent(None)

        if not self._current_images:
            self._selected_id = ''
            self.container.set_empty_art(True)
            self.grid.addWidget(self.empty_label, 0, 0, 1, 1)
            self.empty_label.show()
            self._current_cols = 1
            return

        self.container.set_empty_art(False)
        cols = self._cols()
        self._current_cols = cols
        for i, att in enumerate(self._current_images):
            row, col = divmod(i, cols)
            path = self._current_resolver(att) if self._current_resolver else Path('')
            thumb = ScreenshotThumbnail(att, path, self._current_resolver)
            thumb.set_selected(att.get('id') == self._selected_id)
            thumb.selected_requested.connect(self._on_thumb_selected)
            thumb.delete_requested.connect(self.delete_requested.emit)
            thumb.open_requested.connect(self.open_requested.emit)
            thumb.archive_toggled.connect(self.archive_toggled.emit)
            thumb.memo_changed.connect(self.memo_changed.emit)
            thumb.child_delete_requested.connect(self.delete_requested.emit)
            thumb.child_open_requested.connect(self.open_requested.emit)
            thumb.child_category_change_requested.connect(self.category_change_requested.emit)
            thumb.child_file_dropped.connect(self.child_file_dropped.emit)
            thumb.add_child_requested.connect(self.add_child_requested.emit)
            self.grid.addWidget(thumb, row, col, Qt.AlignTop | Qt.AlignLeft)
            self._thumbnails.append(thumb)

    def _on_thumb_selected(self, attachment_id):
        self.set_selected_attachment(attachment_id)
        self.selected_requested.emit(attachment_id)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_images and self._cols() != self._current_cols:
            # 跨列时只重新排版现有缩略图，不销毁重建（重建要重新解码全部图片）
            self._relayout()

    def _relayout(self):
        cols = self._cols()
        self._current_cols = cols
        while self.grid.count() > 0:
            self.grid.takeAt(0)
        for i, thumb in enumerate(self._thumbnails):
            row, col = divmod(i, cols)
            self.grid.addWidget(thumb, row, col, Qt.AlignTop | Qt.AlignLeft)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasImage():
            event.acceptProposedAction()

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime.hasImage() and not mime.hasUrls():
            img = mime.imageData()
            if isinstance(img, QPixmap):
                img = img.toImage()
            if isinstance(img, QImage) and not img.isNull():
                ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                tmp = Path(tempfile.gettempdir()) / f'截图_{ts}.png'
                idx = 1
                while tmp.exists():
                    tmp = Path(tempfile.gettempdir()) / f'截图_{ts}_{idx}.png'
                    idx += 1
                if img.save(str(tmp), 'PNG'):
                    self.image_pasted.emit(str(tmp))
            event.acceptProposedAction()
            return
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    self.file_dropped.emit(url.toLocalFile())
            event.acceptProposedAction()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            path = grab_clipboard_image_path()
            if path:
                self.image_pasted.emit(path)
                return
            mime = QApplication.clipboard().mimeData()
            if mime.hasUrls():
                for url in mime.urls():
                    if url.isLocalFile():
                        self.file_dropped.emit(url.toLocalFile())
                return
        super().keyPressEvent(event)


class ImageViewerDialog(QDialog):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(Path(file_path).name)
        self.resize(960, 680)
        # 带选择器只作用于对话框本身——无选择器的内联样式会级联到所有
        # 子控件，把 styles.py 里查看器工具栏按钮的样式整个压掉
        self.setObjectName('image_viewer_dialog')
        self.setStyleSheet('QDialog#image_viewer_dialog { background: #1D1D1F; }')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.scene = QGraphicsScene(self)
        self.pixmap = QPixmap(str(file_path))
        self.pixmap_item = None
        if not self.pixmap.isNull():
            self.pixmap_item = QGraphicsPixmapItem(self.pixmap)
            self.pixmap_item.setTransformationMode(Qt.FastTransformation)
            self.scene.addItem(self.pixmap_item)
        else:
            text = self.scene.addText(tr('无法加载图片'))
            text.setDefaultTextColor(QColor('#FFFFFF'))

        self.view = QGraphicsView(self.scene, self)
        self.view.setRenderHint(QPainter.Antialiasing, False)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setBackgroundBrush(QColor("#1D1D1F"))
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.viewport().installEventFilter(self)

        layout.addWidget(self.view)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(14, 8, 14, 10)
        toolbar.setSpacing(8)

        info_text = ''
        if not self.pixmap.isNull():
            info_text = f'{self.pixmap.width()} × {self.pixmap.height()}'
        self.info_label = QLabel(info_text)
        self.info_label.setObjectName('viewer_info')

        zoom_out = QPushButton('−')
        zoom_in = QPushButton('+')
        fit_btn = QPushButton('适应窗口')
        actual_btn = QPushButton('100%')
        for b in (zoom_out, zoom_in, fit_btn, actual_btn):
            b.setObjectName('viewer_toolbar_btn')
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)

        zoom_in.clicked.connect(lambda: self._scale_by(1.2))
        zoom_out.clicked.connect(lambda: self._scale_by(1 / 1.2))
        fit_btn.clicked.connect(self._fit_view)
        actual_btn.clicked.connect(self._actual_size)

        toolbar.addWidget(self.info_label)
        toolbar.addStretch()
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(actual_btn)
        toolbar.addWidget(fit_btn)
        toolbar.addWidget(zoom_in)

        layout.addLayout(toolbar)

        QTimer.singleShot(0, self._fit_view)

    def _fit_view(self):
        if self.pixmap_item is not None:
            self.view.resetTransform()
            self.view.fitInView(self.pixmap_item, Qt.KeepAspectRatio)

    def _actual_size(self):
        if self.pixmap_item is not None:
            self.view.resetTransform()

    def _scale_by(self, factor):
        self.view.scale(factor, factor)

    def _handle_wheel_zoom(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._scale_by(1.15)
        else:
            self._scale_by(1 / 1.15)
        event.accept()

    def eventFilter(self, obj, event):
        if obj is self.view.viewport() and event.type() == QEvent.Wheel:
            self._handle_wheel_zoom(event)
            return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event):
        self._handle_wheel_zoom(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class ArchivePhotoDialog(QDialog):
    def __init__(self, attachment, file_path, categories=None, parent=None):
        super().__init__(parent)
        is_image = is_image_attachment(attachment)
        self.setWindowTitle('归档附件')
        self.setModal(True)
        self.resize(460, 480)
        self.setObjectName('archive_photo_dialog')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        header = QLabel('完成了什么内容？')
        header.setObjectName('archive_dialog_title')

        subtitle = QLabel('这段内容会保存到附件归档记录，并显示在时间线里。')
        subtitle.setObjectName('archive_dialog_subtitle')
        subtitle.setWordWrap(True)

        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(0, 2, 0, 0)
        preview_row.setSpacing(12)

        thumb = QLabel()
        thumb.setObjectName('archive_dialog_thumb')
        thumb.setFixedSize(120, 82)
        thumb.setAlignment(Qt.AlignCenter)
        if is_image:
            pixmap = load_scaled_pixmap(file_path, 120, 82) or QPixmap()
        else:
            # 直接按盒子高度出图（图标固定 36:44 比例，82 高对应 67 宽），
            # 免二次放大缩小，高分屏下也锐利
            pixmap = build_folder_icon(67) if attachment.get('type') == 'folder' else build_file_icon(file_path, 67, AttachmentCard.EXT_COLORS)
        if pixmap.isNull():
            thumb.setText('无法预览')
        else:
            thumb.setPixmap(pixmap)

        name_box = QVBoxLayout()
        name_box.setContentsMargins(0, 0, 0, 0)
        name_box.setSpacing(4)
        filename = QLabel(attachment.get('original_name', '') or attachment_kind_label(attachment))
        filename.setObjectName('archive_dialog_filename')
        filename.setWordWrap(True)
        hint = QLabel('填写后点击“归档附件”。')
        hint.setObjectName('archive_dialog_hint')
        name_box.addWidget(filename)
        name_box.addWidget(hint)
        name_box.addStretch()

        preview_row.addWidget(thumb)
        preview_row.addLayout(name_box, 1)

        category_row = QHBoxLayout()
        category_row.setContentsMargins(0, 0, 0, 0)
        category_row.setSpacing(10)
        category_label = QLabel('分类')
        category_label.setObjectName('archive_dialog_label')
        self.category_combo = QComboBox()
        self.category_combo.setObjectName('archive_dialog_category')
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.NoInsert)
        self.category_combo.lineEdit().setPlaceholderText('选择或输入分类')
        self.category_combo.addItems(categories or [])
        self.category_combo.lineEdit().setText(
            attachment.get('archive_category', '') or attachment.get('category', '') or ''
        )
        # currentTextChanged 已覆盖手动输入，重复连 lineEdit 会让每个按键触发两次
        self.category_combo.currentTextChanged.connect(self._sync_ok_enabled)
        category_row.addWidget(category_label)
        category_row.addWidget(self.category_combo, 1)

        self.content_edit = QTextEdit()
        self.content_edit.setObjectName('archive_dialog_content')
        self.content_edit.setPlaceholderText('例如：整理完资料、确认这个文件的问题已经处理、记录文件夹里这批内容的状态...')
        self.content_edit.setPlainText(attachment.get('archive_content') or attachment.get('memo', '') or '')
        self.content_edit.setMinimumHeight(120)
        self.content_edit.textChanged.connect(self._sync_ok_enabled)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 2, 0, 0)
        buttons.setSpacing(10)
        self.cancel_btn = QPushButton('取消')
        self.cancel_btn.setObjectName('archive_dialog_cancel')
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton('归档附件')
        self.ok_btn.setObjectName('archive_dialog_ok')
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        # 按钮可聚焦 + 默认键，键盘（Tab/Enter/Esc）也能完成归档
        self.ok_btn.setDefault(True)
        self.ok_btn.clicked.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.ok_btn)

        layout.addWidget(header)
        layout.addWidget(subtitle)
        layout.addLayout(preview_row)
        layout.addLayout(category_row)
        layout.addWidget(self.content_edit, 1)
        layout.addLayout(buttons)

        self._sync_ok_enabled()
        QTimer.singleShot(0, self.content_edit.setFocus)

    def content(self):
        return self.content_edit.toPlainText().strip()

    def category(self):
        return self.category_combo.currentText().strip()

    def _sync_ok_enabled(self):
        self.ok_btn.setEnabled(bool(self.content()))


def choose_category(parent, storage, current='', *, required=True,
                    title=None, prompt=None, allow_empty_choice=False):
    """归档分类 / 附件分类共用的选择对话框（两者候选互通）。"""
    title = title or tr('归档分类')
    prompt = prompt or tr('选择或输入分类:')
    current = (current or '').strip()
    categories = list(storage.all_categories() if storage else [])
    categories = [category for category in categories if category]
    if current and current not in categories:
        categories.append(current)
        categories.sort()
    if allow_empty_choice and '' not in categories:
        categories.insert(0, '')

    if categories:
        index = categories.index(current) if current in categories else 0
        category, ok = QInputDialog.getItem(parent, title, prompt, categories, index, True)
    else:
        category, ok = QInputDialog.getText(parent, title, prompt, QLineEdit.Normal, current)
    if not ok:
        return None
    category = (category or '').strip()
    if required and not category:
        QMessageBox.information(parent, tr('需要分类'), tr('请填写归档分类。'))
        return None
    return category


def choose_archive_category(parent, storage, current='', required=True):
    return choose_category(
        parent, storage, current,
        required=required,
        allow_empty_choice=not required,
    )


def attachment_category_candidates(storage):
    categories = set()
    if not storage:
        return []
    for _note, att, _parent, _container in storage.iter_attachments(include_deleted=False):
        category = (att.get('archive_category') or att.get('category') or '').strip()
        if category:
            categories.add(category)
    return sorted(categories)


def choose_attachment_category(parent, storage, current=''):
    # 与归档分类共用同一套候选（笔记 + 附件的全部分类），名字互通。
    return choose_category(
        parent, storage, current,
        required=False,
        title=tr('附件分类'),
        prompt=tr('选择或输入附件分类:'),
        allow_empty_choice=True,
    )


class EmptyState(QWidget):
    primary_action = Signal()
    secondary_action = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName('empty_state')
        # 自定义 QWidget 子类默认不画 QSS 背景，必须显式启用
        self.setAttribute(Qt.WA_StyledBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(0)

        panel = QFrame()
        panel.setObjectName('empty_panel')
        panel.setMinimumSize(246, 204)
        panel.setMaximumWidth(320)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(24, 24, 24, 24)
        panel_layout.setSpacing(12)
        panel_layout.addStretch()

        self.icon = QLabel()
        self.icon.setObjectName('empty_icon')
        self.icon.setAlignment(Qt.AlignCenter)
        self._set_icon('document')

        self.title = QLabel('')
        self.title.setObjectName('empty_title')
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)

        self.message = QLabel('')
        self.message.setObjectName('empty_message')
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(10)
        self.secondary_btn = QPushButton('')
        self.secondary_btn.setObjectName('empty_secondary_btn')
        self.secondary_btn.setCursor(Qt.PointingHandCursor)
        self.secondary_btn.setFocusPolicy(Qt.NoFocus)
        self.secondary_btn.clicked.connect(self.secondary_action.emit)
        self.primary_btn = QPushButton('')
        self.primary_btn.setObjectName('empty_primary_btn')
        self.primary_btn.setCursor(Qt.PointingHandCursor)
        self.primary_btn.setFocusPolicy(Qt.NoFocus)
        self.primary_btn.clicked.connect(self.primary_action.emit)
        actions.addWidget(self.secondary_btn, 1)
        actions.addWidget(self.primary_btn, 1)

        panel_layout.addWidget(self.icon, 0, Qt.AlignCenter)
        panel_layout.addWidget(self.title)
        panel_layout.addWidget(self.message)
        panel_layout.addLayout(actions)
        panel_layout.addStretch()

        outer.addWidget(panel, 0, Qt.AlignCenter)

    def _set_icon(self, name):
        color = '#248A3D' if name == 'check' else '#636366'
        self.icon.setPixmap(build_ui_icon(name, color).pixmap(24, 24))

    def configure(self, view='active', filtered=False, search='', category='', has_rows=False):
        if has_rows:
            self._set_icon('document')
            self.title.setText('选择一条备忘录')
            self.message.setText('从左侧列表打开一条备忘录。')
            self.secondary_btn.hide()
            self.primary_btn.hide()
            return

        if filtered:
            self._set_icon('search')
            self.title.setText('没有匹配的备忘录')
            detail = '换一个关键词或清除分类筛选。'
            if search and category:
                detail = f'当前搜索“{search}”，分类为“{category}”。'
            elif search:
                detail = f'当前搜索“{search}”。'
            elif category:
                detail = f'当前分类为“{category}”。'
            self.message.setText(detail)
            self.secondary_btn.setText('清除筛选')
            self.primary_btn.setText('新建备忘录')
            self.secondary_btn.show()
            self.primary_btn.show()
            return

        if view == 'archived':
            self._set_icon('check')
            self.title.setText('归档里还没有内容')
            self.message.setText('附件或备忘录归档后会出现在这里，也会按分类进入时间线。')
            self.secondary_btn.setText('查看时间线')
            self.primary_btn.setText('回到活跃')
            self.secondary_btn.show()
            self.primary_btn.show()
            return

        self._set_icon('document')
        self.title.setText('点击“新建记事”或拖拽文件到此处')
        self.message.setText('支持 .txt .md 等文本文件')
        self.secondary_btn.hide()
        self.primary_btn.setText('新建备忘录')
        self.primary_btn.show()


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def duration_text(seconds):
    seconds = max(0, float(seconds or 0))
    if seconds < 60:
        return '1 分钟内'
    minutes = seconds / 60
    if minutes < 60:
        return f'{int(round(minutes))} 分钟'
    hours = seconds / 3600
    if hours < 24:
        return f'{hours:.1f} 小时' if hours < 10 else f'{int(round(hours))} 小时'
    days = seconds / 86400
    if days < 60:
        return f'{days:.1f} 天' if days < 10 else f'{int(round(days))} 天'
    months = days / 30
    if months < 24:
        return f'{months:.1f} 个月' if months < 10 else f'{int(round(months))} 个月'
    return f'{days / 365:.1f} 年'


def period_key(dt, granularity):
    if not dt:
        return ''
    if granularity == 'day':
        return dt.strftime('%Y-%m-%d')
    if granularity == 'week':
        start = dt.date() - timedelta(days=dt.weekday())
        return start.strftime('%Y-%m-%d')
    if granularity == 'year':
        return dt.strftime('%Y')
    return dt.strftime('%Y-%m')


def period_label(key, granularity):
    if not key:
        return ''
    try:
        if granularity == 'day':
            return datetime.strptime(key, '%Y-%m-%d').strftime('%m/%d')
        if granularity == 'week':
            return datetime.strptime(key, '%Y-%m-%d').strftime('%m/%d 周')
        if granularity == 'year':
            return key
        return datetime.strptime(key, '%Y-%m').strftime('%Y/%m')
    except Exception:
        return key


def heatmap_end_date(latest, today, weeks):
    """Keep recent heatmaps anchored to today and historical ones on their data."""
    if latest is None:
        return today
    if today is None:
        return latest
    visible_days = max(1, int(weeks or 1)) * 7
    delta = (today - latest).days
    return today if 0 <= delta < visible_days else latest


class TimelineReviewChart(QWidget):
    category_selected = Signal(str)

    # —— 配色（QPainter 硬编码色无法被 QSS 覆盖，集中为类常量便于一处主题化）——
    BLUE = '#007AFF'; BLUE_LIGHT = '#5AC8FA'
    GREEN = '#34C759'; GREEN_LIGHT = '#5AD27A'
    GOLD = '#FF9F0A'; GOLD_LIGHT = '#FFB340'
    SILVER = '#AEB8C6'; SILVER_LIGHT = '#C9D2DE'
    BRONZE = '#CD7F45'; BRONZE_LIGHT = '#E0A87E'
    TEXT = '#1D1D1F'; MUTED = '#6E6E73'; FAINT = '#8E8E93'
    GRID = '#F2F2F7'; AXIS = '#E5E5EA'; TRACK = '#F2F2F7'
    CARD_BORDER = '#E5E5EA'
    DIM = '#C7C7CC'; DIM_LIGHT = '#D6DEEA'
    HOVER = '#F5F5F7'; BADGE_BG = '#E7F1FF'
    PEAK_BLUE = '#0068D9'; PEAK_GREEN = '#248A3D'
    HEAT_EMPTY = '#EBEDF0'
    HEAT_SCALE = ['#C8EBD3', '#86D6A1', '#52C07D', '#2C9E55']
    def __init__(self, chart_type, title, parent=None):
        super().__init__(parent)
        self.chart_type = chart_type
        self.title = title
        self.records = []
        self.selected_category = ''
        self.granularity = 'month'
        self.rank_order = 'slow'
        self._hit_regions = []
        self._rank_regions = []
        self._heat_regions = []
        self._hover_index = -1
        self._grow = 1.0
        self._animations_enabled = True
        self._anim = None
        try:
            self._anim = QVariantAnimation(self)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setDuration(320)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.valueChanged.connect(self._on_grow)
        except Exception:
            self._anim = None
        self.setObjectName('timeline_chart')
        self.setMouseTracking(True)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_records(self, records, selected_category='', granularity='month', rank_order='slow'):
        self.records = list(records or [])
        self.selected_category = selected_category or ''
        self.granularity = granularity or 'month'
        self.rank_order = rank_order or 'slow'
        self._hit_regions = []
        self._rank_regions = []
        self._heat_regions = []
        self._hover_index = -1
        QToolTip.hideText()
        # 过滤/搜索会高频调用 set_records，这里只刷新到终值；入场生长动画由对话框 showEvent 触发 animate_in。
        self._grow = 1.0
        self.update()

    def _anim_allowed(self):
        return (self._animations_enabled and self._anim is not None
                and not os.environ.get('FRESH_NO_ANIM')
                and bool(self.records) and self.chart_type != 'heatmap')

    def animate_in(self):
        # 入场生长动画；由 TimelineDialog.showEvent 调用（构造期 populate 不可见，不会触发）。
        if not self._anim_allowed() or not self.isVisible():
            self._grow = 1.0
            self.update()
            return
        try:
            self._anim.stop()
            self._grow = 0.0
            self._anim.start()
        except Exception:
            self._grow = 1.0
            self.update()

    def _on_grow(self, value):
        try:
            self._grow = max(0.0, min(1.0, float(value)))
        except Exception:
            self._grow = 1.0
        self.update()

    def set_animations_enabled(self, enabled):
        self._animations_enabled = bool(enabled)

    def stop_animation(self):
        try:
            if self._anim is not None:
                self._anim.stop()
        except Exception:
            pass
        self._grow = 1.0

    def hideEvent(self, event):
        self.stop_animation()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        card = self._draw_card(painter, rect)

        title_font = QFont(painter.font())
        title_font.setPointSize(11)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(self.TEXT))
        painter.drawText(card.adjusted(16, 11, -16, 0), Qt.AlignLeft | Qt.AlignTop, self.title)

        plot = card.adjusted(16, 38, -16, -14)
        self._hit_regions = []
        self._rank_regions = []
        self._heat_regions = []
        ct = self.chart_type
        if not self.records and ct != 'category':
            self._draw_empty(painter, plot)
        elif ct == 'trend':
            self._draw_trend(painter, plot)
        elif ct == 'category':
            self._draw_category(painter, plot)
        elif ct == 'heatmap':
            self._draw_heatmap(painter, plot)
        else:
            self._draw_ranking(painter, plot)
        painter.end()

    def _draw_card(self, painter, rect):
        # 白卡 + 多层半透明描边模拟柔和阴影（不挂 QGraphicsDropShadowEffect，避免与列表 OpacityEffect 冲突）
        card = QRectF(rect.left(), rect.top(), rect.width(), max(10.0, rect.height() - 3))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(40, 70, 110, 13), 1))
        painter.drawRoundedRect(card.adjusted(0.5, 2.0, -0.5, 2.0), 12, 12)
        painter.setPen(QPen(QColor(40, 70, 110, 6), 1))
        painter.drawRoundedRect(card.adjusted(0.0, 3.2, 0.0, 3.2), 12, 12)
        painter.setPen(QPen(QColor(self.CARD_BORDER), 1))
        painter.setBrush(QColor('#FFFFFF'))
        painter.drawRoundedRect(card, 12, 12)
        return card

    def _draw_empty(self, painter, rect):
        painter.setPen(QColor(self.FAINT))
        painter.drawText(rect, Qt.AlignCenter, '暂无完成记录')

    def _grad_vert(self, cx, top, bottom, c_top, c_bottom):
        g = QLinearGradient(cx, top, cx, bottom)
        g.setColorAt(0.0, QColor(c_top))
        g.setColorAt(1.0, QColor(c_bottom))
        return QBrush(g)

    def _grad_horiz(self, left, right, cy, c_left, c_right):
        g = QLinearGradient(left, cy, right, cy)
        g.setColorAt(0.0, QColor(c_left))
        g.setColorAt(1.0, QColor(c_right))
        return QBrush(g)

    def _bar_path(self, rect, radius):
        """只圆化顶部两角的柱条路径；底边贴基线保持平直。"""
        r = min(float(radius), rect.width() / 2, max(0.0, rect.height()))
        path = QPainterPath()
        if r <= 0.4:
            path.addRect(rect)
            return path
        path.moveTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + r)
        path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom())
        path.closeSubpath()
        return path

    def _draw_trend(self, painter, rect):
        buckets = defaultdict(lambda: {'created': 0, 'done': 0, 'selected_created': 0, 'selected_done': 0})
        for record in self.records:
            created_key = period_key(record.get('created_dt'), self.granularity)
            done_key = period_key(record.get('completed_dt'), self.granularity)
            is_selected = bool(self.selected_category and record.get('category') == self.selected_category)
            if created_key:
                buckets[created_key]['created'] += 1
                if is_selected:
                    buckets[created_key]['selected_created'] += 1
            if done_key:
                buckets[done_key]['done'] += 1
                if is_selected:
                    buckets[done_key]['selected_done'] += 1
        keys = sorted(buckets.keys())[-14:]
        if not keys:
            self._draw_empty(painter, rect)
            return

        max_count = max(max(buckets[key]['created'], buckets[key]['done']) for key in keys) or 1
        label_h = 18
        plot = rect.adjusted(0, 6, 0, -label_h)
        base_y = plot.bottom()
        chart_h = max(1, plot.height() - 4)
        grow = self._grow

        painter.setPen(QPen(QColor(self.GRID), 1))
        for gi in range(1, 5):
            gy = base_y - chart_h * gi / 4
            painter.drawLine(QPointF(plot.left(), gy), QPointF(plot.right(), gy))
        painter.setPen(QPen(QColor(self.AXIS), 1))
        painter.drawLine(QPointF(plot.left(), base_y), QPointF(plot.right(), base_y))

        group_w = plot.width() / max(1, len(keys))
        bar_w = max(4, min(13, group_w * 0.24))
        peak_idx = max(range(len(keys)), key=lambda i: max(buckets[keys[i]]['created'], buckets[keys[i]]['done']))
        small_font = QFont(painter.font())
        small_font.setPointSize(8)

        for idx, key in enumerate(keys):
            x = plot.left() + idx * group_w + group_w / 2
            created_h = chart_h * buckets[key]['created'] / max_count * grow
            done_h = chart_h * buckets[key]['done'] / max_count * grow
            cb = QRectF(x - bar_w - 1, base_y - created_h, bar_w, created_h)
            db = QRectF(x + 1, base_y - done_h, bar_w, done_h)
            painter.setPen(Qt.NoPen)
            radius = bar_w / 2
            if self.selected_category:
                painter.setBrush(QColor(self.DIM))
                painter.drawPath(self._bar_path(cb, radius))
                painter.drawPath(self._bar_path(db, radius))
                sc_h = chart_h * buckets[key]['selected_created'] / max_count * grow
                sd_h = chart_h * buckets[key]['selected_done'] / max_count * grow
                painter.setBrush(self._grad_vert(x, base_y - sc_h, base_y, self.BLUE_LIGHT, self.BLUE))
                painter.drawPath(self._bar_path(QRectF(x - bar_w - 1, base_y - sc_h, bar_w, sc_h), radius))
                painter.setBrush(self._grad_vert(x, base_y - sd_h, base_y, self.GREEN_LIGHT, self.GREEN))
                painter.drawPath(self._bar_path(QRectF(x + 1, base_y - sd_h, bar_w, sd_h), radius))
            else:
                painter.setBrush(self._grad_vert(x, base_y - created_h, base_y, self.BLUE_LIGHT, self.BLUE))
                painter.drawPath(self._bar_path(cb, radius))
                painter.setBrush(self._grad_vert(x, base_y - done_h, base_y, self.GREEN_LIGHT, self.GREEN))
                painter.drawPath(self._bar_path(db, radius))
            if idx == peak_idx and len(keys) > 1 and grow > 0.82:
                top_v = max(buckets[key]['created'], buckets[key]['done'])
                if top_v > 0:
                    painter.setFont(small_font)
                    painter.setPen(QColor(self.PEAK_BLUE) if buckets[key]['created'] >= buckets[key]['done'] else QColor(self.PEAK_GREEN))
                    ty = base_y - max(created_h, done_h) - 13
                    painter.drawText(QRectF(x - group_w / 2, ty, group_w, 12), Qt.AlignCenter, str(top_v))

        painter.setPen(QColor(self.FAINT))
        painter.setFont(small_font)
        step = max(1, len(keys) // 5)
        for idx, key in enumerate(keys):
            if idx % step != 0 and idx != len(keys) - 1:
                continue
            x = rect.left() + idx * group_w
            painter.drawText(QRectF(x, rect.bottom() - label_h + 2, group_w, label_h), Qt.AlignCenter, period_label(key, self.granularity))

        painter.setFont(small_font)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.BLUE))
        painter.drawRoundedRect(QRectF(rect.right() - 96, rect.top(), 8, 8), 2, 2)
        painter.setPen(QColor(self.MUTED))
        painter.drawText(QRectF(rect.right() - 84, rect.top() - 3, 40, 16), Qt.AlignLeft | Qt.AlignVCenter, '创建')
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self.GREEN))
        painter.drawRoundedRect(QRectF(rect.right() - 44, rect.top(), 8, 8), 2, 2)
        painter.setPen(QColor(self.MUTED))
        painter.drawText(QRectF(rect.right() - 32, rect.top() - 3, 40, 16), Qt.AlignLeft | Qt.AlignVCenter, '完成')

    def _draw_category(self, painter, rect):
        groups = defaultdict(lambda: {'total': 0.0, 'count': 0})
        for record in self.records:
            category = record.get('category') or '未分类'
            groups[category]['total'] += record.get('duration_seconds') or 0
            groups[category]['count'] += 1
        # 这里展示归档数量分布。duration_seconds 是创建到归档的自然周期，
        # 不能相加后称为某个分类的“投入”。
        metric_key = 'count'
        items = sorted(groups.items(), key=lambda item: item[1][metric_key], reverse=True)
        if self.selected_category and self.selected_category in groups:
            head = items[:7]
            if self.selected_category not in [cat for cat, _ in head]:
                head.append((self.selected_category, groups[self.selected_category]))
            items = head
        else:
            items = items[:8]
        if not items:
            self._draw_empty(painter, rect)
            return

        all_total = sum(data[metric_key] for _, data in groups.items()) or 1
        max_total = max(data[metric_key] for _, data in items) or 1
        row_h = max(18, min(28, rect.height() / max(1, len(items))))
        label_w = min(118, rect.width() * 0.32)
        track_w = max(2.0, rect.width() - label_w - 92)
        grow = self._grow
        for idx, (category, data) in enumerate(items):
            y = rect.top() + idx * row_h
            dim = bool(self.selected_category and category != self.selected_category)
            track = QRectF(rect.left() + label_w, y + 4, track_w, row_h - 8)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.TRACK))
            painter.drawRoundedRect(track, 5, 5)
            metric = data[metric_key]
            bw = max(2.0, track_w * metric / max_total * grow)
            bar_rect = QRectF(track.left(), track.top(), bw, track.height())
            if dim:
                painter.setBrush(self._grad_horiz(bar_rect.left(), track.right(), bar_rect.center().y(), self.DIM_LIGHT, self.DIM))
            else:
                painter.setBrush(self._grad_horiz(bar_rect.left(), track.right(), bar_rect.center().y(), self.BLUE, self.BLUE_LIGHT))
            painter.drawRoundedRect(bar_rect, 5, 5)
            painter.setPen(QColor(self.FAINT) if dim else QColor(self.TEXT))
            painter.drawText(
                QRectF(rect.left(), y, label_w - 8, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(category, Qt.ElideRight, int(label_w - 10)),
            )
            pct = round(metric / all_total * 100)
            value_text = f"{data['count']} 项"
            painter.setPen(QColor(self.FAINT) if dim else QColor(self.MUTED))
            painter.drawText(
                QRectF(track.right() + 8, y, 84, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{value_text} · {pct}%",
            )
            self._hit_regions.append((QRectF(rect.left(), y, rect.width(), row_h), category))

    def _draw_ranking(self, painter, rect):
        reverse = self.rank_order != 'fast'
        if self.selected_category:
            records = sorted(
                [record for record in self.records if record.get('category') == self.selected_category],
                key=lambda r: r.get('duration_seconds') or 0,
                reverse=reverse,
            )[:8]
        else:
            records = sorted(self.records, key=lambda r: r.get('duration_seconds') or 0, reverse=reverse)[:8]
        if not records:
            self._draw_empty(painter, rect)
            return
        records = records[:max(1, int(rect.height() // 21))]
        max_duration = max(r.get('duration_seconds') or 0 for r in records) or 1
        row_h = max(20, min(32, rect.height() / max(1, len(records))))
        badge = min(18.0, row_h - 6)
        label_x = rect.left() + badge + 10
        label_w = min(170, rect.width() * 0.42)
        track_left = label_x + label_w
        track_w = max(2.0, rect.right() - track_left - 76)
        grow = self._grow
        badge_font = QFont(painter.font())
        badge_font.setPointSize(8)
        badge_font.setWeight(QFont.Bold)
        base_font = QFont(self.font())
        for idx, record in enumerate(records):
            y = rect.top() + idx * row_h
            duration = record.get('duration_seconds') or 0
            dim = bool(self.selected_category and record.get('category') != self.selected_category)
            if idx == self._hover_index:
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(self.HOVER))
                painter.drawRoundedRect(QRectF(rect.left() - 4, y + 1, rect.width() + 8, row_h - 2), 6, 6)
            bc = QRectF(rect.left(), y + (row_h - badge) / 2, badge, badge)
            painter.setPen(Qt.NoPen)
            if not dim and idx == 0:
                painter.setBrush(self._grad_vert(bc.center().x(), bc.top(), bc.bottom(), self.GOLD_LIGHT, self.GOLD))
            elif not dim and idx == 1:
                painter.setBrush(self._grad_vert(bc.center().x(), bc.top(), bc.bottom(), self.SILVER_LIGHT, self.SILVER))
            elif not dim and idx == 2:
                painter.setBrush(self._grad_vert(bc.center().x(), bc.top(), bc.bottom(), self.BRONZE_LIGHT, self.BRONZE))
            else:
                painter.setBrush(QColor(self.BADGE_BG))
            painter.drawEllipse(bc)
            painter.setFont(badge_font)
            if not dim and idx < 3:
                painter.setPen(QColor('#FFFFFF'))
            else:
                painter.setPen(QColor(self.FAINT) if dim else QColor(self.BLUE))
            painter.drawText(bc, Qt.AlignCenter, str(idx + 1))
            painter.setFont(base_font)
            painter.setPen(QColor(self.FAINT) if dim else QColor(self.TEXT))
            title = record.get('title') or '未命名'
            painter.drawText(
                QRectF(label_x, y, label_w - 8, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(title, Qt.ElideRight, int(label_w - 10)),
            )
            bw = max(2.0, track_w * duration / max_duration * grow)
            bar_rect = QRectF(track_left, y + (row_h - 9) / 2, bw, 9)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.TRACK))
            painter.drawRoundedRect(QRectF(track_left, bar_rect.top(), track_w, 9), 4.5, 4.5)
            if dim:
                painter.setBrush(QColor(self.DIM))
            else:
                painter.setBrush(self._grad_horiz(track_left, track_left + track_w, bar_rect.center().y(), self.GREEN, self.GREEN_LIGHT))
            painter.drawRoundedRect(bar_rect, 4, 4)
            painter.setPen(QColor(self.FAINT) if dim else QColor(self.MUTED))
            painter.drawText(QRectF(track_left + track_w + 8, y, 70, row_h), Qt.AlignLeft | Qt.AlignVCenter, duration_text(duration))
            self._rank_regions.append((QRectF(rect.left(), y, rect.width(), row_h), record))

    def _tooltip_point(self, event):
        if hasattr(event, 'globalPosition'):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def _format_record_dt(self, value):
        if isinstance(value, datetime):
            return format_time_long(value.isoformat())
        return format_time_long(value or '')

    def _heat_level(self, count, max_count):
        if count <= 0:
            return -1
        if max_count <= 1:
            return 3
        if count == 1:
            return 0
        if count <= max(2, max_count * 0.34):
            return 1
        if count <= max(3, max_count * 0.67):
            return 2
        return 3

    def _draw_heatmap(self, painter, rect):
        counts = defaultdict(int)
        latest = None
        for record in self.records:
            dt = record.get('completed_dt')
            if not dt:
                continue
            day = dt.date()
            counts[day] += 1
            if latest is None or day > latest:
                latest = day
        if not counts:
            self._draw_empty(painter, rect)
            return
        top_pad, left_pad, legend_h, gap = 16.0, 22.0, 16.0, 3.0
        grid = QRectF(rect.left() + left_pad, rect.top() + top_pad,
                      rect.width() - left_pad, rect.height() - top_pad - legend_h)
        weeks = int((grid.width() + gap) // (13.0 + gap))
        weeks = max(8, min(27, weeks))
        try:
            today = datetime.now().date()
        except Exception:
            today = latest
        end = heatmap_end_date(latest, today, weeks)
        cell = (grid.width() - gap * (weeks - 1)) / weeks
        cell = max(6.0, min(15.0, cell))
        cell = min(cell, (grid.height() - gap * 6) / 7)
        end_monday = end - timedelta(days=end.weekday())
        start_monday = end_monday - timedelta(weeks=weeks - 1)
        max_count = max(counts.values())

        painter.setPen(Qt.NoPen)
        small_font = QFont(painter.font())
        small_font.setPointSize(7)
        last_month = None
        for col in range(weeks):
            week_start = start_monday + timedelta(weeks=col)
            x = grid.left() + col * (cell + gap)
            if week_start.month != last_month:
                last_month = week_start.month
                painter.setPen(QColor(self.FAINT))
                painter.setFont(small_font)
                painter.drawText(QRectF(x, rect.top(), 32, top_pad), Qt.AlignLeft | Qt.AlignVCenter, f'{week_start.month}月')
                painter.setPen(Qt.NoPen)
            for row in range(7):
                day = week_start + timedelta(days=row)
                if today and day > today:
                    continue
                y = grid.top() + row * (cell + gap)
                count = counts.get(day, 0)
                level = self._heat_level(count, max_count)
                painter.setBrush(QColor(self.HEAT_EMPTY) if level < 0 else QColor(self.HEAT_SCALE[level]))
                cr = QRectF(x, y, cell, cell)
                painter.drawRoundedRect(cr, 2, 2)
                self._heat_regions.append((cr, day, count))

        painter.setFont(small_font)
        painter.setPen(QColor(self.FAINT))
        for row, lab in ((0, '一'), (2, '三'), (4, '五')):
            y = grid.top() + row * (cell + gap)
            painter.drawText(QRectF(rect.left(), y, left_pad - 4, cell), Qt.AlignRight | Qt.AlignVCenter, lab)

        lx = rect.right() - 92
        ly = rect.bottom() - legend_h + 2
        painter.setPen(QColor(self.FAINT))
        painter.drawText(QRectF(lx - 22, ly, 20, 12), Qt.AlignRight | Qt.AlignVCenter, '少')
        painter.setPen(Qt.NoPen)
        for i in range(4):
            painter.setBrush(QColor(self.HEAT_SCALE[i]))
            painter.drawRoundedRect(QRectF(lx + i * 15, ly + 1, 11, 11), 2, 2)
        painter.setPen(QColor(self.FAINT))
        painter.drawText(QRectF(lx + 4 * 15 + 2, ly, 18, 12), Qt.AlignLeft | Qt.AlignVCenter, '多')

    def mouseMoveEvent(self, event):
        pos = QPointF(event.position()) if hasattr(event, 'position') else QPointF(event.pos())
        if self.chart_type == 'ranking':
            hit = -1
            hovered = None
            for i, (region, record) in enumerate(self._rank_regions):
                if region.contains(pos):
                    hit, hovered = i, record
                    break
            if hit != self._hover_index:
                self._hover_index = hit
                self.update()
            if hovered is not None:
                title = hovered.get('title') or '未命名'
                category = hovered.get('category') or '未分类'
                tooltip = (
                    f'{title}\n'
                    f'分类：{category}\n'
                    f'归档周期：{duration_text(hovered.get("duration_seconds") or 0)}\n'
                    f'创建：{self._format_record_dt(hovered.get("created_dt")) or "未知"}\n'
                    f'完成：{self._format_record_dt(hovered.get("completed_dt")) or "未知"}'
                )
                QToolTip.showText(self._tooltip_point(event), tooltip, self)
            else:
                QToolTip.hideText()
        elif self.chart_type == 'heatmap':
            shown = False
            for region, day, count in self._heat_regions:
                if region.contains(pos):
                    QToolTip.showText(self._tooltip_point(event), f'{day.month}月{day.day}日 · 完成 {count} 件', self)
                    shown = True
                    break
            if not shown:
                QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        if self._hover_index != -1:
            self._hover_index = -1
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pos = QPointF(event.position()) if hasattr(event, 'position') else QPointF(event.pos())
        if self.chart_type == 'category':
            for region, category in self._hit_regions:
                if region.contains(pos):
                    self.category_selected.emit(category)
                    return
        super().mousePressEvent(event)


class TimelineItem(QFrame):
    open_requested = Signal(str)
    unarchive_requested = Signal(str, str)
    note_requested = Signal(str)
    category_change_requested = Signal(str, str)

    THUMB_W = 110
    THUMB_H = 74
    HEIGHT = 96

    def __init__(self, note, attachment, file_path):
        super().__init__()
        self.note = note
        self.attachment = attachment
        self.file_path = Path(file_path)
        self.setObjectName('timeline_item')
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(14)

        self.image_label = QLabel()
        self.image_label.setObjectName('timeline_thumb')
        self.image_label.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setPixmap(self._build_thumb())

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 2, 0, 2)
        text_layout.setSpacing(4)

        memo = attachment.get('archive_content') or attachment.get('memo', '') or ''
        memo_label = QLabel(memo if memo else '— 没有备注 —')
        memo_label.setObjectName('timeline_memo' if memo else 'timeline_memo_empty')
        memo_label.setTextFormat(Qt.PlainText)
        memo_label.setWordWrap(True)
        memo_label.setMaximumHeight(40)
        memo_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        note_title = note_display_title(note)
        category = (attachment.get('archive_category') or attachment.get('category') or '').strip()
        meta_text = f'· {note_title}'
        if category:
            meta_text = f'#{category}  · {note_title}'
        meta = QLabel(meta_text)
        meta.setObjectName('timeline_meta')
        meta.setTextFormat(Qt.PlainText)
        meta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        text_layout.addWidget(memo_label)
        text_layout.addStretch()
        text_layout.addWidget(meta)

        time_str = ''
        try:
            dt = datetime.fromisoformat(attachment.get('archived_at', ''))
            time_str = dt.strftime('%H:%M')
        except Exception:
            pass
        time_label = QLabel(time_str)
        time_label.setObjectName('timeline_time')
        time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_label.setFixedWidth(60)

        layout.addWidget(self.image_label)
        layout.addLayout(text_layout, 1)
        layout.addWidget(time_label)

    def _build_thumb(self):
        if not is_image_attachment(self.attachment):
            if self.attachment.get('type') == 'folder':
                return build_folder_icon(58)
            return build_file_icon(self.file_path, 58, AttachmentCard.EXT_COLORS)
        if not self.file_path.exists():
            pix = QPixmap(self.THUMB_W, self.THUMB_H)
            pix.fill(QColor("#F5F5F7"))
            return pix
        pixmap = load_scaled_pixmap(self.file_path, self.THUMB_W, self.THUMB_H)
        if pixmap is None:
            pix = QPixmap(self.THUMB_W, self.THUMB_H)
            pix.fill(QColor("#F5F5F7"))
            return pix
        return pixmap

    def mouseDoubleClickEvent(self, event):
        self.open_requested.emit(self.attachment['id'])
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        is_image = is_image_attachment(self.attachment)
        view = menu.addAction('查看大图' if is_image else '打开')
        open_note = menu.addAction('打开所属备忘录')
        change_category = menu.addAction(tr('修改分类'))
        unarchive = menu.addAction('取消归档')
        action = menu.exec(event.globalPos())
        if action == view:
            self.open_requested.emit(self.attachment['id'])
        elif action == open_note:
            self.note_requested.emit(self.note['id'])
        elif action == change_category:
            self.category_change_requested.emit(self.note['id'], self.attachment['id'])
        elif action == unarchive:
            self.unarchive_requested.emit(self.note['id'], self.attachment['id'])


class TimelineNoteItem(QFrame):
    open_requested = Signal(str)
    unarchive_requested = Signal(str)
    category_change_requested = Signal(str)

    HEIGHT = 96

    def __init__(self, note):
        super().__init__()
        self.note = note
        self.setObjectName('timeline_note_item')
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(14)

        icon = QLabel()
        icon.setObjectName('timeline_note_icon')
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(42, 42)
        icon.setPixmap(build_ui_icon('document', '#248A3D').pixmap(22, 22))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(5)

        title = QLabel(note_display_title(note))
        title.setObjectName('timeline_note_title')
        title.setTextFormat(Qt.PlainText)
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        preview = note_content_preview(note)
        if not preview:
            preview = tr('没有附加文本')
        preview_label = QLabel(preview)
        preview_label.setObjectName('timeline_note_preview')
        preview_label.setTextFormat(Qt.PlainText)
        preview_label.setWordWrap(False)
        preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        category = (note.get('archive_category') or note.get('category') or '').strip()
        meta_text = tr('归档备忘录')
        if category:
            meta_text = f'#{category}  · {tr("归档备忘录")}'
        meta = QLabel(meta_text)
        meta.setObjectName('timeline_meta')
        meta.setTextFormat(Qt.PlainText)
        meta.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        text_layout.addWidget(title)
        text_layout.addWidget(preview_label)
        text_layout.addWidget(meta)

        time_str = ''
        try:
            dt = datetime.fromisoformat(note.get('archived_at') or note.get('updated_at') or '')
            time_str = dt.strftime('%H:%M')
        except Exception:
            pass
        time_label = QLabel(time_str)
        time_label.setObjectName('timeline_time')
        time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        time_label.setFixedWidth(60)

        layout.addWidget(icon)
        layout.addLayout(text_layout, 1)
        layout.addWidget(time_label)

    def mouseDoubleClickEvent(self, event):
        self.open_requested.emit(self.note['id'])
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_note = menu.addAction('打开备忘录')
        change_category = menu.addAction(tr('修改分类'))
        unarchive = menu.addAction('取消归档')
        action = menu.exec(event.globalPos())
        if action == open_note:
            self.open_requested.emit(self.note['id'])
        elif action == change_category:
            self.category_change_requested.emit(self.note['id'])
        elif action == unarchive:
            self.unarchive_requested.emit(self.note['id'])


class TimelineDialog(QDialog):
    state_changed = Signal()
    note_requested = Signal(str)

    def __init__(self, storage, parent=None, workspace_mode='text'):
        super().__init__(parent)
        self.storage = storage
        self.workspace_mode = workspace_mode if workspace_mode in ('text', 'screenshot') else 'text'
        self.setWindowTitle('时间线回顾')
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowMaximizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setMinimumSize(720, 520)
        # 初始尺寸适配屏幕可用区域（之前写死 1004x968，超出常见笔记本屏高）
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            self.resize(min(1004, avail.width() - 80), min(968, avail.height() - 80))
        else:
            self.resize(1004, 700)
        self._updating_category_filter = False
        # 防抖：搜索框/日期每个变更都全量重建列表（含读盘解码缩略图），
        # 停顿 250ms 再刷新
        self._populate_debounce = QTimer(self)
        self._populate_debounce.setSingleShot(True)
        self._populate_debounce.setInterval(250)
        self._populate_debounce.timeout.connect(self._populate)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_box = QWidget()
        header_box.setObjectName('timeline_header_box')
        header_layout = QVBoxLayout(header_box)
        header_layout.setContentsMargins(24, 18, 24, 14)
        header_layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(14)

        title = QLabel('时间线回顾')
        title.setObjectName('timeline_header')
        self.subtitle = QLabel('')
        self.subtitle.setObjectName('timeline_subtitle')

        header_v = QVBoxLayout()
        header_v.setContentsMargins(0, 0, 0, 0)
        header_v.setSpacing(2)
        header_v.addWidget(title)
        header_v.addWidget(self.subtitle)
        top_row.addLayout(header_v)
        top_row.addStretch()

        header_layout.addLayout(top_row)

        filter_row = QGridLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setHorizontalSpacing(8)
        filter_row.setVerticalSpacing(8)

        self.range_filter = QComboBox()
        self.range_filter.setObjectName('timeline_filter_combo')
        self.range_filter.addItem('全部时间', 'all')
        self.range_filter.addItem('近 7 天', '7')
        self.range_filter.addItem('近 30 天', '30')
        self.range_filter.addItem('近 90 天', '90')
        self.range_filter.addItem('本月', 'month')
        self.range_filter.addItem('今年', 'year')
        self.range_filter.addItem(tr('自定义日期'), 'custom')
        self.range_filter.setCurrentIndex(0)
        self.range_filter.currentIndexChanged.connect(lambda _: self._on_range_changed())

        self.custom_range_widget = QWidget()
        self.custom_range_widget.setObjectName('timeline_custom_range')
        custom_range_layout = QHBoxLayout(self.custom_range_widget)
        custom_range_layout.setContentsMargins(0, 0, 0, 0)
        custom_range_layout.setSpacing(6)
        today = QDate.currentDate()
        self.start_date_edit = QDateEdit(today.addDays(-30))
        self.start_date_edit.setObjectName('timeline_date_edit')
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat('yyyy-MM-dd')
        self.start_date_edit.setMinimumDate(QDate(1900, 1, 1))
        self.start_date_edit.setMaximumDate(today.addYears(20))
        self.start_date_edit.dateChanged.connect(lambda _: self._populate_debounce.start())
        self.end_date_edit = QDateEdit(today)
        self.end_date_edit.setObjectName('timeline_date_edit')
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat('yyyy-MM-dd')
        self.end_date_edit.setMinimumDate(QDate(1900, 1, 1))
        self.end_date_edit.setMaximumDate(today.addYears(20))
        self.end_date_edit.dateChanged.connect(lambda _: self._populate_debounce.start())
        from_label = QLabel(tr('从'))
        from_label.setObjectName('timeline_date_label')
        to_label = QLabel(tr('到'))
        to_label.setObjectName('timeline_date_label')
        custom_range_layout.addWidget(from_label)
        custom_range_layout.addWidget(self.start_date_edit)
        custom_range_layout.addWidget(to_label)
        custom_range_layout.addWidget(self.end_date_edit)

        self.granularity_filter = QComboBox()
        self.granularity_filter.setObjectName('timeline_filter_combo')
        self.granularity_filter.addItem('按月', 'month')
        self.granularity_filter.addItem('按周', 'week')
        self.granularity_filter.addItem('按日', 'day')
        self.granularity_filter.addItem('按年', 'year')
        self.granularity_filter.currentIndexChanged.connect(lambda _: self._populate())

        self.category_filter = QComboBox()
        self.category_filter.setObjectName('timeline_filter_combo')
        self.category_filter.setEditable(True)
        self.category_filter.setInsertPolicy(QComboBox.NoInsert)
        self.category_filter.addItem('全部分类', '')
        self.category_filter.lineEdit().setPlaceholderText(tr('搜索分类'))
        self.category_filter.currentIndexChanged.connect(lambda _: self._populate())
        self.category_filter.lineEdit().textChanged.connect(lambda _: self._on_category_search_changed())

        self.rank_filter = QComboBox()
        self.rank_filter.setObjectName('timeline_filter_combo')
        self.rank_filter.addItem('周期最长', 'slow')
        self.rank_filter.addItem('周期最短', 'fast')
        self.rank_filter.currentIndexChanged.connect(lambda _: self._populate())

        self.reset_filter_btn = QPushButton('重置筛选')
        self.reset_filter_btn.setObjectName('timeline_reset_btn')
        self.reset_filter_btn.setCursor(Qt.PointingHandCursor)
        self.reset_filter_btn.setFocusPolicy(Qt.NoFocus)
        self.reset_filter_btn.setIcon(build_ui_icon('reset', '#636366', '#1D1D1F'))
        self.reset_filter_btn.setIconSize(QSize(15, 15))
        self.reset_filter_btn.clicked.connect(self._reset_filters)

        filter_row.addWidget(self.range_filter, 0, 0)
        filter_row.addWidget(self.category_filter, 0, 1)
        filter_row.addWidget(self.reset_filter_btn, 0, 2)
        filter_row.addWidget(self.custom_range_widget, 1, 0, 1, 2)
        filter_row.addWidget(self.granularity_filter, 1, 2)
        filter_row.addWidget(self.rank_filter, 1, 3)
        filter_row.setColumnStretch(4, 1)
        header_layout.addLayout(filter_row)
        self._sync_custom_range_visibility()

        review_box = QWidget()
        review_box.setObjectName('timeline_review_box')
        review_layout = QVBoxLayout(review_box)
        review_layout.setContentsMargins(18, 16, 18, 14)
        review_layout.setSpacing(12)

        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(10)
        stats_grid.setVerticalSpacing(10)
        self.count_value, self.count_sub, count_card = self._make_stat('完成', '0')
        self.streak_value, self.streak_sub, streak_card = self._make_stat('连续打卡', '0', accent=True)
        self.avg_value, self.avg_sub, avg_card = self._make_stat('活跃天数', '0')
        self.total_value, self.total_sub, total_card = self._make_stat('平均归档周期', '0')
        self.span_value, self.span_sub, span_card = self._make_stat('跨度', '0')
        stats_grid.addWidget(count_card, 0, 0, 1, 2)
        stats_grid.addWidget(streak_card, 0, 2, 1, 2)
        stats_grid.addWidget(avg_card, 0, 4, 1, 2)
        stats_grid.addWidget(total_card, 1, 0, 1, 3)
        stats_grid.addWidget(span_card, 1, 3, 1, 3)
        for column in range(6):
            stats_grid.setColumnStretch(column, 1)
        review_layout.addLayout(stats_grid)
        review_layout.addWidget(self._make_insight_strip())

        chart_grid = QGridLayout()
        chart_grid.setContentsMargins(0, 0, 0, 0)
        chart_grid.setHorizontalSpacing(10)
        chart_grid.setVerticalSpacing(10)
        self.heatmap_chart = TimelineReviewChart('heatmap', '活跃热力图')
        self.trend_chart = TimelineReviewChart('trend', '创建 / 完成')
        self.category_chart = TimelineReviewChart('category', '分类分布')
        self.ranking_chart = TimelineReviewChart('ranking', '归档周期排行')
        self.category_chart.category_selected.connect(self._select_category_from_chart)
        self.charts = [self.heatmap_chart, self.trend_chart, self.category_chart, self.ranking_chart]
        self.heatmap_chart.setMinimumHeight(120)
        self.heatmap_chart.setMaximumHeight(142)
        self.trend_chart.setMinimumHeight(150)
        self.trend_chart.setMaximumHeight(162)
        self.category_chart.setMinimumHeight(150)
        self.category_chart.setMaximumHeight(162)
        self.ranking_chart.setMinimumHeight(150)
        self.ranking_chart.setMaximumHeight(172)
        chart_grid.addWidget(self.heatmap_chart, 0, 0, 1, 2)
        chart_grid.addWidget(self.trend_chart, 1, 0)
        chart_grid.addWidget(self.category_chart, 1, 1)
        chart_grid.addWidget(self.ranking_chart, 2, 0, 1, 2)
        review_layout.addLayout(chart_grid)

        self.detail_title = QLabel('归档明细')
        self.detail_title.setObjectName('timeline_detail_title')

        self.list = QListWidget()
        self.list.setObjectName('timeline_list')
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setSelectionMode(QListWidget.NoSelection)

        review_scroll = QScrollArea()
        review_scroll.setObjectName('timeline_review_scroll')
        review_scroll.setWidgetResizable(True)
        review_scroll.setFrameShape(QFrame.NoFrame)
        review_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        review_scroll.setWidget(review_box)
        review_scroll.setMaximumHeight(648)
        self.list.setMinimumHeight(140)

        layout.addWidget(header_box)
        layout.addWidget(review_scroll)
        layout.addWidget(self.detail_title)
        layout.addWidget(self.list, 1)

        self._populate()

    def _make_stat(self, label, value, sub='', accent=False):
        card = QFrame()
        card.setObjectName('timeline_streak_card' if accent else 'timeline_stat_card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(13, 8, 13, 8)
        layout.setSpacing(1)
        value_label = QLabel(value)
        value_label.setObjectName('timeline_streak_value' if accent else 'timeline_stat_value')
        label_widget = QLabel(label)
        label_widget.setObjectName('timeline_stat_label')
        sub_label = QLabel(sub)
        sub_label.setObjectName('timeline_stat_sub')
        sub_label.setTextFormat(Qt.RichText)
        sub_label.setWordWrap(True)
        sub_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(value_label)
        layout.addWidget(label_widget)
        layout.addWidget(sub_label)
        return value_label, sub_label, card

    def _make_insight_strip(self):
        strip = QFrame()
        strip.setObjectName('timeline_insight_strip')
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(16, 9, 16, 9)
        strip_layout.setSpacing(16)
        self.insight_labels = []
        self.insight_seps = []
        for idx in range(3):
            lab = QLabel('')
            lab.setObjectName('timeline_insight_label')
            lab.setTextFormat(Qt.RichText)
            lab.setWordWrap(True)
            lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            strip_layout.addWidget(lab, 1)
            self.insight_labels.append(lab)
            if idx < 2:
                sep = QFrame()
                sep.setObjectName('timeline_insight_sep')
                sep.setFixedWidth(1)
                strip_layout.addWidget(sep)
                self.insight_seps.append(sep)
        self.insight_strip = strip
        return strip

    @staticmethod
    def _sub_html(text, color):
        return f'<span style="color:{color};">{html_escape(str(text))}</span>'

    def _delta_sub(self, insights, count, active_days):
        delta = insights.get('period_delta')
        if delta is None:
            if active_days:
                return self._sub_html(f'日均 {round(count / active_days, 1)} 件', '#8B98AA')
            return ''
        prev = insights.get('prev_count', 0)
        if prev == 0:
            return self._sub_html(f'本期新增 {count} 件 🎉', '#34C759')
        if delta > 0:
            return self._sub_html(f'较上期 +{delta}', '#34C759')
        if delta < 0:
            return self._sub_html(f'较上期 {delta}', '#8B98AA')
        return self._sub_html('与上期相当', '#8B98AA')

    def _compute_insights(
            self, all_records, summary_records, range_bounds, granularity,
            comparison_records=None):
        info = {}
        comparison_records = all_records if comparison_records is None else comparison_records
        try:
            today = datetime.now().date()
        except Exception:
            today = None
        done_days = sorted({r['completed_dt'].date() for r in all_records if r.get('completed_dt')})
        day_set = set(done_days)
        streak = 0
        if day_set and today is not None:
            cursor = today if today in day_set else (today - timedelta(days=1))
            while cursor in day_set:
                streak += 1
                cursor = cursor - timedelta(days=1)
        best = run = 0
        prev_day = None
        for day in done_days:
            run = run + 1 if (prev_day is not None and (day - prev_day).days == 1) else 1
            best = max(best, run)
            prev_day = day
        info['streak'] = streak
        info['best_streak'] = best
        info['today_done'] = bool(today is not None and today in day_set)
        life_total = len(all_records)
        info['life_total'] = life_total
        milestones = [10, 25, 50, 100, 200, 365, 500, 1000, 2000, 5000]
        nxt = next((m for m in milestones if m > life_total), None)
        info['next_milestone'] = nxt
        info['milestone_remaining'] = (nxt - life_total) if nxt else 0
        start, end_excl = range_bounds if range_bounds else (None, None)
        if start is not None:
            try:
                end_eff = end_excl or datetime.now()
                span = end_eff - start
                prev_start = start - span
                info['prev_count'] = sum(
                    1 for r in comparison_records
                    if r.get('completed_dt') and prev_start <= r['completed_dt'] < start
                )
                info['period_delta'] = len(summary_records) - info['prev_count']
            except Exception:
                info['period_delta'] = None
        else:
            info['period_delta'] = None
        s_days = {r['completed_dt'].date() for r in summary_records if r.get('completed_dt')}
        info['active_days'] = len(s_days)
        per_day = defaultdict(int)
        for r in summary_records:
            if r.get('completed_dt'):
                per_day[r['completed_dt'].date()] += 1
        if per_day:
            day, cnt = max(per_day.items(), key=lambda kv: kv[1])
            info['peak_day'] = day
            info['peak_day_count'] = cnt
        cat_count = defaultdict(int)
        for r in summary_records:
            category = r.get('category') or '未分类'
            cat_count[category] += 1
        if cat_count:
            cat, count = max(cat_count.items(), key=lambda kv: kv[1])
            info['top_category'] = cat
            info['top_category_pct'] = round(count / max(1, sum(cat_count.values())) * 100)
            info['top_category_metric'] = '数量'
        durs = [
            r['duration_seconds']
            for r in sorted(summary_records, key=lambda r: r.get('completed_dt') or datetime.min)
            if (r.get('duration_seconds') or 0) >= 60
        ]
        if len(durs) >= 6:
            half = len(durs) // 2
            early = durs[:half]
            recent = durs[half:]
            early_avg = sum(early) / len(early)
            recent_avg = sum(recent) / len(recent)
            if early_avg > 0:
                info['speed_pct'] = round((early_avg - recent_avg) / early_avg * 100)
        hours = defaultdict(int)
        for r in summary_records:
            if r.get('completed_dt'):
                hours[r['completed_dt'].hour] += 1
        if hours:
            info['peak_hour'] = max(hours.items(), key=lambda kv: kv[1])[0]
        return info

    def _render_insight_strip(self, insights):
        msgs = []
        nxt = insights.get('next_milestone')
        life = insights.get('life_total', 0)
        if nxt:
            rem = insights.get('milestone_remaining', 0)
            msgs.append(f'里程碑 · 累计完成 <b>{life}</b> 件，距 {nxt} 件还差 <b>{rem}</b> 件')
        elif life:
            msgs.append(f'里程碑 · 累计完成 <b>{life}</b> 件')
        peak_day = insights.get('peak_day')
        peak_count = insights.get('peak_day_count')
        if peak_day and peak_count:
            msgs.append(f'高峰 · {peak_day.month}月{peak_day.day}日完成 <b>{peak_count}</b> 件')
        top_cat = insights.get('top_category')
        top_pct = insights.get('top_category_pct')
        if top_cat and top_pct:
            msgs.append(f'分类 · <b>#{html_escape(str(top_cat))}</b> 占归档数量的 {top_pct}%')
        peak_hour = insights.get('peak_hour')
        if peak_hour is not None and len(msgs) < 3:
            msgs.append(f'时段 · {peak_hour} 点前后是你的高产时刻')
        labels = getattr(self, 'insight_labels', [])
        any_shown = False
        for idx, lab in enumerate(labels):
            if idx < len(msgs):
                lab.setText(msgs[idx])
                lab.setVisible(True)
                any_shown = True
            else:
                lab.setText('')
                lab.setVisible(False)
        for idx, sep in enumerate(getattr(self, 'insight_seps', [])):
            sep.setVisible(idx + 1 < len(msgs))
        if hasattr(self, 'insight_strip'):
            self.insight_strip.setVisible(any_shown)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, '_entrance_played', False):
            self._entrance_played = True
            for chart in getattr(self, 'charts', []):
                chart.animate_in()

    def closeEvent(self, event):
        for chart in getattr(self, 'charts', []):
            chart.stop_animation()
        super().closeEvent(event)

    def _sync_custom_range_visibility(self):
        self.custom_range_widget.setVisible((self.range_filter.currentData() or 'all') == 'custom')

    def _on_range_changed(self):
        self._sync_custom_range_visibility()
        self._populate()

    def _reset_filters(self):
        widgets = (
            self.range_filter,
            self.granularity_filter,
            self.category_filter,
            self.rank_filter,
        )
        for widget in widgets:
            widget.blockSignals(True)
        try:
            self.range_filter.setCurrentIndex(0)
            self.granularity_filter.setCurrentIndex(0)
            self.category_filter.setCurrentIndex(0)
            editor = self.category_filter.lineEdit()
            if editor:
                editor.clear()
            self.rank_filter.setCurrentIndex(0)
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self._sync_custom_range_visibility()
        self._populate()

    def _on_category_search_changed(self):
        if self._updating_category_filter:
            return
        self._populate_debounce.start()

    def _category_query(self):
        editor = self.category_filter.lineEdit()
        text = (editor.text() if editor else self.category_filter.currentText()).strip()
        if not text or text == tr('全部分类'):
            return ''
        return text

    def _category_matches(self, category, query):
        query = (query or '').strip()
        if not query:
            return True
        return query.casefold() in (category or '未分类').casefold()

    def _exact_category(self, records, query=None):
        query = self._category_query() if query is None else (query or '').strip()
        if not query:
            return ''
        for record in records:
            category = record.get('category') or '未分类'
            if category == query:
                return category
        return ''

    def _refresh_category_filter(self, records):
        query = self._category_query()
        categories = sorted({record.get('category') or '未分类' for record in records})
        visible_categories = [category for category in categories if self._category_matches(category, query)]
        exact_index = 0 if not query else -1
        self._updating_category_filter = True
        self.category_filter.blockSignals(True)
        editor = self.category_filter.lineEdit()
        if editor:
            editor.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem(tr('全部分类'), '')
        for category in visible_categories:
            self.category_filter.addItem(category, category)
        if query:
            for i in range(self.category_filter.count()):
                if self.category_filter.itemData(i) == query:
                    exact_index = i
                    break
        self.category_filter.setCurrentIndex(exact_index)
        if editor:
            editor.setText(query)
            editor.blockSignals(False)
        self.category_filter.blockSignals(False)
        self._updating_category_filter = False

    def _review_records(self):
        records = []
        for item in self.storage.all_timeline_items():
            if not self._timeline_item_matches_workspace(item):
                continue
            note = item.get('note') or {}
            if item.get('kind') == 'note':
                created_at = note.get('created_at') or note.get('updated_at') or item.get('time') or ''
                completed_at = item.get('time') or note.get('archived_at') or note.get('updated_at') or ''
                category = (note.get('archive_category') or note.get('category') or '未分类').strip() or '未分类'
                title = note_display_title(note)
            else:
                att = item.get('attachment') or {}
                created_at = att.get('added_at') or note.get('created_at') or item.get('time') or ''
                completed_at = item.get('time') or att.get('archived_at') or note.get('updated_at') or ''
                category = (att.get('archive_category') or att.get('category') or '未分类').strip() or '未分类'
                title = attachment_display_title(att)
            created_dt = parse_iso_datetime(created_at)
            completed_dt = parse_iso_datetime(completed_at) or created_dt
            if not completed_dt:
                continue
            if not created_dt:
                created_dt = completed_dt
            duration = max(0, (completed_dt - created_dt).total_seconds())
            records.append({
                'item': item,
                'kind': item.get('kind'),
                'title': title,
                'category': category,
                'created_dt': created_dt,
                'completed_dt': completed_dt,
                'duration_seconds': duration,
            })
        records.sort(key=lambda record: record.get('completed_dt') or datetime.min, reverse=True)
        return records

    def _timeline_item_matches_workspace(self, item):
        return True

    def _date_start(self, qdate):
        return datetime(qdate.year(), qdate.month(), qdate.day())

    def _range_bounds(self):
        value = self.range_filter.currentData() or 'all'
        now = datetime.now()
        if value == 'all':
            return None, None
        if value == 'custom':
            start_date = self.start_date_edit.date()
            end_date = self.end_date_edit.date()
            if start_date.toJulianDay() > end_date.toJulianDay():
                start_date, end_date = end_date, start_date
            start = self._date_start(start_date)
            end_exclusive = self._date_start(end_date) + timedelta(days=1)
            return start, end_exclusive
        if value == 'month':
            return datetime(now.year, now.month, 1), None
        if value == 'year':
            return datetime(now.year, 1, 1), None
        try:
            return now - timedelta(days=int(value)), None
        except Exception:
            return None, None

    def _records_in_range(self, records):
        start, end_exclusive = self._range_bounds()
        if not start and not end_exclusive:
            return records
        filtered = []
        for record in records:
            completed_dt = record.get('completed_dt')
            if not completed_dt:
                continue
            if start and completed_dt < start:
                continue
            if end_exclusive and completed_dt >= end_exclusive:
                continue
            filtered.append(record)
        return filtered

    def _active_records(self, records, category_query=None):
        category_query = self._category_query() if category_query is None else (category_query or '').strip()
        if not category_query:
            return records
        return [record for record in records if self._category_matches(record.get('category'), category_query)]

    def _timeline_records_for_list(self, records, active_records):
        return active_records

    def _chart_records(self, records, active_records, selected_category, category_query, chart_type):
        if not category_query:
            return records
        # 分类图保留全局分布作为上下文；趋势、排行和热力图遵循当前筛选。
        if chart_type == 'category' and selected_category:
            return records
        return active_records

    def _select_category_from_chart(self, category):
        current = self._category_query()
        target = '' if current == category else category
        for i in range(self.category_filter.count()):
            if self.category_filter.itemData(i) == target:
                self.category_filter.setCurrentIndex(i)
                return
        editor = self.category_filter.lineEdit()
        if editor:
            editor.setText(target)
        else:
            self._populate()

    def _update_summary(self, records, active_records, all_records, range_bounds, granularity):
        category_query = self._category_query()
        summary_records = active_records if category_query else records
        comparison_records = self._active_records(all_records, category_query) if category_query else all_records
        insights = self._compute_insights(
            all_records,
            summary_records,
            range_bounds,
            granularity,
            comparison_records=comparison_records,
        )
        count = len(summary_records)
        total = sum(record.get('duration_seconds') or 0 for record in summary_records)
        active_days = insights.get('active_days', 0)
        shot_count = sum(1 for record in summary_records if record.get('kind') == 'attachment')
        note_count = sum(1 for record in summary_records if record.get('kind') == 'note')
        done_dates = [r['completed_dt'].date() for r in summary_records if r.get('completed_dt')]
        if summary_records:
            firsts = [r['created_dt'] for r in summary_records if r.get('created_dt')]
            lasts = [r['completed_dt'] for r in summary_records if r.get('completed_dt')]
            span_days = max(1, (max(lasts).date() - min(firsts).date()).days + 1) if (firsts and lasts) else 0
        else:
            span_days = 0

        self.count_value.setText(str(count))
        self.count_sub.setText(self._delta_sub(insights, count, active_days))

        streak = insights.get('streak', 0)
        best = insights.get('best_streak', 0)
        self.streak_value.setText(f'{streak} 天')
        if streak > 0 and insights.get('today_done'):
            self.streak_sub.setText(self._sub_html(f'今日已完成 · 最长 {best} 天', '#FF9F0A'))
        elif streak > 0:
            self.streak_sub.setText(self._sub_html(f'今天再完成 1 条续上 · 最长 {best} 天', '#8B98AA'))
        else:
            self.streak_sub.setText(self._sub_html('归档 1 条开启连续记录', '#8B98AA'))

        self.avg_value.setText(f'{active_days} 天' if count else '—')
        if span_days and active_days:
            pct = round(active_days / span_days * 100)
            tail = ' · 很稳定' if pct >= 80 else ''
            self.avg_sub.setText(self._sub_html(f'{span_days} 天里活跃 {pct}%{tail}', '#8B98AA'))
        else:
            self.avg_sub.setText('')

        if not count:
            self.total_value.setText('—')
            self.total_sub.setText('')
        elif total > 0:
            self.total_value.setText(duration_text(total / count))
            self.total_sub.setText(self._sub_html(f'从创建到归档 · {count} 项平均', '#8B98AA'))
        else:
            self.total_value.setText('—')
            self.total_sub.setText(self._sub_html(f'附件 {shot_count} · 备忘 {note_count}', '#8B98AA'))

        self.span_value.setText(f'{span_days} 天' if count else '—')
        if done_dates:
            first_done = min(done_dates).strftime('%m/%d')
            last_done = max(done_dates).strftime('%m/%d')
            if first_done == last_done:
                self.span_sub.setText(self._sub_html(first_done, '#8B98AA'))
            else:
                self.span_sub.setText(self._sub_html(f'{first_done} 至 {last_done}', '#8B98AA'))
        else:
            self.span_sub.setText('')

        self._render_insight_strip(insights)

    def _populate(self):
        self.list.clear()
        all_records = self._review_records()
        records = self._records_in_range(all_records)
        self._refresh_category_filter(records)
        category_query = self._category_query()
        active_records = self._active_records(records, category_query)
        selected_category = self._exact_category(records, category_query)
        granularity = self.granularity_filter.currentData() or 'month'
        rank_order = self.rank_filter.currentData() or 'slow'
        for chart in self.charts:
            chart_records = self._chart_records(
                records,
                active_records,
                selected_category,
                category_query,
                chart.chart_type,
            )
            highlight_category = selected_category if chart.chart_type == 'category' else ''
            chart.set_records(chart_records, highlight_category, granularity, rank_order)
        self._update_summary(records, active_records, all_records, self._range_bounds(), granularity)

        list_records = self._timeline_records_for_list(records, active_records)
        count_items = [record.get('item') for record in active_records if record.get('item')]
        shot_count = sum(1 for item in count_items if item.get('kind') == 'attachment')
        note_count = sum(1 for item in count_items if item.get('kind') == 'note')
        prefix = ''
        if selected_category:
            prefix = f'#{selected_category} · '
        elif category_query:
            prefix = tr('分类搜索“{category}” · ', category=category_query)
        parts = []
        if shot_count:
            parts.append(tr('{count} 个归档附件', count=shot_count))
        if note_count:
            parts.append(tr('{count} 条归档备忘录', count=note_count))
        self.subtitle.setText(prefix + (' · '.join(parts) if parts else tr('暂无归档内容')))
        self.detail_title.setText(tr('归档明细 · {count} 项', count=len(list_records)))

        if not list_records:
            empty_text = tr('还没有归档内容\n\n归档附件或备忘录后会出现在这里')
            if selected_category:
                empty_text = tr('#{category} 下还没有归档内容', category=selected_category)
            elif category_query:
                empty_text = tr('没有匹配“{category}”的分类内容', category=category_query)
            empty = QLabel(empty_text)
            empty.setObjectName('timeline_empty')
            empty.setAlignment(Qt.AlignCenter)
            it = QListWidgetItem()
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(QSize(0, 280))
            self.list.addItem(it)
            self.list.setItemWidget(it, empty)
            return

        last_date = None
        for record in list_records:
            item = record.get('item') or {}
            item_time = item.get('time', '')
            try:
                dt = datetime.fromisoformat(item_time)
                date_key = dt.strftime('%Y 年 %m 月 %d 日')
            except Exception:
                date_key = tr('未知日期')
            if date_key != last_date:
                last_date = date_key
                head = QLabel(date_key)
                head.setObjectName('timeline_date')
                hi = QListWidgetItem()
                hi.setFlags(Qt.NoItemFlags)
                hi.setSizeHint(QSize(0, 38))
                self.list.addItem(hi)
                self.list.setItemWidget(hi, head)

            note = item.get('note')
            if not note:
                continue
            if item.get('kind') == 'note':
                tw = TimelineNoteItem(note)
                tw.open_requested.connect(self._open_note)
                tw.category_change_requested.connect(self._change_note_category)
                tw.unarchive_requested.connect(self._unarchive_note)
                item_height = TimelineNoteItem.HEIGHT
            else:
                att = item.get('attachment')
                if not att:
                    continue
                tw = TimelineItem(note, att, self.storage.path_for(att))
                tw.open_requested.connect(self._open_attachment)
                tw.note_requested.connect(self._open_note)
                tw.category_change_requested.connect(self._change_attachment_category)
                tw.unarchive_requested.connect(self._unarchive_attachment)
                item_height = TimelineItem.HEIGHT
            it = QListWidgetItem()
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(QSize(0, item_height))
            self.list.addItem(it)
            self.list.setItemWidget(it, tw)

    def _open_attachment(self, attachment_id):
        parent = self.parent()
        if parent is not None and hasattr(parent, '_open_attachment'):
            parent._open_attachment(attachment_id)
            return

    def _open_note(self, note_id):
        self.note_requested.emit(note_id)
        self.accept()

    def _change_attachment_category(self, note_id, attachment_id):
        note, att = self.storage.find_attachment(attachment_id)
        if not note or not att or att.get('deleted'):
            return
        category = choose_archive_category(
            self,
            self.storage,
            att.get('archive_category') or att.get('category') or '',
            required=False,
        )
        if category is None:
            return
        self.storage.update_attachment(note.get('id'), attachment_id, category=category, archive_category=category)
        self._populate()
        self.state_changed.emit()

    def _change_note_category(self, note_id):
        note = self.storage.get_note(note_id)
        if not note or note.get('deleted'):
            return
        category = choose_archive_category(
            self,
            self.storage,
            note.get('archive_category') or note.get('category') or '',
            required=True,
        )
        if category is None:
            return
        self.storage.update_note(note_id, archive_category=category)
        self._populate()
        self.state_changed.emit()

    def _unarchive_attachment(self, note_id, attachment_id):
        self.storage.update_attachment(
            note_id,
            attachment_id,
            archived=False,
            archived_at='',
        )
        self._populate()
        self.state_changed.emit()

    def _unarchive_note(self, note_id):
        self.storage.update_note(note_id, archived=False, archived_at='')
        self._populate()
        self.state_changed.emit()


class RecentlyDeletedDialog(QDialog):
    state_changed = Signal()

    def __init__(self, storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle(tr('最近删除'))
        self.resize(680, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header_box = QWidget()
        header_box.setObjectName('deleted_header_box')
        header_layout = QHBoxLayout(header_box)
        header_layout.setContentsMargins(24, 18, 24, 14)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        title = QLabel(tr('最近删除'))
        title.setObjectName('deleted_header')
        self.subtitle = QLabel('')
        self.subtitle.setObjectName('deleted_subtitle')
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        self.restore_btn = QPushButton(tr('恢复'))
        self.restore_btn.setObjectName('deleted_restore_btn')
        self.restore_btn.setCursor(Qt.PointingHandCursor)
        self.restore_btn.setFocusPolicy(Qt.NoFocus)
        self.restore_btn.clicked.connect(self._restore_selected)
        self.delete_btn = QPushButton(tr('彻底删除'))
        self.delete_btn.setObjectName('deleted_delete_btn')
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFocusPolicy(Qt.NoFocus)
        self.delete_btn.clicked.connect(self._hard_delete_selected)
        self.delete_all_btn = QPushButton(tr('全部彻底删除'))
        self.delete_all_btn.setObjectName('deleted_delete_btn')
        self.delete_all_btn.setCursor(Qt.PointingHandCursor)
        self.delete_all_btn.setFocusPolicy(Qt.NoFocus)
        self.delete_all_btn.clicked.connect(self._hard_delete_all)
        header_layout.addWidget(self.restore_btn)
        header_layout.addWidget(self.delete_btn)
        header_layout.addWidget(self.delete_all_btn)

        self.list = QListWidget()
        self.list.setObjectName('deleted_list')
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        self.list.itemDoubleClicked.connect(lambda _: self._restore_selected())

        layout.addWidget(header_box)
        layout.addWidget(self.list, 1)

        self._populate()

    def _populate(self):
        self.list.clear()
        items = self.storage.deleted_items()
        self.subtitle.setText(
            tr('{count} 项可恢复', count=len(items)) if items else tr('没有最近删除的项目')
        )
        if not items:
            empty = QLabel(tr('删除的备忘录、附件和截图会先保留在这里。'))
            empty.setObjectName('deleted_empty')
            empty.setAlignment(Qt.AlignCenter)
            it = QListWidgetItem()
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(QSize(0, 280))
            self.list.addItem(it)
            self.list.setItemWidget(it, empty)
            self._sync_buttons()
            return

        for data in items:
            title = self._item_title(data)
            detail = self._item_detail(data)
            item = QListWidgetItem(f'{title}\n{detail}')
            item.setData(Qt.UserRole, data)
            item.setSizeHint(QSize(0, 58))
            self.list.addItem(item)
        self._sync_buttons()

    def _item_title(self, data):
        if data.get('kind') == 'note':
            return tr('备忘录 · {title}', title=note_display_title(data.get('note') or {}))
        att = data.get('attachment') or {}
        name = att.get('memo') or att.get('archive_content') or att.get('original_name') or tr('附件')
        prefix = tr('截图') if is_image_attachment(att) else tr('附件')
        return tr('{kind} · {name}', kind=prefix, name=name)

    def _item_detail(self, data):
        time_text = format_time_long(data.get('time') or '') or tr('未知日期')
        if data.get('kind') == 'note':
            return tr('删除于 {time}', time=time_text)
        note = data.get('note') or {}
        return tr('来自 {title} · 删除于 {time}', title=note_display_title(note), time=time_text)

    def _selected_data(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def _sync_buttons(self):
        enabled = bool(self._selected_data())
        has_items = any(
            bool(self.list.item(i).data(Qt.UserRole))
            for i in range(self.list.count())
        )
        self.restore_btn.setEnabled(enabled)
        self.delete_btn.setEnabled(enabled)
        self.delete_all_btn.setEnabled(has_items)

    def _restore_selected(self):
        data = self._selected_data()
        if not data:
            return
        ok = False
        if data.get('kind') == 'note':
            note = data.get('note') or {}
            ok = self.storage.restore_note(note.get('id'))
        else:
            att = data.get('attachment') or {}
            ok = self.storage.restore_attachment(att.get('id'))
        if ok:
            self._populate()
            self.state_changed.emit()

    def _hard_delete_all(self):
        items = list(self.storage.deleted_items())
        if not items:
            return
        reply = QMessageBox.question(
            self,
            tr('全部彻底删除'),
            tr('确定要彻底删除最近删除里的全部 {count} 项吗？此操作无法撤销。', count=len(items)),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        changed = False
        # batch()：N 项删除只在最后落盘一次。之前每项都全量序列化+加密
        # +写盘，几十项就能让界面冻结数秒。
        with self.storage.batch():
            for data in items:
                if data.get('kind') == 'note':
                    note = data.get('note') or {}
                    changed = self.storage.hard_delete_note(note.get('id')) or changed
                else:
                    note = data.get('note') or {}
                    att = data.get('attachment') or {}
                    changed = self.storage.hard_remove_attachment(note.get('id'), att.get('id')) or changed
        if changed:
            self._populate()
            self.state_changed.emit()

    def _hard_delete_selected(self):
        data = self._selected_data()
        if not data:
            return
        reply = QMessageBox.question(
            self,
            tr('彻底删除'),
            tr('确定要彻底删除选中的项目吗？此操作无法撤销。'),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        ok = False
        if data.get('kind') == 'note':
            note = data.get('note') or {}
            ok = self.storage.hard_delete_note(note.get('id'))
        else:
            note = data.get('note') or {}
            att = data.get('attachment') or {}
            ok = self.storage.hard_remove_attachment(note.get('id'), att.get('id'))
        if ok:
            self._populate()
            self.state_changed.emit()


# ============ 通用后台任务 ============

class WorkerCancelled(Exception):
    """后台任务被用户取消。"""


class FuncWorker(QThread):
    """把一个函数放到工作线程执行，配合模态进度对话框使用。

    导出/导入备份、重加密这类长 I/O 之前全部在 UI 线程同步执行，
    数据量大时主窗口直接"未响应"。
    """
    progressed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn
        self.result = None
        self.error = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def check_cancelled(self):
        if self.cancelled:
            raise WorkerCancelled()

    def report(self, text):
        self.progressed.emit(str(text))

    def run(self):
        try:
            self.result = self._fn(self)
        except WorkerCancelled:
            self.cancelled = True
        except Exception as exc:
            self.error = exc
            logger.exception('后台任务失败')


def run_with_progress(parent, title, label, fn, cancellable=True):
    """在工作线程跑 fn(worker)，期间显示模态进度对话框。

    返回完成后的 FuncWorker（检查 .cancelled / .error / .result）。
    模态对话框同时阻止用户在任务进行中改动数据，避免并发修改。
    """
    worker = FuncWorker(fn)
    dlg = QProgressDialog(label, tr('取消') if cancellable else '', 0, 0, parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(300)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    if not cancellable:
        dlg.setCancelButton(None)
    worker.progressed.connect(dlg.setLabelText)
    if cancellable:
        dlg.canceled.connect(worker.cancel)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    dlg.show()
    loop.exec()
    try:
        dlg.canceled.disconnect()
    except Exception:
        pass
    dlg.close()
    dlg.deleteLater()
    return worker


# ============ 文件追踪扫描 ============

class FtrackScanWorker(QThread):
    """单个文件的"重点扫描"：先按 ADS 标记，找不到改按文件名兜底。"""
    progress = Signal(str)
    phase_changed = Signal(str)
    finished_with_result = Signal(object)

    def __init__(self, tracking, name_fallback=None, scan_settings=None, is_folder=False, parent=None):
        super().__init__(parent)
        self.tracking = tracking
        self.name_fallback = name_fallback
        self.scan_settings = scan_settings or {}
        self.is_folder = bool(is_folder)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _is_cancelled(self):
        return self._cancel

    def run(self):
        result = {'path': None, 'candidates': []}
        try:
            tag = self.tracking.get('tracking_id')
            name = self.name_fallback
            hint = self.tracking.get('drive_hint')
            es_path = self.scan_settings.get('es_path') if self.scan_settings.get('use_everything', True) else None

            # 1. File ID 快速恢复
            self.phase_changed.emit('正在按 File ID 查找')
            quick = ftrack.try_recover(self.tracking, scan=False)
            if quick:
                result['path'] = quick
                self.finished_with_result.emit(result)
                return

            # 1b. 文件夹：用固定标记名 .fresh_folder_id 快速定位。
            # 文件夹改名 / 内部文件增删改都不影响这个标记，所以与"现在叫什么"无关地把它找回。
            # 有 Everything 时一次查询秒级命中；没装/没开 Everything 时退化到只读目录 marker
            # 的全盘扫描（scan_for_folder_markers，文件夹版 scan_for_hash），仍不必逐文件读 ADS，
            # 比最后兜底的 scan_for_tag 快得多。
            if self.is_folder and tag and not self._cancel:
                paths = []
                if self.scan_settings.get('use_everything', True) and ftrack.everything_mode(es_path):
                    self.phase_changed.emit('按文件夹标记定位')
                    groups = ftrack.find_folders_by_marker(
                        {tag},
                        drive_hints=[hint] if hint else None,
                        es_path=es_path,
                        cancel=self._is_cancelled,
                    )
                    paths = groups.get(tag) or []
                if not paths and not self._cancel:
                    self.phase_changed.emit('按文件夹标记扫描')
                    marker_roots = recovery_scan_roots(self.scan_settings, [hint] if hint else None)
                    groups = ftrack.scan_for_folder_markers(
                        {tag},
                        roots=marker_roots,
                        drive_hints=[hint] if hint else None,
                        progress=lambda d: self.progress.emit(d),
                        cancel=self._is_cancelled,
                    )
                    paths = groups.get(tag) or []
                if len(paths) == 1:
                    result['path'] = paths[0]
                    self.finished_with_result.emit(result)
                    return
                if len(paths) > 1:
                    # 用户复制过同一文件夹（多个副本都带同一标记）——交给用户选择，
                    # 不自动采纳，避免指向错误的副本。
                    result['candidates'] = paths
                    self.finished_with_result.emit(result)
                    return

            # 2. ADS 全盘扫描。Everything 的按旧文件名查询可能漏掉“已改名的
            # 标签副本”，因此不能据其单个命中直接采纳；完整收集后才知道是否唯一。
            if not self._cancel and tag:
                self.phase_changed.emit('按追踪标记全盘扫描')
                scan_roots = recovery_scan_roots(self.scan_settings, [hint] if hint else None)
                tag_candidates = ftrack.scan_for_tag_candidates(
                    tag,
                    roots=scan_roots,
                    progress=lambda d: self.progress.emit(d),
                    cancel=self._is_cancelled,
                    drive_hints=[hint] if hint else None,
                )
                if len(tag_candidates) == 1:
                    result['path'] = tag_candidates[0]
                    self.finished_with_result.emit(result)
                    return
                if len(tag_candidates) > 1:
                    result['candidates'] = tag_candidates
                    self.finished_with_result.emit(result)
                    return

            # 3. 按名兜底 (Everything 优先 / os.walk)。
            # 文件夹有 .fresh_folder_id 时不能再按旧名兜底，否则改名后会扫旧目录名。
            if name and not self._cancel and not (self.is_folder and tag):
                self.phase_changed.emit('按文件名查找候选')
                size_hint = self.tracking.get('size_snapshot')
                cands = ftrack.find_candidates_by_name(
                    name,
                    drive_hint=hint,
                    size_hint=size_hint,
                    es_path=es_path,
                    fallback_walk=True,
                    cancel=self._is_cancelled,
                    progress=lambda d: self.progress.emit(d),
                )
                if cands and self.tracking.get('content_hash'):
                    hash_matches = [p for p in cands if ftrack.path_matches_hash(p, self.tracking)]
                    if len(hash_matches) == 1:
                        result['path'] = hash_matches[0]
                        self.finished_with_result.emit(result)
                        return
                    if hash_matches:
                        result['candidates'] = hash_matches
                        self.finished_with_result.emit(result)
                        return
                    # 有 hash 但没有一个候选对得上：这些只是同名文件，
                    # 不能被上层当成"已验证"自动采纳
                    result['unverified'] = True
                result['candidates'] = cands or []

            # 4. 内容 hash 全盘兜底（覆盖跨盘复制、ADS 丢失、改名）
            if not self._cancel and self.tracking.get('content_hash'):
                self.phase_changed.emit('按内容 hash 扫描')
                scan_roots = recovery_scan_roots(self.scan_settings, [hint] if hint else None)
                hash_matches = ftrack.scan_for_hash(
                    self.tracking,
                    roots=scan_roots,
                    progress=lambda d: self.progress.emit(d),
                    cancel=self._is_cancelled,
                    drive_hints=[hint] if hint else None,
                )
                if len(hash_matches) == 1:
                    result['path'] = hash_matches[0]
                    self.finished_with_result.emit(result)
                    return
                if hash_matches:
                    result['candidates'] = hash_matches
        except Exception as exc:
            # 扫描出错和"未找到"必须可区分，否则任何编码/权限问题都被伪装成文件不存在
            logger.exception('重点扫描失败')
            result['error'] = str(exc)
        if self._cancel and not result.get('path'):
            # 用户主动取消：不要再弹"未找到"或候选选择框
            result['cancelled'] = True
        self.finished_with_result.emit(result)


class AutoRecoveryWorker(QThread):
    """启动后自动跑：用 Everything (如果可用) 一次性把所有失踪的找回。"""
    progress = Signal(str, int)  # (current_dir, dirs_scanned_count)
    found_one = Signal(str, str)  # (tracking_id, path)
    finished_clean = Signal(int)  # 已扫目录数

    def __init__(
        self, tag_to_name, tag_to_tracking=None, drive_hints=None, scan_settings=None,
        tag_to_is_folder=None, tag_to_has_tag=None, parent=None,
    ):
        super().__init__(parent)
        self.tag_to_name = dict(tag_to_name)
        self.tag_to_tracking = dict(tag_to_tracking or {})
        self.tag_to_is_folder = dict(tag_to_is_folder or {})
        self.tag_to_has_tag = dict(tag_to_has_tag or {})
        self.drive_hints = list(drive_hints or [])
        self.scan_settings = scan_settings or {}
        self._cancel = False
        self._dirs_scanned = 0

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            def on_found(tag, path):
                self.found_one.emit(tag, path)

            def on_progress(directory):
                self._dirs_scanned += 1
                if self._dirs_scanned % 50 == 0:
                    self.progress.emit(directory, self._dirs_scanned)

            def on_phase(text):
                self.progress.emit(text, self._dirs_scanned)

            es_path = self.scan_settings.get('es_path') if self.scan_settings.get('use_everything', True) else None
            scan_roots = recovery_scan_roots(self.scan_settings, self.drive_hints)
            quick_roots = (self.scan_settings or {}).get('scan_roots') or []

            found = {}
            remaining = set(self.tag_to_tracking.keys())

            # 0. 文件夹：用固定标记名 .fresh_folder_id 一次性把改名/移动过的文件夹找回。
            # 与文件夹当前名无关，所以一条 Everything 查询就能批量定位；没装/没开 Everything
            # 时退化到只读目录 marker 的全盘扫描（scan_for_folder_markers，不依赖 Everything）。
            # 只有唯一命中才自动采纳，复制出多个副本（同一标记）的情况留给用户手动选择。
            folder_tags = {
                t for t in remaining
                if self.tag_to_is_folder.get(t) and self.tag_to_has_tag.get(t, True)
            }
            if folder_tags and not self._cancel:
                groups = {}
                if self.scan_settings.get('use_everything', True) and ftrack.everything_mode(es_path):
                    on_phase('用文件夹标记定位已移动的文件夹')
                    groups = ftrack.find_folders_by_marker(
                        folder_tags,
                        drive_hints=self.drive_hints,
                        es_path=es_path,
                        cancel=lambda: self._cancel,
                    ) or {}
                # Everything 没命中的（或没装 Everything）继续用不依赖 Everything 的
                # 只读目录 marker 全盘扫描兜底。
                still = {t for t in folder_tags if not groups.get(t)}
                if still and not self._cancel:
                    on_phase('按文件夹标记扫描已移动的文件夹')
                    scan_groups = ftrack.scan_for_folder_markers(
                        still,
                        roots=scan_roots,
                        drive_hints=self.drive_hints,
                        progress=on_progress,
                        cancel=lambda: self._cancel,
                    )
                    for t, paths in (scan_groups or {}).items():
                        if paths:
                            groups[t] = paths
                for tag, paths in (groups or {}).items():
                    if tag not in folder_tags:
                        continue
                    if len(paths) == 1:
                        found[tag] = paths[0]
                        remaining.discard(tag)
                        on_found(tag, paths[0])
                    elif len(paths) > 1:
                        # 多个副本带同一标记（用户复制过同一文件夹）——不自动认，
                        # 也从 remaining 移除以免后面的全盘扫描”先到先得”乱指；
                        # 留给用户在”重点查找”里手动选择正确的那个。
                        remaining.discard(tag)

            if remaining and not self._cancel:
                real_tag_remaining = {
                    tag for tag in remaining
                    if self.tag_to_has_tag.get(tag, True) and not self.tag_to_is_folder.get(tag)
                }
                if real_tag_remaining:
                    on_phase('按追踪标记扫描并排除重复副本')
                    found_by_tag = ftrack.scan_for_tags(
                        real_tag_remaining,
                        roots=scan_roots,
                        drive_hints=self.drive_hints,
                        on_found=on_found,
                        cancel=lambda: self._cancel,
                        progress=on_progress,
                        unique_only=True,
                    )
                    found.update(found_by_tag or {})
                    remaining -= set((found_by_tag or {}).keys())

            hash_targets = {
                tag: self.tag_to_tracking[tag]
                for tag in remaining
                if self.tag_to_tracking.get(tag, {}).get('content_hash')
            }
            if hash_targets and not self._cancel:
                on_phase('按内容 hash 扫描剩余文件')
                ftrack.scan_for_hashes(
                    hash_targets,
                    roots=scan_roots,
                    drive_hints=self.drive_hints,
                    on_found=on_found,
                    cancel=lambda: self._cancel,
                    progress=on_progress,
                    unique_only=True,
                )
            self.finished_clean.emit(self._dirs_scanned)
        except Exception:
            logger.exception('自动找回扫描失败')
            self.finished_clean.emit(0)


class ScanSettingsDialog(QDialog):
    """文件查找设置：es.exe 路径、扫描范围。"""

    def __init__(self, storage, parent=None):
        super().__init__(parent)
        self.setWindowTitle('文件查找设置')
        self.resize(700, 560)
        self.storage = storage
        self.settings = dict(storage.scan_settings)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(14)

        # ========== Everything 区 ==========
        es_group = QGroupBox('Everything 加速（强烈推荐）')
        es_layout = QVBoxLayout(es_group)
        es_layout.setSpacing(8)

        intro = QLabel('FRESH 优先用 Everything 的索引秒级定位文件，找不到再读 ADS 验证。\n'
                       '只要 Everything 主程序在跑，自动启用 IPC 直连模式（无需 es.exe）。')
        intro.setStyleSheet('color: #8E8E93;')
        intro.setWordWrap(True)
        es_layout.addWidget(intro)

        self.es_status_label = QLabel()
        self.es_status_label.setWordWrap(True)
        es_layout.addWidget(self.es_status_label)

        self.use_everything_chk = QCheckBox('启用 Everything 加速')
        self.use_everything_chk.setChecked(bool(self.settings.get('use_everything', True)))
        es_layout.addWidget(self.use_everything_chk)

        # 手动路径
        es_path_row = QHBoxLayout()
        es_path_row.setSpacing(8)
        es_path_row.addWidget(QLabel('es.exe 路径:'))
        self.es_path_edit = QLineEdit(self.settings.get('es_path', ''))
        self.es_path_edit.setPlaceholderText('留空 = 自动检测 PATH / 程序目录 / 常见安装目录')
        es_path_row.addWidget(self.es_path_edit, 1)
        es_browse = QPushButton('浏览...')
        es_browse.clicked.connect(self._browse_es)
        es_path_row.addWidget(es_browse)
        es_layout.addLayout(es_path_row)

        # 下载链接
        dl_row = QHBoxLayout()
        dl_label = QLabel('没装 es.exe？')
        dl_btn = QPushButton('打开 voidtools 下载页面')
        dl_btn.clicked.connect(self._open_download_page)
        dl_row.addWidget(dl_label)
        dl_row.addWidget(dl_btn)
        dl_row.addStretch()
        es_layout.addLayout(dl_row)

        # 检测按钮
        detect_btn = QPushButton('重新检测 es.exe')
        detect_btn.clicked.connect(self._refresh_es_status)
        es_layout.addWidget(detect_btn, 0, Qt.AlignLeft)

        layout.addWidget(es_group)

        # ========== 扫描范围 ==========
        roots_group = QGroupBox('扫描范围')
        roots_layout = QVBoxLayout(roots_group)
        roots_layout.setSpacing(8)

        hint = QLabel('指定的位置会被优先扫描；为覆盖跨盘剪切，找不到时仍会继续扫描全部本地磁盘'
                      '（含移动硬盘，不限 NTFS）。Everything 总是查询全盘索引。')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: #8E8E93;')
        roots_layout.addWidget(hint)

        self.roots_list = QListWidget()
        self.roots_list.setSelectionMode(QListWidget.SingleSelection)
        for r in self.settings.get('scan_roots', []) or []:
            self.roots_list.addItem(QListWidgetItem(r))
        roots_layout.addWidget(self.roots_list, 1)

        btn_row = QHBoxLayout()
        add_dir_btn = QPushButton('添加文件夹...')
        add_dir_btn.clicked.connect(self._add_dir)
        add_drive_btn = QPushButton('添加盘符...')
        add_drive_btn.clicked.connect(self._add_drive)
        remove_btn = QPushButton('移除选中')
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_dir_btn)
        btn_row.addWidget(add_drive_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        roots_layout.addLayout(btn_row)

        layout.addWidget(roots_group, 1)

        # ========== OK / Cancel ==========
        ok_row = QHBoxLayout()
        ok_row.addStretch()
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton('保存')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_save)
        ok_row.addWidget(cancel_btn)
        ok_row.addWidget(ok_btn)
        layout.addLayout(ok_row)

        self._refresh_es_status()

    def _refresh_es_status(self):
        manual = self.es_path_edit.text().strip()
        ftrack._ES_EXE_CACHE = None
        # IPC 模式（最优）
        try:
            ipc_ok = ftrack.everything_ipc and ftrack.everything_ipc.is_everything_running()
        except Exception:
            ipc_ok = False
        es_path = ftrack.find_es_exe(manual or None)

        if ipc_ok:
            text = '✅ Everything 正在运行 — 已启用 IPC 直连模式（最快，无需 es.exe）'
            color = '#34C759'
            if es_path:
                text += f'\n    （同时检测到 es.exe: {es_path}，作为备用）'
        elif es_path:
            text = f'✅ es.exe 已就绪: {es_path}\n    ⚠️ Everything 主程序未运行，请先打开 Everything 才能加速'
            color = '#FF9500'
        else:
            text = ('❌ 无 Everything 可用\n'
                    '    建议：1) 启动 Everything.exe 使用 IPC；或 2) 手动指定 es.exe / 放到 PATH')
            color = '#FF3B30'
        self.es_status_label.setText(text)
        self.es_status_label.setStyleSheet(f'color: {color};')

    def _update_everything_dir_tip_async(self):
        return

    def _open_download_page(self):
        QDesktopServices.openUrl(QUrl(ftrack.EVERYTHING_DOWNLOAD_URL))

    def _browse_es(self):
        start = self.es_path_edit.text().strip()
        if not start:
            start = ftrack.find_running_everything_dir() or ''
        f, _ = QFileDialog.getOpenFileName(self, '选择 es.exe', start, 'es.exe (es.exe);;所有文件 (*.*)')
        if f:
            self.es_path_edit.setText(f)
            self._refresh_es_status()

    def _add_dir(self):
        folder = QFileDialog.getExistingDirectory(self, '添加扫描根目录', '')
        if folder:
            existing = {self.roots_list.item(i).text() for i in range(self.roots_list.count())}
            if folder not in existing:
                self.roots_list.addItem(QListWidgetItem(folder))

    def _add_drive(self):
        roots = ftrack.local_drive_roots()
        if not roots:
            QMessageBox.information(self, '无可用盘', '未检测到本地盘符。')
            return
        existing = {self.roots_list.item(i).text() for i in range(self.roots_list.count())}
        available = [r for r in roots if r not in existing]
        if not available:
            QMessageBox.information(self, '已全部添加', '所有盘符都已在列表中。')
            return
        item, ok = QInputDialog.getItem(self, '选择盘符', '选择要添加的盘:', available, 0, False)
        if ok and item:
            self.roots_list.addItem(QListWidgetItem(item))

    def _remove_selected(self):
        for it in self.roots_list.selectedItems():
            self.roots_list.takeItem(self.roots_list.row(it))

    def _on_save(self):
        new_settings = {
            'es_path': self.es_path_edit.text().strip(),
            'use_everything': self.use_everything_chk.isChecked(),
            'scan_roots': [self.roots_list.item(i).text() for i in range(self.roots_list.count())],
        }
        self.storage.save_scan_settings(new_settings)
        self.accept()


class CustomizationDialog(QDialog):
    """In-app editor for UI text overrides and custom QSS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('外观与文字配置')
        self.resize(860, 640)
        self.setObjectName('customization_dialog')
        self._all_texts = load_text_config_values()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setObjectName('customization_tabs')
        self.tabs.addTab(self._build_text_tab(), '文字覆盖')
        self.tabs.addTab(self._build_style_tab(), '样式覆盖')
        layout.addWidget(self.tabs, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        open_folder_btn = QPushButton('打开配置文件夹')
        open_folder_btn.clicked.connect(self._open_folder)
        reset_btn = QPushButton('全部恢复默认')
        reset_btn.clicked.connect(self._reset_all_texts)
        button_row.addWidget(open_folder_btn)
        button_row.addWidget(reset_btn)
        button_row.addStretch()

        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton('保存并应用')
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(save_btn)
        layout.addLayout(button_row)

        self._populate_text_table()

    def _open_folder(self):
        directory = ensure_custom_files()
        text_config_path()
        custom_qss_path()
        if not open_local_path(directory):
            QMessageBox.warning(self, '打开失败', f'文件夹不存在或无法打开:\n{directory}')

    def _build_text_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        hint = QLabel('这里修改界面文字。左侧是程序原文，右侧是实际显示文字。')
        hint.setObjectName('customization_hint')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self.text_search = QLineEdit()
        self.text_search.setPlaceholderText('搜索界面文字')
        self.text_search.setClearButtonEnabled(True)
        self.text_search.textChanged.connect(self._populate_text_table)
        reset_selected_btn = QPushButton('恢复选中默认')
        reset_selected_btn.clicked.connect(self._reset_selected_text)
        search_row.addWidget(self.text_search, 1)
        search_row.addWidget(reset_selected_btn)
        layout.addLayout(search_row)

        self.text_table = QTableWidget(0, 2)
        self.text_table.setObjectName('customization_text_table')
        self.text_table.setHorizontalHeaderLabels(['原文', '显示文字'])
        self.text_table.verticalHeader().hide()
        self.text_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.text_table.setSelectionMode(QTableWidget.SingleSelection)
        self.text_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.text_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.text_table.itemChanged.connect(self._on_text_item_changed)
        layout.addWidget(self.text_table, 1)
        return page

    def _build_style_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(10)

        hint = QLabel('这里编辑 custom.qss，会追加在内置样式之后。保存后立即应用。')
        hint.setObjectName('customization_hint')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.qss_edit = QPlainTextEdit()
        self.qss_edit.setObjectName('customization_qss_editor')
        self.qss_edit.setPlainText(load_custom_qss_text())
        self.qss_edit.setTabStopDistance(28)
        layout.addWidget(self.qss_edit, 1)
        return page

    def _populate_text_table(self):
        query = (self.text_search.text() if hasattr(self, 'text_search') else '').strip().lower()
        rows = []
        for source in DEFAULT_TEXTS:
            value = self._all_texts.get(source, DEFAULT_TEXTS[source])
            haystack = f'{source}\n{value}'.lower()
            if not query or query in haystack:
                rows.append((source, value))

        self.text_table.blockSignals(True)
        self.text_table.setRowCount(len(rows))
        for row, (source, value) in enumerate(rows):
            source_item = QTableWidgetItem(source)
            source_item.setFlags(source_item.flags() & ~Qt.ItemIsEditable)
            source_item.setData(Qt.UserRole, source)
            value_item = QTableWidgetItem(value)
            value_item.setData(Qt.UserRole, source)
            self.text_table.setItem(row, 0, source_item)
            self.text_table.setItem(row, 1, value_item)
        self.text_table.blockSignals(False)

    def _on_text_item_changed(self, item):
        if item.column() != 1:
            return
        source = item.data(Qt.UserRole)
        if source:
            self._all_texts[source] = item.text()

    def _reset_selected_text(self):
        row = self.text_table.currentRow()
        if row < 0:
            return
        source_item = self.text_table.item(row, 0)
        value_item = self.text_table.item(row, 1)
        if not source_item or not value_item:
            return
        source = source_item.data(Qt.UserRole)
        if source in DEFAULT_TEXTS:
            self._all_texts[source] = DEFAULT_TEXTS[source]
            value_item.setText(DEFAULT_TEXTS[source])

    def _reset_all_texts(self):
        self._all_texts = dict(DEFAULT_TEXTS)
        self._populate_text_table()

    def _missing_placeholders(self):
        problems = []
        for source, default in DEFAULT_TEXTS.items():
            expected = set(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', source))
            value = self._all_texts.get(source, default)
            actual = set(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', value))
            missing = sorted(expected - actual)
            if missing:
                problems.append(f'{source} -> 缺少 {", ".join(missing)}')
            # 多出/拼错的占位符同样致命：format 会抛 KeyError，整句回退原文
            unknown = sorted(actual - expected)
            if unknown:
                problems.append(f'{source} -> 未知占位符 {", ".join(unknown)}')
        return problems

    def _save(self):
        missing = self._missing_placeholders()
        if missing:
            reply = QMessageBox.question(
                self,
                '占位符问题',
                tr('下面这些文字的占位符有问题，保存后动态数字或名称可能无法显示：\n\n{items}\n\n仍然保存吗？',
                   items='\n'.join(missing[:8])),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        qss_text = self.qss_edit.toPlainText()
        qss_warnings = validate_qss_text(qss_text)
        if qss_warnings:
            # Qt 对非法 QSS 只在控制台打 warning 然后静默忽略整条规则，
            # 用户只会看到"没生效"——保存前必须提示
            reply = QMessageBox.question(
                self,
                'QSS 语法警告',
                tr('自定义样式可能存在语法问题：\n\n{items}\n\n有问题的规则会被 Qt 静默忽略。仍然保存吗？',
                   items='\n'.join(qss_warnings[:6])),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        try:
            save_text_config_values(self._all_texts)
            save_custom_qss_text(qss_text)
        except Exception as e:
            QMessageBox.warning(self, '保存失败', tr('无法保存配置：{error}', error=e))
            return
        self.accept()


class ShortcutsDialog(QDialog):
    """列出所有快捷键并允许编辑/重置。"""

    def __init__(self, parent, actions, settings):
        super().__init__(parent)
        self.setWindowTitle('快捷键设置')
        self.resize(560, 480)
        self._actions = actions
        self._settings = settings
        self._editors = {}     # action_id -> QKeySequenceEdit
        self._defaults = {}    # action_id -> default seq str
        self.result_map = {}   # 提交时 = action_id -> seq str

        layout = QVBoxLayout(self)

        tip = QLabel(
            '点击右侧输入框按下需要的组合键即可改动。\n'
            '清空输入框 = 禁用此快捷键。点击「重置默认」恢复全部出厂设定。'
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        table = QTableWidget(self)
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(['功能', '快捷键', '默认'])
        table.setRowCount(len(actions))
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        table.setColumnWidth(1, 180)
        table.setColumnWidth(2, 140)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)

        for row, (action_id, label, default_seq, _handler, _context) in enumerate(actions):
            self._defaults[action_id] = default_seq
            name_item = QTableWidgetItem(label)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, name_item)

            current = settings.value(f'shortcuts/{action_id}', default_seq)
            if not isinstance(current, str):
                current = default_seq

            editor = QKeySequenceEdit(QKeySequence(current))
            try:
                editor.setMaximumSequenceLength(1)
            except Exception:
                pass
            # QKeySequenceEdit 自身没有清空手段，提示里却写着"清空=禁用"
            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(0, 0, 0, 0)
            cell_layout.setSpacing(4)
            clear_btn = QPushButton('✕')
            clear_btn.setFixedSize(22, 22)
            clear_btn.setToolTip('清除（禁用此快捷键）')
            clear_btn.setCursor(Qt.PointingHandCursor)
            clear_btn.clicked.connect(editor.clear)
            cell_layout.addWidget(editor, 1)
            cell_layout.addWidget(clear_btn, 0)
            self._editors[action_id] = editor
            table.setCellWidget(row, 1, cell)

            default_item = QTableWidgetItem(default_seq or '（无）')
            default_item.setFlags(default_item.flags() & ~Qt.ItemIsEditable)
            default_item.setForeground(QColor('#888'))
            table.setItem(row, 2, default_item)

        layout.addWidget(table, 1)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton('重置默认')
        reset_btn.clicked.connect(self._reset_defaults)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton('保存')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _reset_defaults(self):
        for action_id, editor in self._editors.items():
            editor.setKeySequence(QKeySequence(self._defaults.get(action_id, '')))

    def _on_accept(self):
        # 校验：不允许同一组合绑定到多个动作
        seen = {}
        for action_id, editor in self._editors.items():
            seq = editor.keySequence().toString()
            if not seq:
                continue
            if seq in seen:
                QMessageBox.warning(
                    self, '快捷键冲突',
                    f'「{seq}」同时绑定到多个功能，请修改后再保存。'
                )
                return
            seen[seq] = action_id

        for action_id, editor in self._editors.items():
            self.result_map[action_id] = editor.keySequence().toString()
        self.accept()


class CandidatePickerDialog(QDialog):
    def __init__(self, candidates, attachment_name, size_hint=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('选择匹配的文件')
        self.resize(720, 420)
        self.selected_path = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        hint = f'扫描到 {len(candidates)} 个同名文件，请选择哪个是 "{attachment_name}"：'
        if size_hint:
            hint += f'（原文件大小 {format_size(size_hint)}，已用 ★ 标出匹配项）'
        hint_label = QLabel(hint)
        hint_label.setWordWrap(True)  # 长文件名不再把对话框撑爆
        layout.addWidget(hint_label)

        self.list_widget = QListWidget()
        for path in candidates:
            label = path
            try:
                sz = os.path.getsize(path)
                marker = '★ ' if size_hint and sz == size_hint else '   '
                label = f"{marker}{path}    [{format_size(sz)}]"
            except OSError:
                pass
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, path)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self._accept_selected)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton('取消')
        cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton('选定')
        self.ok_btn.setDefault(True)
        self.ok_btn.setEnabled(False)  # 未选中时置灰，点了才不会"毫无反应"
        self.ok_btn.clicked.connect(self._accept_selected)
        self.list_widget.itemSelectionChanged.connect(
            lambda: self.ok_btn.setEnabled(self.list_widget.currentItem() is not None)
        )
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.ok_btn)
        layout.addLayout(btn_row)

    def _accept_selected(self, *_):
        item = self.list_widget.currentItem()
        if not item:
            return
        self.selected_path = item.data(Qt.UserRole)
        self.accept()


def make_scan_dialog(parent, name):
    dlg = QProgressDialog(
        f'正在后台查找"{name}"...',
        '取消', 0, 0, parent,
    )
    dlg.setWindowTitle('查找已移动的文件')
    dlg.setWindowModality(Qt.NonModal)
    dlg.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowTitleHint | Qt.WindowSystemMenuHint)
    dlg.setMinimumDuration(0)
    dlg.setMinimumWidth(460)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    return dlg


# ============ 附件卡片 ============

class AttachmentCard(QFrame):
    delete_requested = Signal(str)
    category_change_requested = Signal(str)

    EXT_COLORS = {
        '.png': '#FF9500', '.jpg': '#FF9500', '.jpeg': '#FF9500',
        '.gif': '#FF9500', '.bmp': '#FF9500', '.webp': '#FF9500', '.svg': '#FF9500',
        '.pdf': '#FF3B30',
        '.doc': '#2B7DE9', '.docx': '#2B7DE9', '.rtf': '#2B7DE9',
        '.xls': '#34C759', '.xlsx': '#34C759', '.csv': '#34C759',
        '.ppt': '#FF6B35', '.pptx': '#FF6B35',
        '.mp4': '#AF52DE', '.mov': '#AF52DE', '.avi': '#AF52DE', '.mkv': '#AF52DE',
        '.mp3': '#FF2D55', '.wav': '#FF2D55', '.flac': '#FF2D55', '.m4a': '#FF2D55',
        '.zip': '#8E8E93', '.rar': '#8E8E93', '.7z': '#8E8E93', '.tar': '#8E8E93',
        '.txt': '#5856D6', '.md': '#5856D6',
        '.py': '#3776AB', '.js': '#F0B000', '.html': '#E34F26', '.css': '#1572B6',
        '.json': '#444444', '.xml': '#0060AC',
    }

    def __init__(self, attachment, file_path, recover_resolver=None):
        super().__init__()
        self.attachment = attachment
        self.file_path = Path(file_path)
        self.recover_resolver = recover_resolver
        self.is_folder = (attachment.get('type') == 'folder')
        self.setObjectName('attachment_card')
        self.setFixedSize(174, 64)
        self.setProperty('categorized', bool((attachment.get('archive_category') or attachment.get('category') or '').strip()))
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        kind = '文件夹' if self.is_folder else '文件'
        category = (attachment.get('archive_category') or attachment.get('category') or '').strip()
        tooltip = f"{attachment['original_name']} ({kind})\n双击打开 · 右键更多"
        if category:
            tooltip = f'{tooltip}\n#{category}'
        self.setToolTip(tooltip)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setFixedSize(36, 44)
        icon_label.setPixmap(self._build_icon())
        icon_label.setAlignment(Qt.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        name_label = QLabel()
        name_label.setObjectName('att_name')
        metrics = QFontMetrics(name_label.font())
        elided = metrics.elidedText(attachment['original_name'], Qt.ElideMiddle, 104)
        name_label.setText(elided)

        if self.is_folder:
            sub_text = '文件夹'
        else:
            sub_text = format_size(attachment.get('size', 0))
        size_label = QLabel(sub_text)
        size_label.setObjectName('att_size')
        size_label.setText(QFontMetrics(size_label.font()).elidedText(sub_text, Qt.ElideRight, 46 if category else 104))

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(5)
        meta_row.addWidget(size_label)
        if category:
            badge = QLabel()
            badge.setObjectName('att_category_badge')
            badge_text = f'#{category}'
            badge.setText(QFontMetrics(badge.font()).elidedText(badge_text, Qt.ElideRight, 54))
            badge.setToolTip(badge_text)
            badge.setFixedHeight(17)
            badge.setMaximumWidth(62)
            meta_row.addWidget(badge)
        meta_row.addStretch()

        text_layout.addStretch()
        text_layout.addWidget(name_label)
        text_layout.addLayout(meta_row)
        text_layout.addStretch()

        layout.addWidget(icon_label)
        layout.addLayout(text_layout, 1)

        self.delete_btn = QPushButton('×', self)
        self.delete_btn.setObjectName('att_delete_btn')
        self.delete_btn.setFixedSize(22, 22)
        self.delete_btn.move(self.width() - 28, 6)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setFocusPolicy(Qt.NoFocus)
        self.delete_btn.setAttribute(Qt.WA_NoMousePropagation, True)
        self.delete_btn.setToolTip('删除')
        self.delete_btn.hide()
        self.delete_btn.clicked.connect(lambda: self.delete_requested.emit(self.attachment['id']))

    def _build_icon(self):
        if self.is_folder:
            return self._build_folder_icon()
        return self._build_file_icon()

    def _build_folder_icon(self):
        return build_folder_icon()

    def _build_file_icon(self):
        return build_file_icon(self.file_path, colors=self.EXT_COLORS)

    def mouseDoubleClickEvent(self, event):
        self._open_file()
        super().mouseDoubleClickEvent(event)

    def enterEvent(self, event):
        self.delete_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.delete_btn.hide()
        super().leaveEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        open_action = menu.addAction('打开')
        reveal_action = menu.addAction('在文件夹中显示')
        category_action = menu.addAction(tr('修改分类'))
        find_action = None
        if self.attachment.get('tracking'):
            menu.addSeparator()
            label = '重新定位文件...' if self.file_path.exists() else '查找已移动的文件...'
            find_action = menu.addAction(label)
        menu.addSeparator()
        delete_action = menu.addAction('从备忘录中移除')

        action = menu.exec(event.globalPos())
        if action == open_action:
            self._open_file()
        elif action == reveal_action:
            self._reveal_in_folder()
        elif action == category_action:
            self.category_change_requested.emit(self.attachment['id'])
        elif find_action is not None and action == find_action:
            self._scan_recover()
        elif action == delete_action:
            self.delete_requested.emit(self.attachment['id'])

    def _scan_recover(self):
        if not self.recover_resolver:
            QMessageBox.information(self, '无法查找', '该附件加入时未生成追踪标记，无法定位。')
            return
        # 委托给 MainWindow 去启动后台扫描；不阻塞当前 UI
        self.recover_resolver(self.attachment, request_scan=True)

    def _request_recovery_scan(self):
        if not self.recover_resolver or not self.attachment.get('tracking'):
            return False
        self.recover_resolver(self.attachment, request_scan=True)
        return True

    def _ensure_path(self):
        """路径若失效，尝试通过 recover_resolver 找回新位置。返回是否可访问。"""
        if self.recover_resolver and self.attachment.get('tracking'):
            new_path = self.recover_resolver(self.attachment)
            if new_path and Path(new_path).exists():
                self.file_path = Path(new_path)
                return True
            return False
        if self.file_path.exists():
            return True
        if not self.recover_resolver:
            return False
        new_path = self.recover_resolver(self.attachment)
        if new_path and Path(new_path).exists():
            self.file_path = Path(new_path)
            return True
        return False

    def _open_file(self):
        if not self._ensure_path():
            msg = '该文件夹已被移动或删除。' if self.is_folder else '该附件文件已被移动或删除。'
            if self._request_recovery_scan():
                self.setToolTip(tr('{msg}\n正在查找当前位置。', msg=msg))
                return
            QMessageBox.warning(self, '路径不存在', msg)
            return
        if not open_local_path(self.file_path):
            QMessageBox.warning(self, '打开失败', f'无法打开:\n{self.file_path}')

    def _reveal_in_folder(self):
        if not self._ensure_path():
            if self._request_recovery_scan():
                return
            QMessageBox.warning(self, '路径不存在', '该附件已被移动或删除。')
            return
        if not reveal_in_file_manager(self.file_path):
            QMessageBox.warning(self, '定位失败', f'无法定位:\n{self.file_path}')


# ============ 附件栏 ============

class AttachmentBar(QWidget):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('attachment_bar')
        # 自定义 QWidget 子类默认不画 QSS 背景/边框：不开这个属性，
        # #attachment_bar 的底色和 border-top 分隔线整条都不会渲染
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(128)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 12, 48, 16)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel('附件')
        title.setObjectName('att_section_title')
        self.category_filter = QComboBox()
        self.category_filter.setObjectName('att_category_filter')
        self.category_filter.addItem(tr('全部附件'), '')
        self.category_filter.currentIndexChanged.connect(lambda _: self._render_attachments())
        self.hint = QLabel('拖入文件或文件夹')
        self.hint.setObjectName('att_hint')
        self.add_btn = QPushButton('+')
        self.add_btn.setObjectName('att_add_btn')
        self.add_btn.setFixedSize(24, 24)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.browse_file)
        header.addWidget(title)
        header.addWidget(self.category_filter)
        header.addStretch()
        header.addWidget(self.hint)
        header.addWidget(self.add_btn)

        self.scroll = QScrollArea()
        self.scroll.setObjectName('att_scroll')
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        self.scroll_content = QWidget()
        self.scroll_content.setObjectName('att_scroll_content')
        self.scroll_layout = QHBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.addStretch()

        self.empty_label = QLabel('')
        self.empty_label.setObjectName('att_empty')
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.scroll.setWidget(self.scroll_content)

        layout.addLayout(header)
        layout.addWidget(self.scroll)

        self._attachments = []
        self._path_resolver = None
        self._on_delete = None
        self._recover_resolver = None
        self._on_category_change = None
        self._attachment_signature = ()

    def set_attachments(self, attachments, path_resolver, on_delete, recover_resolver=None, on_category_change=None):
        self._attachments = list(attachments or [])
        signature = tuple(att.get('id', '') for att in self._attachments)
        reset_filter = signature != self._attachment_signature
        self._attachment_signature = signature
        self._path_resolver = path_resolver
        self._on_delete = on_delete
        self._recover_resolver = recover_resolver
        self._on_category_change = on_category_change
        self._refresh_category_filter(reset=reset_filter)
        self._render_attachments()

    def _attachment_category(self, attachment):
        return (attachment.get('archive_category') or attachment.get('category') or '').strip()

    def _selected_category(self):
        return self.category_filter.currentData() or ''

    def _refresh_category_filter(self, reset=False):
        current = '' if reset else self._selected_category()
        categories = sorted({
            self._attachment_category(att)
            for att in self._attachments
            if self._attachment_category(att)
        })
        if current and current not in categories:
            current = ''
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem(tr('全部附件'), '')
        for category in categories:
            self.category_filter.addItem(category, category)
        index = 0
        if current:
            for i in range(self.category_filter.count()):
                if self.category_filter.itemData(i) == current:
                    index = i
                    break
        self.category_filter.setCurrentIndex(index)
        self.category_filter.setVisible(bool(categories))
        self.category_filter.blockSignals(False)

    def _clear_cards(self):
        while self.scroll_layout.count() > 0:
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is self.empty_label:
                widget.hide()
                widget.setParent(None)
            elif widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _render_attachments(self):
        self._clear_cards()
        category = self._selected_category()
        attachments = [
            att for att in self._attachments
            if not category or self._attachment_category(att) == category
        ]
        if attachments:
            for att in attachments:
                try:
                    card = AttachmentCard(att, self._path_resolver(att), recover_resolver=self._recover_resolver)
                    if self._on_delete is not None:
                        card.delete_requested.connect(self._on_delete)
                    if self._on_category_change is not None:
                        card.category_change_requested.connect(self._on_category_change)
                    self.scroll_layout.addWidget(card)
                except Exception:
                    # 渲染失败的附件不能无声消失——给个占位提示并记日志
                    logger.exception('附件卡片渲染失败: %s', att.get('original_name', ''))
                    broken = QLabel(tr('附件 {name} 显示失败',
                                       name=att.get('original_name', '') or att.get('id', '')))
                    broken.setObjectName('attachment_render_error')
                    broken.setWordWrap(True)
                    self.scroll_layout.addWidget(broken)
        elif self._attachments:
            self.empty_label.setText(tr('这个分类下没有附件'))
            self.scroll_layout.addWidget(self.empty_label)
            self.empty_label.show()
        else:
            self.empty_label.setText(tr('暂无附件'))
            self.scroll_layout.addWidget(self.empty_label)
            self.empty_label.show()
        self.scroll_layout.addStretch()

    def browse_file(self):
        menu = QMenu(self)
        file_action = menu.addAction('选择文件...')
        folder_action = menu.addAction('选择文件夹...')
        action = menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))
        if action == file_action:
            files, _ = QFileDialog.getOpenFileNames(self, '选择文件', '', '所有文件 (*.*)')
            for f in files:
                self.file_dropped.emit(f)
        elif action == folder_action:
            folder = QFileDialog.getExistingDirectory(self, '选择文件夹', '')
            if folder:
                self.file_dropped.emit(folder)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.file_dropped.emit(url.toLocalFile())
            event.acceptProposedAction()


# ============ 支持拖拽文件的富文本编辑器 ============

class DropTextEdit(QTextEdit):
    file_dropped = Signal(str)
    image_pasted = Signal(str)

    def canInsertFromMimeData(self, source):
        if source.hasUrls() or source.hasImage():
            return True
        return super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            handled = False
            for url in source.urls():
                if url.isLocalFile():
                    self.file_dropped.emit(url.toLocalFile())
                    handled = True
            if handled:
                return
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QPixmap):
                img = img.toImage()
            if isinstance(img, QImage) and not img.isNull():
                ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                tmp_dir = Path(tempfile.gettempdir())
                tmp = tmp_dir / f'截图_{ts}.png'
                idx = 1
                while tmp.exists():
                    tmp = tmp_dir / f'截图_{ts}_{idx}.png'
                    idx += 1
                if img.save(str(tmp), 'PNG'):
                    self.image_pasted.emit(str(tmp))
                    return
        super().insertFromMimeData(source)


# ============ 编辑器 ============

class NoteEditor(QWidget):
    title_changed = Signal(str)
    content_changed = Signal(str)
    category_changed = Signal(str)
    file_dropped = Signal(str)
    image_pasted = Signal(str)
    mode_changed = Signal(str)
    open_image = Signal(str)
    delete_attachment = Signal(str)
    archive_attachment = Signal(str)
    memo_changed = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self._loading = False
        self._content_format = 'rich'

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 30, 48, 28)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(12)

        self.title_input = QLineEdit()
        self.title_input.setObjectName('title_input')
        self.title_input.setPlaceholderText('未命名备忘录')
        self.title_input.textChanged.connect(self._on_title_changed)

        self.mode_switch = ModeSwitch()
        self.mode_switch.changed.connect(self._on_mode_changed)
        self.mode_switch.hide()

        title_row.addWidget(self.title_input, 1)
        title_row.addWidget(self.mode_switch, 0, Qt.AlignBottom)

        self.time_label = QLabel('')
        self.time_label.setObjectName('editor_time')

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(10)
        time_row.addWidget(self.time_label, 0, Qt.AlignVCenter)
        time_row.addStretch()

        self.category_combo = QComboBox()
        self.category_combo.setObjectName('note_category_combo')
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.NoInsert)
        self.category_combo.lineEdit().setPlaceholderText(tr('分类'))
        self.category_combo.setToolTip(tr('分类'))
        # currentTextChanged 已覆盖手动输入，重复连 lineEdit 会让信号每键发两遍
        self.category_combo.currentTextChanged.connect(self._on_category_changed)
        self.format_switch = TextFormatSwitch()
        self.format_switch.changed.connect(self._on_content_format_changed)
        time_row.addWidget(self.format_switch, 0, Qt.AlignRight | Qt.AlignVCenter)
        time_row.addWidget(self.category_combo, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.divider = QFrame()
        self.divider.setObjectName('divider')
        self.divider.setFrameShape(QFrame.HLine)
        self.divider.setFixedHeight(1)

        self.content_edit = DropTextEdit()
        self.content_edit.setObjectName('content_edit')
        self.content_edit.setPlaceholderText('开始记录...')
        self.content_edit.textChanged.connect(self._on_content_changed)
        self.content_edit.file_dropped.connect(self.file_dropped)
        self.content_edit.image_pasted.connect(self.image_pasted)
        self.content_edit.cursorPositionChanged.connect(self._sync_format_buttons)

        font = QFont()
        font.setPointSize(11)
        self.content_edit.setFont(font)

        self.format_toolbar = self._build_format_toolbar()

        self.screenshot_grid = ScreenshotGrid()
        self.screenshot_grid.file_dropped.connect(self.file_dropped)
        self.screenshot_grid.image_pasted.connect(self.image_pasted)
        self.screenshot_grid.open_requested.connect(self.open_image)
        self.screenshot_grid.delete_requested.connect(self.delete_attachment)
        self.screenshot_grid.archive_toggled.connect(self.archive_attachment)
        self.screenshot_grid.memo_changed.connect(self.memo_changed)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.content_edit)
        self.content_stack.addWidget(self.screenshot_grid)

        layout.addLayout(title_row)
        layout.addLayout(time_row)
        layout.addLayout(self.format_toolbar)
        layout.addWidget(self.divider)
        layout.addWidget(self.content_stack, 1)
        # 让 acceptRichText 等 UI 状态与初始 _content_format 保持同步
        self._sync_content_format_ui()

    def _build_format_toolbar(self):
        toolbar = QHBoxLayout()
        toolbar.setObjectName('format_toolbar')
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self.bold_btn = self._format_button('B', '加粗')
        self.bold_btn.setCheckable(True)
        self.bold_btn.clicked.connect(self._toggle_bold)
        self.italic_btn = self._format_button('I', '斜体')
        self.italic_btn.setCheckable(True)
        self.italic_btn.clicked.connect(self._toggle_italic)
        self.underline_btn = self._format_button('U', '下划线')
        self.underline_btn.setCheckable(True)
        self.underline_btn.clicked.connect(self._toggle_underline)
        self.bullet_btn = self._format_button('•', '项目符号列表')
        self.bullet_btn.clicked.connect(self._insert_bullet_list)
        self.clear_format_btn = self._format_button('Tx', '清除格式')
        self.clear_format_btn.clicked.connect(self._clear_selection_format)

        for btn in (
            self.bold_btn,
            self.italic_btn,
            self.underline_btn,
            self.bullet_btn,
            self.clear_format_btn,
        ):
            toolbar.addWidget(btn)
        toolbar.addStretch()

        # 键盘可达性：工具栏按钮都是 NoFocus，必须给标准快捷键
        for seq, handler in (
            (QKeySequence.Bold, self._toggle_bold),
            (QKeySequence.Italic, self._toggle_italic),
            (QKeySequence.Underline, self._toggle_underline),
        ):
            shortcut = QShortcut(seq, self.content_edit)
            shortcut.setContext(Qt.WidgetShortcut)
            shortcut.activated.connect(self._shortcut_format_handler(handler))
        return toolbar

    def _shortcut_format_handler(self, handler):
        def run():
            # Markdown 模式下富文本格式不可用
            if self._content_format != 'markdown':
                handler()
        return run

    def _format_button(self, text, tooltip):
        btn = QPushButton(text)
        btn.setObjectName('format_btn')
        btn.setFixedSize(30, 30)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setToolTip(tooltip)
        return btn

    def _merge_char_format(self, fmt):
        cursor = self.content_edit.textCursor()
        cursor.mergeCharFormat(fmt)
        self.content_edit.mergeCurrentCharFormat(fmt)
        self.content_edit.setFocus()

    def _toggle_bold(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if self.content_edit.fontWeight() == QFont.Bold else QFont.Bold)
        self._merge_char_format(fmt)
        self._sync_format_buttons()

    def _toggle_italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.content_edit.fontItalic())
        self._merge_char_format(fmt)
        self._sync_format_buttons()

    def _toggle_underline(self):
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not self.content_edit.fontUnderline())
        self._merge_char_format(fmt)
        self._sync_format_buttons()

    def _insert_bullet_list(self):
        cursor = self.content_edit.textCursor()
        cursor.beginEditBlock()
        list_format = QTextListFormat()
        list_format.setStyle(QTextListFormat.ListDisc)
        cursor.createList(list_format)
        cursor.endEditBlock()
        self.content_edit.setTextCursor(cursor)
        self.content_edit.setFocus()

    def _clear_selection_format(self):
        cursor = self.content_edit.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(11)
        cursor.mergeCharFormat(fmt)
        block_fmt = cursor.blockFormat()
        block_fmt.setObjectIndex(-1)
        cursor.setBlockFormat(block_fmt)
        self.content_edit.setCurrentCharFormat(fmt)
        self.content_edit.setFocus()
        self._sync_format_buttons()

    def _sync_format_buttons(self):
        if not hasattr(self, 'bold_btn'):
            return
        if getattr(self, '_content_format', 'rich') == 'markdown':
            return
        self.bold_btn.blockSignals(True)
        self.italic_btn.blockSignals(True)
        self.underline_btn.blockSignals(True)
        self.bold_btn.setChecked(self.content_edit.fontWeight() == QFont.Bold)
        self.italic_btn.setChecked(self.content_edit.fontItalic())
        self.underline_btn.setChecked(self.content_edit.fontUnderline())
        self.bold_btn.blockSignals(False)
        self.italic_btn.blockSignals(False)
        self.underline_btn.blockSignals(False)

    def load_note(self, note):
        self._loading = True
        try:
            self.title_input.setText(note.get('title', ''))
            self.category_combo.lineEdit().setText((note.get('category') or '').strip())
            content = note.get('content', '') or ''
            self._content_format = 'markdown' if note.get('content_format') == 'markdown' else 'rich'
            self.format_switch.set_format(self._content_format, emit=False)
            if self._content_format == 'markdown':
                self.content_edit.setPlainText(content)
            elif looks_like_qt_html(content):
                self.content_edit.setHtml(content)
            else:
                self.content_edit.setPlainText(content)
            self._sync_content_format_ui()
            self.time_label.setText(format_time_long(note.get('updated_at', '')))
            self.set_mode('text')
        finally:
            self._loading = False

    def set_mode(self, mode):
        self.mode_switch.set_mode(mode, emit=False)
        if mode == 'screenshot':
            self.content_stack.setCurrentWidget(self.screenshot_grid)
            self.screenshot_grid.setFocus()
        else:
            self.content_stack.setCurrentWidget(self.content_edit)

    def get_mode(self):
        return 'text'

    def update_screenshot_grid(self, attachments, path_resolver):
        self.screenshot_grid.set_attachments(attachments, path_resolver)

    def clear(self):
        self._loading = True
        try:
            self.title_input.clear()
            self.category_combo.lineEdit().clear()
            self._content_format = 'rich'
            self.format_switch.set_format('rich', emit=False)
            self._sync_content_format_ui()
            self.content_edit.clear()
            self.time_label.clear()
            self.set_mode('text')
            self.screenshot_grid.set_attachments([], lambda a: Path(''))
        finally:
            self._loading = False

    def get_title(self):
        return self.title_input.text().strip()

    def get_content(self):
        if not self.content_edit.toPlainText().strip():
            return ''
        if self._content_format == 'markdown':
            return self.content_edit.toPlainText()
        return self.content_edit.toHtml()

    def get_content_format(self):
        return self._content_format

    def get_category(self):
        return self.category_combo.currentText().strip()

    def set_categories(self, categories):
        current = self.get_category()
        self.category_combo.blockSignals(True)
        if self.category_combo.lineEdit():
            self.category_combo.lineEdit().blockSignals(True)
        try:
            self.category_combo.clear()
            for category in categories or []:
                category = (category or '').strip()
                if category:
                    self.category_combo.addItem(category)
            self.category_combo.lineEdit().setText(current)
        finally:
            if self.category_combo.lineEdit():
                self.category_combo.lineEdit().blockSignals(False)
            self.category_combo.blockSignals(False)

    def update_time_label(self, iso_time):
        self.time_label.setText(format_time_long(iso_time))

    def focus_title(self):
        self.title_input.setFocus()

    def focus_body(self):
        if self.content_stack.currentWidget() == self.screenshot_grid:
            self.screenshot_grid.setFocus()
        else:
            self.content_edit.setFocus()

    def _on_title_changed(self, text):
        if not self._loading:
            self.title_changed.emit(text)

    def _on_content_changed(self):
        if not self._loading:
            self.content_changed.emit(self.get_content())

    def _on_content_format_changed(self, fmt):
        if self._loading:
            return
        # 富文本→Markdown 是有损转换（颜色/字号等格式会丢），且会清空撤销栈
        # 并随自动保存立刻落盘，必须先确认
        if self.content_edit.toPlainText().strip():
            target = 'Markdown' if fmt == 'markdown' else tr('富文本')
            reply = QMessageBox.question(
                self, tr('切换格式'),
                tr('切换到 {format} 会转换当前内容，部分格式可能丢失，且无法撤销。\n确定切换吗？', format=target),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.format_switch.set_format(self._content_format, emit=False)
                return
        self._switch_content_format(fmt)
        self.content_changed.emit(self.get_content())

    def _switch_content_format(self, fmt):
        fmt = 'markdown' if fmt == 'markdown' else 'rich'
        if fmt == self._content_format:
            self._sync_content_format_ui()
            return
        if fmt == 'markdown':
            if hasattr(self.content_edit, 'toMarkdown'):
                try:
                    content = self.content_edit.toMarkdown()
                except Exception:
                    content = self.content_edit.toPlainText()
            else:
                content = self.content_edit.toPlainText()
            self._content_format = 'markdown'
            self.content_edit.setPlainText(content)
        else:
            content = self.content_edit.toPlainText()
            self._content_format = 'rich'
            if content.strip() and hasattr(self.content_edit, 'setMarkdown'):
                try:
                    self.content_edit.setMarkdown(content)
                except Exception:
                    self.content_edit.setPlainText(content)
            else:
                self.content_edit.setPlainText(content)
        self.format_switch.set_format(self._content_format, emit=False)
        self._sync_content_format_ui()

    def _sync_content_format_ui(self):
        markdown = self._content_format == 'markdown'
        # Markdown 模式必须拒收富文本粘贴：否则浏览器/Word 复制来的加粗、
        # 颜色在编辑器里以富格式显示，保存却只落纯文本，重开笔记后格式
        # 全部消失（所见非所存）。降级为纯文本让丢失在粘贴瞬间即可见。
        self.content_edit.setAcceptRichText(not markdown)
        for btn in (
            getattr(self, 'bold_btn', None),
            getattr(self, 'italic_btn', None),
            getattr(self, 'underline_btn', None),
            getattr(self, 'bullet_btn', None),
            getattr(self, 'clear_format_btn', None),
        ):
            if btn is not None:
                btn.setEnabled(not markdown)
                btn.setVisible(not markdown)

    def _on_category_changed(self, text):
        if not self._loading:
            self.category_changed.emit(text)

    def _on_mode_changed(self, mode):
        if self._loading:
            return
        self.set_mode(mode)
        self.mode_changed.emit(mode)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self.file_dropped.emit(url.toLocalFile())
            event.acceptProposedAction()


# ============ 主窗口 ============


class CustomTitleBar(QWidget):
    HEIGHT = 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setObjectName("custom_title_bar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # A quiet document-style title keeps the chrome visually balanced while
        # leaving the whole empty area available for native window dragging.
        self.drag_area = QLabel('FRESH')
        self.drag_area.setObjectName('window_title')
        self.drag_area.setAlignment(Qt.AlignCenter)
        self.drag_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.drag_area)

        # Window controls
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 12, 0)
        btn_layout.setSpacing(2)

        self.min_btn = QPushButton('')
        self.min_btn.setObjectName("win_min_btn")
        self.min_btn.setFixedSize(32, 28)
        self.min_btn.setCursor(Qt.PointingHandCursor)
        self.min_btn.setIcon(build_ui_icon('minus', '#636366', '#1D1D1F'))
        self.min_btn.setIconSize(QSize(14, 14))

        self.max_btn = QPushButton('')
        self.max_btn.setObjectName("win_max_btn")
        self.max_btn.setFixedSize(32, 28)
        self.max_btn.setCursor(Qt.PointingHandCursor)
        self.max_btn.setIcon(build_ui_icon('maximize', '#636366', '#1D1D1F'))
        self.max_btn.setIconSize(QSize(13, 13))

        self.close_btn = QPushButton('')
        self.close_btn.setObjectName("win_close_btn")
        self.close_btn.setFixedSize(32, 28)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setIcon(build_ui_icon('close', '#636366', '#FFFFFF'))
        self.close_btn.setIconSize(QSize(13, 13))

        btn_layout.addWidget(self.min_btn)
        btn_layout.addWidget(self.max_btn)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

        # Connections (parent is expected to be MainWindow)
        self.min_btn.clicked.connect(self._minimize_window)
        self.max_btn.clicked.connect(self._maximize_restore_window)
        self.close_btn.clicked.connect(self._close_window)

        # Drag state
        self._is_dragging = False
        self._drag_start_pos = None

    def _minimize_window(self):
        window = self.window()
        if window:
            window.showMinimized()

    def _maximize_restore_window(self):
        window = self.window()
        if not window:
            return
        # 原生框架生效时必须走原生状态机（ShowWindow），并以 IsZoomed 为分支
        # 判据：贴边/Win+Up/双击走 DefWindowProc 的原生 SC_MAXIMIZE 后，Qt 的
        # showNormal() 是彻底 no-op 且 isMaximized() 会与真实 zoomed 位脱钩，
        # 按 Qt 状态分支会让还原按钮点了没反应。
        if getattr(window, '_native_frame_applied', False):
            try:
                hwnd = int(window.winId())
            except Exception:
                hwnd = 0
            if hwnd:
                if win_frame.is_zoomed(hwnd):
                    if win_frame.restore_window(hwnd):
                        self.sync_max_button(window.isMaximized())
                        return
                else:
                    if win_frame.maximize_window(hwnd):
                        self.sync_max_button(window.isMaximized())
                        return
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()
        self.sync_max_button(window.isMaximized())

    def sync_max_button(self, maximized):
        """由 MainWindow.changeEvent 在任何状态变化时调用（含启动恢复、
        托盘还原、原生贴边最大化），保证图标不滞留在旧状态。"""
        self.max_btn.setIcon(build_ui_icon(
            'restore' if maximized else 'maximize',
            '#636366',
            '#1D1D1F',
        ))
        self.max_btn.setToolTip('还原' if maximized else '最大化')

    def _close_window(self):
        window = self.window()
        if window:
            window.close()

    def mousePressEvent(self, event):
        # 正常情况下拖动/双击由 win_frame 的 WM_NCHITTEST(HTCAPTION) 原生接管，
        # 这里只是原生集成失败时的兜底。startSystemMove 让系统跑移动循环：
        # 支持 Aero Snap 贴边，最大化状态下拖动也会按系统惯例先还原。
        if event.button() == Qt.LeftButton:
            handle = self.window().windowHandle() if self.window() else None
            if handle is not None:
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
            self._is_dragging = not self.window().isMaximized()
            self._drag_start_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging and self._drag_start_pos is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_start_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._is_dragging = False
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._maximize_restore_window()
            event.accept()

class MainWindow(QMainWindow):
    SIDEBAR_WIDTH = 288

    def __init__(self, storage, account=None, account_manager=None):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self._native_frame_applied = False
        self.storage = storage
        self.account = account or {}
        self.account_manager = account_manager
        self.screenshot_board = self.storage.get_screenshot_board()
        self.current_note_id = None
        self.current_note_id = self.screenshot_board['id']
        self.workspace_mode = 'screenshot'
        self._suppress_auto_select = False
        self._updating_archive_category_filter = False
        self._capture_in_progress = False
        self._settings = QSettings('FRESH', 'FRESH')

        refresh_autostart_if_needed()
        self._sync_everything_flag()

        self.setWindowTitle('FRESH')
        self.resize(1080, 700)
        self.setMinimumSize(880, 560)
        self.setAcceptDrops(True)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self._save_current_now)

        self._setup_ui()
        self._restore_window_state()
        self._setup_shortcuts()
        self._setup_tray()
        # 存储回调：保存失败提示、数据损坏只读保护提示
        self._wire_storage(self.storage)
        self._notify_legacy_archive()

        # 文件追踪：实时监听已跟踪附件的父目录与文件本身，捕捉编辑保存
        self._tracked_watcher = QFileSystemWatcher(self)
        self._tracked_watcher.directoryChanged.connect(self._on_tracked_dir_changed)
        self._tracked_watcher.fileChanged.connect(self._on_tracked_file_changed)
        self._refresh_pending_dirs = set()
        self._refresh_dirs_timer = QTimer(self)
        self._refresh_dirs_timer.setSingleShot(True)
        self._refresh_dirs_timer.timeout.connect(self._flush_refresh_pending_dirs)

        # 剪贴板监听只做状态提示，避免自动扫描窗口打扰。
        self._clipboard_trigger_timer = QTimer(self)
        self._clipboard_trigger_timer.setSingleShot(True)
        self._clipboard_trigger_timer.timeout.connect(self._on_clipboard_settled)
        self._clipboard_move_candidates = []
        self._clipboard_probe_timer = QTimer(self)
        self._clipboard_probe_timer.setSingleShot(True)
        self._clipboard_probe_timer.timeout.connect(self._probe_clipboard_move_targets)
        try:
            QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        except Exception:
            pass
        self._recent_create_match_timer = QTimer(self)
        self._recent_create_match_timer.setSingleShot(True)
        self._recent_create_match_timer.timeout.connect(self._retry_recent_shell_creates)

        # 焦点监听只刷新仍在原位的追踪信息，不自动扫描。
        self._focus_trigger_timer = QTimer(self)
        self._focus_trigger_timer.setSingleShot(True)
        self._focus_trigger_timer.timeout.connect(self._on_focus_settled)
        self._last_focus_recovery = 0  # 上次基于焦点触发恢复的时间戳
        self._last_auto_recovery_start = 0.0
        self._last_window_activation = 0.0

        # 周期性轮询只维护 watcher，不自动扫描，避免反复弹窗。
        self._recovery_poll_timer = QTimer(self)
        self._recovery_poll_timer.timeout.connect(self._poll_missing_attachments)
        self._recovery_poll_timer.start(60000)

        # 启动时立即挂上 watcher（不再等后台打标完成）
        QTimer.singleShot(50, self._setup_tracking_watchers)

        # Windows Shell 通知：剪切/粘贴/移动文件时直接拿到 (旧路径, 新路径)，
        # 不用扫盘 —— 用户操作完瞬间就能改 original_path
        self._shell_filter = None
        QTimer.singleShot(0, self._install_shell_notifications)

        # 启动后台为老附件补打 ftrack 跟踪标签
        QTimer.singleShot(1500, self._start_background_tagging)

    def _start_background_tagging(self):
        self._tagging_queue = list(self.storage.all_external_attachments())
        self._tagging_changed = False
        self._tag_next_batch()

    def _tag_next_batch(self):
        queue = getattr(self, '_tagging_queue', None)
        if queue is None:
            return
        if not queue:
            if getattr(self, '_tagging_changed', False):
                self._tagging_changed = False
                self._refresh_external_attachment_views()
            self._setup_tracking_watchers()
            self._tagging_queue = None
            return
        batch = queue[:5]
        self._tagging_queue = queue[5:]

        # 已有 tracking 的只做轻量刷新；batch() 把逐项 save 合并成一次
        need_build = []
        with self.storage.batch():
            for _note, att in batch:
                try:
                    if not att.get('tracking'):
                        p = att.get('original_path', '')
                        if p and Path(p).exists():
                            resolved = str(Path(p).resolve())
                            identity = _path_identity_snapshot(resolved)
                            if identity is not None:
                                need_build.append((att.get('id'), resolved, identity))
                    else:
                        if self.storage.refresh_tracking_if_changed(att):
                            self._tagging_changed = True
                except Exception:
                    logger.exception('后台刷新追踪信息失败')

        if not need_build:
            QTimer.singleShot(80, self._tag_next_batch)
            return

        # 补打标签要对文件做最多 64MB 的 SHA-256——放到后台线程，
        # 主线程只回填结果（之前是在 UI 线程哈希且每个附件落盘一次）
        def job(worker):
            out = []
            for att_id, path, expected_identity in need_build:
                try:
                    if worker.cancelled:
                        break
                    snapshot = _build_tracking_snapshot(
                        path,
                        expected_identity=expected_identity,
                    )
                    out.append((att_id, path, snapshot))
                except Exception:
                    logger.exception('后台补打追踪标签失败: %s', path)
                    out.append((att_id, path, None))
            return out

        tag_worker = FuncWorker(job)
        self._tagging_worker = tag_worker

        def _apply():
            results = tag_worker.result or []
            tag_worker.deleteLater()
            if getattr(self, '_tagging_worker', None) is tag_worker:
                self._tagging_worker = None
            with self.storage.batch():
                for att_id, path, snapshot in results:
                    if not snapshot:
                        continue
                    tr_data, identity = snapshot
                    note, att = self.storage.find_attachment(att_id)
                    if not note or not att or att.get('tracking'):
                        continue
                    try:
                        current = os.path.normcase(os.path.normpath(att.get('original_path', '')))
                        expected = os.path.normcase(os.path.normpath(path))
                    except Exception:
                        current = att.get('original_path', '')
                        expected = path
                    if current != expected or _path_identity_snapshot(path) != identity:
                        continue
                    finalized = _finalize_tracking_identity(path, tr_data)
                    if not finalized:
                        continue
                    att['tracking'] = finalized
                    self.storage.save()
                    self._tagging_changed = True
            QTimer.singleShot(80, self._tag_next_batch)

        tag_worker.finished.connect(_apply)
        tag_worker.start()

    def _schedule_tracking_rebuilds(self, jobs):
        """Rebuild tracking in the background after fast shell-path adoption.

        jobs: iterable of (attachment_id, adopted_path, old_tracking_id). The
        worker only hashes/builds tracking data; applying results stays on the
        UI thread and is guarded by the current original_path so stale worker
        results cannot overwrite a later move.
        """
        clean_jobs = []
        seen = set()
        for att_id, path, old_uuid in jobs or []:
            if not att_id or not path:
                continue
            try:
                norm = os.path.normcase(os.path.normpath(str(path)))
            except Exception:
                norm = str(path)
            key = (att_id, norm)
            if key in seen:
                continue
            seen.add(key)
            identity = _path_identity_snapshot(path)
            if identity is None:
                continue
            clean_jobs.append((att_id, str(path), old_uuid or '', identity))
        if not clean_jobs:
            return

        def job(worker):
            out = []
            for att_id, path, old_uuid, expected_identity in clean_jobs:
                try:
                    if worker.cancelled:
                        break
                    snapshot = _build_tracking_snapshot(
                        path,
                        old_tracking_id=old_uuid,
                        expected_identity=expected_identity,
                    )
                    out.append((att_id, path, old_uuid, snapshot))
                except Exception:
                    logger.exception('后台重建追踪信息失败: %s', path)
                    out.append((att_id, path, old_uuid, None))
            return out

        worker = FuncWorker(job, self)
        workers = getattr(self, '_tracking_rebuild_workers', None)
        if workers is None:
            workers = set()
            self._tracking_rebuild_workers = workers
        workers.add(worker)

        def _apply():
            try:
                results = worker.result or []
                changed = False
                with self.storage.batch():
                    for att_id, path, old_uuid, snapshot in results:
                        if not snapshot:
                            continue
                        tr_data, identity = snapshot
                        note, att = self.storage.find_attachment(att_id)
                        if not att:
                            continue
                        try:
                            current = os.path.normcase(os.path.normpath(att.get('original_path', '')))
                            expected = os.path.normcase(os.path.normpath(path))
                        except Exception:
                            current = att.get('original_path', '')
                            expected = path
                        if current != expected:
                            continue
                        if _path_identity_snapshot(path) != identity:
                            continue
                        current_uuid = (att.get('tracking') or {}).get('tracking_id', '')
                        if current_uuid != old_uuid:
                            continue
                        finalized = _finalize_tracking_identity(
                            path,
                            tr_data,
                            old_tracking_id=old_uuid,
                        )
                        if not finalized:
                            continue
                        att['tracking'] = finalized
                        self.storage.save()
                        changed = True
                if changed and hasattr(self, '_tracked_watcher'):
                    self._setup_tracking_watchers()
            finally:
                workers = getattr(self, '_tracking_rebuild_workers', set())
                workers.discard(worker)
                worker.deleteLater()

        worker.finished.connect(_apply)
        worker.start()

    def _setup_tracking_watchers(self):
        """为每个已跟踪附件的父目录加监听；同时也直接监听文件本身，
        以便在编辑器原地保存（File ID 不变、内容改变）时也能收到事件。"""
        dirs = set()
        files = set()
        for _note, att in self.storage.all_external_attachments():
            if not att.get('tracking'):
                continue
            p = Path(att.get('original_path', ''))
            if p.exists():
                if p.is_dir():
                    dirs.add(str(p))
                parent = str(p.parent)
                if parent:
                    dirs.add(parent)
                if p.is_file():
                    files.add(str(p))
        current_dirs = set(self._tracked_watcher.directories())
        current_files = set(self._tracked_watcher.files())
        to_add_dirs = list(dirs - current_dirs)
        to_add_files = list(files - current_files)
        if to_add_dirs:
            self._tracked_watcher.addPaths(to_add_dirs)
        if to_add_files:
            self._tracked_watcher.addPaths(to_add_files)
        # 没了的目录/文件就摘掉，避免越攒越多
        stale_dirs = list(current_dirs - dirs)
        stale_files = list(current_files - files)
        if stale_dirs:
            self._tracked_watcher.removePaths(stale_dirs)
        if stale_files:
            self._tracked_watcher.removePaths(stale_files)

    def _on_tracked_file_changed(self, file_path):
        # 跟 dir 事件一起合并刷新
        self._refresh_pending_dirs.add(str(Path(file_path).parent))
        self._refresh_dirs_timer.start(300)
        # 有些编辑器原子保存后会把 watcher 摘掉，需要补挂回去
        if file_path not in self._tracked_watcher.files() and Path(file_path).exists():
            self._tracked_watcher.addPath(file_path)

    def _on_tracked_dir_changed(self, dir_path):
        # 短延迟合并多次抖动事件（编辑器原子保存通常触发多次）
        self._refresh_pending_dirs.add(dir_path)
        self._refresh_dirs_timer.start(300)

    def _flush_refresh_pending_dirs(self):
        dirs = self._refresh_pending_dirs
        self._refresh_pending_dirs = set()
        if not dirs:
            return
        affected = False   # 被跟踪文件所在目录有事件（可能只是同目录别的文件在写）
        changed = False    # 被跟踪文件本身确实变了（移动 / 改名 / atomic save）
        for _note, att in self.storage.all_external_attachments():
            if not att.get('tracking'):
                continue
            p = Path(att.get('original_path', ''))
            if str(p.parent) in dirs or str(p) in dirs:
                affected = True
                try:
                    if self.storage.refresh_tracking_if_changed(att, allow_path_rebind=True):
                        changed = True
                except Exception:
                    pass
        # watcher 在 atomic save 后会失效，只要目录有事件就补挂回来（开销小，不重建 UI）
        if affected:
            self._setup_tracking_watchers()
        # 只有被跟踪文件“确实”变化时才重建视图。否则同目录里别的文件频繁写入
        # （如外部程序刷日志）会让截图板每隔几百毫秒整体重建，导致右键菜单闪退、
        # 缩略图窗口闪烁以及无谓的 CPU 占用。
        if changed:
            self._refresh_external_attachment_views()
            self.statusBar().showMessage(tr('附件路径信息已刷新'), 2500)

    def _poll_missing_attachments(self):
        """周期性兜底：watcher 漏报 / 关 FRESH 之外操作时也能找回。"""
        try:
            changed = False
            missing_folder = False
            missing_other = False
            for _note, att in self.storage.all_external_attachments():
                recovery_key, has_real_tag = _attachment_recovery_key(att)
                if not recovery_key:
                    continue
                old_name = att.get('original_name', '')
                if has_real_tag and self.storage.refresh_tracking_if_changed(att):
                    changed = True
                    continue
                if self.storage.attachment_path_matches_tracking(att):
                    if att.get('original_name', '') != old_name:
                        changed = True
                    if _clear_recovery_failure(att):
                        changed = True
                    continue
                p = Path(att.get('original_path', ''))
                if not p.exists():
                    if att.get('type') == 'folder':
                        missing_folder = True
                    else:
                        missing_other = True
            if changed:
                self._refresh_external_attachment_views()
                if hasattr(self, '_tracked_watcher'):
                    self._setup_tracking_watchers()
                self.statusBar().showMessage(tr('附件路径信息已刷新'), 2500)
            # 文件夹被改名/移动找不到时，在后台静默用 .fresh_folder_id 标记自动找回，
            # 不弹窗、不阻塞 UI。受 30s 冷却 + 单项 180s 抑制保护，不会反复扫盘。
            # 这样"改名后需要手动重新扫描"变成"后台自动识别"，与文件的自愈体验一致。
            if missing_folder or missing_other:
                self._start_auto_recovery(reason='auto')
                # 永久失效的文件不再每 60 秒重复唠叨，本次会话只提醒一次；
                # 真正的自动扫描由 _start_auto_recovery 的单项退避限流。
                if missing_other and not missing_folder and not getattr(self, '_missing_attachment_notified', False):
                    self._missing_attachment_notified = True
                    self.statusBar().showMessage(tr('有附件路径失效，正在后台尝试查找'), 5000)
            else:
                self._missing_attachment_notified = False
        except Exception:
            logger.exception('附件状态轮询失败')

    def _install_shell_notifications(self):
        """订阅 Windows Shell 文件变更事件。"""
        if sys.platform != 'win32':
            return
        try:
            hwnd = int(self.winId())
        except Exception:
            return
        if not hwnd:
            return
        app = QApplication.instance()
        if app is None:
            return
        self._shell_filter = ShellChangeFilter(self._on_shell_event)
        try:
            app.installNativeEventFilter(self._shell_filter)
            if not self._shell_filter.install(hwnd):
                # 注册失败就当没装上
                try:
                    app.removeNativeEventFilter(self._shell_filter)
                except Exception:
                    pass
                self._shell_filter = None
        except Exception:
            self._shell_filter = None

    def _on_shell_event(self, event_code, path1, path2):
        """Shell 通知入口：只入队，合并 200ms 内的事件后批处理。

        往磁盘复制一个大文件夹会产生成百上千条 CREATE/UPDATE 事件，
        之前每条都在 UI 线程同步做附件匹配（stat/读 ADS），界面秒级冻结。
        """
        timer = getattr(self, '_shell_event_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(200)
            timer.timeout.connect(self._flush_shell_events)
            self._shell_event_timer = timer
        queue = getattr(self, '_shell_event_queue', None)
        if queue is None:
            queue = []
            self._shell_event_queue = queue
        item = (int(event_code or 0), str(path1 or ''), str(path2 or ''))
        if not queue or queue[-1] != item:
            queue.append(item)
        if len(queue) >= 500:
            timer.start(0)
            return
        if not timer.isActive():
            timer.start()

    def _collect_shell_missing_attachments(self):
        """Return attachments that are worth probing against CREATE events.

        The expensive identity check used to run once per CREATE event. Building
        this small candidate set once per shell batch keeps ordinary copy storms
        cheap when no tracked attachment is actually missing.
        """
        missing = []
        for note, att in self.storage.all_external_attachments():
            if not att.get('tracking'):
                continue
            cur = att.get('original_path', '')
            try:
                cur_norm = os.path.normcase(os.path.normpath(cur)) if cur else ''
            except Exception:
                cur_norm = ''
            try:
                if cur and self.storage.attachment_path_matches_tracking(att, save=False):
                    continue
            except Exception:
                pass
            missing.append((note, att, cur_norm))
        return missing

    def _flush_shell_events(self):
        queue = getattr(self, '_shell_event_queue', None) or []
        if not queue:
            self._shell_event_queue = None
            return
        batch = queue[:80]
        rest = queue[80:]
        self._shell_event_queue = rest or None
        seen = set()
        self._shell_cached_explorer_folders = explorer_open_folders()
        needs_create_probe = any(code in (SHCNE_CREATE, SHCNE_MKDIR) for code, _p1, _p2 in batch)
        self._shell_missing_attachment_cache = (
            self._collect_shell_missing_attachments() if needs_create_probe else []
        )
        try:
            for code, p1, p2 in batch:
                key = (code, p1, p2)
                if key in seen:
                    continue
                seen.add(key)
                try:
                    self._process_shell_event(code, p1, p2)
                except Exception:
                    logger.exception('处理 Shell 事件失败')
        finally:
            self._shell_cached_explorer_folders = None
            self._shell_missing_attachment_cache = None
        if rest:
            QTimer.singleShot(0, self._flush_shell_events)

    def _process_shell_event(self, event_code, path1, path2):
        """Shell 通知回调：检查 path1 是否匹配某个跟踪附件，匹配就改成 path2。"""
        if not path1 and not path2:
            return
        try:
            old_norm = os.path.normcase(os.path.normpath(path1)) if path1 else ''
            new_norm = os.path.normcase(os.path.normpath(path2)) if path2 else ''
        except Exception:
            return

        # 重命名/移动：path1 -> path2
        if event_code & (SHCNE_RENAMEITEM | SHCNE_RENAMEFOLDER) and old_norm and new_norm:
            self._apply_shell_move(old_norm, new_norm)
            return

        # 跨盘剪切（尤其到 exFAT/FAT 移动硬盘）常见事件顺序是：
        # 先在目标盘 CREATE，复制完成后才在源盘 DELETE。先记住目标候选，
        # 等源路径删除时再用 hash / 类型验证并采纳。
        if event_code & (SHCNE_CREATE | SHCNE_MKDIR) and old_norm:
            self._note_shell_create(old_norm)
            if self._try_match_clipboard_target_dirs([old_norm, os.path.dirname(old_norm)]):
                return
            if self._adopt_shell_created_path(old_norm):
                return
            self._try_match_pending_delete(old_norm)
            return

        # 删除事件：可能是剪切操作的源端被清理，先记下来；如果短时间内有
        # CREATE 同名的就当作移动；否则启动一次轻量 recovery 兜底。
        if event_code & (SHCNE_DELETE | SHCNE_RMDIR) and old_norm:
            self._note_shell_delete(old_norm)
            return

        # 目标文件夹被更新：跨盘剪切时有时只收到目标父目录更新，
        # 用 pending delete 里的原名拼出新位置。
        if event_code & SHCNE_UPDATEDIR and old_norm:
            if self._try_match_clipboard_target_dirs([old_norm]):
                return
            if self._try_match_pending_paste_target(old_norm):
                return

        # 文件被原地编辑（atomic save 等）→ 立刻刷新当前视图
        if event_code & (SHCNE_UPDATEITEM | SHCNE_UPDATEDIR) and old_norm:
            if self._try_match_clipboard_target_dirs([old_norm, os.path.dirname(old_norm)]):
                return
            self._maybe_refresh_for_path(old_norm)

    def _remember_clipboard_move_candidates(self, mime):
        try:
            urls = mime.urls()
        except Exception:
            return []
        effect = clipboard_drop_effect(mime)
        is_cut = bool(effect & DROPEFFECT_MOVE)
        tracked_by_norm = {}
        for _note, att in self.storage.all_external_attachments():
            if not att.get('tracking'):
                continue
            path = att.get('original_path', '')
            if not path:
                continue
            try:
                norm = os.path.normcase(os.path.normpath(path))
            except Exception:
                continue
            tracked_by_norm[norm] = att

        now = time.time()
        fresh = [
            item for item in getattr(self, '_clipboard_move_candidates', [])
            if now - item.get('ts', 0) <= CLIPBOARD_MOVE_MATCH_WINDOW_SECONDS
        ]
        seen = {(item.get('att_id'), item.get('source_norm')) for item in fresh}
        hit_names = []
        for url in urls:
            path = url.toLocalFile()
            if not path:
                continue
            try:
                norm = os.path.normcase(os.path.normpath(path))
            except Exception:
                continue
            att = tracked_by_norm.get(norm)
            if not att:
                continue
            name = att.get('original_name') or os.path.basename(path)
            key = (att.get('id'), norm)
            if key not in seen:
                fresh.append({
                    'att_id': att.get('id'),
                    'source_norm': norm,
                    'name': name,
                    'is_cut': is_cut,
                    'ts': now,
                })
                seen.add(key)
            hit_names.append(name)
        self._clipboard_move_candidates = fresh[-100:]
        if hit_names and hasattr(self, '_clipboard_probe_timer'):
            self._clipboard_probe_timer.start(900)
        return hit_names

    def _active_clipboard_move_candidates(self):
        now = time.time()
        fresh = [
            item for item in getattr(self, '_clipboard_move_candidates', [])
            if now - item.get('ts', 0) <= CLIPBOARD_MOVE_MATCH_WINDOW_SECONDS
        ]
        self._clipboard_move_candidates = fresh
        return list(fresh)

    def _candidate_paths_from_target_hint(self, name, hint):
        if not name or not hint:
            return []
        try:
            p = Path(hint)
        except Exception:
            return []
        target = name.lower()
        out = []
        try:
            if p.name.lower() == target:
                out.append(p)
            if p.parent and p.parent.name.lower() == target:
                out.append(p.parent)
            if p.exists() and p.is_dir():
                out.append(p / name)
        except Exception:
            pass
        return out

    def _recent_shell_target_hints(self):
        hints = []
        creates = getattr(self, '_recent_shell_creates', None) or []
        now = time.time()
        for item in creates:
            if now - item.get('ts', 0) > SHELL_CREATE_MATCH_WINDOW_SECONDS:
                continue
            path = item.get('path', '')
            if path:
                hints.append(path)
                try:
                    hints.append(str(Path(path).parent))
                except Exception:
                    pass
        return hints

    def _try_match_clipboard_target_dirs(self, target_hints=None):
        candidates = self._active_clipboard_move_candidates()
        if not candidates:
            return False
        hints = list(target_hints or [])
        hints.extend(self._recent_shell_target_hints())
        cached_explorer = getattr(self, '_shell_cached_explorer_folders', None)
        hints.extend(cached_explorer if cached_explorer is not None else explorer_open_folders())

        seen_hints = set()
        unique_hints = []
        for hint in hints:
            if not hint:
                continue
            try:
                key = os.path.normcase(os.path.normpath(str(hint)))
            except Exception:
                continue
            if key in seen_hints:
                continue
            seen_hints.add(key)
            unique_hints.append(str(hint))

        adopted = []
        remaining = []
        for item in candidates:
            att_id = item.get('att_id')
            note, att = self.storage.find_attachment(att_id) if att_id else (None, None)
            if not att:
                continue
            # 源路径仍与 tracking 对得上 → 附件根本没丢，绝不能被磁盘上某个
            # 同内容副本（备份目录、以前复制过的一份）抢走身份。剪切(is_cut)
            # 同样要做这一检查：Ctrl+X 之后、粘贴完成之前源文件一直健在，此时
            # 的任何 hash 命中都只能是旧副本；源真被删除后守卫自然放行，跨盘
            # 剪切的采纳本就发生在源删除之后，不受影响。每个 item 只查一次，
            # 不放进 hint×candidate 双层循环里反复读盘。
            try:
                if self.storage.attachment_path_matches_tracking(att, save=False):
                    remaining.append(item)
                    continue
            except Exception:
                pass
            name = item.get('name') or att.get('original_name') or ''
            source_norm = item.get('source_norm') or ''
            matched_path = ''
            for hint in unique_hints:
                for candidate in self._candidate_paths_from_target_hint(name, hint):
                    try:
                        cand_norm = os.path.normcase(os.path.normpath(str(candidate)))
                    except Exception:
                        continue
                    if cand_norm == source_norm or not candidate.exists():
                        continue
                    if self._clipboard_target_matches(att, item, candidate):
                        matched_path = str(candidate)
                        break
                if matched_path:
                    break
            if matched_path:
                adopted.append((att, matched_path, note))
            else:
                remaining.append(item)

        self._clipboard_move_candidates = remaining
        if not adopted:
            return False

        rebuild_jobs = []
        with self.storage.batch():
            for att, matched_path, _note in adopted:
                old_uuid = (att.get('tracking') or {}).get('tracking_id', '')
                self.storage.adopt_external_path(att, matched_path, rebuild=False)
                rebuild_jobs.append((att.get('id'), matched_path, old_uuid))
        self._schedule_tracking_rebuilds(rebuild_jobs)

        self._refresh_external_attachment_views()
        if hasattr(self, '_tracked_watcher'):
            self._setup_tracking_watchers()
        shown = adopted[0][1]
        self.statusBar().showMessage(
            tr('已按剪切/粘贴位置同步附件：{path}', path=shown),
            5000,
        )
        return True

    def _clipboard_target_matches(self, att, item, candidate):
        if att.get('type') != 'folder':
            return self._tracking_identity_matches(att, str(candidate))
        try:
            p = Path(candidate)
        except Exception:
            return False
        if not p.exists() or not p.is_dir():
            return False

        tracking = att.get('tracking') or {}
        tag = tracking.get('tracking_id')
        if tag and ftrack.read_tracking_tag(str(p)) == tag:
            return True

        # 文件夹没有内容 hash。这里仅对“剪贴板记录过这个原始文件夹”的场景放宽：
        # 目标名已由调用方按 original_name 拼出，且源路径已经失效时，可认为这是剪切目标。
        source_norm = item.get('source_norm') or ''
        if not source_norm:
            return False
        try:
            source_exists = Path(source_norm).exists()
        except Exception:
            source_exists = False
        if source_exists:
            try:
                if self.storage.attachment_path_matches_tracking(att, save=False):
                    return False
            except Exception:
                pass
        return True

    def _probe_clipboard_move_targets(self):
        if self._try_match_clipboard_target_dirs():
            return
        if self._active_clipboard_move_candidates() and hasattr(self, '_clipboard_probe_timer'):
            self._clipboard_probe_timer.start(1500)

    def _tracking_identity_matches(self, att, norm_path):
        """Shell 事件候选是否足够像这个附件。文件优先用 hash，文件夹只做类型兜底。"""
        try:
            p = Path(norm_path)
        except Exception:
            return False
        if not p.exists():
            return False
        tracking = att.get('tracking') or {}
        if att.get('type') == 'file_ref':
            if not p.is_file():
                return False
            if tracking.get('content_hash'):
                return ftrack.path_matches_hash(str(p), tracking)
            try:
                size = tracking.get('size_snapshot') or att.get('size')
                return size is None or p.stat().st_size == int(size)
            except Exception:
                # stat 都失败说明对这个候选一无所知，宁可漏配不可错配
                return False
        if att.get('type') == 'folder':
            if not p.is_dir():
                return False
            tag = tracking.get('tracking_id')
            if tag:
                return ftrack.read_tracking_tag(str(p)) == tag
            return True
        return False

    def _shell_move_target_matches(self, att, old_norm, candidate_path):
        if att.get('type') != 'folder':
            return self._tracking_identity_matches(att, candidate_path)
        try:
            p = Path(candidate_path)
        except Exception:
            return False
        if not p.exists() or not p.is_dir():
            return False
        tag = (att.get('tracking') or {}).get('tracking_id')
        if tag:
            candidate_tag = ftrack.read_tracking_tag(str(p))
            if candidate_tag == tag:
                return True
            if candidate_tag:
                # 候选文件夹带着别人的标签——是另一个被追踪的文件夹，
                # 绝不能因为"旧路径没了"就认领
                return False
        try:
            return bool(old_norm) and not Path(old_norm).exists()
        except Exception:
            return False

    def _attachment_under_path(self, att, base_norm):
        """附件是否位于某个目录树下面。"""
        cur = att.get('original_path', '')
        if not cur:
            return False
        try:
            cur_norm = os.path.normcase(os.path.normpath(cur))
        except Exception:
            return False
        base_norm = os.path.normcase(os.path.normpath(base_norm))
        if cur_norm == base_norm:
            return True
        prefix = base_norm.rstrip('\\/')
        return cur_norm.startswith(prefix + os.sep)

    def _path_for_pending_target(self, att, old_norm, new_norm):
        """根据 Shell 新路径计算附件应采用的位置。

        只采纳附件本身的剪切/移动，避免目录内某个新建文件把文件夹附件
        错误同步到子文件路径。
        """
        cur = att.get('original_path', '')
        if not cur:
            return ''
        try:
            cur_norm = os.path.normcase(os.path.normpath(cur))
        except Exception:
            return ''
        if cur_norm != old_norm:
            return ''
        return new_norm

    def _note_shell_create(self, new_norm):
        """记录最近创建的路径，用于处理“先复制到目标盘、后删除源文件”的剪切流程。"""
        if ftrack.is_recycled_path(new_norm):
            return
        if not hasattr(self, '_recent_shell_creates'):
            self._recent_shell_creates = []
        import time as _time
        now = _time.time()
        creates = [
            item for item in self._recent_shell_creates
            if now - item.get('ts', 0) <= SHELL_CREATE_MATCH_WINDOW_SECONDS
        ]
        base = os.path.basename(new_norm).lower()
        if base:
            creates.append({'path': new_norm, 'base': base, 'ts': now})
        self._recent_shell_creates = creates[-200:]
        if hasattr(self, '_recent_create_match_timer'):
            self._recent_create_match_timer.start(1500)

    def _adopt_shell_created_path(self, new_norm, missing_attachments=None):
        """用新建路径直接修复已失效的引用附件。

        这覆盖一种真实场景：FRESH 里记录的 original_path 已经旧了，用户从
        当前真实位置剪切到 F: 时，DELETE 事件路径和记录路径对不上；此时只能
        从目标盘 CREATE 事件按文件名 + 内容 hash 反向匹配。
        """
        if missing_attachments is None:
            missing_attachments = getattr(self, '_shell_missing_attachment_cache', None)
        if missing_attachments is None:
            missing_attachments = self._collect_shell_missing_attachments()
        if not missing_attachments:
            return False
        try:
            p = Path(new_norm)
        except Exception:
            return False
        if not p.exists() or ftrack.is_recycled_path(new_norm):
            return False

        new_base = os.path.basename(new_norm).lower()
        matches = []
        for _note, att, cached_cur_norm in missing_attachments:
            cur = att.get('original_path', '')
            try:
                cur_norm = os.path.normcase(os.path.normpath(cur)) if cur else ''
            except Exception:
                cur_norm = ''
            if cur_norm and cached_cur_norm and cur_norm != cached_cur_norm:
                continue
            if cur_norm == new_norm:
                continue
            tracking = att.get('tracking') or {}
            expected = (att.get('original_name') or os.path.basename(cur or '')).lower()
            if expected and expected != new_base and not tracking.get('content_hash'):
                continue
            if self._tracking_identity_matches(att, new_norm):
                matches.append(att)

        if len(matches) != 1:
            return False

        att = matches[0]
        old_uuid = (att.get('tracking') or {}).get('tracking_id', '')
        with self.storage.batch():
            self.storage.adopt_external_path(att, new_norm, rebuild=False)
        self._schedule_tracking_rebuilds([(att.get('id'), new_norm, old_uuid)])
        self._refresh_external_attachment_views()
        if hasattr(self, '_tracked_watcher'):
            self._setup_tracking_watchers()
        try:
            self.statusBar().showMessage(
                tr('已同步文件到新位置：{path}', path=new_norm),
                4000,
            )
        except Exception:
            pass
        return True

    def _retry_recent_shell_creates(self):
        """复制完成较慢时，持续用近期 CREATE 候选匹配已失效附件。"""
        creates = getattr(self, '_recent_shell_creates', None) or []
        if not creates:
            return
        import time as _time
        now = _time.time()
        fresh = []
        missing = self._collect_shell_missing_attachments()
        should_retry = False
        for item in creates:
            if now - item.get('ts', 0) > SHELL_CREATE_MATCH_WINDOW_SECONDS:
                continue
            if missing and self._adopt_shell_created_path(item.get('path', ''), missing):
                continue
            fresh.append(item)
            should_retry = bool(missing)
        self._recent_shell_creates = fresh
        if should_retry and fresh and hasattr(self, '_recent_create_match_timer'):
            self._recent_create_match_timer.start(2500)

    def _find_recent_create_for_delete(self, old_norm, att):
        """源路径刚删除时，从近期 CREATE 中找出同名且身份匹配的目标路径。"""
        creates = getattr(self, '_recent_shell_creates', None) or []
        if not creates:
            return ''
        import time as _time
        now = _time.time()
        old_base = os.path.basename(old_norm).lower()
        candidates = []
        fresh = []
        for item in creates:
            if now - item.get('ts', 0) > SHELL_CREATE_MATCH_WINDOW_SECONDS:
                continue
            fresh.append(item)
            new_norm = item.get('path', '')
            tracking = att.get('tracking') or {}
            if new_norm == old_norm:
                continue
            if item.get('base') != old_base and not tracking.get('content_hash'):
                continue
            check_path = self._path_for_pending_target(att, old_norm, new_norm)
            if not check_path:
                continue
            if self._shell_move_target_matches(att, old_norm, check_path):
                candidates.append(new_norm)
        self._recent_shell_creates = fresh
        if len(candidates) == 1:
            return candidates[0]
        return ''

    def _apply_shell_move(self, old_norm, new_norm):
        """把 old_norm 命中的跟踪附件 original_path 改成 new_norm，刷新 UI。"""
        if ftrack.is_recycled_path(new_norm):
            # "删除到回收站"就是一次 RENAMEITEM——绝不能把附件同步成
            # $Recycle.Bin\$Rxxxx，那等于替用户把附件改名成乱码
            return
        moved = []
        rebuild_jobs = []
        old_prefix = old_norm.rstrip('\\/') + os.sep
        with self.storage.batch():
            for _note, att in self.storage.all_external_attachments():
                cur = att.get('original_path', '')
                if not cur:
                    continue
                cur_norm = os.path.normcase(os.path.normpath(cur))
                adopted_path = ''
                if cur_norm == old_norm:
                    adopted_path = new_norm
                elif cur_norm.startswith(old_prefix):
                    # 附件在被改名/移动的文件夹里面：按前缀改写，
                    # 否则文件夹一改名里面的附件全部失联。
                    # 后缀取自 normcase 后的路径（小写），adopt 里的 resolve()
                    # 会把它还原成盘上的真实大小写
                    candidate = os.path.join(new_norm, cur_norm[len(old_prefix):])
                    if os.path.exists(candidate):
                        adopted_path = candidate
                if not adopted_path:
                    continue
                old_uuid = (att.get('tracking') or {}).get('tracking_id', '')
                self.storage.adopt_external_path(att, adopted_path, rebuild=False)
                moved.append(att)
                rebuild_jobs.append((att.get('id'), adopted_path, old_uuid))
        if not moved:
            return
        self._schedule_tracking_rebuilds(rebuild_jobs)
        # 即时刷新预览 + 把新父目录挂进 watcher
        self._refresh_external_attachment_views()
        if hasattr(self, '_tracked_watcher'):
            self._setup_tracking_watchers()
        try:
            self.statusBar().showMessage(
                tr('已同步 {n} 个文件到新位置：{path}', n=len(moved), path=new_norm),
                4000,
            )
        except Exception:
            pass

    def _note_shell_delete(self, old_norm):
        """记录被删除的路径 + 时间戳，等可能配对的 CREATE。"""
        if not hasattr(self, '_pending_shell_deletes'):
            self._pending_shell_deletes = {}
        if not hasattr(self, '_pending_recovery_timer'):
            self._pending_recovery_timer = QTimer(self)
            self._pending_recovery_timer.setSingleShot(True)
            self._pending_recovery_timer.timeout.connect(self._flush_pending_deletes)
        # 只关心跟踪过的附件本身。
        tracked_att = None
        for _note, att in self.storage.all_external_attachments():
            cur = att.get('original_path', '')
            if cur and os.path.normcase(os.path.normpath(cur)) == old_norm:
                tracked_att = att
                break
        if not tracked_att:
            return

        created_target = self._find_recent_create_for_delete(old_norm, tracked_att)
        if created_target:
            self._apply_shell_move(old_norm, created_target)
            return

        import time as _time
        self._pending_shell_deletes[old_norm] = {
            'ts': _time.time(),
            'last_recovery_ts': 0.0,
        }
        # 目标文件可能还在复制中，短延迟后重试 Shell 候选，再启动恢复兜底。
        self._pending_recovery_timer.start(1200)

    def _try_match_pending_delete(self, new_norm):
        """新增事件：如果同名文件最近被删过，那就当作移动了。"""
        pending = getattr(self, '_pending_shell_deletes', None) or {}
        if not pending:
            return
        new_base = os.path.basename(new_norm).lower()
        if not new_base:
            return
        import time as _time
        now = _time.time()
        for old_norm, state in list(pending.items()):
            ts = state.get('ts', 0) if isinstance(state, dict) else state
            if now - ts > SHELL_DELETE_RETRY_WINDOW_SECONDS:
                pending.pop(old_norm, None)
                continue
            base_matches = os.path.basename(old_norm).lower() == new_base
            tracked_att = None
            for _note, att in self.storage.all_external_attachments():
                cur = att.get('original_path', '')
                if cur and os.path.normcase(os.path.normpath(cur)) == old_norm:
                    tracked_att = att
                    break
            if not tracked_att:
                continue
            tracking = tracked_att.get('tracking') or {}
            if not base_matches and not tracking.get('content_hash'):
                continue
            check_path = self._path_for_pending_target(tracked_att, old_norm, new_norm)
            if not check_path:
                continue
            if not self._shell_move_target_matches(tracked_att, old_norm, check_path):
                continue
            pending.pop(old_norm, None)
            self._apply_shell_move(old_norm, new_norm)
            return

    def _try_match_pending_paste_target(self, target_dir_norm):
        """目标父目录更新时，尝试用目标目录 + 原名补全剪切后的路径。"""
        pending = getattr(self, '_pending_shell_deletes', None) or {}
        if not pending:
            return False
        try:
            target_dir = Path(target_dir_norm)
        except Exception:
            return False
        if not target_dir.exists() or not target_dir.is_dir():
            return False

        import time as _time
        now = _time.time()
        for old_norm, state in list(pending.items()):
            ts = state.get('ts', 0) if isinstance(state, dict) else state
            if now - ts > SHELL_DELETE_RETRY_WINDOW_SECONDS:
                pending.pop(old_norm, None)
                continue
            candidate = target_dir / os.path.basename(old_norm)
            if not candidate.exists():
                continue
            tracked_att = None
            for _note, att in self.storage.all_external_attachments():
                cur = att.get('original_path', '')
                if cur and os.path.normcase(os.path.normpath(cur)) == old_norm:
                    tracked_att = att
                    break
            if not tracked_att or not self._shell_move_target_matches(tracked_att, old_norm, str(candidate)):
                continue
            pending.pop(old_norm, None)
            self._apply_shell_move(old_norm, str(candidate))
            return True
        return False

    def _flush_pending_deletes(self):
        """没有等到配对 CREATE 时，重试近期候选并启动 recovery 兜底。"""
        pending = getattr(self, '_pending_shell_deletes', None) or {}
        if not pending:
            return
        import time as _time
        now = _time.time()
        keep_waiting = False
        should_recover = False
        for old_norm, state in list(pending.items()):
            if isinstance(state, dict):
                ts = state.get('ts', 0)
                last_recovery_ts = state.get('last_recovery_ts', 0.0)
            else:
                ts = state
                last_recovery_ts = 0.0

            if now - ts > SHELL_DELETE_RETRY_WINDOW_SECONDS:
                pending.pop(old_norm, None)
                should_recover = True
                continue

            tracked_att = None
            for _note, att in self.storage.all_external_attachments():
                cur = att.get('original_path', '')
                if cur and (
                    os.path.normcase(os.path.normpath(cur)) == old_norm
                    or self._attachment_under_path(att, old_norm)
                ):
                    tracked_att = att
                    break
            if not tracked_att:
                pending.pop(old_norm, None)
                continue

            created_target = self._find_recent_create_for_delete(old_norm, tracked_att)
            if created_target:
                pending.pop(old_norm, None)
                self._apply_shell_move(old_norm, created_target)
                continue

            keep_waiting = True
            if now - last_recovery_ts >= 10.0:
                if isinstance(state, dict):
                    state['last_recovery_ts'] = now
                    # 同一个路径只提示一次，别每 10 秒骚扰一遍——
                    # 用户主动删除文件时这条提示毫无意义
                    if not state.get('notified'):
                        state['notified'] = True
                        should_recover = True
                else:
                    should_recover = True

        if should_recover:
            try:
                self.statusBar().showMessage(tr('有附件路径变化，可在更多菜单手动查找'), 5000)
            except Exception:
                pass
        if keep_waiting:
            self._pending_recovery_timer.start(2500)

    def _maybe_refresh_for_path(self, norm_path):
        """跟踪附件所在路径有改动时，只有当它“确实”变了（File ID / 名称变化）才
        重建当前 workspace；否则同目录里别的文件写入也会触发刷新，造成截图板
        频繁重建（右键菜单闪退 / 缩略图窗口闪烁）。"""
        changed = False
        for _note, att in self.storage.all_external_attachments():
            cur = att.get('original_path', '')
            if not cur:
                continue
            cur_norm = os.path.normcase(os.path.normpath(cur))
            if cur_norm == norm_path or os.path.dirname(cur_norm) == norm_path:
                try:
                    if self.storage.refresh_tracking_if_changed(att, allow_path_rebind=True):
                        changed = True
                except Exception:
                    pass
        if changed:
            self._refresh_external_attachment_views()

    # ============ 窗口状态 / 快捷键 ============


    def showEvent(self, event):
        super().showEvent(event)
        # FramelessWindowHint 会把 WS_THICKFRAME/WS_CAPTION 一起去掉：
        # 边缘无法拉伸、没有贴边分屏、没有 Win11 圆角阴影。
        # win_frame 补回这些样式并用 WM_NCCALCSIZE 吞掉原生标题栏。
        if not self._native_frame_applied:
            try:
                self._native_frame_applied = win_frame.apply_native_frame(int(self.winId()))
            except Exception:
                self._native_frame_applied = False
            # WS_POPUP（FramelessWindowHint 附带）不在 Win11 自动圆角范围内，
            # 得显式向 DWM 要圆角；最大化时 DWM 自己会切回直角。
            try:
                win_frame.apply_rounded_corners(int(self.winId()), True)
            except Exception:
                pass

    def nativeEvent(self, eventType, message):
        if self._native_frame_applied and eventType in (b'windows_generic_MSG', 'windows_generic_MSG'):
            try:
                dpr = self.devicePixelRatioF() or 1.0
            except Exception:
                dpr = 1.0
            handled, result = win_frame.handle_native_message(
                int(message),
                int(CustomTitleBar.HEIGHT * dpr),
                lambda x, y, _dpr=dpr: self._caption_hit_test(x, y, _dpr),
            )
            if handled:
                return True, result
        return super().nativeEvent(eventType, message)

    def _caption_hit_test(self, x_px, y_px, dpr):
        """窗口顶部条带内该点是否算"标题栏空白"（可拖动/双击最大化）。
        坐标为相对窗口左上角的物理像素。命中按钮/输入框时交还给控件。"""
        pos = QPoint(int(x_px / dpr), int(y_px / dpr))
        child = self.childAt(pos)
        if child is None:
            return True
        if child is getattr(self, 'title_bar', None) or child is getattr(self.title_bar, 'drag_area', None):
            return True
        if child is getattr(self, 'sidebar', None):
            return True
        return isinstance(child, QLabel)

    def _set_new_button_text(self):
        if hasattr(self, 'new_btn'):
            self.new_btn.setText('新建记事')

    def _set_archive_filter_visible(self, visible):
        if hasattr(self, 'archive_category_filter'):
            self.archive_category_filter.setVisible(bool(visible))

    def _restore_window_state(self):
        geometry = self._settings.value('main/geometry')
        if geometry:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass

        if hasattr(self, 'title_bar'):
            self.title_bar.sync_max_button(self.isMaximized())

        view = self._settings.value('main/view', 'active')
        if view not in ('active', 'archived'):
            view = 'active'
        self.view_switch.set_view(view, emit=False)

        mode = self._settings.value('main/workspace_mode', 'screenshot')
        if mode == 'text':
            self.workspace_mode = 'text'
            self.workspace_switch.set_mode('text', emit=False)
            self._set_new_button_text()
            self.search_input.setPlaceholderText('搜索记录')
            self._set_list_delegate('note')
            self.current_note_id = None
            self._suppress_auto_select = True
            try:
                self._populate_list()
            finally:
                self._suppress_auto_select = False
            note_id = self._settings.value('main/current_note_id', '')
            self.list_widget.clearSelection()
            if note_id and self._select_note_by_id(note_id):
                self._load_note_by_id(note_id)
            else:
                self._sync_empty_state()
            return

        self.workspace_mode = 'screenshot'
        self.workspace_switch.set_mode('screenshot', emit=False)
        self._set_new_button_text()
        self.search_input.setPlaceholderText('搜索记录')
        self._set_list_delegate('shot')
        self.current_note_id = self.screenshot_board['id']
        self._refresh_screenshot_board()

    def _save_window_state(self):
        try:
            self._settings.setValue('main/geometry', self.saveGeometry())
            self._settings.setValue('main/workspace_mode', self.workspace_mode)
            self._settings.setValue('main/view', self.view_switch.current_view())
            self._settings.setValue('main/current_note_id', self.current_note_id or '')
        except Exception:
            pass

    def _shortcut_actions(self):
        """所有可自定义的快捷键。返回 (id, 描述, 默认按键, handler, context_widget) 元组列表。"""
        return [
            ('new_note',        '新建文字便签',         'Ctrl+N',            self.create_new_note,                None),
            ('capture_region',  '框选截图',             'Ctrl+Shift+N',      self._capture_screenshot_region,     None),
            ('browse_image',    '选择截图图片',         'Ctrl+Alt+N',        self._browse_screenshot,             None),
            ('focus_search',    '聚焦搜索框',           'Ctrl+F',            self._focus_search,                  None),
            ('timeline',        '时间线·归档与完成',    'Ctrl+L',            self._show_timeline,                 None),
            ('recent_deleted',  '最近删除',             'Ctrl+Shift+Delete', self._show_recently_deleted,         None),
            ('toggle_archive',  '归档/取消归档当前',    'Ctrl+E',            self._toggle_current_archive,        None),
            ('toggle_pin',      '置顶/取消置顶当前',    'Ctrl+T',            self._toggle_current_pin,            None),
            ('nav_up',          '上一条',               'Alt+Up',            lambda: self._navigate_visible(-1),  None),
            ('nav_down',        '下一条',               'Alt+Down',          lambda: self._navigate_visible(1),   None),
            ('advance_focus',   '切换聚焦/新建',        'Ctrl+Enter',        self._advance_keyboard_focus,        None),
            ('delete_item',     '删除当前项（列表中）', 'Delete',            self._delete_current_item,           'list'),
            ('show_shortcuts',  '查看 / 修改快捷键',    'Ctrl+/',            self._show_shortcuts_dialog,         None),
        ]

    def _shortcut_settings_key(self, action_id):
        return f'shortcuts/{action_id}'

    def _current_shortcut_for(self, action_id, default_seq):
        try:
            val = self._settings.value(self._shortcut_settings_key(action_id), default_seq)
            return val if isinstance(val, str) and val else default_seq
        except Exception:
            return default_seq

    def _setup_shortcuts(self):
        # 清掉已有的（重新应用配置时调用）
        for sc in getattr(self, '_shortcuts', []) or []:
            try:
                sc.setParent(None)
                sc.deleteLater()
            except Exception:
                pass
        self._shortcuts = []
        for action_id, _label, default_seq, handler, context in self._shortcut_actions():
            seq_str = self._current_shortcut_for(action_id, default_seq)
            if not seq_str:
                continue  # 用户清空了 = 禁用
            seq = QKeySequence(seq_str)
            if seq.isEmpty():
                continue
            parent = self.list_widget if context == 'list' else self
            shortcut = QShortcut(seq, parent)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut if context == 'list' else Qt.WindowShortcut)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)

    def _show_shortcuts_dialog(self):
        dlg = ShortcutsDialog(self, self._shortcut_actions(), self._settings)
        if dlg.exec() == QDialog.Accepted:
            for action_id, seq_str in dlg.result_map.items():
                self._settings.setValue(self._shortcut_settings_key(action_id), seq_str)
            self._setup_shortcuts()

    def _focus_search(self):
        self.search_input.setFocus()
        self.search_input.selectAll()

    def _focus_list(self):
        if self.list_widget.count() <= 0:
            return False
        if self.list_widget.currentRow() < 0:
            self.list_widget.setCurrentRow(0)
        self.list_widget.setFocus()
        return True

    def _focus_title(self):
        if self.workspace_mode != 'text' or not self.current_note_id:
            return False
        self.editor.focus_title()
        return True

    def _focus_body(self):
        if self.workspace_mode == 'screenshot':
            self.screenshot_grid.setFocus()
            return True
        if not self.current_note_id:
            return False
        self.editor.focus_body()
        return True

    def _advance_keyboard_focus(self):
        focus = QApplication.focusWidget()
        if self.workspace_mode != 'text':
            self._focus_list()
            return
        if focus is self.editor.content_edit:
            self.create_new_note()
            return
        if focus is self.search_input or focus is self.list_widget:
            if self.list_widget.currentRow() < 0 and self.list_widget.count() > 0:
                self.list_widget.setCurrentRow(0)
            self._focus_title()
            return
        self._focus_body()

    def _navigate_visible(self, delta):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now(refresh_list=False)
        count = self.list_widget.count()
        if count <= 0:
            self._sync_empty_state()
            return
        current = self.list_widget.currentRow()
        if current < 0:
            target = 0 if delta >= 0 else count - 1
        else:
            target = max(0, min(count - 1, current + delta))
        self.list_widget.setCurrentRow(target)
        self.list_widget.setFocus()

    def _toggle_current_archive(self):
        if self.view_switch.current_view() == 'archived':
            item = self.list_widget.currentItem()
            data = item.data(Qt.UserRole) if item else None
            if not data:
                return
            if data.get('kind') == 'attachment':
                att = data.get('attachment') or {}
                if att.get('id'):
                    self._on_attachment_archive_toggled(att['id'])
                return
            note = data.get('note') or {}
            if note.get('id'):
                self._toggle_archive(note['id'])
            return
        if self.workspace_mode == 'screenshot':
            item = self.list_widget.currentItem()
            att = item.data(Qt.UserRole) if item else None
            if att and att.get('id'):
                self._on_attachment_archive_toggled(att['id'])
            return
        if self.current_note_id:
            self._toggle_archive(self.current_note_id)

    def _delete_current_item(self):
        if self.view_switch.current_view() == 'archived':
            item = self.list_widget.currentItem()
            data = item.data(Qt.UserRole) if item else None
            if not data:
                return
            if data.get('kind') == 'attachment':
                att = data.get('attachment') or {}
                if att.get('id'):
                    self._on_attachment_delete(att['id'])
                return
            note = data.get('note') or {}
            if note.get('id'):
                self._delete_note(note['id'])
            return
        if self.workspace_mode == 'screenshot':
            item = self.list_widget.currentItem()
            att = item.data(Qt.UserRole) if item else None
            if att and att.get('id'):
                self._on_attachment_delete(att['id'])
            return
        if self.current_note_id:
            self._delete_note(self.current_note_id)

    def _toggle_current_pin(self):
        if self.workspace_mode != 'text' or not self.current_note_id:
            return
        self._toggle_pin(self.current_note_id)

    def _toggle_pin(self, note_id):
        note = self.storage.get_note(note_id)
        if not note or note.get('deleted') or note.get('system'):
            return
        if self.save_timer.isActive() and note_id == self.current_note_id:
            self.save_timer.stop()
            self._save_current_now()
            note = self.storage.get_note(note_id)
            if not note:
                return
        new_state = not bool(note.get('pinned'))
        updated = self.storage.set_note_pinned(note_id, new_state)
        if not updated:
            return
        self.current_note_id = note_id
        self._populate_list()
        self._select_note_by_id(note_id, silent=True)
        self.statusBar().showMessage(
            tr('已置顶') if new_state else tr('已取消置顶'),
            2500,
        )

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress:
            key = event.key()
            if obj is getattr(self, 'search_input', None):
                if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Down):
                    self._focus_list()
                    return True
                if key == Qt.Key_Escape:
                    if self.search_input.text():
                        self.search_input.clear()
                    else:
                        self._focus_body()
                    return True
            if obj is getattr(self, 'list_widget', None):
                if key in (Qt.Key_Return, Qt.Key_Enter):
                    item = self.list_widget.currentItem()
                    data = item.data(Qt.UserRole) if item else None
                    if self.view_switch.current_view() == 'archived' and data and data.get('kind'):
                        self._open_archive_item(data)
                    elif self.workspace_mode == 'screenshot':
                        att = data if isinstance(data, dict) else None
                        if att and att.get('id'):
                            self._open_attachment(att['id'])
                    else:
                        self._focus_body()
                    return True
                if key == Qt.Key_Escape:
                    self._focus_body()
                    return True
        return super().eventFilter(obj, event)

    # ============ 剪贴板 + 焦点监听 ============

    def _on_clipboard_changed(self):
        """剪贴板变了。如果包含追踪文件（多半是用户在剪切/复制），延后跑一次恢复。"""
        try:
            mime = QApplication.clipboard().mimeData()
        except Exception:
            return
        if not mime or not mime.hasUrls():
            return
        hit_names = self._remember_clipboard_move_candidates(mime)
        if not hit_names:
            return
        names_str = ', '.join(hit_names[:3]) + ('...' if len(hit_names) > 3 else '')
        self.statusBar().showMessage(
            tr('监听到 {names} 被复制/剪切，正在监测粘贴目标...', names=names_str),
            4000,
        )
        # 2.5s 后查一次（给粘贴留时间），再 8s 后兜底再查一次（用户慢慢操作的情况）
        self._clipboard_trigger_timer.start(2500)
        QTimer.singleShot(8000, self._on_clipboard_settled)

    def _on_clipboard_settled(self):
        if self._try_match_clipboard_target_dirs():
            return
        self.statusBar().showMessage(tr('还未确认粘贴目标；双击时会继续查找'), 4000)

    def _tracked_path_set(self):
        out = set()
        for _note, att in self.storage.all_external_attachments():
            if not att.get('tracking'):
                continue
            p = att.get('original_path', '')
            if p:
                out.add(os.path.normcase(os.path.normpath(p)))
        return out

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            # 覆盖所有最大化/还原路径：按钮、双击、原生贴边、启动恢复、托盘还原
            if hasattr(self, 'title_bar'):
                self.title_bar.sync_max_button(self.isMaximized())
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            # 切回 FRESH：30 秒内只触发一次，避免来回切换刷屏
            now = time.time()
            if now - self._last_focus_recovery > 30:
                self._last_focus_recovery = now
                self._focus_trigger_timer.start(400)

    def _on_focus_settled(self):
        # 切回 FRESH 时跑：1) 刷新所有路径仍在原位的追踪 (atomic save 检测)
        #               2) 对失踪的文件夹在后台静默用标记自动找回（受冷却/抑制保护）
        changed = False
        missing_folder = False
        for _note, att in self.storage.all_external_attachments():
            if att.get('tracking'):
                try:
                    if self.storage.refresh_tracking_if_changed(att):
                        changed = True
                        continue
                except Exception:
                    pass
            if att.get('type') == 'folder' and (att.get('tracking') or {}).get('tracking_id'):
                try:
                    if not self.storage.attachment_path_matches_tracking(att) \
                            and not Path(att.get('original_path', '')).exists():
                        missing_folder = True
                except Exception:
                    pass
        self._setup_tracking_watchers()
        if changed:
            self._refresh_external_attachment_views()
            self.statusBar().showMessage(tr('附件路径信息已刷新'), 2500)
        if missing_folder:
            self._start_auto_recovery(reason='auto')

    def _setup_ui(self):
        central = QWidget()
        central.setObjectName('app_shell')
        self.setCentralWidget(central)

        # 状态栏提前创建：懒创建会在第一条消息弹出时把整个内容区顶起来一跳，
        # 而且原生拉伸角标(size grip)在无边框窗口里非常突兀
        status = self.statusBar()
        status.setSizeGripEnabled(False)

        # 侧栏通到窗口顶部，标题栏只盖右栏（Notion/Linear 布局）；
        # 窗口拖动由 win_frame 的 HTCAPTION 命中测试接管，标题栏和
        # 侧栏顶部的空白处都可拖。
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.title_bar = CustomTitleBar(self)

        # 左侧栏
        self.sidebar = QWidget()
        self.sidebar.setObjectName('sidebar')
        self.sidebar.setFixedWidth(self.SIDEBAR_WIDTH)

        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 14)
        sidebar_layout.setSpacing(10)
        self.sidebar_layout = sidebar_layout

        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.new_btn = QPushButton('新建记事')
        self.new_btn.setObjectName('new_button')
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setIcon(build_ui_icon('plus', '#FFFFFF'))
        self.new_btn.setIconSize(QSize(16, 16))
        self.new_btn.clicked.connect(self._new_primary_action)
        self.more_btn = QPushButton('')
        self.more_btn.setObjectName('more_button')
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setFixedSize(36, 36)
        self.more_btn.setIcon(build_ui_icon('more', '#636366', '#1D1D1F'))
        self.more_btn.setIconSize(QSize(18, 18))
        self.more_btn.setToolTip('更多')
        self.more_btn.clicked.connect(self._show_more_menu)
        top_row.addWidget(self.new_btn, 1)
        top_row.addWidget(self.more_btn)

        self.workspace_switch = ModeSwitch()
        self.workspace_switch.text_btn.setText('文字记事')
        self.workspace_switch.shot_btn.setText('截图')
        self.workspace_switch.set_mode('screenshot', emit=False)
        self.workspace_switch.changed.connect(self._on_workspace_changed)

        self.search_input = QLineEdit()
        self.search_input.setObjectName('search_box')
        self.search_input.setPlaceholderText('搜索记录')
        self.search_input.setClearButtonEnabled(True)
        # 防抖：每个按键全量重建列表+缩略图太重，停顿 250ms 再刷新
        self._search_debounce = QTimer(self)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.setInterval(250)
        self._search_debounce.timeout.connect(self._refresh_current_workspace)
        self.search_input.textChanged.connect(lambda _: self._search_debounce.start())
        self.search_input.installEventFilter(self)

        self.view_switch = ViewSwitch()
        self.view_switch.changed.connect(self._on_view_changed)

        self.archive_category_filter = QComboBox()
        self.archive_category_filter.setObjectName('timeline_category_filter')
        self.archive_category_filter.setEditable(True)
        self.archive_category_filter.setInsertPolicy(QComboBox.NoInsert)
        self.archive_category_filter.addItem('全部分类', '')
        self.archive_category_filter.lineEdit().setPlaceholderText(tr('搜索分类'))
        self.archive_category_filter.currentIndexChanged.connect(lambda _: self._refresh_current_workspace())
        self.archive_category_filter.lineEdit().textChanged.connect(lambda _: self._on_archive_category_search_changed())

        self.list_widget = QListWidget()
        self.list_widget.setObjectName('note_list')
        self.list_widget.setMouseTracking(True)
        self._set_list_delegate('shot')
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_list_item_activated)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_list_menu)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list_widget.installEventFilter(self)

        sidebar_layout.addLayout(top_row)
        sidebar_layout.addWidget(self.workspace_switch)
        sidebar_layout.addWidget(self.search_input)
        sidebar_layout.addWidget(self.view_switch)
        sidebar_layout.addWidget(self.archive_category_filter)
        sidebar_layout.addWidget(self.list_widget, 1)

        # 底部时间线按钮
        self.timeline_btn = QPushButton('回顾时间线')
        self.timeline_btn.setObjectName('timeline_btn')
        self.timeline_btn.setCursor(Qt.PointingHandCursor)
        self.timeline_btn.setFocusPolicy(Qt.NoFocus)
        self.timeline_btn.setIcon(build_ui_icon('timeline', '#007AFF', '#0066D6'))
        self.timeline_btn.setIconSize(QSize(17, 17))
        self.timeline_btn.setToolTip('查看所有已完成的事项')
        self.timeline_btn.clicked.connect(self._show_timeline)
        sidebar_layout.addWidget(self.timeline_btn)

        # 右侧
        right = QWidget()
        right.setObjectName('right_panel')
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.editor = NoteEditor()
        self.editor.title_changed.connect(self._on_title_changed)
        self.editor.content_changed.connect(self._on_content_changed)
        self.editor.category_changed.connect(self._on_category_changed)
        self.editor.file_dropped.connect(self._on_file_dropped)
        self.editor.image_pasted.connect(self._on_image_pasted)
        self.editor.mode_changed.connect(self._on_mode_changed)
        self.editor.open_image.connect(self._open_image_viewer)
        self.editor.delete_attachment.connect(self._on_attachment_delete)
        self.editor.archive_attachment.connect(self._on_attachment_archive_toggled)
        self.editor.memo_changed.connect(self._on_attachment_memo_changed)

        self.screenshot_grid = ScreenshotGrid()
        self.screenshot_grid.selected_requested.connect(self._select_attachment_by_id)
        self.screenshot_grid.file_dropped.connect(self._on_file_dropped)
        self.screenshot_grid.image_pasted.connect(self._on_image_pasted)
        self.screenshot_grid.child_file_dropped.connect(self._add_child_attachment_to_screenshot)
        self.screenshot_grid.add_child_requested.connect(self._choose_child_attachment_for_screenshot)
        self.screenshot_grid.open_requested.connect(self._open_attachment)
        self.screenshot_grid.delete_requested.connect(self._on_attachment_delete)
        self.screenshot_grid.category_change_requested.connect(self._change_attachment_category)
        self.screenshot_grid.archive_toggled.connect(self._on_attachment_archive_toggled)
        self.screenshot_grid.memo_changed.connect(self._on_attachment_memo_changed)

        self.attachment_bar = AttachmentBar()
        self.attachment_bar.file_dropped.connect(self._on_attachment_bar_file_dropped)

        self.empty_state = EmptyState()
        self.empty_state.primary_action.connect(self._empty_primary_action)
        self.empty_state.secondary_action.connect(self._empty_secondary_action)

        self.right_stack = QStackedWidget()
        self.right_stack.setObjectName('right_stack')
        self.right_stack.addWidget(self.screenshot_grid)
        self.right_stack.addWidget(self.editor)
        self.right_stack.addWidget(self.empty_state)

        right_layout.addWidget(self.title_bar)
        right_layout.addWidget(self.right_stack, 1)
        right_layout.addWidget(self.attachment_bar)

        main_layout.addWidget(self.sidebar)
        main_layout.addWidget(right, 1)

    # ---- 列表 ----
    def _refresh_current_workspace(self):
        if self.view_switch.current_view() == 'archived':
            self._populate_archive_items()
            return
        if self.workspace_mode == 'screenshot':
            self.search_input.setPlaceholderText('搜索记录')
            self._refresh_screenshot_board()
        else:
            self.search_input.setPlaceholderText('搜索记录')
            self._populate_list()
            note = self.storage.get_note(self.current_note_id) if self.current_note_id else None
            if note and not note.get('deleted'):
                self._refresh_attachments_for(note)

    def _safe_refresh_current_workspace(self):
        try:
            self._refresh_current_workspace()
        except Exception:
            pass

    def _set_list_delegate(self, kind):
        """复用三个列表 delegate 实例。

        之前每次刷新都 new 一个新 delegate（旧的以 list_widget 为父对象
        永不释放），搜索时每个按键泄漏一个。"""
        cache = getattr(self, '_list_delegates', None)
        if cache is None:
            cache = {
                'note': NoteListDelegate(self.list_widget),
                'shot': ScreenshotListDelegate(self.list_widget),
                'archive': ArchiveListDelegate(self.list_widget),
            }
            self._list_delegates = cache
        delegate = cache[kind]
        if self.list_widget.itemDelegate() is not delegate:
            self.list_widget.setItemDelegate(delegate)

    def _refresh_external_attachment_views(self):
        # 合并刷新：同一事件循环内的多次触发只重建一次（之前是同步+singleShot(0)
        # 连刷两遍，每遍都全量重建列表和缩略图）
        timer = getattr(self, '_ext_refresh_timer', None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(0)
            timer.timeout.connect(self._safe_refresh_current_workspace)
            self._ext_refresh_timer = timer
        timer.start()

    def _on_workspace_changed(self, mode):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now(refresh_list=False)
        self.workspace_mode = mode
        self.current_note_id = None
        self.list_widget.clearSelection()
        if self.view_switch.current_view() == 'archived':
            self._set_new_button_text()
            self.search_input.setPlaceholderText('搜索记录')
            self.editor.clear()
            self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
            self.attachment_bar.setVisible(False)
            self._populate_archive_items()
            return
        if mode == 'screenshot':
            self._set_new_button_text()
            self.search_input.setPlaceholderText('搜索记录')
            self._set_list_delegate('shot')
            self.current_note_id = self.screenshot_board['id']
            self._refresh_screenshot_board()
            return

        self._set_new_button_text()
        self.search_input.setPlaceholderText('搜索记录')
        self._set_archive_filter_visible(False)
        self._set_list_delegate('note')
        self.editor.clear()
        self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
        self.current_note_id = None
        self._populate_list()
        if self.list_widget.count() > 0:
            first = self.list_widget.item(0).data(Qt.UserRole)
            if first and first.get('id'):
                self._select_note_by_id(first['id'])
        else:
            self._sync_empty_state()

    def _on_archive_category_search_changed(self):
        if self._updating_archive_category_filter:
            return
        self._search_debounce.start()

    def _archive_category_query(self):
        editor = self.archive_category_filter.lineEdit()
        text = (editor.text() if editor else self.archive_category_filter.currentText()).strip()
        if not text or text == tr('全部分类'):
            return ''
        return text

    def _archive_item_matches_workspace(self, item):
        return True

    def _archive_items_for_workspace(self):
        return [
            item for item in self.storage.all_timeline_items()
            if self._archive_item_matches_workspace(item)
        ]

    def _archive_categories_for_workspace(self):
        categories = set()
        for item in self._archive_items_for_workspace():
            category = self._archive_item_category(item)
            if category:
                categories.add(category)
        return sorted(categories)

    def _archive_item_category(self, item):
        if not item:
            return ''
        note = item.get('note') or {}
        if item.get('kind') == 'note':
            return (note.get('archive_category') or note.get('category') or '').strip()
        att = item.get('attachment') or {}
        return (att.get('archive_category') or att.get('category') or '').strip()

    def _archive_category_matches(self, category, query):
        query = (query or '').strip()
        if not query:
            return True
        category = (category or tr('未分类')).strip() or tr('未分类')
        return query.casefold() in category.casefold()

    def _archive_exact_category(self, query=None):
        query = self._archive_category_query() if query is None else (query or '').strip()
        if not query:
            return ''
        for category in self._archive_categories_for_workspace():
            if category == query:
                return category
        return ''

    def _clear_archive_category_filter_text(self):
        if not self._archive_category_query() and self.archive_category_filter.currentIndex() == 0:
            return False
        self._updating_archive_category_filter = True
        self.archive_category_filter.blockSignals(True)
        editor = self.archive_category_filter.lineEdit()
        if editor:
            editor.blockSignals(True)
        self.archive_category_filter.setCurrentIndex(0)
        if editor:
            editor.clear()
            editor.blockSignals(False)
        self.archive_category_filter.blockSignals(False)
        self._updating_archive_category_filter = False
        return True

    def _refresh_archive_category_filter(self):
        query = self._archive_category_query()
        visible_categories = [
            category for category in self._archive_categories_for_workspace()
            if self._archive_category_matches(category, query)
        ]
        exact_index = 0 if not query else -1
        self._updating_archive_category_filter = True
        self.archive_category_filter.blockSignals(True)
        editor = self.archive_category_filter.lineEdit()
        if editor:
            editor.blockSignals(True)
        self.archive_category_filter.clear()
        self.archive_category_filter.addItem(tr('全部分类'), '')
        for category in visible_categories:
            self.archive_category_filter.addItem(category, category)
        if query:
            for i in range(self.archive_category_filter.count()):
                if self.archive_category_filter.itemData(i) == query:
                    exact_index = i
                    break
        self.archive_category_filter.setCurrentIndex(exact_index)
        if editor:
            editor.setText(query)
            editor.setCursorPosition(len(query))
            editor.blockSignals(False)
        self.archive_category_filter.blockSignals(False)
        self._updating_archive_category_filter = False

    def _refresh_screenshot_board(self, preferred_attachment_id=None):
        if not hasattr(self, 'screenshot_grid'):
            return
        if self.view_switch.current_view() == 'archived':
            key = f'attachment:{preferred_attachment_id}' if preferred_attachment_id else ''
            self._populate_archive_items(selected_key=key)
            return
        self.search_input.setPlaceholderText('搜索记录')
        self._set_list_delegate('shot')
        selected_id = preferred_attachment_id
        if not selected_id:
            item = self.list_widget.currentItem()
            current_att = item.data(Qt.UserRole) if item else None
            selected_id = current_att.get('id') if current_att else None
        view = self.view_switch.current_view()
        self._refresh_archive_category_filter()
        self._set_archive_filter_visible(view == 'archived')
        category = self._archive_exact_category() if view == 'archived' else ''
        search = self.search_input.text().strip()
        items = self.storage.screenshot_items(view=view, category=category, search=search)
        if view == 'archived' and self._archive_category_query() and not category:
            category_query = self._archive_category_query()
            items = [
                att for att in items
                if self._archive_category_matches(att.get('archive_category') or att.get('category') or '', category_query)
            ]
        active_count, archived_count = self.storage.screenshot_counts()
        self.view_switch.set_counts(active_count, self._archive_total_count())

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for att in items:
            item = QListWidgetItem()
            item.setText(attachment_display_title(att))
            item.setData(Qt.UserRole, att)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        if selected_id and self._select_attachment_by_id(selected_id):
            pass
        elif self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        selected_id = ''
        item = self.list_widget.currentItem()
        current_att = item.data(Qt.UserRole) if item else None
        if current_att and current_att.get('id'):
            selected_id = current_att.get('id')
        self.screenshot_grid.set_attachments(items, self.storage.path_for, selected_id=selected_id)
        self.right_stack.setCurrentWidget(self.screenshot_grid)
        self.current_note_id = self.screenshot_board['id']
        self._refresh_screenshot_child_attachments()

    def _current_screenshot_attachment(self):
        if self.workspace_mode != 'screenshot' or self.view_switch.current_view() == 'archived':
            return None
        item = self.list_widget.currentItem()
        data = item.data(Qt.UserRole) if item else None
        if data and is_image_attachment(data):
            return data
        return None

    def _current_screenshot_attachment_id(self):
        att = self._current_screenshot_attachment()
        return att.get('id') if att else ''

    def _refresh_screenshot_child_attachments(self):
        if self.workspace_mode != 'screenshot' or self.view_switch.current_view() == 'archived':
            return
        # 把“当前选中的那张截图”的子附件显示到底部附件栏（与文字模式同一个栏、
        # 同样位置）。换一张截图就显示那张截图的附件；没选中截图则隐藏。
        parent = self._current_screenshot_attachment()
        children = [
            c for c in ((parent.get('attachments') if parent else []) or [])
            if not c.get('deleted')
        ]
        self.attachment_bar.set_attachments(
            children,
            self.storage.path_for,
            self._on_attachment_delete,
            recover_resolver=self._resolve_attachment_path,
            on_category_change=self._change_attachment_category,
        )
        # 选中截图时即显示附件栏（即使为空，方便直接拖入 / 点 + 添加）。
        self.attachment_bar.setVisible(parent is not None)

    def _active_note_count(self):
        return sum(
            1 for note in self.storage.notes
            if not note_belongs_to_screenshot_workspace(note) and not note.get('deleted') and not note.get('archived')
        )

    def _archive_total_count(self):
        return len(self._archive_items_for_workspace())

    def _populate_archive_items(self, selected_key=''):
        if not hasattr(self, 'list_widget'):
            return
        if not selected_key:
            item = self.list_widget.currentItem()
            selected_key = archive_item_key(item.data(Qt.UserRole)) if item else ''

        self._set_list_delegate('archive')
        self._refresh_archive_category_filter()
        self._set_archive_filter_visible(True)
        self.search_input.setPlaceholderText('搜索记录')

        category_query = self._archive_category_query()
        search = self.search_input.text().strip().lower()
        items = self._archive_items_for_workspace()
        if category_query:
            items = [
                item for item in items
                if self._archive_category_matches(self._archive_item_category(item), category_query)
            ]
        if search:
            items = [item for item in items if search in archive_item_search_text(item)]

        active_count = self.storage.screenshot_counts()[0] if self.workspace_mode == 'screenshot' else self._active_note_count()
        self.view_switch.set_counts(active_count, self._archive_total_count())

        image_attachments = [
            item.get('attachment') for item in items
            if item.get('kind') == 'attachment'
        ]
        image_attachments = [att for att in image_attachments if att]
        selected_image_id = ''
        selected_item = self.list_widget.currentItem()
        if selected_item:
            selected_data = selected_item.data(Qt.UserRole) or {}
            if selected_data.get('kind') == 'attachment':
                selected_image_id = (selected_data.get('attachment') or {}).get('id', '')
        self.screenshot_grid.set_attachments(
            image_attachments,
            self.storage.path_for,
            selected_id=selected_image_id,
        )

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for data in items:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, data)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)

        selected = bool(selected_key and self._select_archive_item_by_key(selected_key))
        if not selected and not self._suppress_auto_select and self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        if self.list_widget.currentRow() < 0:
            self.current_note_id = None
            self.editor.clear()
            self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
            self.attachment_bar.setVisible(False)
            if image_attachments:
                self.right_stack.setCurrentWidget(self.screenshot_grid)
            else:
                self._sync_empty_state()

    def _first_visible_note(self):
        if self.list_widget.count() <= 0:
            return None
        item = self.list_widget.item(0)
        return item.data(Qt.UserRole) if item else None

    def _populate_list(self):
        if self.view_switch.current_view() == 'archived':
            self._populate_archive_items()
            return
        self.search_input.setPlaceholderText('搜索记录')
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self._set_list_delegate('note')
        search = self.search_input.text().strip().lower()
        view = self.view_switch.current_view()
        self._refresh_archive_category_filter()
        self._set_archive_filter_visible(view == 'archived')
        category = self._archive_exact_category() if view == 'archived' else ''
        category_query = self._archive_category_query() if view == 'archived' else ''
        active_count = 0
        archived_count = 0
        for note in self.storage.notes:
            if note_belongs_to_screenshot_workspace(note):
                continue
            if note.get('deleted'):
                continue
            is_archived = bool(note.get('archived', False))
            if is_archived:
                archived_count += 1
            else:
                active_count += 1
            if view == 'active' and is_archived:
                continue
            if view == 'archived' and not is_archived:
                continue
            if category and (note.get('archive_category') or note.get('category') or '') != category:
                continue
            if category_query and not category:
                note_category = note.get('archive_category') or note.get('category') or ''
                if not self._archive_category_matches(note_category, category_query):
                    continue
            if search:
                if search not in note_search_text(note):
                    continue
            item = QListWidgetItem()
            item.setData(Qt.UserRole, note)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self.view_switch.set_counts(active_count, self._archive_total_count())
        if self.current_note_id:
            visible_current = self._select_note_by_id(self.current_note_id, silent=True)
            if not visible_current:
                if self.save_timer.isActive():
                    self.save_timer.stop()
                    self._save_current_now(refresh_list=False)
                self.current_note_id = None
                self.editor.clear()
                self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
                self.attachment_bar.setVisible(False)

        if not self._suppress_auto_select and not self.current_note_id and self.list_widget.count() > 0:
            first = self.list_widget.item(0).data(Qt.UserRole)
            if first and first.get('id'):
                self._select_note_by_id(first['id'])
        self._sync_empty_state()

    def _has_active_filters(self):
        has_search = bool((self.search_input.text() or '').strip())
        has_category = (
            self.view_switch.current_view() == 'archived'
            and bool(self._archive_category_query())
        )
        return has_search or has_category

    def _sync_empty_state(self):
        if not hasattr(self, 'right_stack'):
            return
        if self.view_switch.current_view() != 'archived' and self.workspace_mode == 'screenshot':
            self.right_stack.setCurrentWidget(self.screenshot_grid)
            self.current_note_id = self.screenshot_board['id']
            # 附件栏跟随当前选中的截图（选中则显示其附件，未选中则隐藏）。
            self._refresh_screenshot_child_attachments()
            return
        current_note = self.storage.get_note(self.current_note_id) if self.current_note_id else None
        has_current = bool(current_note and not current_note.get('deleted'))
        if has_current:
            self.right_stack.setCurrentWidget(self.editor)
            return

        filtered = self._has_active_filters()
        category = self._archive_category_query() if self.view_switch.current_view() == 'archived' else ''
        self.empty_state.configure(
            view=self.view_switch.current_view(),
            filtered=filtered,
            search=(self.search_input.text() or '').strip(),
            category=category,
            has_rows=self.list_widget.count() > 0,
        )
        self.right_stack.setCurrentWidget(self.empty_state)
        self.attachment_bar.setVisible(False)

    def _clear_filters(self):
        changed = False
        if self.search_input.text():
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            changed = True
        if self._clear_archive_category_filter_text():
            changed = True
        if changed:
            self._refresh_current_workspace()

    def _empty_primary_action(self):
        if self._has_active_filters():
            self._new_primary_action()
            return

        if self.view_switch.current_view() == 'archived':
            self.view_switch.set_view('active', emit=True)
            return

        self._new_primary_action()

    def _empty_secondary_action(self):
        if self._has_active_filters():
            self._clear_filters()
            return
        if self.view_switch.current_view() == 'archived':
            self._show_timeline()

    def _select_note_by_id(self, note_id, silent=False):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            note = data.get('note') if isinstance(data, dict) and data.get('kind') == 'note' else data
            if note and note.get('id') == note_id:
                if silent:
                    self.list_widget.blockSignals(True)
                    self.list_widget.setCurrentItem(item)
                    self.list_widget.blockSignals(False)
                else:
                    self.list_widget.setCurrentItem(item)
                return True
        return False

    def _select_attachment_by_id(self, attachment_id):
        found = False
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            att = data.get('attachment') if isinstance(data, dict) and data.get('kind') == 'attachment' else data
            if att and att.get('id') == attachment_id:
                if self.list_widget.currentItem() is not item:
                    self.list_widget.setCurrentItem(item)
                found = True
                break
        if hasattr(self, 'screenshot_grid'):
            self.screenshot_grid.set_selected_attachment(attachment_id if found else '')
        return found

    def _select_archive_item_by_key(self, key):
        if not key:
            return False
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if archive_item_key(item.data(Qt.UserRole)) == key:
                self.list_widget.setCurrentItem(item)
                return True
        return False

    def _archive_image_attachments_from_list(self):
        attachments = []
        for i in range(self.list_widget.count()):
            data = self.list_widget.item(i).data(Qt.UserRole)
            if data and data.get('kind') == 'attachment':
                att = data.get('attachment') or {}
                attachments.append(att)
        return attachments

    def _load_note_by_id(self, note_id):
        note = self.storage.get_note(note_id)
        if not note or note.get('deleted'):
            return False
        self.current_note_id = note_id
        self.editor.load_note(note)
        self._refresh_editor_categories()
        self._refresh_attachments_for(note)
        self.right_stack.setCurrentWidget(self.editor)
        return True

    def _open_archive_item(self, data):
        if not data:
            return
        if data.get('kind') == 'attachment':
            att = data.get('attachment') or {}
            if att.get('id'):
                self._open_attachment(att['id'])
            return
        note = data.get('note') or {}
        if note.get('id'):
            self._load_note_by_id(note['id'])

    def _on_list_item_activated(self, item):
        if not item:
            return
        data = item.data(Qt.UserRole)
        if self.view_switch.current_view() == 'archived' and data and data.get('kind'):
            self._open_archive_item(data)
            return
        if self.workspace_mode == 'screenshot':
            att = data if isinstance(data, dict) else None
            if att and att.get('id'):
                self._open_attachment(att['id'])
            return
        self._focus_body()

    def _on_selection_changed(self):
        if self.view_switch.current_view() == 'archived':
            items = self.list_widget.selectedItems()
            if not items:
                self._sync_empty_state()
                return
            data = items[0].data(Qt.UserRole)
            if not data:
                self._sync_empty_state()
                return
            if data.get('kind') == 'attachment':
                if self.save_timer.isActive():
                    self.save_timer.stop()
                    self._save_current_now(refresh_list=False)
                self.current_note_id = None
                self.screenshot_grid.set_attachments(
                    self._archive_image_attachments_from_list(),
                    self.storage.path_for,
                    selected_id=(data.get('attachment') or {}).get('id', ''),
                )
                self.right_stack.setCurrentWidget(self.screenshot_grid)
                self.attachment_bar.setVisible(False)
                return
            note = data.get('note') or {}
            if not note or note.get('id') == self.current_note_id:
                self._sync_empty_state()
                return
            if self.save_timer.isActive():
                self.save_timer.stop()
                self._save_current_now(refresh_list=False)
            self.current_note_id = note['id']
            refreshed = self.storage.get_note(note['id']) or note
            self.editor.load_note(refreshed)
            self._refresh_editor_categories()
            self._refresh_attachments_for(refreshed)
            self.right_stack.setCurrentWidget(self.editor)
            return

        if self.workspace_mode == 'screenshot':
            self._refresh_screenshot_child_attachments()
            item = self.list_widget.currentItem()
            data = item.data(Qt.UserRole) if item else None
            att = data.get('attachment') if isinstance(data, dict) and data.get('kind') == 'attachment' else data
            self.screenshot_grid.set_selected_attachment(att.get('id') if att else '')
            return
        items = self.list_widget.selectedItems()
        if not items:
            self._sync_empty_state()
            return
        note = items[0].data(Qt.UserRole)
        if not note or note['id'] == self.current_note_id:
            self._sync_empty_state()
            return

        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now(refresh_list=False)

        self.current_note_id = note['id']
        # 重新从 storage 取最新数据
        for n in self.storage.notes:
            if n['id'] == note['id']:
                note = n
                break
        self.editor.load_note(note)
        self._refresh_editor_categories()
        self._refresh_attachments_for(note)
        self.right_stack.setCurrentWidget(self.editor)

    def _show_list_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        if self.view_switch.current_view() == 'archived' and data.get('kind'):
            self._show_archive_menu(data, self.list_widget.viewport().mapToGlobal(pos))
            return
        if self.workspace_mode == 'screenshot' and data.get('id') and data.get('original_name'):
            self._show_screenshot_menu(data, self.list_widget.viewport().mapToGlobal(pos))
            return
        note = data
        is_archived = bool(note.get('archived', False))
        is_pinned = bool(note.get('pinned', False))
        menu = QMenu(self)
        pin_action = menu.addAction(tr('取消置顶') if is_pinned else tr('置顶'))
        menu.addSeparator()
        archive_action = menu.addAction('取消归档' if is_archived else '归档')
        menu.addSeparator()
        delete_action = menu.addAction('删除')
        action = menu.exec(self.list_widget.viewport().mapToGlobal(pos))
        if action == pin_action:
            self._toggle_pin(note['id'])
        elif action == archive_action:
            self._toggle_archive(note['id'])
        elif action == delete_action:
            self._delete_note(note['id'])

    def _show_archive_menu(self, data, global_pos):
        menu = QMenu(self)
        if data.get('kind') == 'attachment':
            note = data.get('note') or {}
            att = data.get('attachment') or {}
            view = menu.addAction('查看大图' if is_image_attachment(att) else '打开')
            open_note = menu.addAction('打开所属备忘录')
            change_category = menu.addAction(tr('修改分类'))
            unarchive = menu.addAction('取消归档')
            menu.addSeparator()
            delete = menu.addAction(tr('删除附件'))
            action = menu.exec(global_pos)
            if action == view:
                self._open_attachment(att.get('id'))
            elif action == open_note:
                self._load_note_by_id(note.get('id'))
            elif action == change_category:
                self._change_archive_attachment_category(note.get('id'), att.get('id'))
            elif action == unarchive:
                self.storage.update_attachment(note.get('id'), att.get('id'), archived=False, archived_at='')
                self._refresh_current_workspace()
            elif action == delete:
                self._delete_archived_attachment(att.get('id'))
            return

        note = data.get('note') or {}
        open_note = menu.addAction('打开备忘录')
        change_category = menu.addAction(tr('修改分类'))
        unarchive = menu.addAction('取消归档')
        menu.addSeparator()
        delete = menu.addAction('删除')
        action = menu.exec(global_pos)
        if action == open_note:
            self._load_note_by_id(note.get('id'))
        elif action == change_category:
            self._change_archive_note_category(note.get('id'))
        elif action == unarchive:
            self._toggle_archive(note.get('id'))
        elif action == delete:
            self._delete_note(note.get('id'))

    def _delete_archived_attachment(self, attachment_id):
        if not attachment_id:
            return False
        note, att = self.storage.find_attachment(attachment_id)
        if not note or note.get('deleted') or not att or att.get('deleted'):
            return False
        if not self.storage.remove_attachment(note.get('id'), attachment_id):
            return False
        self._populate_archive_items(selected_key=f'attachment:{attachment_id}')
        self.statusBar().showMessage(tr('附件已移到最近删除'), 4000)
        return True

    def _update_item_for_note(self, note):
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            item_note = data.get('note') if isinstance(data, dict) and data.get('kind') == 'note' else data
            if item_note and item_note.get('id') == note['id']:
                item.setData(Qt.UserRole, note)
                idx = self.list_widget.indexFromItem(item)
                self.list_widget.update(idx)
                break

    # ---- 操作 ----
    def _new_primary_action(self):
        if self.workspace_mode == 'screenshot':
            self._show_screenshot_add_menu()
        else:
            self.create_new_note()

    def _show_screenshot_add_menu(self):
        menu = QMenu(self)
        capture_action = menu.addAction('框选截图')
        image_action = menu.addAction('选择截图图片...')
        file_action = menu.addAction('给当前截图添加文件...')
        folder_action = menu.addAction('给当前截图添加文件夹...')
        action = menu.exec(self.new_btn.mapToGlobal(self.new_btn.rect().bottomLeft()))
        if action == capture_action:
            self._capture_screenshot_region()
        elif action == image_action:
            self._browse_screenshot()
        elif action == file_action:
            self._add_file_to_current_screenshot()
        elif action == folder_action:
            self._add_folder_to_current_screenshot()

    def _prepare_screenshot_workspace(self, clear_filters=False):
        if self.workspace_mode != 'screenshot' and self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        if self.workspace_mode != 'screenshot':
            self.workspace_mode = 'screenshot'
            self.workspace_switch.set_mode('screenshot', emit=False)
            self._set_new_button_text()
            self.search_input.setPlaceholderText('搜索记录')
            self._set_list_delegate('shot')
            self.current_note_id = self.screenshot_board['id']
        if clear_filters:
            if self.view_switch.current_view() != 'active':
                self.view_switch.set_view('active', emit=False)
            if self.search_input.text():
                self.search_input.blockSignals(True)
                self.search_input.clear()
                self.search_input.blockSignals(False)
            self._clear_archive_category_filter_text()
        self._set_archive_filter_visible(self.view_switch.current_view() == 'archived')
        self.current_note_id = self.screenshot_board['id']
        self._refresh_screenshot_board()

    def _capture_screenshot_region(self, clear_filters=False, quiet_failure=False):
        if getattr(self, '_capture_in_progress', False):
            return
        self._capture_in_progress = True
        try:
            self._prepare_screenshot_workspace(clear_filters=clear_filters)
        except Exception:
            self._capture_in_progress = False
            raise

        was_visible = self.isVisible()
        was_minimized = self.isMinimized()
        if was_visible:
            self.hide()

        def restore_after_capture():
            self._capture_in_progress = False
            if was_visible:
                self.showMinimized() if was_minimized else self.show()
                self.raise_()
                self.activateWindow()

        def do_capture():
            # try/finally 保证 _capture_in_progress 一定被复位——
            # 之前任何一处抛异常都会让截图功能直到重启前永久失效
            accepted = False
            result_path = None
            failed = False
            try:
                pixmap, virtual = grab_virtual_desktop_pixmap()
                if pixmap is None or pixmap.isNull() or virtual.isEmpty():
                    failed = True
                else:
                    dlg = RegionCaptureOverlay(pixmap, virtual)
                    accepted = dlg.exec() == QDialog.Accepted
                    result_path = dlg.result_path
            except Exception:
                logger.exception('框选截图过程出错')
                failed = True
            finally:
                restore_after_capture()
            if failed:
                if quiet_failure and getattr(self, 'tray_icon', None):
                    self.tray_icon.showMessage('框选截图失败', '无法获取屏幕截图。', QSystemTrayIcon.Warning, 3000)
                else:
                    QMessageBox.warning(self, '框选截图失败', '无法获取屏幕截图。')
                return
            if accepted and result_path:
                self._on_image_pasted(result_path)

        QTimer.singleShot(180, do_capture)

    def _browse_screenshot(self):
        self._prepare_screenshot_workspace()
        files, _ = QFileDialog.getOpenFileNames(
            self,
            '选择截图',
            '',
            '图片文件 (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.svg *.ico);;所有文件 (*.*)'
        )
        for file_path in files:
            self._add_screenshot_from_path(file_path, copy=False)

    def _browse_screenshot_folder(self):
        self._add_folder_to_current_screenshot()

    def _quick_new_text_note(self):
        self._show_window_from_tray(force=True)
        self.create_new_note()

    def _quick_capture_region(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        self._capture_screenshot_region(clear_filters=True, quiet_failure=True)

    def _quick_capture_clipboard_image(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        self._prepare_screenshot_workspace(clear_filters=True)
        path = grab_clipboard_image_path()
        if not path:
            if getattr(self, 'tray_icon', None):
                self.tray_icon.showMessage(
                    tr('剪贴板里没有图片'),
                    tr('没有可保存的剪贴板图片。'),
                    QSystemTrayIcon.Information,
                    2600,
                )
            else:
                self.statusBar().showMessage(tr('剪贴板里没有图片'), 3000)
            return
        self._on_image_pasted(path)
        if getattr(self, 'tray_icon', None):
            self.tray_icon.showMessage(
                tr('已保存剪贴板图片'),
                tr('剪贴板图片已保存到截图工作区。'),
                QSystemTrayIcon.Information,
                2600,
            )
        else:
            self.statusBar().showMessage(tr('已保存剪贴板图片'), 3000)

    def _show_screenshot_menu(self, attachment, global_pos):
        menu = QMenu(self)
        view = menu.addAction('查看大图' if is_image_attachment(attachment) else '打开')
        archive = menu.addAction('取消归档' if attachment.get('archived') else '归档')
        menu.addSeparator()
        delete = menu.addAction(tr('删除附件'))
        action = menu.exec(global_pos)
        if action == view:
            self._open_attachment(attachment['id'])
        elif action == archive:
            self._on_attachment_archive_toggled(attachment['id'])
        elif action == delete:
            self._on_attachment_delete(attachment['id'])

    def create_new_note(self):
        self.workspace_mode = 'text'
        self.workspace_switch.set_mode('text', emit=False)
        self._set_list_delegate('note')
        self._set_new_button_text()
        self.search_input.setPlaceholderText('搜索记录')
        self._set_archive_filter_visible(False)
        if self.view_switch.current_view() != 'active':
            self.view_switch.set_view('active', emit=False)
        if self.search_input.text():
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)

        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()

        note = self.storage.create_note()
        self.current_note_id = note['id']
        self._populate_list()
        self._select_note_by_id(note['id'], silent=True)
        self.editor.load_note(note)
        self._refresh_editor_categories()
        self._refresh_attachments_for(note)
        self.right_stack.setCurrentWidget(self.editor)
        self.editor.focus_title()

    def _delete_note(self, note_id):
        if note_id == self.current_note_id and self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()

        was_current = (note_id == self.current_note_id)
        self.storage.delete_note(note_id)

        if was_current:
            self.current_note_id = None
            self.editor.clear()
            self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
            self.attachment_bar.setVisible(False)

        self._populate_list()
        self._select_first_or_empty()
        self._sync_empty_state()
        self.statusBar().showMessage(tr('已移到最近删除'), 4000)

    def _choose_archive_category(self, current='', required=True):
        return choose_archive_category(self, self.storage, current, required=required)

    def _archive_category_status(self, category):
        category = (category or '').strip()
        if category:
            return tr('已修改分类为“{category}”', category=category)
        return tr('已清除分类')

    def _attachment_category_status(self, category):
        category = (category or '').strip()
        if category:
            return tr('已修改附件分类为“{category}”', category=category)
        return tr('已清除附件分类')

    def _change_attachment_category(self, attachment_id):
        note, att = self.storage.find_attachment(attachment_id)
        if not note or note.get('deleted') or not att or att.get('deleted'):
            return
        category = choose_attachment_category(
            self, self.storage, att.get('archive_category') or att.get('category') or ''
        )
        if category is None:
            return
        self.storage.update_attachment(note.get('id'), attachment_id, category=category, archive_category=category)
        self._refresh_current_workspace()
        self.statusBar().showMessage(self._attachment_category_status(category), 3000)

    def _change_archive_attachment_category(self, note_id, attachment_id):
        note, att = self.storage.find_attachment(attachment_id)
        if not note or note.get('deleted') or not att or att.get('deleted'):
            return
        category = self._choose_archive_category(
            att.get('archive_category') or att.get('category') or '',
            required=False,
        )
        if category is None:
            return
        self.storage.update_attachment(note.get('id'), attachment_id, category=category, archive_category=category)
        self._refresh_editor_categories()
        self._refresh_current_workspace()
        self.statusBar().showMessage(self._archive_category_status(category), 3000)

    def _change_archive_note_category(self, note_id):
        note = self.storage.get_note(note_id)
        if not note or note.get('deleted'):
            return
        category = self._choose_archive_category(
            note.get('archive_category') or note.get('category') or '',
            required=True,
        )
        if category is None:
            return
        self.storage.update_note(note_id, archive_category=category)
        if note_id == self.current_note_id:
            refreshed = self.storage.get_note(note_id)
            if refreshed:
                self.editor.load_note(refreshed)
                self._refresh_attachments_for(refreshed)
        self._refresh_editor_categories()
        self._refresh_current_workspace()
        self.statusBar().showMessage(self._archive_category_status(category), 3000)

    def _toggle_archive(self, note_id):
        target = None
        for note in self.storage.notes:
            if note['id'] == note_id:
                target = note
                break
        if not target:
            return
        new_state = not bool(target.get('archived', False))
        archive_category = ''
        if new_state:
            archive_category = self._choose_archive_category(
                target.get('archive_category') or target.get('category') or ''
            )
            if archive_category is None:
                return
        updates = {
            'archived': new_state,
            'archived_at': datetime.now().isoformat() if new_state else '',
        }
        if new_state:
            updates['archive_category'] = archive_category
        self.storage.update_note(note_id, **updates)

        view = self.view_switch.current_view()
        still_in_view = (view == 'active' and not new_state) or (view == 'archived' and new_state)
        leaving_current_view = note_id == self.current_note_id and not still_in_view
        if leaving_current_view:
            self.current_note_id = None
            self.editor.clear()
            self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
            self.attachment_bar.setVisible(False)

        if leaving_current_view:
            self._suppress_auto_select = True
            try:
                self._populate_list()
            finally:
                self._suppress_auto_select = False
            self.list_widget.clearSelection()
        else:
            self._populate_list()
        self._sync_empty_state()

    def _on_view_changed(self, view):
        if self.save_timer.isActive():
            self.save_timer.stop()
            # refresh_list=False：此刻列表即将按新视图整体重建，带默认刷新的
            # 保存会提前填充归档列表并自动选中，编辑器残留一条未选中的归档
            # 笔记（与 _on_workspace_changed 的处理一致）
            self._save_current_now(refresh_list=False)

        if self.workspace_mode == 'screenshot':
            self._refresh_screenshot_board()
            return

        self.current_note_id = None
        self.editor.clear()
        self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
        self.attachment_bar.setVisible(False)
        self._suppress_auto_select = True
        try:
            self._populate_list()
        finally:
            self._suppress_auto_select = False
        self.list_widget.clearSelection()
        self._sync_empty_state()
        # 归档视图为空就保持空白(不自动建新note)

    def _select_first_or_empty(self):
        if self.list_widget.count() > 0:
            first = self.list_widget.item(0).data(Qt.UserRole)
            if isinstance(first, dict) and first.get('kind'):
                self._select_archive_item_by_key(archive_item_key(first))
            elif first and first.get('id'):
                self._select_note_by_id(first['id'])
        else:
            self._sync_empty_state()

    def _on_title_changed(self, text):
        if not self.current_note_id:
            return
        note = self.storage.get_note(self.current_note_id)
        if note and note.get('deleted'):
            return
        self.save_timer.start(400)

    def _on_content_changed(self, content):
        if not self.current_note_id:
            return
        note = self.storage.get_note(self.current_note_id)
        if note and note.get('deleted'):
            return
        self.save_timer.start(700)

    def _on_category_changed(self, text):
        if not self.current_note_id:
            return
        note = self.storage.get_note(self.current_note_id)
        if note and note.get('deleted'):
            return
        self.save_timer.start(400)

    def _save_current_now(self, refresh_list=True):
        if not self.current_note_id:
            return
        current = self.storage.get_note(self.current_note_id)
        if current and current.get('deleted'):
            return
        title = self.editor.get_title() or '新建备忘录'
        content = self.editor.get_content()
        content_format = self.editor.get_content_format()
        category = self.editor.get_category()
        mode = self.editor.get_mode()
        note = self.storage.update_note(
            self.current_note_id,
            title=title,
            content=content,
            content_format=content_format,
            category=category,
            mode=mode,
        )
        if note:
            self.editor.update_time_label(note.get('updated_at', ''))
            self._refresh_editor_categories()
            self._refresh_archive_category_filter()
            if refresh_list and self.workspace_mode == 'text':
                self._populate_list()
            else:
                self._update_item_for_note(note)

    def _flush_pending_editor(self, refresh_list=True):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now(refresh_list=refresh_list)

    def prepare_for_session_end(self):
        self._session_ending = True
        self._flush_pending_editor()
        try:
            self.storage.save()
        except Exception:
            logger.exception('会话结束前保存数据失败')
        try:
            self._save_window_state()
        except Exception:
            logger.exception('会话结束前保存窗口状态失败')

    def _refresh_editor_categories(self):
        if hasattr(self, 'editor'):
            self.editor.set_categories(self.storage.all_categories())

    def _attachment_archive_categories(self):
        return sorted(
            set(self.storage.all_categories())
            | set(attachment_category_candidates(self.storage))
        )

    def _refresh_attachments_for(self, note):
        attachments = [
            att for att in (note.get('attachments', []) or [])
            if not att.get('deleted')
        ]
        mode = note.get('mode', 'text')
        self.attachment_bar.set_attachments(
            attachments,
            self.storage.path_for,
            self._on_attachment_delete,
            recover_resolver=self._resolve_attachment_path,
            on_category_change=self._change_attachment_category,
        )
        self.editor.update_screenshot_grid(attachments, self.storage.path_for)
        self.attachment_bar.setVisible(mode != 'screenshot' and bool(attachments))
        # 新加进来的附件需要补挂监听
        if hasattr(self, '_tracked_watcher'):
            self._setup_tracking_watchers()

    def _resolve_attachment_path(self, attachment, scanned_path=None, request_scan=False):
        """供 AttachmentCard 调用。
        - request_scan=True: 启动后台扫描（非阻塞），找到后自动更新
        - scanned_path 给出: 采纳并持久化
        - 否则: 仅尝试快速 File ID 恢复
        """
        if request_scan:
            self._start_targeted_scan(attachment)
            return None
        if scanned_path:
            self.storage.adopt_external_path(attachment, scanned_path)
            self._refresh_external_attachment_views()
            return scanned_path
        new_path, changed = self.storage.resolve_external_path(attachment, scan=False)
        if new_path and Path(new_path).exists():
            if changed:
                self._refresh_external_attachment_views()
            return str(new_path)
        return None

    # ============ 后台扫描管理 ============

    def _ensure_scan_state(self):
        if not hasattr(self, '_targeted_scans'):
            self._targeted_scans = []
        if not hasattr(self, '_auto_recovery_worker'):
            self._auto_recovery_worker = None

    def _update_scan_status(self):
        """根据当前活跃的扫描任务，更新状态栏文字。"""
        self._ensure_scan_state()
        active = len(self._targeted_scans)
        auto = self._auto_recovery_worker is not None and self._auto_recovery_worker.isRunning()
        parts = []
        if auto:
            parts.append(tr('正在后台自动查找已移动的文件'))
        if active:
            parts.append(tr('重点查找 {count} 项', count=active))
        if parts:
            self.statusBar().showMessage(' · '.join(parts))
        else:
            self.statusBar().clearMessage()

    def _start_targeted_scan(self, attachment):
        """针对单个附件的全盘扫描（用户主动触发，非阻塞）。"""
        self._ensure_scan_state()
        tracking = attachment.get('tracking') or {}
        if not tracking:
            QMessageBox.information(self, '无法查找', '该附件加入时未生成追踪标记，无法定位。')
            return
        if attachment.get('type') == 'folder':
            new_path, changed = self.storage.resolve_external_path(attachment, scan=False)
            if new_path and Path(new_path).exists():
                if changed:
                    self._refresh_external_attachment_views()
                    if hasattr(self, '_tracked_watcher'):
                        self._setup_tracking_watchers()
                self.statusBar().showMessage(
                    tr('已同步文件夹位置：{path}', path=str(new_path)),
                    4000,
                )
                return
        att_id = attachment['id']
        for s in self._targeted_scans:
            if s['att_id'] == att_id:
                if s.get('dlg'):
                    s['dlg'].raise_()
                return

        name = attachment.get('original_name', '')
        scan_name = '' if attachment.get('type') == 'folder' and tracking.get('tracking_id') else name
        size_hint = tracking.get('size_snapshot') or attachment.get('size')

        worker = FtrackScanWorker(
            tracking, name_fallback=scan_name,
            scan_settings=self.storage.scan_settings,
            is_folder=(attachment.get('type') == 'folder'),
            parent=self,
        )
        dlg = make_scan_dialog(self, name)

        state = {
            'worker': worker, 'dlg': dlg, 'att_id': att_id,
            'name': name, 'size_hint': size_hint,
        }
        self._targeted_scans.append(state)

        def on_phase(text):
            dlg.setLabelText(text + '...')

        def on_progress(directory):
            shown = directory if len(directory) <= 64 else '...' + directory[-61:]
            dlg.setLabelText(tr('扫描中:\n{path}', path=shown))

        def on_finished(result):
            dlg.close()
            if state in self._targeted_scans:
                self._targeted_scans.remove(state)
            self._update_scan_status()
            self._apply_targeted_scan_result(att_id, name, size_hint, result)

        worker.phase_changed.connect(on_phase)
        worker.progress.connect(on_progress)
        worker.finished_with_result.connect(on_finished)
        dlg.canceled.connect(worker.cancel)
        worker.start()
        dlg.show()
        self._update_scan_status()

    def _apply_targeted_scan_result(self, att_id, name, size_hint, result):
        note, att = self.storage.find_attachment(att_id)
        if not att:
            return
        if (result or {}).get('cancelled'):
            return
        found = result.get('path') if result else None
        if not found:
            error = (result or {}).get('error')
            if error:
                # 扫描中途出错和"确实不存在"是两回事，不能都说"未找到"
                QMessageBox.warning(
                    self, '扫描出错',
                    f'查找 "{name}" 时扫描过程出错，结果可能不完整：\n{error}\n\n'
                    f'详细信息见数据目录下的 fresh.log。')
                return
            candidates = (result or {}).get('candidates') or []
            candidates = [c for c in candidates if not ftrack.is_recycled_path(c)]
            if not candidates:
                QMessageBox.warning(self, '未找到', f'未在磁盘上找到与 "{name}" 匹配的文件。')
                return
            if len(candidates) == 1 and not (result or {}).get('unverified'):
                found = candidates[0]
            else:
                # 唯一候选但内容 hash 对不上时也交给用户确认，不能静默采纳
                picker = CandidatePickerDialog(candidates, name, size_hint=size_hint, parent=self)
                if picker.exec() != QDialog.Accepted:
                    return
                found = picker.selected_path
        # 扫描/候选框停留的几分钟里文件可能又被移走，Everything 索引滞后也会
        # 给出旧路径；adopt 里的 resolve() 对不存在路径不报错，会把死路径写进
        # original_path，还弹"已找到"——采纳前必须做一次存在性校验。
        try:
            found_exists = Path(found).exists()
        except OSError:
            found_exists = False
        if not found_exists:
            QMessageBox.warning(
                self, '位置已变化',
                f'"{name}" 的位置在扫描完成后又发生了变化，请重新查找。')
            return
        self.storage.adopt_external_path(att, found)
        if note and note.get('id') == self.current_note_id:
            self._refresh_attachments_for(note)
        QMessageBox.information(self, '已找到', f'文件当前位置:\n{found}')

    def _start_auto_recovery(self, reason='auto', force=False):
        """启动后扫一遍所有失踪的 tracked 附件，找回所有的。"""
        self._ensure_scan_state()
        if self._auto_recovery_worker and self._auto_recovery_worker.isRunning():
            return
        now = time.time()
        if not force and now - getattr(self, '_last_auto_recovery_start', 0.0) < AUTO_RECOVERY_COOLDOWN_SECONDS:
            return
        tag_to_name = {}
        tag_to_att = {}
        tag_to_tracking = {}
        tag_to_is_folder = {}
        tag_to_has_tag = {}
        drive_hints = []
        changed_without_worker = False
        for _note, att in self.storage.all_external_attachments():
            trk = att.get('tracking') or {}
            tag, has_real_tag = _attachment_recovery_key(att)
            if not tag:
                continue
            old_name = att.get('original_name', '')
            if self.storage.attachment_path_matches_tracking(att):
                if att.get('original_name', '') != old_name:
                    changed_without_worker = True
                if _clear_recovery_failure(att):
                    changed_without_worker = True
                continue
            original = Path(att.get('original_path', ''))
            if original.exists():
                continue
            if force and _clear_recovery_failure(att):
                changed_without_worker = True
            failed_at = float(att.get('recovery_failed_at') or 0.0)
            if not force and failed_at:
                # 连续失败按档位退避：永久丢失的附件（Shift+Del、所在盘拔掉）
                # 不该每 3 分钟唤醒一次全盘扫描。成功找回或手动“立即查找”
                # (force=True) 会清零计数。
                fail_count = int(att.get('recovery_failed_count') or 1)
                backoff = _auto_recovery_backoff_seconds(fail_count)
                if now - failed_at < backoff:
                    continue
            new_path, changed = self.storage.resolve_external_path(att, scan=False)
            if new_path and Path(new_path).exists():
                if self.storage.attachment_path_matches_tracking(att):
                    cleared = _clear_recovery_failure(att)
                    if changed or cleared:
                        changed_without_worker = True
                    continue
            tag_to_name[tag] = att.get('original_name', '')
            att_ids = tag_to_att.setdefault(tag, [])
            if att['id'] not in att_ids:
                att_ids.append(att['id'])
            tag_to_tracking[tag] = trk
            tag_to_is_folder[tag] = (att.get('type') == 'folder')
            tag_to_has_tag[tag] = has_real_tag
            hint = trk.get('drive_hint')
            if hint and hint not in drive_hints:
                drive_hints.append(hint)
        if changed_without_worker:
            try:
                self.storage.save()
            except Exception:
                pass
        if not tag_to_name:
            if changed_without_worker:
                self._refresh_external_attachment_views()
                if hasattr(self, '_tracked_watcher'):
                    self._setup_tracking_watchers()
            return

        self._last_auto_recovery_start = now
        worker = AutoRecoveryWorker(
            tag_to_name, tag_to_tracking=tag_to_tracking, drive_hints=drive_hints,
            scan_settings=self.storage.scan_settings, tag_to_is_folder=tag_to_is_folder,
            tag_to_has_tag=tag_to_has_tag,
            parent=self,
        )
        self._auto_recovery_total = len(tag_to_name)
        using_everything = bool(ftrack.everything_mode(self.storage.scan_settings.get('es_path'))) \
                           and self.storage.scan_settings.get('use_everything', True)

        def on_found(tag, path):
            self._on_auto_recovery_found(tag, path, tag_to_att)

        def on_progress(directory, dirs_scanned):
            remaining = self._auto_recovery_total - len(getattr(self, '_auto_recovered_tags', set()))
            if using_everything and dirs_scanned == 0:
                self.statusBar().showMessage(
                    tr('Everything 加速查找：{count} 个待找', count=remaining)
                )
            else:
                self.statusBar().showMessage(
                    tr('后台扫描中：剩 {remaining} 个 · 已扫 {dirs_scanned} 目录',
                       remaining=remaining, dirs_scanned=dirs_scanned)
                )

        def on_done(dirs_scanned):
            count = len(getattr(self, '_auto_recovered_tags', set()))
            recovered_tags = set(getattr(self, '_auto_recovered_tags', set()))
            self._auto_recovery_worker = None
            self._auto_recovered_tags = set()
            for tag, att_ids in tag_to_att.items():
                if tag in recovered_tags:
                    continue
                for att_id in att_ids:
                    note, att = self.storage.find_attachment(att_id)
                    if not att:
                        continue
                    # 只记录失败时间做冷却，不改 updated_at——
                    # 之前找回失败反而把便笺顶到列表最上面
                    att['recovery_failed_at'] = time.time()
                    att['recovery_failed_count'] = int(att.get('recovery_failed_count') or 0) + 1
            if tag_to_att:
                try:
                    self.storage.save()
                except Exception:
                    pass
            if count > 0:
                self.statusBar().showMessage(tr('已自动找回 {count} 个移动过的文件', count=count), 6000)
            else:
                self.statusBar().clearMessage()

        self._auto_recovered_tags = set()
        worker.found_one.connect(on_found)
        worker.progress.connect(on_progress)
        worker.finished_clean.connect(on_done)
        self._auto_recovery_worker = worker
        worker.start()
        mode = tr('Everything 加速') if using_everything else tr('全盘扫描')
        self.statusBar().showMessage(
            tr('{mode}：正在查找 {count} 个已移动的文件...',
               mode=mode, count=self._auto_recovery_total)
        )

    def _on_auto_recovery_found(self, tag, path, tag_to_att):
        att_ids = tag_to_att.get(tag) or []
        if isinstance(att_ids, str):
            att_ids = [att_ids]
        if not att_ids:
            return
        if not hasattr(self, '_auto_recovered_tags'):
            self._auto_recovered_tags = set()
        self._auto_recovered_tags.add(tag)
        refresh_current = False
        for att_id in att_ids:
            note, att = self.storage.find_attachment(att_id)
            if not att:
                continue
            self.storage.adopt_external_path(att, path)
            _clear_recovery_failure(att)
            if note and note.get('id') == self.current_note_id:
                refresh_current = True
        if refresh_current:
            self._refresh_external_attachment_views()
        # 无论是否正看着这条笔记，都把新位置的父目录挂上监听，
        # 下次它再被移走也能立即触发自动同步
        if hasattr(self, '_tracked_watcher'):
            self._setup_tracking_watchers()

    def _on_mode_changed(self, mode):
        if not self.current_note_id:
            return
        current = self.storage.get_note(self.current_note_id)
        if current and current.get('deleted'):
            return
        note = self.storage.update_note(self.current_note_id, mode=mode)
        if note:
            self._refresh_attachments_for(note)
            self.editor.update_time_label(note.get('updated_at', ''))
            self._populate_list()

    def _on_attachment_archive_toggled(self, attachment_id):
        note, att = self.storage.find_attachment(attachment_id)
        if not note or note.get('deleted'):
            return
        if not att or att.get('deleted'):
            return
        if self.workspace_mode == 'screenshot' and not is_image_attachment(att):
            archive_content = att.get('memo', '') or ''
            archive_category = att.get('archive_category') or att.get('category') or ''
            new_state = not bool(att.get('archived', False))
            if new_state:
                dlg = ArchivePhotoDialog(att, self.storage.path_for(att), self._attachment_archive_categories(), self)
                if dlg.exec() != QDialog.Accepted:
                    return
                archive_content = dlg.content()
                archive_category = dlg.category()
            updates = {
                'archived': new_state,
                'archived_at': datetime.now().isoformat() if new_state else '',
            }
            if new_state:
                updates.update(
                    archive_content=archive_content,
                    archive_category=archive_category,
                    category=archive_category,
                    memo=archive_content,
                )
            self.storage.update_attachment(note['id'], attachment_id, **updates)
            parent_id = self.storage.parent_attachment_id(attachment_id)
            self._refresh_screenshot_board(preferred_attachment_id=parent_id or self._current_screenshot_attachment_id())
            return
        new_state = not bool(att.get('archived', False))
        archive_content = att.get('memo', '') or ''
        archive_category = att.get('archive_category') or att.get('category') or ''
        if new_state:
            dlg = ArchivePhotoDialog(att, self.storage.path_for(att), self._attachment_archive_categories(), self)
            if dlg.exec() != QDialog.Accepted:
                return
            archive_content = dlg.content()
            archive_category = dlg.category()
        updates = {
            'archived': new_state,
            'archived_at': datetime.now().isoformat() if new_state else '',
        }
        if new_state:
            updates.update(
                archive_content=archive_content,
                archive_category=archive_category,
                category=archive_category,
                memo=archive_content,
            )
        self.storage.update_attachment(note['id'], attachment_id, **updates)
        if self.workspace_mode == 'screenshot':
            self._refresh_screenshot_board()
        else:
            refreshed = self.storage.get_note(note['id'])
            if refreshed:
                self._refresh_attachments_for(refreshed)
                self._populate_list()

    def _on_attachment_memo_changed(self, attachment_id, memo):
        note, att = self.storage.find_attachment(attachment_id)
        if note and note.get('deleted'):
            return
        if att and att.get('deleted'):
            return
        self.storage.update_screenshot(attachment_id, memo=memo)
        if self.workspace_mode == 'screenshot':
            self._refresh_screenshot_board()
        elif note and note.get('id') == self.current_note_id:
            refreshed = self.storage.get_note(note['id'])
            if refreshed:
                self._refresh_attachments_for(refreshed)
                self._populate_list()

    def _path_for_opening_attachment(self, att):
        if att.get('tracking'):
            path, changed = self.storage.resolve_external_path(att, scan=False)
            if path and Path(path).exists():
                if changed:
                    QTimer.singleShot(0, self._refresh_current_workspace)
                return Path(path)
            return None

        path = self.storage.path_for(att)
        if path.exists():
            return path
        return None

    def _open_image_viewer(self, attachment_id):
        self._open_attachment(attachment_id)

    def _open_attachment(self, attachment_id):
        note, att = self.storage.find_attachment(attachment_id)
        if att and not att.get('deleted') and not (note and note.get('deleted')):
            path = self._path_for_opening_attachment(att)
            if not path:
                if att.get('tracking'):
                    message = tr('该附件已被移动或删除，正在查找当前位置...')
                    self._start_targeted_scan(att)
                else:
                    message = tr('该附件已被移动或删除。')
                self.statusBar().showMessage(message, 5000)
                # 从时间线等模态窗口里双击时主窗口状态栏被挡住，看起来
                # 像“点了没反应”——直接在模态窗口上提示
                modal = QApplication.activeModalWidget()
                if modal is not None and modal is not self:
                    QMessageBox.information(modal, tr('附件不可用'), message)
                return
            if is_image_attachment(att):
                dlg = ImageViewerDialog(str(path), self)
                dlg.exec()
            else:
                if not open_local_path(path):
                    QMessageBox.warning(self, '打开失败', f'无法打开:\n{path}')
            return

    def _on_file_dropped(self, file_path):
        # 多文件拖入时每个文件发一次信号；攒一拍批量入库，
        # 之前是每个文件一次全量加密落盘 + 一次整板重建
        pending = getattr(self, '_pending_dropped_files', None)
        if pending is None:
            pending = []
            self._pending_dropped_files = pending
            QTimer.singleShot(0, self._flush_dropped_files)
        pending.append(str(file_path))

    def _flush_dropped_files(self):
        paths = getattr(self, '_pending_dropped_files', None) or []
        self._pending_dropped_files = None
        if not paths:
            return
        if self.workspace_mode != 'screenshot':
            with self.storage.batch():
                for p in paths:
                    self._add_attachment_to_current(p, copy=False)
            return
        parent = self._current_screenshot_attachment()
        if parent is not None:
            failed = 0
            with self.storage.batch():
                for p in paths:
                    if not self.storage.add_child_attachment(parent.get('id'), p, copy=False):
                        failed += 1
            self._refresh_screenshot_board(preferred_attachment_id=parent.get('id'))
            if failed:
                QMessageBox.warning(self, '添加失败', f'{failed} 个文件或文件夹无法添加。')
            else:
                self.statusBar().showMessage(tr('已添加到当前截图'), 3000)
            return
        last_id = None
        failed = 0
        non_image = 0
        with self.storage.batch():
            for p in paths:
                source = Path(p)
                if source.is_file() and source.suffix.lower() in IMAGE_EXTS:
                    att = self.storage.add_screenshot(p)
                    if att:
                        last_id = att.get('id')
                    else:
                        failed += 1
                else:
                    non_image += 1
        if last_id:
            self._refresh_screenshot_board(preferred_attachment_id=last_id)
        if failed:
            QMessageBox.warning(self, '添加失败', '只能添加图片截图。')
        if non_image:
            QMessageBox.information(self, '先选择截图', '请先选中一张截图，再给这张截图添加文件或文件夹。')

    def _on_attachment_bar_file_dropped(self, file_path):
        if self.workspace_mode == 'screenshot':
            self._add_child_attachment_to_current_screenshot(file_path)
            return
        self._add_attachment_to_current(file_path, copy=False)

    def _on_image_pasted(self, file_path):
        self._add_attachment_to_current(file_path, copy=True)

    def _add_screenshot_from_path(self, file_path, copy=False):
        # 截图板图片一律落为加密副本，copy 参数仅保留兼容旧调用
        attachment = self.storage.add_screenshot(file_path)
        if not attachment:
            QMessageBox.warning(self, '添加失败', '只能添加图片截图。')
            return None
        self._refresh_screenshot_board(preferred_attachment_id=attachment.get('id'))
        return attachment

    def _add_child_attachment_to_current_screenshot(self, file_path):
        if self.workspace_mode != 'screenshot':
            return self._add_attachment_to_current(file_path, copy=False)
        parent = self._current_screenshot_attachment()
        if not parent:
            QMessageBox.information(self, '先选择截图', '请先选中一张截图，再给这张截图添加文件或文件夹。')
            return None
        return self._add_child_attachment_to_screenshot(parent.get('id'), file_path)

    def _add_child_attachment_to_screenshot(self, screenshot_id, file_path):
        attachment = self.storage.add_child_attachment(screenshot_id, file_path, copy=False)
        if not attachment:
            QMessageBox.warning(self, '添加失败', '无法添加该文件或文件夹。')
            return None
        self._refresh_screenshot_board(preferred_attachment_id=screenshot_id)
        self.statusBar().showMessage(tr('已添加到当前截图'), 3000)
        return attachment

    def _choose_child_attachment_for_screenshot(self, screenshot_id):
        menu = QMenu(self)
        file_action = menu.addAction('选择文件...')
        folder_action = menu.addAction('选择文件夹...')
        action = menu.exec(QCursor.pos())
        if action == file_action:
            files, _ = QFileDialog.getOpenFileNames(self, '选择文件', '', '所有文件 (*.*)')
            for file_path in files:
                self._add_child_attachment_to_screenshot(screenshot_id, file_path)
        elif action == folder_action:
            folder = QFileDialog.getExistingDirectory(self, '选择文件夹', '')
            if folder:
                self._add_child_attachment_to_screenshot(screenshot_id, folder)

    def _add_attachment_to_current(self, file_path, copy=False):
        if self.workspace_mode != 'screenshot':
            if not self.current_note_id:
                return
            current = self.storage.get_note(self.current_note_id)
            if current and current.get('deleted'):
                return
            attachment = self.storage.add_attachment(self.current_note_id, file_path, copy=copy)
            if not attachment:
                QMessageBox.warning(self, '添加失败', '无法添加该附件。')
                return
            for note in self.storage.notes:
                if note['id'] == self.current_note_id:
                    self._refresh_attachments_for(note)
                    self.editor.update_time_label(note.get('updated_at', ''))
                    self._populate_list()
                    break
            return

        source = Path(file_path)
        if source.is_file() and source.suffix.lower() in IMAGE_EXTS:
            self._add_screenshot_from_path(file_path, copy=copy)
            return

        self._add_child_attachment_to_current_screenshot(file_path)

    def _add_file_to_current_screenshot(self):
        self._prepare_screenshot_workspace()
        parent = self._current_screenshot_attachment()
        if not parent:
            QMessageBox.information(self, '先选择截图', '请先选中一张截图，再给这张截图添加文件或文件夹。')
            return
        files, _ = QFileDialog.getOpenFileNames(self, '选择文件', '', '所有文件 (*.*)')
        for file_path in files:
            self._add_child_attachment_to_current_screenshot(file_path)

    def _add_folder_to_current_screenshot(self):
        self._prepare_screenshot_workspace()
        parent = self._current_screenshot_attachment()
        if not parent:
            QMessageBox.information(self, '先选择截图', '请先选中一张截图，再给这张截图添加文件或文件夹。')
            return
        folder = QFileDialog.getExistingDirectory(self, '选择文件夹', '')
        if folder:
            self._add_child_attachment_to_current_screenshot(folder)

    def _on_attachment_delete(self, attachment_id):
        if self.view_switch.current_view() == 'archived':
            self._delete_archived_attachment(attachment_id)
            return
        if self.workspace_mode == 'screenshot':
            preferred_id = self._current_screenshot_attachment_id()
            note, _att = self.storage.find_attachment(attachment_id)
            if note and not note.get('deleted'):
                self.storage.remove_attachment(note.get('id'), attachment_id)
                self._refresh_screenshot_board(preferred_attachment_id=preferred_id)
                self.statusBar().showMessage(tr('附件已移到最近删除'), 4000)
            return
        if self.workspace_mode != 'screenshot':
            if not self.current_note_id:
                return
            self.storage.remove_attachment(self.current_note_id, attachment_id)
            for note in self.storage.notes:
                if note['id'] == self.current_note_id:
                    self._refresh_attachments_for(note)
                    self._populate_list()
                    break
            self.statusBar().showMessage(tr('附件已移到最近删除'), 4000)
            return

    # ---- 全局拖拽 ----
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    self._on_file_dropped(url.toLocalFile())
            event.acceptProposedAction()

    # ---- 更多菜单 / 数据迁移 ----
    def _show_more_menu(self):
        menu = QMenu(self)

        timeline_action = menu.addAction('时间线 · 归档与完成')
        deleted_action = menu.addAction(tr('最近删除'))
        menu.addSeparator()

        capture_action = menu.addAction('框选截图')
        browse_screenshot_action = menu.addAction('选择截图图片...')
        add_file_to_screenshot_action = menu.addAction('给当前截图添加文件...')
        add_folder_to_screenshot_action = menu.addAction('给当前截图添加文件夹...')
        recover_action = menu.addAction('立即查找移动过的文件')
        menu.addSeparator()

        autostart_action = menu.addAction('开机启动')
        autostart_action.setCheckable(True)
        autostart_action.setChecked(is_autostart_enabled())
        autostart_action.setEnabled(autostart_supported())
        menu.addSeparator()

        account_action = menu.addAction('账户管理...')
        menu.addSeparator()

        scan_settings_action = menu.addAction('文件查找设置...')
        menu.addSeparator()

        open_custom_action = menu.addAction('外观与文字配置...')
        reload_custom_action = menu.addAction('重新加载外观与文字')
        shortcuts_action = menu.addAction('快捷键设置...')
        menu.addSeparator()

        export_action = menu.addAction('导出全部数据...')
        import_action = menu.addAction('从备份导入...')
        menu.addSeparator()
        open_dir_action = menu.addAction('打开数据文件夹')
        choose_dir_action = menu.addAction('选择数据文件夹...')

        pos = self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft())
        action = menu.exec(pos)

        if action == timeline_action:
            self._show_timeline()
        elif action == deleted_action:
            self._show_recently_deleted()
        elif action == capture_action:
            self._capture_screenshot_region()
        elif action == browse_screenshot_action:
            self._browse_screenshot()
        elif action == add_file_to_screenshot_action:
            self._add_file_to_current_screenshot()
        elif action == add_folder_to_screenshot_action:
            self._add_folder_to_current_screenshot()
        elif action == recover_action:
            self._manual_recover_now()
        elif action == autostart_action:
            self._toggle_autostart()
        elif action == account_action:
            self._show_account_settings()
        elif action == scan_settings_action:
            self._show_scan_settings()
        elif action == open_custom_action:
            self._show_customization_dialog()
        elif action == reload_custom_action:
            self._reload_customization()
        elif action == shortcuts_action:
            self._show_shortcuts_dialog()
        elif action == export_action:
            self._export_data()
        elif action == import_action:
            self._import_data()
        elif action == open_dir_action:
            self._open_data_folder()
        elif action == choose_dir_action:
            self._choose_data_folder()

    def _show_scan_settings(self):
        dlg = ScanSettingsDialog(self.storage, parent=self)
        dlg.exec()
        self._sync_everything_flag()

    def _sync_everything_flag(self):
        """把"启用 Everything 加速"的设置同步给 ftrack 总开关。
        之前只把 es_path 置 None，IPC 直连完全不受设置控制。"""
        try:
            enabled = bool((self.storage.scan_settings or {}).get('use_everything', True))
        except Exception:
            enabled = True
        ftrack.set_everything_enabled(enabled)

    def _show_account_settings(self):
        if not self.account_manager:
            return
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        previous_account_id = self.account.get('id')
        dlg = AccountSettingsDialog(
            self.account_manager,
            self.account,
            self.storage.crypter,
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        if not dlg.current_account or not dlg.current_crypter:
            return
        if dlg.current_account.get('id') != previous_account_id:
            self._switch_account(dlg.current_account, dlg.current_crypter)
            return
        self.account = dlg.current_account
        self.storage.crypter = dlg.current_crypter
        self.statusBar().showMessage('账户设置已更新', 3000)

    def _on_storage_save_failed(self, error):
        # 保存失败必须显式提醒——之前是静默 pass，用户以为已保存
        try:
            self.statusBar().showMessage(tr('保存失败：{error}', error=error), 8000)
        except Exception:
            pass
        now = time.monotonic()
        if now - getattr(self, '_last_save_warn', 0.0) > 60:
            self._last_save_warn = now
            QMessageBox.warning(
                self, tr('保存失败'),
                tr('数据写入磁盘失败：\n{error}\n\n'
                   '请检查磁盘空间或文件是否被占用。问题解决前请勿退出程序，'
                   '否则最近的修改会丢失。', error=error),
            )

    def _wire_storage(self, storage):
        storage.on_save_failed = self._on_storage_save_failed
        if storage.load_failed:
            QMessageBox.critical(
                self, tr('数据加载失败'),
                tr('数据文件无法解密或已损坏：\n{error}\n\n'
                   '已进入只读保护：本次会话的任何修改都不会写入磁盘，'
                   '以免覆盖仅存的原始数据。\n'
                   '原文件已留底为 data.corrupt-*.json，请先备份数据目录'
                   '或修复密钥文件后重启程序。', error=storage.load_error),
            )

    def _notify_legacy_archive(self):
        manager = self.account_manager
        archive = getattr(manager, 'last_legacy_archive', None) if manager else None
        if not archive:
            return
        manager.last_legacy_archive = None
        QMessageBox.information(
            self, tr('旧数据已迁移'),
            tr('检测到旧版数据并已导入当前账户。\n'
               '原始旧数据已归档到：\n{path}\n\n'
               '归档副本不受账户密码保护，确认数据完整后建议删除该目录。',
               path=str(archive)),
        )

    def _attach_storage(self, storage, account, *, flush_pending=True):
        """统一的存储切换路径（切换账户 / 切换数据目录共用）。

        之前两处各拷贝了一份近 30 行的清理+重置样板，且已出现"是否先
        保存挂起编辑"的行为分叉。
        """
        if flush_pending and self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        try:
            if getattr(self, '_tracked_watcher', None):
                paths = self._tracked_watcher.files() + self._tracked_watcher.directories()
                if paths:
                    self._tracked_watcher.removePaths(paths)
        except Exception:
            pass
        try:
            self.storage._cleanup_cache_dir()
        except Exception:
            pass

        self.account = account
        self.storage = storage
        self._wire_storage(storage)
        self.screenshot_board = self.storage.get_screenshot_board()
        self.current_note_id = self.screenshot_board['id'] if self.workspace_mode == 'screenshot' else None
        self.view_switch.set_view('active', emit=False)
        self.search_input.blockSignals(True)
        self.search_input.clear()
        self.search_input.blockSignals(False)
        self.editor.clear()
        self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
        self.attachment_bar.setVisible(False)
        self._refresh_editor_categories()
        self._refresh_current_workspace()
        self._setup_tracking_watchers()
        self._start_background_tagging()

    def _switch_account(self, account, crypter):
        if not self.account_manager:
            return
        try:
            storage = Storage(
                app_dir=self.account_manager.account_dir(account),
                crypter=crypter,
            )
        except SaltFileError as exc:
            QMessageBox.critical(self, tr('密钥文件异常'), str(exc))
            return
        self._attach_storage(storage, account)
        self.statusBar().showMessage(f'已进入 {account.get("name") or "我的账户"}', 3000)

    def _show_timeline(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        dlg = TimelineDialog(self.storage, self, workspace_mode=self.workspace_mode)
        dlg.state_changed.connect(self._refresh_after_timeline)
        dlg.note_requested.connect(self._open_note_from_timeline)
        dlg.exec()
        # 退出后刷新当前 note (可能有附件状态被改变)
        self._refresh_after_timeline()

    def _show_recently_deleted(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        dlg = RecentlyDeletedDialog(self.storage, self)
        dlg.state_changed.connect(self._refresh_after_deleted)
        dlg.exec()
        self._refresh_after_deleted()

    def _manual_recover_now(self):
        """用户主动触发的"立即查找"。统计失踪数量，提示是否启动扫描。"""
        missing = []
        cleared = False
        for _note, att in self.storage.all_external_attachments():
            recovery_key, _has_tag = _attachment_recovery_key(att)
            if not recovery_key:
                continue
            if self.storage.attachment_path_matches_tracking(att):
                if _clear_recovery_failure(att):
                    cleared = True
                continue
            p = Path(att.get('original_path', ''))
            if not p.exists():
                missing.append(att.get('original_name', '(未命名)'))
        if cleared:
            try:
                self.storage.save()
            except Exception:
                pass
        if not missing:
            QMessageBox.information(self, '一切正常', '所有跟踪的文件都在原位，无需查找。')
            return
        self._ensure_scan_state()
        if self._auto_recovery_worker is not None and self._auto_recovery_worker.isRunning():
            QMessageBox.information(
                self, '正在查找',
                f'后台扫描已在进行中（待找 {len(missing)} 个），请留意底部状态栏。')
            return
        preview = '\n'.join(missing[:8])
        more = f'\n... 共 {len(missing)} 个' if len(missing) > 8 else ''
        QMessageBox.information(
            self, '开始查找',
            f'有 {len(missing)} 个文件已被移动或暂时找不到，'
            f'正在后台扫描所有盘（含 U 盘 / 外接硬盘）寻找。\n\n{preview}{more}'
        )
        self._start_auto_recovery(reason='manual', force=True)

    def _refresh_after_deleted(self):
        if self.current_note_id and not self.storage.get_note(self.current_note_id):
            self.current_note_id = None
        if self.current_note_id:
            note = self.storage.get_note(self.current_note_id)
            if note and note.get('deleted'):
                self.current_note_id = None
                self.editor.clear()
                self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
                self.attachment_bar.setVisible(False)
        self._refresh_current_workspace()

    def _open_note_from_timeline(self, note_id):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        self.workspace_mode = 'text'
        self.workspace_switch.set_mode('text', emit=False)
        self._set_list_delegate('note')
        self._set_new_button_text()
        self.search_input.setPlaceholderText('搜索记录')
        self.view_switch.set_view('archived', emit=False)
        self._set_archive_filter_visible(True)
        if self.search_input.text():
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
        self._refresh_archive_category_filter()
        self._clear_archive_category_filter_text()

        self.current_note_id = None
        self._suppress_auto_select = True
        try:
            self._populate_list()
        finally:
            self._suppress_auto_select = False
        self.list_widget.clearSelection()
        if self._select_note_by_id(note_id):
            self._load_note_by_id(note_id)
        else:
            self._sync_empty_state()

    def _refresh_after_timeline(self):
        self._refresh_current_workspace()

    def _toggle_autostart(self):
        if not autostart_supported():
            QMessageBox.information(self, '不支持', '当前系统不支持此功能。')
            return
        target = not is_autostart_enabled()
        ok = set_autostart(target)
        if not ok:
            QMessageBox.warning(self, '设置失败', '修改开机启动设置时出错。')

    def _open_customization_folder(self):
        directory = ensure_custom_files()
        text_config_path()
        custom_qss_path()
        if not open_local_path(directory):
            QMessageBox.warning(self, '打开失败', f'文件夹不存在或无法打开:\n{directory}')

    def _show_customization_dialog(self):
        dlg = CustomizationDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._reload_customization(message='已保存外观与文字配置')

    def _reload_customization(self, message='已重新加载外观与文字配置'):
        reload_customization()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(customized_stylesheet(STYLE))
        apply_text_overrides()
        if getattr(self, 'tray_icon', None):
            self.tray_icon.setToolTip('FRESH')
        self._refresh_current_workspace()
        self.statusBar().showMessage(message, 3000)

    def _choose_backup_scope(self):
        dlg = QDialog(self)
        dlg.setObjectName('account_dialog')
        dlg.setWindowTitle('备份范围')
        dlg.setModal(True)
        dlg.setMinimumWidth(390)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(14)

        title = QLabel('备份范围')
        title.setObjectName('account_title_small')
        layout.addWidget(title)

        note = QLabel('文字记录始终备份。未勾选的引用仍保留原路径。')
        note.setObjectName('account_subtitle')
        note.setWordWrap(True)
        layout.addWidget(note)

        folder_check = QCheckBox('文件夹')
        file_check = QCheckBox('文件')
        image_check = QCheckBox('图片')
        for checkbox in (folder_check, file_check, image_check):
            checkbox.setObjectName('account_check')
            checkbox.setChecked(True)
            layout.addWidget(checkbox)

        row = QHBoxLayout()
        row.setSpacing(8)
        cancel_btn = QPushButton('取消')
        cancel_btn.setObjectName('account_secondary')
        cancel_btn.clicked.connect(dlg.reject)
        ok_btn = QPushButton('导出')
        ok_btn.setObjectName('account_primary')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(dlg.accept)
        row.addWidget(cancel_btn, 1)
        row.addWidget(ok_btn, 1)
        layout.addLayout(row)

        if dlg.exec() != QDialog.Accepted:
            return None

        include_folders = folder_check.isChecked()
        include_files = file_check.isChecked()
        include_images = image_check.isChecked()
        all_data = include_folders and include_files and include_images
        parts = []
        if include_folders:
            parts.append('文件夹')
        if include_files:
            parts.append('文件')
        if include_images:
            parts.append('图片')
        label = '全部数据' if all_data else ('文字 + ' + '、'.join(parts) if parts else '仅文字')
        scope_id = 'all_data' if all_data else 'text'
        if parts and not all_data:
            scope_id += '_' + '_'.join(
                part for part, enabled in (
                    ('folders', include_folders),
                    ('files', include_files),
                    ('images', include_images),
                )
                if enabled
            )
        return {
            'id': scope_id,
            'label': label,
            'include_folders': include_folders,
            'include_files': include_files,
            'include_images': include_images,
            'all_data': all_data,
            'account_folder': all_data,
        }

    def _choose_backup_passphrase(self):
        """选择备份口令。返回 None=取消；''=不设口令；其余为口令文本。

        不设口令的备份用"本机+账户"绑定的密钥加密，重装系统/换电脑后
        将永远无法解密——恰好在最需要备份的灾难场景下失效，所以默认
        引导用户设置口令。
        """
        dlg = QDialog(self)
        dlg.setObjectName('account_dialog')
        dlg.setWindowTitle(tr('备份口令'))
        dlg.setModal(True)
        dlg.setMinimumWidth(430)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(12)

        title = QLabel(tr('备份口令'))
        title.setObjectName('account_title_small')
        layout.addWidget(title)

        note = QLabel(tr(
            '设置口令后，备份可以在任何电脑上用口令恢复（推荐）。\n'
            '不设口令的备份只能在本机当前账户恢复，重装系统或换电脑后将无法解密。'
        ))
        note.setObjectName('account_subtitle')
        note.setWordWrap(True)
        layout.addWidget(note)

        pass1 = QLineEdit()
        pass1.setEchoMode(QLineEdit.Password)
        pass1.setPlaceholderText(tr('备份口令（至少 8 个字符）'))
        layout.addWidget(pass1)

        pass2 = QLineEdit()
        pass2.setEchoMode(QLineEdit.Password)
        pass2.setPlaceholderText(tr('再次输入口令'))
        layout.addWidget(pass2)

        skip_check = QCheckBox(tr('不设口令（仅本机当前账户可恢复）'))
        skip_check.setObjectName('account_check')
        layout.addWidget(skip_check)

        def _toggle(checked):
            pass1.setEnabled(not checked)
            pass2.setEnabled(not checked)
        skip_check.toggled.connect(_toggle)

        row = QHBoxLayout()
        row.setSpacing(8)
        cancel_btn = QPushButton(tr('取消'))
        cancel_btn.setObjectName('account_secondary')
        cancel_btn.clicked.connect(dlg.reject)
        ok_btn = QPushButton(tr('继续'))
        ok_btn.setObjectName('account_primary')
        ok_btn.setDefault(True)
        row.addWidget(cancel_btn, 1)
        row.addWidget(ok_btn, 1)
        layout.addLayout(row)

        def _confirm():
            if skip_check.isChecked():
                dlg.accept()
                return
            text = pass1.text()
            if len(text) < 8:
                QMessageBox.warning(dlg, tr('备份口令'), tr('口令至少需要 8 个字符。'))
                return
            if text != pass2.text():
                QMessageBox.warning(dlg, tr('备份口令'), tr('两次输入的口令不一致。'))
                return
            dlg.accept()
        ok_btn.clicked.connect(_confirm)

        if dlg.exec() != QDialog.Accepted:
            return None
        return '' if skip_check.isChecked() else pass1.text()

    def _write_backup_data(self, zf, scope, backup_crypter, kdf_info):
        notes_payload = json.dumps(self.storage.notes, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        zf.writestr('data.json', backup_crypter.encrypt_bytes(notes_payload))
        manifest = {
            'app': 'FRESH',
            'backup_format': 2,
            'created_at': datetime.now().isoformat(),
            'scope': scope.get('id'),
            'scope_label': scope.get('label'),
            'include_folders': bool(scope.get('include_folders')),
            'include_files': bool(scope.get('include_files')),
            'include_images': bool(scope.get('include_images')),
            'all_data': bool(scope.get('all_data')),
            'notes_encrypted': True,
            'references_preserved': True,
        }
        manifest.update(kdf_info or {})
        zf.writestr(
            'backup_manifest.json',
            json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'),
        )

    def _backup_stored_names(self, include_files=False, include_images=False):
        if include_files and include_images:
            return None
        names = set()
        for note in self.storage.notes:
            for att in iter_attachment_tree(note.get('attachments', []) or []):
                if att.get('type', 'file') != 'file':
                    continue
                stored_name = att.get('stored_name') or ''
                if not stored_name:
                    continue
                is_image = is_image_attachment(att) or Path(stored_name).suffix.lower() in IMAGE_EXTS
                if is_image and include_images:
                    names.add(stored_name)
                elif not is_image and include_files:
                    names.add(stored_name)
        return names

    def _write_backup_blob_dir(self, zf, source_dir, zip_prefix, stored_names=None,
                               backup_crypter=None, worker=None):
        """打包附件目录。返回 (成功数, 失败文件名列表)。

        失败必须让用户知道，否则用户会以为备份是完整的。"""
        source_dir = Path(source_dir)
        if not source_dir.exists():
            return 0, []
        backup_crypter = backup_crypter or self.storage.crypter
        account_crypter = self.storage.crypter
        count = 0
        failed = []
        allowed_names = set(stored_names) if stored_names is not None else None
        for f in source_dir.iterdir():
            if worker is not None:
                worker.check_cancelled()
            if not f.is_file() or f.name.startswith('.'):
                continue
            if allowed_names is not None and f.name not in allowed_names:
                continue
            try:
                blob = f.read_bytes()
                if backup_crypter is account_crypter:
                    if not account_crypter.is_encrypted(blob):
                        blob = account_crypter.encrypt_bytes(blob)
                else:
                    # 口令备份：先用账户密钥解出明文，再用备份口令密钥加密
                    plain = account_crypter.decrypt_bytes(blob) if account_crypter.is_encrypted(blob) else blob
                    blob = backup_crypter.encrypt_bytes(plain)
                zf.writestr(f'{zip_prefix}/{f.name}', blob)
                count += 1
            except WorkerCancelled:
                raise
            except Exception:
                failed.append(f.name)
                logger.exception('备份附件失败: %s', f)
        return count, failed

    def _safe_archive_name(self, name, fallback='未命名'):
        value = (name or fallback or '未命名').replace('\\', '/').strip('/')
        if not value:
            return fallback
        return value.split('/')[-1] or fallback

    def _write_external_references(self, zf, include_folders=False, include_files=False, include_images=False, worker=None):
        missing = []
        count = 0
        for note in self.storage.notes:
            for att in iter_attachment_tree(note.get('attachments', []) or []):
                if worker is not None:
                    worker.check_cancelled()
                att_type = att.get('type')
                if att_type == 'folder':
                    if not include_folders:
                        continue
                elif att_type == 'file_ref':
                    is_image = is_image_attachment(att)
                    if is_image and not include_images:
                        continue
                    if not is_image and not include_files:
                        continue
                else:
                    continue

                att_id = att.get('id') or uuid.uuid4().hex
                raw_path = att.get('original_path') or ''
                name = self._safe_archive_name(att.get('original_name'), Path(raw_path).name or att_id)
                if not raw_path:
                    missing.append(name)
                    continue

                src = Path(raw_path)
                try:
                    same_identity = self.storage.attachment_path_matches_tracking(att, save=False)
                except Exception:
                    same_identity = False

                if att_type == 'file_ref':
                    if src.exists() and src.is_file() and same_identity:
                        try:
                            zf.write(src, f'external/{att_id}/{name}')
                            count += 1
                        except Exception:
                            missing.append(name)
                    else:
                        missing.append(name)
                elif att_type == 'folder':
                    if src.exists() and src.is_dir() and same_identity:
                        wrote_any = False
                        try:
                            for f in src.rglob('*'):
                                if not f.is_file():
                                    continue
                                # 不要把内部的隐藏追踪标记导出去：它带着本机的 tracking_id，
                                # 导出/再导入会制造重复标记，干扰按标记的文件夹定位。
                                if f.name == ftrack.FOLDER_MARKER_NAME:
                                    continue
                                rel = f.relative_to(src).as_posix()
                                zf.write(f, f'external/{att_id}/{name}/{rel}')
                                count += 1
                                wrote_any = True
                            if not wrote_any:
                                zf.writestr(f'external/{att_id}/{name}/', '')
                                count += 1
                        except Exception:
                            missing.append(name + '/')
                    else:
                        missing.append(name + '/')
        return count, missing

    def _write_account_folder_snapshot(self, zf, destination_path):
        root = self.storage.app_dir.resolve()
        destination = Path(destination_path).resolve()
        count = 0
        if not root.exists():
            return count
        for path in root.rglob('*'):
            try:
                resolved = path.resolve()
                if resolved == destination:
                    continue
                rel = resolved.relative_to(root).as_posix()
                if path.is_file():
                    zf.write(path, f'account_folder/{rel}')
                    count += 1
                elif path.is_dir():
                    try:
                        if not any(path.iterdir()):
                            zf.writestr(f'account_folder/{rel}/', '')
                    except Exception:
                        pass
            except Exception:
                pass
        return count

    def _write_app_bundle(self, zf):
        app_dir = Path(__file__).resolve().parent
        count = 0
        for fname in (
            'main.py', 'accounts.py', 'crypter.py', 'storage.py', 'styles.py',
            'customization.py', 'ftrack.py', 'everything_ipc.py', 'shell_notify.py',
            'FRESH.spec', 'README.md', '启动.bat', '调试启动.bat'
        ):
            src = app_dir / fname
            if src.exists():
                zf.write(src, f'app/{fname}')
                count += 1
        exe_candidates = [
            app_dir / 'dist' / 'FRESH.exe',
            app_dir / 'FRESH.exe',
            app_dir / 'dist' / 'Memo.exe',
            app_dir / 'Memo.exe',
        ]
        for exe in exe_candidates:
            if exe.exists() and exe.is_file():
                zf.write(exe, 'app/FRESH.exe')
                count += 1
                break
        return count

    def _export_data(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()

        scope = self._choose_backup_scope()
        if not scope:
            return

        passphrase = self._choose_backup_passphrase()
        if passphrase is None:
            return

        default_name = f'fresh_backup_{scope["id"]}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        file_path, _ = QFileDialog.getSaveFileName(
            self, '导出备份', default_name, 'Zip 压缩包 (*.zip)'
        )
        if not file_path:
            return

        if passphrase:
            kdf_salt = os.urandom(32)
            backup_crypter = PasswordCrypter(passphrase, kdf_salt, PASSWORD_KDF_ITERATIONS)
            kdf_info = {
                'payload_encrypted': 'passphrase',
                'kdf': 'pbkdf2-sha256',
                'kdf_salt': base64.urlsafe_b64encode(kdf_salt).decode('ascii'),
                'kdf_iterations': PASSWORD_KDF_ITERATIONS,
            }
        else:
            backup_crypter = self.storage.crypter
            kdf_info = {'payload_encrypted': 'account'}

        include_files = bool(scope.get('include_files'))
        include_images = bool(scope.get('include_images'))
        include_folders = bool(scope.get('include_folders'))
        # 口令备份的目标是跨机可恢复，账户目录原样快照（机器绑定密文 + .fkey）
        # 对它没有意义，跳过
        snapshot_account_folder = bool(scope.get('account_folder')) and not passphrase

        def job(worker):
            out = {
                'missing': [], 'failed': [],
                'local_count': 0, 'trash_count': 0,
                'external_count': 0, 'account_folder_count': 0,
            }
            with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                worker.report(tr('正在打包文字数据...'))
                self._write_backup_data(zf, scope, backup_crypter, kdf_info)
                stored_names = self._backup_stored_names(
                    include_files=include_files,
                    include_images=include_images,
                )
                worker.report(tr('正在打包本地附件...'))
                out['local_count'], failed1 = self._write_backup_blob_dir(
                    zf, self.storage.attachments_dir, 'attachments', stored_names,
                    backup_crypter=backup_crypter, worker=worker,
                )
                out['trash_count'], failed2 = self._write_backup_blob_dir(
                    zf, self.storage.trash_dir, 'trash', stored_names,
                    backup_crypter=backup_crypter, worker=worker,
                )
                out['failed'] = failed1 + failed2
                worker.report(tr('正在打包外部引用...'))
                out['external_count'], out['missing'] = self._write_external_references(
                    zf,
                    include_folders=include_folders,
                    include_files=include_files,
                    include_images=include_images,
                    worker=worker,
                )
                if snapshot_account_folder:
                    worker.report(tr('正在打包账户文件夹快照...'))
                    out['account_folder_count'] = self._write_account_folder_snapshot(zf, file_path)
            return out

        worker = run_with_progress(self, tr('导出备份'), tr('正在导出备份...'), job)
        if worker.cancelled or worker.error:
            try:
                Path(file_path).unlink()
            except Exception:
                pass
            if worker.error:
                QMessageBox.critical(self, '导出失败', f'导出过程中出错:\n{worker.error}')
            else:
                self.statusBar().showMessage(tr('已取消导出'), 3000)
            return

        result = worker.result or {}
        missing = result.get('missing') or []
        failed = result.get('failed') or []
        included = ['加密文字数据']
        if result.get('local_count'):
            included.append(f"本地附件/截图 {result['local_count']} 个")
        if result.get('trash_count'):
            included.append(f"最近删除附件 {result['trash_count']} 个")
        if result.get('external_count'):
            included.append(f"引用文件/文件夹内容 {result['external_count']} 个")
        if result.get('account_folder_count'):
            included.append(f"账户完整文件夹快照 {result['account_folder_count']} 个文件")

        msg = f'{scope["label"]}已导出到:\n{file_path}\n\n包含: ' + ' · '.join(included)
        if passphrase:
            msg += '\n\n该备份已用口令加密，可在任何电脑恢复，请妥善保管口令。'
        else:
            msg += '\n\n该备份只能在本机当前账户恢复；如需跨电脑恢复，请重新导出并设置备份口令。'
        msg += '\n未打包的外部引用仍保留原路径和追踪记录。'
        if failed:
            preview = '\n'.join(failed[:5])
            more = f'\n... 共 {len(failed)} 个' if len(failed) > 5 else ''
            msg += f'\n\n警告：以下 {len(failed)} 个本地附件读取失败，未包含在备份中:\n{preview}{more}'
        if missing:
            preview = '\n'.join(missing[:5])
            more = f'\n... 共 {len(missing)} 个' if len(missing) > 5 else ''
            msg += f'\n\n以下 {len(missing)} 个引用源已不存在,未打包:\n{preview}{more}'
        if failed:
            QMessageBox.warning(self, '导出完成（有警告）', msg)
        else:
            QMessageBox.information(self, '导出成功', msg)

    def _ask_backup_passphrase_crypter(self, manifest, raw_probe):
        """口令备份：向用户索要口令并验证，返回解密器或 None。"""
        try:
            salt = base64.urlsafe_b64decode((manifest.get('kdf_salt') or '').encode('ascii'))
            iterations = int(manifest.get('kdf_iterations') or PASSWORD_KDF_ITERATIONS)
            if not salt:
                raise ValueError('empty salt')
        except Exception:
            QMessageBox.critical(self, '导入失败', tr('备份的口令参数缺失或损坏，无法解密。'))
            return None
        for _ in range(3):
            text, ok = QInputDialog.getText(
                self, tr('备份口令'),
                tr('这个备份使用口令加密，请输入备份口令：'),
                QLineEdit.Password,
            )
            if not ok:
                return None
            crypter = PasswordCrypter(text, salt, iterations)
            try:
                crypter.decrypt_bytes(raw_probe)
                return crypter
            except Exception:
                QMessageBox.warning(self, tr('备份口令'), tr('口令不正确，请重试。'))
        return None

    def _import_data(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, '导入备份', '', 'Zip 压缩包 (*.zip);;所有文件 (*.*)'
        )
        if not file_path:
            return

        # 先读 manifest 与 data.json，确定解密方式并提前验证密钥
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                if 'data.json' not in names:
                    raise ValueError('备份文件中缺少 data.json')
                manifest = {}
                if 'backup_manifest.json' in names:
                    try:
                        manifest = json.loads(zf.read('backup_manifest.json').decode('utf-8'))
                    except Exception:
                        manifest = {}
                raw_probe = zf.read('data.json')
        except Exception as e:
            QMessageBox.critical(self, '导入失败', f'无法读取备份文件:\n{e}')
            return

        if (manifest or {}).get('payload_encrypted') == 'passphrase':
            backup_crypter = self._ask_backup_passphrase_crypter(manifest, raw_probe)
            if backup_crypter is None:
                return
        else:
            backup_crypter = self.storage.crypter
            if self.storage.crypter.is_encrypted(raw_probe):
                try:
                    self.storage.crypter.decrypt_bytes(raw_probe)
                except Exception:
                    QMessageBox.critical(
                        self, '导入失败',
                        tr('这个备份是用其他账户或其他电脑的密钥加密的，当前账户无法解密。\n'
                           '如果导出时设置过备份口令，请使用带口令的备份文件。'))
                    return

        msg = QMessageBox(self)
        msg.setWindowTitle('选择导入方式')
        msg.setText('请选择导入方式')
        msg.setInformativeText(
            '合并 — 将备份中的备忘录追加到现有数据中\n'
            '替换 — 清除当前所有数据,完全用备份替换'
        )
        merge_btn = msg.addButton('合并', QMessageBox.AcceptRole)
        replace_btn = msg.addButton('替换', QMessageBox.DestructiveRole)
        cancel_btn = msg.addButton('取消', QMessageBox.RejectRole)
        msg.setDefaultButton(merge_btn)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked is None or clicked == cancel_btn:
            return
        mode = 'replace' if clicked == replace_btn else 'merge'
        if mode == 'replace':
            confirm = QMessageBox.warning(
                self, '确认替换',
                tr('替换将清除当前账户的全部备忘录和附件，并用备份内容代替。\n此操作无法撤销，确定继续吗？'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()

        stamp = datetime.now().strftime('%Y%m%d%H%M%S')
        staging = self.storage.app_dir / f'import_tmp_{stamp}'
        imported_dir = self.storage.app_dir / 'imported'
        account_crypter = self.storage.crypter

        def job(worker):
            """阶段 A（后台线程）：把备份完整解压、校验、按账户密钥重新加密到
            临时目录。这一阶段不碰任何现有数据，失败/取消可整体丢弃。"""
            out = {}
            staging_att = staging / 'attachments'
            staging_ext = staging / 'imported'
            staging_att.mkdir(parents=True, exist_ok=True)
            staging_ext.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(file_path, 'r') as zf:
                zip_names = zf.namelist()
                raw = zf.read('data.json')
                if backup_crypter.is_encrypted(raw):
                    raw = backup_crypter.decrypt_bytes(raw)
                imported_notes = json.loads(raw.decode('utf-8'))
                if not isinstance(imported_notes, list):
                    raise ValueError('备份文件格式错误')

                worker.report(tr('正在解包附件...'))
                for name in zip_names:
                    worker.check_cancelled()
                    if name.startswith('attachments/') and not name.endswith('/'):
                        rel = name[len('attachments/'):]
                        if not rel or '..' in rel.replace('\\', '/').split('/'):
                            continue
                        target = staging_att / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as src:
                            raw_blob = src.read()
                        if backup_crypter.is_encrypted(raw_blob):
                            payload = account_crypter.encrypt_bytes(backup_crypter.decrypt_bytes(raw_blob))
                        else:
                            payload = account_crypter.encrypt_bytes(raw_blob)
                        target.write_bytes(payload)

                worker.report(tr('正在解包外部引用...'))
                external_present = set()
                for name in zip_names:
                    worker.check_cancelled()
                    if not name.startswith('external/'):
                        continue
                    parts = name.split('/', 2)
                    if len(parts) < 3 or not parts[1]:
                        continue
                    att_id, rest = parts[1], parts[2]
                    if '..' in rest.replace('\\', '/').split('/'):
                        continue
                    external_present.add(att_id)
                    if name.endswith('/'):
                        (staging_ext / att_id / rest).mkdir(parents=True, exist_ok=True)
                        continue
                    target = staging_ext / att_id / rest
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(target, 'wb') as dst:
                        shutil.copyfileobj(src, dst)

                # 引用类型附件重定向到最终的 imported/ 目录
                redirected = 0
                for note in imported_notes:
                    for att in iter_attachment_tree(note.get('attachments', []) or []):
                        t = att.get('type')
                        if t in ('file_ref', 'folder') and att.get('id') in external_present:
                            new_path = imported_dir / att['id'] / att.get('original_name', '')
                            att['original_path'] = str(new_path)
                            redirected += 1

                out['notes'] = imported_notes
                out['redirected'] = redirected
                out['has_app'] = any(n.startswith('app/') for n in zip_names)
            return out

        worker = run_with_progress(self, tr('导入备份'), tr('正在校验并解包备份...'), job)
        if worker.cancelled or worker.error:
            shutil.rmtree(staging, ignore_errors=True)
            if worker.error:
                QMessageBox.critical(self, '导入失败', f'导入过程中出错:\n{worker.error}\n\n现有数据未受影响。')
            else:
                self.statusBar().showMessage(tr('已取消导入'), 3000)
            return

        result = worker.result or {}
        imported_notes = result.get('notes') or []

        # 阶段 B（主线程）：提交。只剩同卷移动和内存操作，速度快、可回滚。
        old_notes = self.storage.notes
        replaced_dir = None
        try:
            if mode == 'replace':
                replaced_dir = self.storage.app_dir / f'replaced_{stamp}'
                replaced_dir.mkdir(parents=True, exist_ok=True)
                if self.storage.attachments_dir.exists():
                    shutil.move(str(self.storage.attachments_dir), str(replaced_dir / 'attachments'))
                self.storage.attachments_dir.mkdir(parents=True, exist_ok=True)
                if imported_dir.exists():
                    shutil.move(str(imported_dir), str(replaced_dir / 'imported'))
                self.storage.notes = []

            staging_att = staging / 'attachments'
            if staging_att.exists():
                for f in staging_att.iterdir():
                    target = self.storage.attachments_dir / f.name
                    if not target.exists():
                        shutil.move(str(f), str(target))
            staging_ext = staging / 'imported'
            if staging_ext.exists():
                imported_dir.mkdir(parents=True, exist_ok=True)
                for child in staging_ext.iterdir():
                    dest = imported_dir / child.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest, ignore_errors=True)
                        else:
                            dest.unlink()
                    shutil.move(str(child), str(dest))

            # batch()：抑制 get_screenshot_board() 等中间步骤的落盘，
            # 整个提交只在最后写一次
            with self.storage.batch():
                screenshot_board = self.storage.get_screenshot_board()
                existing_ids = {n['id'] for n in self.storage.notes}
                existing_att_ids = {
                    att.get('id') for _n, att, _p, _c in self.storage.iter_attachments()
                }
                for note in imported_notes:
                    if note.get('id') == SCREENSHOT_BOARD_ID:
                        for att in note.get('attachments', []) or []:
                            self._dedupe_attachment_tree_ids(att, existing_att_ids)
                            screenshot_board.setdefault('attachments', []).append(att)
                        screenshot_board['updated_at'] = datetime.now().isoformat()
                        continue
                    if mode == 'merge' and note.get('id') in existing_ids:
                        note['id'] = uuid.uuid4().hex
                    # 普通便笺的附件 id 也要去重，否则重复导入会产生重复 id
                    for att in note.get('attachments', []) or []:
                        self._dedupe_attachment_tree_ids(att, existing_att_ids)
                    self.storage.notes.append(note)
                self.storage.sort_notes()
            if not self.storage.save():
                raise OSError(self.storage.save_error or '数据写盘失败')
        except Exception as e:
            logger.exception('导入提交阶段失败，正在回滚')
            self.storage.notes = old_notes
            self.storage.save()  # 立即把旧数据重新持久化，防止中间态留在磁盘上
            if replaced_dir is not None:
                try:
                    if (replaced_dir / 'attachments').exists():
                        shutil.rmtree(self.storage.attachments_dir, ignore_errors=True)
                        shutil.move(str(replaced_dir / 'attachments'), str(self.storage.attachments_dir))
                    if (replaced_dir / 'imported').exists():
                        shutil.rmtree(imported_dir, ignore_errors=True)
                        shutil.move(str(replaced_dir / 'imported'), str(imported_dir))
                    replaced_dir.rmdir()
                except Exception:
                    logger.exception('回滚旧附件目录失败: %s', replaced_dir)
            shutil.rmtree(staging, ignore_errors=True)
            QMessageBox.critical(self, '导入失败', f'导入过程中出错:\n{e}\n\n已恢复原有数据。')
            return

        shutil.rmtree(staging, ignore_errors=True)
        if replaced_dir is not None:
            shutil.rmtree(replaced_dir, ignore_errors=True)
            logger.info('替换导入完成，旧附件已清理')

        # 刷新 UI：尊重当前工作区，不再强切到截图板
        self.current_note_id = None
        self.editor.clear()
        self.screenshot_board = self.storage.get_screenshot_board()
        if self.workspace_mode == 'screenshot':
            self.current_note_id = self.screenshot_board['id']
        self._refresh_current_workspace()

        extra = ''
        if result.get('redirected'):
            extra += f"\n· {result['redirected']} 个引用文件/文件夹已还原到本地"
        if result.get('has_app'):
            extra += '\n· 备份中包含软件源码 (位于 zip 内 app/ 目录,需手动解压使用)'
        QMessageBox.information(
            self, '导入成功',
            f'已导入 {len(imported_notes)} 条备忘录。{extra}'
        )

    def _dedupe_attachment_tree_ids(self, attachment, existing_ids):
        if not attachment:
            return
        if attachment.get('id') in existing_ids:
            attachment['id'] = uuid.uuid4().hex
        existing_ids.add(attachment.get('id'))
        for child in attachment.get('attachments', []) or []:
            self._dedupe_attachment_tree_ids(child, existing_ids)

    def _open_data_folder(self):
        path = self.account_manager.app_root if self.account_manager else self.storage.app_dir
        if not open_local_path(path):
            QMessageBox.warning(self, '打开失败', f'文件夹不存在或无法打开:\n{path}')

    def _choose_data_folder(self):
        if not self.account_manager:
            return
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()

        current_root = self.account_manager.app_root
        folder = QFileDialog.getExistingDirectory(self, '选择数据文件夹', str(current_root))
        if not folder:
            return
        new_root = Path(folder)
        if new_root.resolve() == current_root.resolve():
            self.statusBar().showMessage(tr('数据文件夹未改变'), 3000)
            return
        if is_path_inside(new_root, current_root):
            QMessageBox.warning(self, '选择数据文件夹', tr('新的数据文件夹不能放在当前数据文件夹里面。'))
            return

        reply = QMessageBox.question(
            self,
            '选择数据文件夹',
            tr('是否把当前数据复制到新的数据文件夹？\n\n当前：{current}\n新的：{new}',
               current=current_root, new=new_root),
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if reply == QMessageBox.Cancel:
            return

        try:
            if reply == QMessageBox.Yes:
                failures = copy_data_root(current_root, new_root)
                if failures:
                    preview = '\n'.join(f'{p}: {err}' for p, err in failures[:8])
                    more = f'\n... 共 {len(failures)} 项失败' if len(failures) > 8 else ''
                    QMessageBox.critical(
                        self, '复制失败',
                        tr('部分数据未能复制到新文件夹，已取消切换，当前数据保持不变：\n\n')
                        + preview + more,
                    )
                    return
            if not self._reload_data_root(new_root):
                QMessageBox.information(self, '选择数据文件夹', tr('没有进入新数据文件夹，已保留当前数据文件夹。'))
                return
            self._settings.setValue(DATA_ROOT_SETTINGS, str(new_root))
            refresh_autostart_if_needed()
            self.statusBar().showMessage(tr('数据文件夹已切换到 {path}', path=new_root), 5000)
        except Exception as exc:
            QMessageBox.critical(self, '切换失败', tr('切换数据文件夹时出错:\n{error}', error=exc))

    def _reload_data_root(self, app_root):
        app_root = Path(app_root)

        try:
            new_manager = AccountManager(app_root=app_root)
            account, crypter = new_manager.ensure_default_account()
            if not crypter:
                selected, selected_crypter = select_start_account(new_manager)
                if not selected or not selected_crypter:
                    return False
                account, crypter = selected, selected_crypter
        except SaltFileError as exc:
            QMessageBox.critical(self, tr('密钥文件异常'), str(exc))
            return False

        set_data_root(app_root)
        ensure_custom_files()
        reload_customization()
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(customized_stylesheet(STYLE))
        apply_text_overrides()
        self.account_manager = new_manager
        try:
            storage = Storage(
                app_dir=new_manager.account_dir(account),
                crypter=crypter,
            )
        except SaltFileError as exc:
            QMessageBox.critical(self, tr('密钥文件异常'), str(exc))
            return False
        self._attach_storage(storage, account)
        return True

    def closeEvent(self, event):
        self._flush_pending_editor()
        self._save_window_state()
        # 关闭按钮 → 隐藏到托盘（除非用户主动选了退出）
        if (
            not getattr(self, '_real_quit', False)
            and not getattr(self, '_session_ending', False)
            and getattr(self, 'tray_icon', None)
            and self.tray_icon.isVisible()
        ):
            event.ignore()
            self.hide()
            if not getattr(self, '_hide_notified', False):
                self._hide_notified = True
                try:
                    self.tray_icon.showMessage(
                        'FRESH 已最小化到系统托盘',
                        '点击托盘图标可重新打开。右键图标可退出。',
                        QSystemTrayIcon.Information, 3500,
                    )
                except Exception:
                    pass
            return
        try:
            self.storage.save()
        except Exception:
            logger.exception('退出前保存数据失败')
        # 真正退出：清理后台扫描线程
        for s in getattr(self, '_targeted_scans', []):
            try:
                s['worker'].cancel()
            except Exception:
                pass
        for s in getattr(self, '_targeted_scans', []):
            try:
                s['worker'].wait(2000)
            except Exception:
                pass
        auto = getattr(self, '_auto_recovery_worker', None)
        if auto is not None:
            try:
                auto.cancel()
                auto.wait(2000)
            except Exception:
                pass
        tagw = getattr(self, '_tagging_worker', None)
        if tagw is not None:
            try:
                tagw.cancel()
                tagw.wait(2000)
            except Exception:
                pass
        for worker in list(getattr(self, '_tracking_rebuild_workers', set())):
            try:
                worker.cancel()
                worker.wait(2000)
            except Exception:
                pass
        # Shell 通知只在托盘退出路径注销过；系统会话结束等其他退出路径
        # 也要注销，避免留下悬空的通知注册
        if getattr(self, '_shell_filter', None) is not None:
            try:
                self._shell_filter.uninstall()
                QApplication.instance().removeNativeEventFilter(self._shell_filter)
            except Exception:
                pass
            self._shell_filter = None
        if getattr(self, 'tray_icon', None):
            self.tray_icon.hide()
        super().closeEvent(event)

    # ============ 系统托盘 ============

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        icon = self._make_app_icon()
        self.setWindowIcon(icon)

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip('FRESH')

        menu = QMenu()
        show_action = menu.addAction(tr('显示 FRESH'))
        # 用户主动点菜单必须立即生效，不能吃 8 秒激活冷却
        show_action.triggered.connect(lambda: self._show_window_from_tray(force=True))
        lock_action = menu.addAction(tr('锁定'))
        lock_action.triggered.connect(self._lock_now)
        menu.addSeparator()
        quick_note_action = menu.addAction(tr('快速新建文字'))
        quick_note_action.triggered.connect(self._quick_new_text_note)
        quick_capture_action = menu.addAction(tr('快速框选截图'))
        quick_capture_action.triggered.connect(self._quick_capture_region)
        clipboard_image_action = menu.addAction(tr('保存剪贴板图片'))
        clipboard_image_action.triggered.connect(self._quick_capture_clipboard_image)
        menu.addSeparator()
        quit_action = menu.addAction(tr('退出 FRESH'))
        quit_action.triggered.connect(self._quit_from_tray)
        self.tray_icon.setContextMenu(menu)

        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _make_app_icon(self):
        # 纯路径“便笺 + 勾”标志，不依赖字体，确保托盘、标题栏和 EXE
        # 在不同 DPI/字体环境中保持一致。
        size = 256
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        bg = QLinearGradient(0, 0, size, size)
        bg.setColorAt(0.0, QColor('#5AC8FA'))
        bg.setColorAt(1.0, QColor('#007AFF'))
        painter.setBrush(bg)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(8, 8, size - 16, size - 16, 48, 48)
        painter.setBrush(QColor('#FFFFFF'))
        painter.drawRoundedRect(QRectF(55, 42, 146, 172), 24, 24)
        ink = QPen(QColor('#007AFF'), 13)
        ink.setCapStyle(Qt.RoundCap)
        ink.setJoinStyle(Qt.RoundJoin)
        painter.setPen(ink)
        painter.drawLine(QPointF(82, 86), QPointF(174, 86))
        painter.drawLine(QPointF(82, 119), QPointF(151, 119))
        painter.drawLine(QPointF(83, 163), QPointF(109, 187))
        painter.drawLine(QPointF(109, 187), QPointF(174, 145))
        painter.end()
        return QIcon(pix)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_window_from_tray(force=True)

    def _show_window_from_tray(self, force=False):
        now = time.time()
        if not force and now - getattr(self, '_last_window_activation', 0.0) < WINDOW_ACTIVATE_COOLDOWN_SECONDS:
            return
        self._last_window_activation = now
        if self.isMinimized():
            # 最大化状态下最小化/进托盘后，showNormal 会把最大化也丢掉；
            # 只清掉 Minimized 位才能还原到之前的状态
            self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
            self.show()
        else:
            self.show()
        self.raise_()
        self.activateWindow()

    def _lock_now(self):
        """手动锁定：丢弃当前存储与解密缓存，重新走登录验证。

        之前解锁后没有任何再锁定路径——关窗只是进托盘，离开电脑的
        任何人点托盘图标就能看到全部内容。
        """
        if not self.account_manager:
            return
        has_password_account = any(
            self.account_manager.account_has_password(acc)
            for acc in self.account_manager.accounts()
        )
        if not has_password_account:
            QMessageBox.information(
                self, tr('锁定'),
                tr('当前没有设置密码的账户，锁定不起作用。\n请先在「账户设置」里为账户设置密码。'))
            return
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        self.hide()
        while True:
            account, crypter = select_start_account(self.account_manager)
            if account and crypter:
                break
            reply = QMessageBox.question(
                None, tr('已锁定'),
                tr('未解锁任何账户。要退出 FRESH 吗？'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._quit_from_tray()
                return
        try:
            storage = Storage(
                app_dir=self.account_manager.account_dir(account),
                crypter=crypter,
            )
        except SaltFileError as exc:
            QMessageBox.critical(None, tr('密钥文件异常'), str(exc))
            self._quit_from_tray()
            return
        self._attach_storage(storage, account)
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self):
        self._real_quit = True
        if getattr(self, '_shell_filter', None) is not None:
            try:
                self._shell_filter.uninstall()
                QApplication.instance().removeNativeEventFilter(self._shell_filter)
            except Exception:
                pass
            self._shell_filter = None
        self.close()
        QApplication.quit()


SINGLE_INSTANCE_KEY = 'FRESH-SingleInstance-v1'


def _activate_running_instance():
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if sock.waitForConnected(500):
        sock.write(b'already-running')
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True
    return False


class LoginDialog(QDialog):
    def __init__(self, manager, parent=None, exclude_account_id=''):
        super().__init__(parent)
        self.manager = manager
        self.exclude_account_id = exclude_account_id or ''
        self.account = None
        self.crypter = None
        self.setObjectName('account_dialog')
        self.setWindowTitle('FRESH')
        self.setModal(True)
        self.setMinimumWidth(390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(14)

        title = QLabel('FRESH')
        title.setObjectName('account_title')
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        password_accounts = [
            a for a in self.manager.accounts()
            if a.get('id') != self.exclude_account_id and self.manager.account_has_password(a)
        ]
        passwordless = [
            a for a in self.manager.passwordless_accounts()
            if a.get('id') != self.exclude_account_id
        ]

        if password_accounts:
            self.password_edit = QLineEdit()
            self.password_edit.setObjectName('account_field')
            self.password_edit.setEchoMode(QLineEdit.Password)
            self.password_edit.setPlaceholderText('密码')
            self.password_edit.returnPressed.connect(self._unlock)
            layout.addWidget(self.password_edit)

            self.error_label = QLabel('')
            self.error_label.setObjectName('account_error')
            self.error_label.setAlignment(Qt.AlignCenter)
            self.error_label.setWordWrap(True)
            layout.addWidget(self.error_label)

            enter_btn = QPushButton('进入')
            enter_btn.setObjectName('account_primary')
            enter_btn.setDefault(True)
            enter_btn.setCursor(Qt.PointingHandCursor)
            enter_btn.clicked.connect(self._unlock)
            layout.addWidget(enter_btn)
        else:
            self.password_edit = None
            self.error_label = QLabel('')
            self.error_label.hide()

        if passwordless:
            if password_accounts:
                line = QFrame()
                line.setObjectName('account_line')
                line.setFrameShape(QFrame.HLine)
                layout.addWidget(line)

            for account in passwordless:
                btn = QPushButton(account.get('name') or '我的账户')
                btn.setObjectName('account_choice')
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _checked=False, account_id=account.get('id'): self._unlock_passwordless(account_id))
                layout.addWidget(btn)

        cancel_btn = QPushButton('取消')
        cancel_btn.setObjectName('account_flat')
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        if self.password_edit:
            QTimer.singleShot(0, self.password_edit.setFocus)

    def _unlock(self):
        if not self.password_edit:
            return
        account, crypter = self.manager.unlock(self.password_edit.text())
        if not account or account.get('id') == self.exclude_account_id:
            self.error_label.setText('密码不正确')
            self.error_label.show()
            self.password_edit.selectAll()
            self.password_edit.setFocus()
            return
        self.account = account
        self.crypter = crypter
        self.accept()

    def _unlock_passwordless(self, account_id):
        account, crypter = self.manager.unlock_passwordless(account_id)
        if not account:
            return
        self.account = account
        self.crypter = crypter
        self.accept()


class PasswordSetupDialog(QDialog):
    def __init__(self, title='设置密码', parent=None):
        super().__init__(parent)
        self.password = ''
        self.setObjectName('account_dialog')
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(14)

        label = QLabel(title)
        label.setObjectName('account_title_small')
        layout.addWidget(label)

        self.password_edit = QLineEdit()
        self.password_edit.setObjectName('account_field')
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText(f'新密码（至少 {MIN_PASSWORD_LENGTH} 位，建议混合字母数字）')
        layout.addWidget(self.password_edit)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setObjectName('account_field')
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        self.confirm_edit.setPlaceholderText('再次输入')
        self.confirm_edit.returnPressed.connect(self._accept)
        layout.addWidget(self.confirm_edit)

        self.error_label = QLabel('')
        self.error_label.setObjectName('account_error')
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        cancel_btn = QPushButton('取消')
        cancel_btn.setObjectName('account_secondary')
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton('完成')
        ok_btn.setObjectName('account_primary')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept)
        row.addWidget(cancel_btn, 1)
        row.addWidget(ok_btn, 1)
        layout.addLayout(row)

    def _accept(self):
        password = self.password_edit.text()
        confirm = self.confirm_edit.text()
        if password != confirm:
            self.error_label.setText('两次输入不一致')
            self.confirm_edit.selectAll()
            self.confirm_edit.setFocus()
            return
        if len(password) < MIN_PASSWORD_LENGTH:
            # 账户密码是离线暴力破解的唯一防线，6 位口令几小时就能被穷举
            self.error_label.setText(f'密码至少 {MIN_PASSWORD_LENGTH} 位')
            self.password_edit.setFocus()
            return
        self.password = password
        self.accept()


class NewAccountDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.name = ''
        self.password = ''
        self.setObjectName('account_dialog')
        self.setWindowTitle('新建账户')
        self.setModal(True)
        self.setMinimumWidth(390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(14)

        label = QLabel('新建账户')
        label.setObjectName('account_title_small')
        layout.addWidget(label)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName('account_field')
        self.name_edit.setPlaceholderText('账户名')
        layout.addWidget(self.name_edit)

        self.password_check = QCheckBox('设置密码')
        self.password_check.setObjectName('account_check')
        self.password_check.toggled.connect(self._sync_password_fields)
        layout.addWidget(self.password_check)

        self.password_edit = QLineEdit()
        self.password_edit.setObjectName('account_field')
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText('密码')
        layout.addWidget(self.password_edit)

        self.confirm_edit = QLineEdit()
        self.confirm_edit.setObjectName('account_field')
        self.confirm_edit.setEchoMode(QLineEdit.Password)
        self.confirm_edit.setPlaceholderText('再次输入')
        self.confirm_edit.returnPressed.connect(self._accept)
        layout.addWidget(self.confirm_edit)

        self.error_label = QLabel('')
        self.error_label.setObjectName('account_error')
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        cancel_btn = QPushButton('取消')
        cancel_btn.setObjectName('account_secondary')
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton('创建并进入')
        ok_btn.setObjectName('account_primary')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept)
        row.addWidget(cancel_btn, 1)
        row.addWidget(ok_btn, 1)
        layout.addLayout(row)
        self._sync_password_fields(False)

    def _sync_password_fields(self, checked):
        self.password_edit.setVisible(checked)
        self.confirm_edit.setVisible(checked)
        if checked:
            self.password_edit.setFocus()

    def _accept(self):
        self.name = self.name_edit.text().strip() or '我的账户'
        self.password = ''
        if self.password_check.isChecked():
            password = self.password_edit.text()
            confirm = self.confirm_edit.text()
            if password != confirm:
                self.error_label.setText('两次输入不一致')
                self.confirm_edit.selectAll()
                self.confirm_edit.setFocus()
                return
            if len(password) < MIN_PASSWORD_LENGTH:
                self.error_label.setText(f'密码至少 {MIN_PASSWORD_LENGTH} 位')
                self.password_edit.setFocus()
                return
            self.password = password
        self.accept()


class AccountSettingsDialog(QDialog):
    def __init__(self, manager, current_account, current_crypter, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.current_account = dict(current_account or {})
        self.current_crypter = current_crypter
        self.setObjectName('account_dialog')
        self.setWindowTitle('账户')
        self.setModal(True)
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(14)

        title = QLabel('账户')
        title.setObjectName('account_title_small')
        layout.addWidget(title)

        self.name_edit = QLineEdit()
        self.name_edit.setObjectName('account_field')
        self.name_edit.setText(self.current_account.get('name') or '我的账户')
        layout.addWidget(self.name_edit)

        status = '已设置密码' if self.manager.account_has_password(self.current_account) else '无密码'
        self.status_label = QLabel(status)
        self.status_label.setObjectName('account_subtitle')
        layout.addWidget(self.status_label)

        save_btn = QPushButton('保存名称')
        save_btn.setObjectName('account_secondary')
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._rename_current)
        layout.addWidget(save_btn)

        password_btn = QPushButton('修改密码' if self.manager.account_has_password(self.current_account) else '设置密码')
        password_btn.setObjectName('account_primary')
        password_btn.setCursor(Qt.PointingHandCursor)
        password_btn.clicked.connect(self._set_password)
        layout.addWidget(password_btn)

        if self.manager.account_has_password(self.current_account):
            clear_btn = QPushButton('移除密码')
            clear_btn.setObjectName('account_secondary')
            clear_btn.setCursor(Qt.PointingHandCursor)
            clear_btn.clicked.connect(self._clear_password)
            layout.addWidget(clear_btn)

        new_btn = QPushButton('新建账户')
        new_btn.setObjectName('account_secondary')
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(self._create_account)
        layout.addWidget(new_btn)

        delete_btn = QPushButton('删除当前账户')
        delete_btn.setObjectName('account_danger')
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.clicked.connect(self._delete_current)
        layout.addWidget(delete_btn)

        switchable = [
            account for account in self.manager.passwordless_accounts()
            if account.get('id') != self.current_account.get('id')
        ]
        if switchable:
            line = QFrame()
            line.setObjectName('account_line')
            line.setFrameShape(QFrame.HLine)
            layout.addWidget(line)
            for account in switchable:
                btn = QPushButton(account.get('name') or '我的账户')
                btn.setObjectName('account_choice')
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _checked=False, account_id=account.get('id'): self._switch_passwordless(account_id))
                layout.addWidget(btn)

        done_btn = QPushButton('完成')
        done_btn.setObjectName('account_flat')
        done_btn.setCursor(Qt.PointingHandCursor)
        done_btn.clicked.connect(self.accept)
        layout.addWidget(done_btn)

    def _rename_current(self):
        try:
            self.current_account = self.manager.rename_account(
                self.current_account.get('id'),
                self.name_edit.text(),
            )
            self.accept()
        except AccountError as exc:
            QMessageBox.warning(self, '账户', str(exc))

    def _verify_current_password(self, action_label):
        """改/清密码前先验证当前密码。

        之前会话内任何人都能静默移除密码实现永久访问。"""
        if not self.manager.account_has_password(self.current_account):
            return True
        for _ in range(3):
            text, ok = QInputDialog.getText(
                self, action_label,
                tr('请输入当前密码以继续：'),
                QLineEdit.Password,
            )
            if not ok:
                return False
            account, _crypter = self.manager.unlock(text)
            if account and account.get('id') == self.current_account.get('id'):
                return True
            QMessageBox.warning(self, action_label, tr('密码不正确，请重试。'))
        return False

    def _set_password(self):
        action = '修改密码' if self.manager.account_has_password(self.current_account) else '设置密码'
        if not self._verify_current_password(action):
            return
        dlg = PasswordSetupDialog(action, self)
        if dlg.exec() != QDialog.Accepted:
            return
        manager = self.manager
        account = self.current_account
        crypter = self.current_crypter
        password = dlg.password

        def job(worker):
            worker.report(tr('正在用新密码重新加密账户数据...'))
            return manager.set_account_password(account, crypter, password)

        # 重加密全部附件可能要几十秒，放后台线程；进度对话框模态防并发修改
        worker = run_with_progress(self, action, tr('正在重新加密账户数据...'), job, cancellable=False)
        if worker.error:
            if isinstance(worker.error, AccountError):
                QMessageBox.warning(self, '账户', str(worker.error))
            else:
                QMessageBox.critical(self, '账户', f'设置密码失败:\n{worker.error}')
            return
        self.current_account, self.current_crypter = worker.result
        self.accept()

    def _clear_password(self):
        if not self._verify_current_password('移除密码'):
            return
        reply = QMessageBox.question(
            self,
            '移除密码',
            '移除后，这个账户打开时不需要输入密码。',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        manager = self.manager
        account = self.current_account
        crypter = self.current_crypter

        def job(worker):
            worker.report(tr('正在用本机密钥重新加密账户数据...'))
            return manager.clear_account_password(account, crypter)

        worker = run_with_progress(self, '移除密码', tr('正在重新加密账户数据...'), job, cancellable=False)
        if worker.error:
            if isinstance(worker.error, AccountError):
                QMessageBox.warning(self, '账户', str(worker.error))
            else:
                QMessageBox.critical(self, '账户', f'移除密码失败:\n{worker.error}')
            return
        self.current_account, self.current_crypter = worker.result
        self.accept()

    def _create_account(self):
        dlg = NewAccountDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self.current_account, self.current_crypter = self.manager.create_account(
                dlg.name,
                dlg.password,
                import_legacy=False,
            )
            self.accept()
        except AccountError as exc:
            QMessageBox.warning(self, '账户', str(exc))
        except Exception as exc:
            QMessageBox.critical(self, '账户', f'创建账户失败:\n{exc}')

    def _next_account_after_delete(self, deleted_account_id):
        others = [
            account for account in self.manager.accounts()
            if account.get('id') != deleted_account_id
        ]
        if not others:
            return None, None

        for account in others:
            if not self.manager.account_has_password(account):
                return self.manager.unlock_passwordless(account.get('id'))

        QMessageBox.information(
            self,
            '进入其他账户',
            '删除当前账户前，需要先输入另一个账户的密码。',
        )
        dlg = LoginDialog(self.manager, self, exclude_account_id=deleted_account_id)
        if dlg.exec() != QDialog.Accepted or not dlg.account or not dlg.crypter:
            return None, None
        return dlg.account, dlg.crypter

    def _delete_current(self):
        account_id = self.current_account.get('id')
        if not account_id:
            return
        account_name = self.current_account.get('name') or '我的账户'
        reply = QMessageBox.question(
            self,
            '删除账户',
            f'确定删除“{account_name}”？\n\n这个账户里的文字、图片、文件和设置都会从本机移除。此操作不能撤销。',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            remaining_accounts = [
                account for account in self.manager.accounts()
                if account.get('id') != account_id
            ]
            next_account, next_crypter = self._next_account_after_delete(account_id)
            if remaining_accounts and (not next_account or not next_crypter):
                QMessageBox.information(self, '删除已取消', '没有进入其他账户，当前账户未删除。')
                return

            self.manager.delete_account(account_id)
            if next_account and next_crypter:
                self.current_account = next_account
                self.current_crypter = next_crypter
            else:
                self.current_account, self.current_crypter = self.manager.ensure_default_account()
            self.accept()
        except AccountError as exc:
            QMessageBox.warning(self, '账户', str(exc))
        except Exception as exc:
            QMessageBox.critical(self, '账户', f'删除账户失败:\n{exc}')

    def _switch_passwordless(self, account_id):
        account, crypter = self.manager.unlock_passwordless(account_id)
        if not account:
            return
        self.current_account = account
        self.current_crypter = crypter
        self.accept()


def select_start_account(account_manager):
    if not account_manager.has_accounts():
        return account_manager.ensure_default_account()
    passwordless = account_manager.passwordless_accounts()
    password_accounts = [a for a in account_manager.accounts() if account_manager.account_has_password(a)]
    if len(passwordless) == 1 and not password_accounts:
        return account_manager.unlock_passwordless(passwordless[0].get('id'))
    login = LoginDialog(account_manager)
    if login.exec() != QDialog.Accepted or not login.account or not login.crypter:
        return None, None
    return login.account, login.crypter


def main():
    data_root_override, qt_argv = parse_startup_args(sys.argv)
    app = QApplication(qt_argv)
    app.setApplicationName('FRESH')
    app.setOrganizationName('FRESH')
    configure_application_font(app)

    # 单实例：已有实例运行时静默退出，避免外部重复启动时不断把窗口拉到前台。
    runtime_dir = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation) or tempfile.gettempdir()
    Path(runtime_dir).mkdir(parents=True, exist_ok=True)
    lock_file = QLockFile(str(Path(runtime_dir) / 'FRESH.lock'))
    lock_file.setStaleLockTime(0)
    if not lock_file.tryLock(100):
        if _activate_running_instance():
            return
        # 没有活着的实例却拿不到锁：多半是崩溃残留，清掉重试，
        # 不再让用户双击后毫无反应
        lock_file.removeStaleLockFile()
        if not lock_file.tryLock(100):
            QMessageBox.critical(
                None, 'FRESH',
                'FRESH 似乎已在运行，或上次异常退出留下了锁文件。\n'
                '请结束已运行的 FRESH 进程后重试。',
            )
            return

    settings = QSettings('FRESH', 'FRESH')
    data_root = configured_data_root(settings, data_root_override)
    setup_logging(data_root)
    logger.info('FRESH 启动，数据目录: %s', data_root)
    ensure_custom_files()
    install_text_overrides(app)
    app.setStyleSheet(customized_stylesheet(STYLE))
    # 关闭窗口后不退出应用（保留在系统托盘）
    app.setQuitOnLastWindowClosed(False)

    try:
        account_manager = AccountManager(app_root=data_root)
        account, crypter = select_start_account(account_manager)
        if not account or not crypter:
            return
        storage = Storage(
            app_dir=account_manager.account_dir(account),
            crypter=crypter,
        )
    except SaltFileError as exc:
        logger.critical('密钥文件异常: %s', exc)
        QMessageBox.critical(None, '密钥文件异常', str(exc))
        return

    window = MainWindow(storage, account=account, account_manager=account_manager)
    window.show()

    try:
        app.commitDataRequest.connect(lambda _manager: window.prepare_for_session_end())
    except Exception:
        logger.exception('注册会话结束保存钩子失败')
    app.aboutToQuit.connect(window.prepare_for_session_end)

    # 监听本地 socket 只用于兼容已有启动流程；不再响应 show，避免窗口反复弹出。
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)

    def _on_new_connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        def _read_request():
            try:
                sock.readAll()
            except Exception:
                pass
        sock.readyRead.connect(_read_request)
        sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(_on_new_connection)
    app._single_instance_server = server  # 保活引用
    app._single_instance_lock = lock_file

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
