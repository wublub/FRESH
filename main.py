"""FRESH - 苹果风格便签"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    import winreg
except ImportError:
    winreg = None

from PySide6.QtCore import (
    Qt, QSize, Signal, QTimer, QRect, QRectF, QUrl, QPoint, QPointF, QThread,
    QFileSystemWatcher, QEvent, QSettings, QLockFile, QStandardPaths
)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (
    QPixmap, QImage, QFont, QColor, QPainter, QPolygonF,
    QDesktopServices, QFontMetrics, QKeySequence, QIcon, QShortcut, QGuiApplication,
    QPen,
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
    QToolTip
)

from accounts import AccountError, AccountManager
from storage import SCREENSHOT_BOARD_ID, Storage
from styles import STYLE
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
)
import ftrack
from shell_notify import (
    ShellChangeFilter,
    SHCNE_RENAMEITEM, SHCNE_RENAMEFOLDER,
    SHCNE_CREATE, SHCNE_DELETE, SHCNE_MKDIR, SHCNE_RMDIR,
    SHCNE_UPDATEDIR, SHCNE_UPDATEITEM,
)


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


def looks_like_qt_html(text: str) -> bool:
    stripped = (text or '').lstrip().lower()
    return (
        stripped.startswith('<!doctype html')
        or stripped.startswith('<html')
        or 'meta name="qrichtext"' in stripped[:500]
    )


def note_content_preview(note: dict) -> str:
    content = note.get('content', '') or ''
    if note.get('content_format') == 'markdown':
        return markdown_to_preview(content)
    return html_to_preview(content)


def note_display_title(note: dict) -> str:
    title = (note.get('title') or '').strip()
    if title:
        return title
    preview = note_content_preview(note)
    return preview[:28] if preview else tr('未命名备忘录')


def note_search_text(note: dict) -> str:
    parts = [
        note.get('title', ''),
        note_content_preview(note),
        note.get('category', ''),
        note.get('archive_category', ''),
        note.get('created_at', ''),
        note.get('updated_at', ''),
        note.get('archived_at', ''),
    ]
    for att in note.get('attachments', []) or []:
        if att.get('deleted'):
            continue
        parts.extend([
            att.get('original_name', ''),
            att.get('memo', ''),
            att.get('archive_content', ''),
            att.get('archive_category', ''),
            att.get('original_path', ''),
            att.get('stored_name', ''),
            att.get('added_at', ''),
            att.get('archived_at', ''),
        ])
    return ' '.join(str(part) for part in parts if part).lower()


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


def reveal_in_file_manager(path):
    p = Path(path)
    if not p.exists():
        return
    try:
        p = p.resolve()
    except Exception:
        pass
    if sys.platform == 'win32':
        try:
            if p.is_file():
                subprocess.Popen(f'explorer.exe /select,"{str(p)}"')
            else:
                subprocess.Popen(['explorer.exe', str(p)])
            return
        except Exception:
            pass
    target = p.parent if p.is_file() else p
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


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

AUTOSTART_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
AUTOSTART_NAME = 'FRESH'


def _autostart_command():
    main_path = Path(__file__).resolve()
    python_exe = sys.executable
    pythonw = python_exe
    if python_exe and python_exe.lower().endswith('python.exe'):
        candidate = Path(python_exe).with_name('pythonw.exe')
        if candidate.exists():
            pythonw = str(candidate)
    return f'"{pythonw}" "{main_path}"'


def autostart_supported():
    return winreg is not None and sys.platform == 'win32'


def is_autostart_enabled():
    if not autostart_supported():
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            winreg.QueryValueEx(k, AUTOSTART_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_autostart(enable):
    if not autostart_supported():
        return False
    try:
        if enable:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, _autostart_command())
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False


def refresh_autostart_if_needed():
    if not autostart_supported():
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY) as k:
            current_cmd, _ = winreg.QueryValueEx(k, AUTOSTART_NAME)
    except FileNotFoundError:
        return
    except OSError:
        return
    new_cmd = _autostart_command()
    if current_cmd != new_cmd:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ, new_cmd)
        except OSError:
            pass


# ============ 备忘录列表自定义渲染 ============

class NoteListDelegate(QStyledItemDelegate):
    ITEM_HEIGHT = 68
    SIDE_MARGIN = 4
    PADDING = 12

    def sizeHint(self, option, index):
        return QSize(0, self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        note = index.data(Qt.UserRole)
        if not note:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(self.SIDE_MARGIN, 2, -self.SIDE_MARGIN, -2)

        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setBrush(QColor("#007AFF"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
            c_title = QColor("#FFFFFF")
            c_time = QColor(255, 255, 255, 220)
            c_preview = QColor(255, 255, 255, 200)
        elif hovered:
            painter.setBrush(QColor(0, 0, 0, 12))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
            c_title = QColor("#1D1D1F")
            c_time = QColor("#86868B")
            c_preview = QColor("#86868B")
        else:
            c_title = QColor("#1D1D1F")
            c_time = QColor("#86868B")
            c_preview = QColor("#86868B")

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
                painter.setBrush(QColor(255, 255, 255, 70))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(badge_rect, 8, 8)
                painter.setPen(QColor("#FFFFFF"))
            else:
                painter.setBrush(QColor("#E5E5E7"))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(badge_rect, 8, 8)
                painter.setPen(QColor("#6E6E73"))
            painter.drawText(badge_rect, Qt.AlignCenter, str(att_count))

        if pinned:
            pf = QFont(painter.font())
            pf.setPointSize(8)
            pf.setWeight(QFont.DemiBold)
            painter.setFont(pf)
            right_edge = rect.right() - self.PADDING - (badge_w + 6 if badge_w > 0 else 0)
            pin_rect = QRectF(right_edge - pin_w, rect.top() + 12, pin_w, 16)
            if selected:
                painter.setBrush(QColor(255, 255, 255, 70))
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(pin_rect, 8, 8)
                painter.setPen(QColor("#FFFFFF"))
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
    ITEM_HEIGHT = 62
    SIDE_MARGIN = 4
    PADDING = 12

    def sizeHint(self, option, index):
        return QSize(0, self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        att = index.data(Qt.UserRole)
        if not att:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(self.SIDE_MARGIN, 2, -self.SIDE_MARGIN, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setBrush(QColor("#007AFF"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
            title_color = QColor("#FFFFFF")
            sub_color = QColor(255, 255, 255, 210)
        elif hovered:
            painter.setBrush(QColor(0, 0, 0, 12))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
            title_color = QColor("#1D1D1F")
            sub_color = QColor("#86868B")
        else:
            title_color = QColor("#1D1D1F")
            sub_color = QColor("#86868B")

        title = att.get('archive_content') or att.get('memo') or att.get('original_name') or '截图'
        sub = format_time_short(att.get('archived_at') or att.get('added_at') or '')
        category = (att.get('archive_category') or '').strip()
        if category:
            sub = f'#{category}  · {sub}' if sub else f'#{category}'

        title_font = QFont(painter.font())
        title_font.setPointSize(10)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(title_color)
        title_rect = rect.adjusted(self.PADDING, 9, -self.PADDING, 0)
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
            painter.fontMetrics().elidedText(sub or '未归档截图', Qt.ElideRight, sub_rect.width()),
        )
        painter.restore()


class ArchiveListDelegate(QStyledItemDelegate):
    ITEM_HEIGHT = 68
    SIDE_MARGIN = 4
    PADDING = 12

    def sizeHint(self, option, index):
        return QSize(0, self.ITEM_HEIGHT)

    def paint(self, painter, option, index):
        data = index.data(Qt.UserRole)
        if not data:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(self.SIDE_MARGIN, 2, -self.SIDE_MARGIN, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        if selected:
            painter.setBrush(QColor("#007AFF"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
            title_color = QColor("#FFFFFF")
            sub_color = QColor(255, 255, 255, 210)
            badge_bg = QColor(255, 255, 255, 70)
            badge_fg = QColor("#FFFFFF")
        elif hovered:
            painter.setBrush(QColor(0, 0, 0, 12))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 8, 8)
            title_color = QColor("#1D1D1F")
            sub_color = QColor("#86868B")
            badge_bg = QColor("#E5E5E7")
            badge_fg = QColor("#6E6E73")
        else:
            title_color = QColor("#1D1D1F")
            sub_color = QColor("#86868B")
            badge_bg = QColor("#E5E5E7")
            badge_fg = QColor("#6E6E73")

        note = data.get('note') or {}
        att = data.get('attachment') or {}
        is_note = data.get('kind') == 'note'
        kind_label = tr('文字') if is_note else tr('截图')
        if is_note:
            title = note_display_title(note)
            preview = note_content_preview(note) or tr('没有附加文本')
            category = (note.get('archive_category') or note.get('category') or '').strip()
        else:
            title = att.get('archive_content') or att.get('memo') or att.get('original_name') or tr('截图')
            preview = tr('来自 {title}', title=note_display_title(note))
            category = (att.get('archive_category') or '').strip()
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

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}
SHELL_CREATE_MATCH_WINDOW_SECONDS = 180.0
SHELL_DELETE_RETRY_WINDOW_SECONDS = 180.0


def is_image_attachment(att):
    if att.get('type') == 'folder':
        return False
    name = att.get('original_name', '')
    return Path(name).suffix.lower() in IMAGE_EXTS


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
                painter.drawPixmap(sel, self.pixmap.copy(source))
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

        layout.addWidget(self.text_btn)
        layout.addWidget(self.shot_btn)

        self.text_btn.clicked.connect(lambda: self._click('text'))
        self.shot_btn.clicked.connect(lambda: self._click('screenshot'))

    def _click(self, mode):
        self.set_mode(mode, emit=True)

    def set_mode(self, mode, emit=False):
        self.text_btn.blockSignals(True)
        self.shot_btn.blockSignals(True)
        self.text_btn.setChecked(mode == 'text')
        self.shot_btn.setChecked(mode == 'screenshot')
        self.text_btn.blockSignals(False)
        self.shot_btn.blockSignals(False)
        if emit:
            self.changed.emit(mode)

    def current_mode(self):
        return 'screenshot' if self.shot_btn.isChecked() else 'text'


class ViewSwitch(QWidget):
    """活跃 / 归档 视图切换"""
    changed = Signal(str)

    def __init__(self):
        super().__init__()
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
        self.set_view(view, emit=True)

    def set_view(self, view, emit=False):
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
        return 'archived' if self.archived_btn.isChecked() else 'active'


class TextFormatSwitch(QWidget):
    """富文本 / Markdown 格式切换"""
    changed = Signal(str)

    def __init__(self):
        super().__init__()
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
        self.set_format(fmt, emit=True)

    def set_format(self, fmt, emit=False):
        fmt = 'markdown' if fmt == 'markdown' else 'rich'
        self.rich_btn.blockSignals(True)
        self.markdown_btn.blockSignals(True)
        self.rich_btn.setChecked(fmt == 'rich')
        self.markdown_btn.setChecked(fmt == 'markdown')
        self.rich_btn.blockSignals(False)
        self.markdown_btn.blockSignals(False)
        if emit:
            self.changed.emit(fmt)

    def current_format(self):
        return 'markdown' if self.markdown_btn.isChecked() else 'rich'


class ScreenshotThumbnail(QFrame):
    delete_requested = Signal(str)
    open_requested = Signal(str)
    archive_toggled = Signal(str)
    memo_changed = Signal(str, str)

    THUMB_W = 220
    THUMB_H = 150
    CARD_H = THUMB_H + 38

    def __init__(self, attachment, file_path):
        super().__init__()
        self.attachment = attachment
        self.file_path = Path(file_path)
        self.is_archived = bool(attachment.get('archived', False))
        self.setObjectName('screenshot_thumb')
        self.setProperty('archived', self.is_archived)
        self.setFixedSize(self.THUMB_W, self.CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr('{name}\n双击查看大图 · 右键更多', name=attachment['original_name']))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.image_label = QLabel()
        self.image_label.setObjectName('thumb_image')
        self.image_label.setFixedSize(self.THUMB_W, self.THUMB_H)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setPixmap(self._build_thumbnail())

        # 右上角完成按钮 (浮在图片上)
        self.check_btn = QPushButton('✓', self.image_label)
        self.check_btn.setObjectName('thumb_check')
        self.check_btn.setProperty('done', self.is_archived)
        self.check_btn.setFixedSize(28, 28)
        self.check_btn.move(self.THUMB_W - 36, 8)
        self.check_btn.setCursor(Qt.PointingHandCursor)
        self.check_btn.setFocusPolicy(Qt.NoFocus)
        self.check_btn.setAttribute(Qt.WA_NoMousePropagation, True)
        self.check_btn.setToolTip('已归档 · 点击取消' if self.is_archived else '归档这张照片')
        self.check_btn.clicked.connect(lambda: self.archive_toggled.emit(self.attachment['id']))

        self.memo_input = QLineEdit()
        self.memo_input.setObjectName('thumb_memo')
        self.memo_input.setPlaceholderText('备注…')
        self.memo_input.setText(attachment.get('memo', '') or '')
        self.memo_input.editingFinished.connect(self._on_memo_committed)

        layout.addWidget(self.image_label)
        layout.addWidget(self.memo_input)

    def _build_thumbnail(self):
        if not self.file_path.exists():
            pix = QPixmap(self.THUMB_W, self.THUMB_H)
            pix.fill(QColor("#F5F5F7"))
            painter = QPainter(pix)
            painter.setPen(QColor("#86868B"))
            painter.drawText(pix.rect(), Qt.AlignCenter, tr('图片不存在'))
            painter.end()
            return pix
        pixmap = QPixmap(str(self.file_path))
        if pixmap.isNull():
            pix = QPixmap(self.THUMB_W, self.THUMB_H)
            pix.fill(QColor("#F5F5F7"))
            painter = QPainter(pix)
            painter.setPen(QColor("#86868B"))
            painter.drawText(pix.rect(), Qt.AlignCenter, tr('无法加载'))
            painter.end()
            return pix
        return pixmap.scaled(
            self.THUMB_W, self.THUMB_H,
            Qt.KeepAspectRatio, Qt.FastTransformation
        )

    def _on_memo_committed(self):
        text = self.memo_input.text().strip()
        if text != (self.attachment.get('memo', '') or ''):
            self.memo_changed.emit(self.attachment['id'], text)

    def mouseDoubleClickEvent(self, event):
        # 双击在备注输入框上不触发 (因为 LineEdit 自己消费事件)
        # 双击在图片或边缘触发
        self.open_requested.emit(self.attachment['id'])
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        view = menu.addAction('查看大图')
        toggle = menu.addAction('取消归档照片' if self.is_archived else '归档照片')
        menu.addSeparator()
        save = menu.addAction('保存为...')
        reveal = menu.addAction('在文件夹中显示')
        menu.addSeparator()
        delete = menu.addAction('从备忘录中移除')
        action = menu.exec(event.globalPos())
        if action == view:
            self.open_requested.emit(self.attachment['id'])
        elif action == toggle:
            self.archive_toggled.emit(self.attachment['id'])
        elif action == save:
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
        if not self.file_path.exists():
            return
        reveal_in_file_manager(self.file_path)


class ScreenshotGrid(QScrollArea):
    file_dropped = Signal(str)
    image_pasted = Signal(str)
    delete_requested = Signal(str)
    open_requested = Signal(str)
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

        self.container = QWidget()
        self.container.setObjectName('screenshot_grid_inner')
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(self.PADDING, self.PADDING, self.PADDING, self.PADDING)
        self.grid.setSpacing(self.THUMB_SPACING)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)

        self.empty_label = QLabel('粘贴 (Ctrl+V) 或拖入图片到此处')
        self.empty_label.setObjectName('grid_empty')
        self.empty_label.setAlignment(Qt.AlignCenter)

        self.setWidget(self.container)

        self._thumbnails = []
        self._current_images = []
        self._current_resolver = None
        self._current_cols = 0

    def set_attachments(self, attachments, path_resolver):
        images = [att for att in (attachments or []) if is_image_attachment(att)]
        self._current_images = images
        self._current_resolver = path_resolver
        self._current_cols = 0
        self._render()

    def _cols(self):
        avail = max(1, self.viewport().width() - 2 * self.PADDING)
        cell = ScreenshotThumbnail.THUMB_W + self.THUMB_SPACING
        return max(1, (avail + self.THUMB_SPACING) // cell)

    def _render(self):
        for w in self._thumbnails:
            w.setParent(None)
            w.deleteLater()
        self._thumbnails = []
        self.empty_label.setParent(None)

        while self.grid.count() > 0:
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if not self._current_images:
            self.grid.addWidget(self.empty_label, 0, 0, 1, 1)
            self.empty_label.show()
            self._current_cols = 1
            return

        cols = self._cols()
        self._current_cols = cols
        for i, att in enumerate(self._current_images):
            row, col = divmod(i, cols)
            path = self._current_resolver(att) if self._current_resolver else Path('')
            thumb = ScreenshotThumbnail(att, path)
            thumb.delete_requested.connect(self.delete_requested.emit)
            thumb.open_requested.connect(self.open_requested.emit)
            thumb.archive_toggled.connect(self.archive_toggled.emit)
            thumb.memo_changed.connect(self.memo_changed.emit)
            self.grid.addWidget(thumb, row, col, Qt.AlignTop | Qt.AlignLeft)
            self._thumbnails.append(thumb)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._current_images and self._cols() != self._current_cols:
            self._render()

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
        self.setStyleSheet("background: #1D1D1F;")

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

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta > 0:
            self._scale_by(1.15)
        else:
            self._scale_by(1 / 1.15)
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)


class ArchivePhotoDialog(QDialog):
    def __init__(self, attachment, file_path, categories=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('归档照片')
        self.setModal(True)
        self.resize(460, 480)
        self.setObjectName('archive_photo_dialog')

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)

        header = QLabel('完成了什么内容？')
        header.setObjectName('archive_dialog_title')

        subtitle = QLabel('这段内容会保存到照片归档记录，并显示在时间线里。')
        subtitle.setObjectName('archive_dialog_subtitle')
        subtitle.setWordWrap(True)

        preview_row = QHBoxLayout()
        preview_row.setContentsMargins(0, 2, 0, 0)
        preview_row.setSpacing(12)

        thumb = QLabel()
        thumb.setObjectName('archive_dialog_thumb')
        thumb.setFixedSize(120, 82)
        thumb.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(str(file_path))
        if pixmap.isNull():
            thumb.setText('无法预览')
        else:
            thumb.setPixmap(pixmap.scaled(120, 82, Qt.KeepAspectRatio, Qt.FastTransformation))

        name_box = QVBoxLayout()
        name_box.setContentsMargins(0, 0, 0, 0)
        name_box.setSpacing(4)
        filename = QLabel(attachment.get('original_name', '') or '截图')
        filename.setObjectName('archive_dialog_filename')
        filename.setWordWrap(True)
        hint = QLabel('填写后点击“归档照片”。')
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
        self.category_combo.lineEdit().setText(attachment.get('archive_category', '') or '')
        self.category_combo.currentTextChanged.connect(self._sync_ok_enabled)
        self.category_combo.lineEdit().textChanged.connect(self._sync_ok_enabled)
        category_row.addWidget(category_label)
        category_row.addWidget(self.category_combo, 1)

        self.content_edit = QTextEdit()
        self.content_edit.setObjectName('archive_dialog_content')
        self.content_edit.setPlaceholderText('例如：整理完登录页错误状态、标注了按钮位置、确认这张图的问题已经处理...')
        self.content_edit.setPlainText(attachment.get('archive_content') or attachment.get('memo', '') or '')
        self.content_edit.setMinimumHeight(120)
        self.content_edit.textChanged.connect(self._sync_ok_enabled)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 2, 0, 0)
        buttons.setSpacing(10)
        self.cancel_btn = QPushButton('取消')
        self.cancel_btn.setObjectName('archive_dialog_cancel')
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setFocusPolicy(Qt.NoFocus)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn = QPushButton('归档照片')
        self.ok_btn.setObjectName('archive_dialog_ok')
        self.ok_btn.setCursor(Qt.PointingHandCursor)
        self.ok_btn.setFocusPolicy(Qt.NoFocus)
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
        self.ok_btn.setEnabled(bool(self.content()) and bool(self.category()))


class EmptyState(QWidget):
    primary_action = Signal()
    secondary_action = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName('empty_state')

        outer = QVBoxLayout(self)
        outer.setContentsMargins(44, 44, 44, 44)
        outer.setSpacing(0)
        outer.addStretch(1)

        panel = QFrame()
        panel.setObjectName('empty_panel')
        panel.setMaximumWidth(420)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(28, 26, 28, 28)
        panel_layout.setSpacing(12)

        self.icon = QLabel('⌘')
        self.icon.setObjectName('empty_icon')
        self.icon.setAlignment(Qt.AlignCenter)

        self.title = QLabel('')
        self.title.setObjectName('empty_title')
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)

        self.message = QLabel('')
        self.message.setObjectName('empty_message')
        self.message.setAlignment(Qt.AlignCenter)
        self.message.setWordWrap(True)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 10, 0, 0)
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
        actions.addWidget(self.secondary_btn)
        actions.addWidget(self.primary_btn)

        panel_layout.addWidget(self.icon, 0, Qt.AlignCenter)
        panel_layout.addWidget(self.title)
        panel_layout.addWidget(self.message)
        panel_layout.addLayout(actions)

        outer.addWidget(panel, 0, Qt.AlignCenter)
        outer.addStretch(2)

    def configure(self, view='active', filtered=False, search='', category='', has_rows=False):
        if has_rows:
            self.icon.setText('✎')
            self.title.setText('选择一条备忘录')
            self.message.setText('从左侧列表打开一条备忘录。')
            self.secondary_btn.hide()
            self.primary_btn.hide()
            return

        if filtered:
            self.icon.setText('⌕')
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
            self.icon.setText('✓')
            self.title.setText('归档里还没有内容')
            self.message.setText('截图归档后会出现在这里，也会按分类进入时间线。')
            self.secondary_btn.setText('查看时间线')
            self.primary_btn.setText('回到活跃')
            self.secondary_btn.show()
            self.primary_btn.show()
            return

        self.icon.setText('✎')
        self.title.setText('还没有备忘录')
        self.message.setText('新建一条文字备忘录，或拖入文件作为附件。')
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


class TimelineReviewChart(QWidget):
    category_selected = Signal(str)

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
        self.setObjectName('timeline_chart')
        self.setMouseTracking(True)
        self.setMinimumHeight(172)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_records(self, records, selected_category='', granularity='month', rank_order='slow'):
        self.records = list(records or [])
        self.selected_category = selected_category or ''
        self.granularity = granularity or 'month'
        self.rank_order = rank_order or 'slow'
        self._hit_regions = []
        self._rank_regions = []
        QToolTip.hideText()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QPen(QColor('#E8E8ED'), 1))
        painter.setBrush(QColor('#FFFFFF'))
        painter.drawRoundedRect(rect, 8, 8)

        title_font = QFont(painter.font())
        title_font.setPointSize(11)
        title_font.setWeight(QFont.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor('#1D1D1F'))
        painter.drawText(rect.adjusted(16, 12, -16, 0), Qt.AlignLeft | Qt.AlignTop, self.title)

        plot = rect.adjusted(16, 40, -16, -16)
        self._hit_regions = []
        self._rank_regions = []
        if not self.records and self.chart_type != 'category':
            self._draw_empty(painter, plot)
        elif self.chart_type == 'trend':
            self._draw_trend(painter, plot)
        elif self.chart_type == 'category':
            self._draw_category(painter, plot)
        else:
            self._draw_ranking(painter, plot)
        painter.end()

    def _draw_empty(self, painter, rect):
        painter.setPen(QColor('#AEAEB2'))
        painter.drawText(rect, Qt.AlignCenter, '暂无完成记录')

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
        plot = rect.adjusted(0, 0, 0, -label_h)
        group_w = plot.width() / max(1, len(keys))
        bar_w = max(4, min(13, group_w * 0.24))
        base_y = plot.bottom()
        chart_h = max(1, plot.height() - 4)

        for idx, key in enumerate(keys):
            x = plot.left() + idx * group_w + group_w / 2
            created_h = chart_h * buckets[key]['created'] / max_count
            done_h = chart_h * buckets[key]['done'] / max_count
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#C7C7CC') if self.selected_category else QColor('#007AFF'))
            painter.drawRoundedRect(QRectF(x - bar_w - 1, base_y - created_h, bar_w, created_h), 3, 3)
            painter.setBrush(QColor('#C7C7CC') if self.selected_category else QColor('#34C759'))
            painter.drawRoundedRect(QRectF(x + 1, base_y - done_h, bar_w, done_h), 3, 3)
            if self.selected_category:
                selected_created_h = chart_h * buckets[key]['selected_created'] / max_count
                selected_done_h = chart_h * buckets[key]['selected_done'] / max_count
                painter.setBrush(QColor('#007AFF'))
                painter.drawRoundedRect(QRectF(x - bar_w - 1, base_y - selected_created_h, bar_w, selected_created_h), 3, 3)
                painter.setBrush(QColor('#34C759'))
                painter.drawRoundedRect(QRectF(x + 1, base_y - selected_done_h, bar_w, selected_done_h), 3, 3)

        painter.setPen(QColor('#86868B'))
        label_font = QFont(painter.font())
        label_font.setPointSize(8)
        painter.setFont(label_font)
        step = max(1, len(keys) // 5)
        for idx, key in enumerate(keys):
            if idx % step != 0 and idx != len(keys) - 1:
                continue
            x = rect.left() + idx * group_w
            painter.drawText(QRectF(x, rect.bottom() - label_h + 2, group_w, label_h), Qt.AlignCenter, period_label(key, self.granularity))

        legend_font = QFont(painter.font())
        legend_font.setPointSize(8)
        painter.setFont(legend_font)
        painter.setPen(QColor('#6E6E73'))
        painter.fillRect(QRectF(rect.right() - 96, rect.top(), 8, 8), QColor('#007AFF'))
        painter.drawText(QRectF(rect.right() - 84, rect.top() - 3, 38, 16), Qt.AlignLeft | Qt.AlignVCenter, '创建')
        painter.fillRect(QRectF(rect.right() - 44, rect.top(), 8, 8), QColor('#34C759'))
        painter.drawText(QRectF(rect.right() - 32, rect.top() - 3, 38, 16), Qt.AlignLeft | Qt.AlignVCenter, '完成')

    def _draw_category(self, painter, rect):
        groups = defaultdict(lambda: {'total': 0.0, 'count': 0})
        for record in self.records:
            category = record.get('category') or '未分类'
            groups[category]['total'] += record.get('duration_seconds') or 0
            groups[category]['count'] += 1
        items = sorted(groups.items(), key=lambda item: item[1]['total'], reverse=True)
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

        self._hit_regions = []
        max_total = max(data['total'] for _, data in items) or 1
        row_h = max(18, min(28, rect.height() / max(1, len(items))))
        label_w = min(118, rect.width() * 0.34)
        for idx, (category, data) in enumerate(items):
            y = rect.top() + idx * row_h
            dim = bool(self.selected_category and category != self.selected_category)
            color = QColor('#8E8E93' if dim else '#007AFF')
            text_color = QColor('#AEAEB2' if dim else '#1D1D1F')
            bar_rect = QRectF(rect.left() + label_w, y + 4, max(2, (rect.width() - label_w - 70) * data['total'] / max_total), row_h - 8)
            painter.setPen(text_color)
            painter.drawText(
                QRectF(rect.left(), y, label_w - 8, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(category, Qt.ElideRight, int(label_w - 10)),
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(bar_rect, 5, 5)
            painter.setPen(QColor('#AEAEB2' if dim else '#6E6E73'))
            painter.drawText(
                QRectF(bar_rect.right() + 8, y, 62, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                duration_text(data['total']),
            )
            self._hit_regions.append((QRectF(rect.left(), y, rect.width(), row_h), category))

    def _draw_ranking(self, painter, rect):
        reverse = self.rank_order != 'fast'
        if self.selected_category:
            selected_records = sorted(
                [record for record in self.records if record.get('category') == self.selected_category],
                key=lambda r: r.get('duration_seconds') or 0,
                reverse=reverse,
            )
            other_records = sorted(
                [record for record in self.records if record.get('category') != self.selected_category],
                key=lambda r: r.get('duration_seconds') or 0,
                reverse=reverse,
            )
            records = (selected_records + other_records)[:8]
        else:
            records = sorted(self.records, key=lambda r: r.get('duration_seconds') or 0, reverse=reverse)[:8]
        if not records:
            self._draw_empty(painter, rect)
            return
        max_duration = max(r.get('duration_seconds') or 0 for r in records) or 1
        row_h = max(19, min(29, rect.height() / max(1, len(records))))
        label_w = min(160, rect.width() * 0.45)
        for idx, record in enumerate(records):
            y = rect.top() + idx * row_h
            duration = record.get('duration_seconds') or 0
            dim = bool(self.selected_category and record.get('category') != self.selected_category)
            color = QColor('#C7C7CC' if dim else '#34C759')
            text_color = QColor('#AEAEB2' if dim else '#1D1D1F')
            painter.setPen(text_color)
            title = record.get('title') or '未命名'
            painter.drawText(
                QRectF(rect.left(), y, label_w - 8, row_h),
                Qt.AlignLeft | Qt.AlignVCenter,
                painter.fontMetrics().elidedText(title, Qt.ElideRight, int(label_w - 10)),
            )
            bar_rect = QRectF(rect.left() + label_w, y + 5, max(2, (rect.width() - label_w - 76) * duration / max_duration), row_h - 10)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(bar_rect, 5, 5)
            painter.setPen(QColor('#AEAEB2' if dim else '#6E6E73'))
            painter.drawText(QRectF(bar_rect.right() + 8, y, 68, row_h), Qt.AlignLeft | Qt.AlignVCenter, duration_text(duration))
            self._rank_regions.append((QRectF(rect.left(), y, rect.width(), row_h), record))

    def _tooltip_point(self, event):
        if hasattr(event, 'globalPosition'):
            return event.globalPosition().toPoint()
        return event.globalPos()

    def _format_record_dt(self, value):
        if isinstance(value, datetime):
            return format_time_long(value.isoformat())
        return format_time_long(value or '')

    def mouseMoveEvent(self, event):
        if self.chart_type == 'ranking':
            pos = QPointF(event.position()) if hasattr(event, 'position') else QPointF(event.pos())
            for rect, record in self._rank_regions:
                if rect.contains(pos):
                    title = record.get('title') or '未命名'
                    category = record.get('category') or '未分类'
                    tooltip = (
                        f'{title}\n'
                        f'分类：{category}\n'
                        f'耗时：{duration_text(record.get("duration_seconds") or 0)}\n'
                        f'创建：{self._format_record_dt(record.get("created_dt")) or "未知"}\n'
                        f'完成：{self._format_record_dt(record.get("completed_dt")) or "未知"}'
                    )
                    QToolTip.showText(self._tooltip_point(event), tooltip, self)
                    return
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self.chart_type != 'category':
            return super().mousePressEvent(event)
        pos = QPointF(event.position()) if hasattr(event, 'position') else QPointF(event.pos())
        for rect, category in self._hit_regions:
            if rect.contains(pos):
                self.category_selected.emit(category)
                return
        super().mousePressEvent(event)


class TimelineItem(QFrame):
    open_requested = Signal(str)
    unarchive_requested = Signal(str, str)
    note_requested = Signal(str)

    THUMB_W = 110
    THUMB_H = 74
    HEIGHT = 92

    def __init__(self, note, attachment, file_path):
        super().__init__()
        self.note = note
        self.attachment = attachment
        self.file_path = Path(file_path)
        self.setObjectName('timeline_item')
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
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
        category = (attachment.get('archive_category') or '').strip()
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
        time_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        time_label.setFixedWidth(60)

        layout.addWidget(self.image_label)
        layout.addLayout(text_layout, 1)
        layout.addWidget(time_label)

    def _build_thumb(self):
        if not self.file_path.exists():
            pix = QPixmap(self.THUMB_W, self.THUMB_H)
            pix.fill(QColor("#F5F5F7"))
            return pix
        pixmap = QPixmap(str(self.file_path))
        if pixmap.isNull():
            pix = QPixmap(self.THUMB_W, self.THUMB_H)
            pix.fill(QColor("#F5F5F7"))
            return pix
        return pixmap.scaled(
            self.THUMB_W, self.THUMB_H,
            Qt.KeepAspectRatio, Qt.FastTransformation
        )

    def mouseDoubleClickEvent(self, event):
        self.open_requested.emit(self.attachment['id'])
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        view = menu.addAction('查看大图')
        open_note = menu.addAction('打开所属备忘录')
        unarchive = menu.addAction('取消归档照片')
        action = menu.exec(event.globalPos())
        if action == view:
            self.open_requested.emit(self.attachment['id'])
        elif action == open_note:
            self.note_requested.emit(self.note['id'])
        elif action == unarchive:
            self.unarchive_requested.emit(self.note['id'], self.attachment['id'])


class TimelineNoteItem(QFrame):
    open_requested = Signal(str)
    unarchive_requested = Signal(str)

    HEIGHT = 100

    def __init__(self, note):
        super().__init__()
        self.note = note
        self.setObjectName('timeline_note_item')
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(14)

        icon = QLabel('✓')
        icon.setObjectName('timeline_note_icon')
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(42, 42)

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
        time_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
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
        unarchive = menu.addAction('取消归档')
        action = menu.exec(event.globalPos())
        if action == open_note:
            self.open_requested.emit(self.note['id'])
        elif action == unarchive:
            self.unarchive_requested.emit(self.note['id'])


class TimelineDialog(QDialog):
    state_changed = Signal()
    note_requested = Signal(str)

    def __init__(self, storage, parent=None):
        super().__init__(parent)
        self.storage = storage
        self.setWindowTitle('时间线回顾')
        self.resize(980, 820)

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

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(8)

        self.range_filter = QComboBox()
        self.range_filter.setObjectName('timeline_filter_combo')
        self.range_filter.addItem('全部时间', 'all')
        self.range_filter.addItem('近 7 天', '7')
        self.range_filter.addItem('近 30 天', '30')
        self.range_filter.addItem('近 90 天', '90')
        self.range_filter.addItem('本月', 'month')
        self.range_filter.addItem('今年', 'year')
        self.range_filter.setCurrentIndex(0)
        self.range_filter.currentIndexChanged.connect(lambda _: self._populate())

        self.granularity_filter = QComboBox()
        self.granularity_filter.setObjectName('timeline_filter_combo')
        self.granularity_filter.addItem('按月', 'month')
        self.granularity_filter.addItem('按周', 'week')
        self.granularity_filter.addItem('按日', 'day')
        self.granularity_filter.addItem('按年', 'year')
        self.granularity_filter.currentIndexChanged.connect(lambda _: self._populate())

        self.category_filter = QComboBox()
        self.category_filter.setObjectName('timeline_filter_combo')
        self.category_filter.addItem('全部分类', '')
        self.category_filter.currentIndexChanged.connect(lambda _: self._populate())

        self.rank_filter = QComboBox()
        self.rank_filter.setObjectName('timeline_filter_combo')
        self.rank_filter.addItem('耗时最多', 'slow')
        self.rank_filter.addItem('耗时最少', 'fast')
        self.rank_filter.currentIndexChanged.connect(lambda _: self._populate())

        filter_row.addWidget(self.range_filter)
        filter_row.addWidget(self.granularity_filter)
        filter_row.addWidget(self.category_filter)
        filter_row.addWidget(self.rank_filter)
        filter_row.addStretch()
        header_layout.addLayout(filter_row)

        review_box = QWidget()
        review_box.setObjectName('timeline_review_box')
        review_layout = QVBoxLayout(review_box)
        review_layout.setContentsMargins(18, 16, 18, 14)
        review_layout.setSpacing(12)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.count_value, count_card = self._make_stat('完成', '0')
        self.avg_value, avg_card = self._make_stat('平均耗时', '0')
        self.total_value, total_card = self._make_stat('总耗时', '0')
        self.span_value, span_card = self._make_stat('跨度', '0')
        stats_row.addWidget(count_card)
        stats_row.addWidget(avg_card)
        stats_row.addWidget(total_card)
        stats_row.addWidget(span_card)
        review_layout.addLayout(stats_row)

        chart_grid = QGridLayout()
        chart_grid.setContentsMargins(0, 0, 0, 0)
        chart_grid.setHorizontalSpacing(10)
        chart_grid.setVerticalSpacing(10)
        self.trend_chart = TimelineReviewChart('trend', '创建 / 完成')
        self.category_chart = TimelineReviewChart('category', '分类耗时')
        self.ranking_chart = TimelineReviewChart('ranking', '耗时排行')
        self.category_chart.category_selected.connect(self._select_category_from_chart)
        chart_grid.addWidget(self.trend_chart, 0, 0)
        chart_grid.addWidget(self.category_chart, 0, 1)
        chart_grid.addWidget(self.ranking_chart, 1, 0, 1, 2)
        review_layout.addLayout(chart_grid)

        detail_title = QLabel('归档明细')
        detail_title.setObjectName('timeline_detail_title')

        self.list = QListWidget()
        self.list.setObjectName('timeline_list')
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setSelectionMode(QListWidget.NoSelection)

        layout.addWidget(header_box)
        layout.addWidget(review_box)
        layout.addWidget(detail_title)
        layout.addWidget(self.list, 1)

        self._populate()

    def _make_stat(self, label, value):
        card = QFrame()
        card.setObjectName('timeline_stat_card')
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        value_label = QLabel(value)
        value_label.setObjectName('timeline_stat_value')
        label_widget = QLabel(label)
        label_widget.setObjectName('timeline_stat_label')
        layout.addWidget(value_label)
        layout.addWidget(label_widget)
        return value_label, card

    def _refresh_category_filter(self, records):
        current = self.category_filter.currentData() or ''
        categories = sorted({record.get('category') or '未分类' for record in records})
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem('全部分类', '')
        for category in categories:
            self.category_filter.addItem(category, category)
        index = 0
        for i in range(self.category_filter.count()):
            if self.category_filter.itemData(i) == current:
                index = i
                break
        self.category_filter.setCurrentIndex(index)
        self.category_filter.blockSignals(False)

    def _review_records(self):
        records = []
        for item in self.storage.all_timeline_items():
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
                category = (att.get('archive_category') or note.get('archive_category') or note.get('category') or '未分类').strip() or '未分类'
                title = att.get('archive_content') or att.get('memo') or att.get('original_name') or '截图'
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

    def _range_start(self):
        value = self.range_filter.currentData() or 'all'
        now = datetime.now()
        if value == 'all':
            return None
        if value == 'month':
            return datetime(now.year, now.month, 1)
        if value == 'year':
            return datetime(now.year, 1, 1)
        try:
            return now - timedelta(days=int(value))
        except Exception:
            return None

    def _records_in_range(self, records):
        start = self._range_start()
        if not start:
            return records
        return [record for record in records if record.get('completed_dt') and record['completed_dt'] >= start]

    def _active_records(self, records):
        category = self.category_filter.currentData() or ''
        if not category:
            return records
        return [record for record in records if record.get('category') == category]

    def _timeline_records_for_list(self, records, active_records):
        selected_category = self.category_filter.currentData() or ''
        return records if selected_category else active_records

    def _select_category_from_chart(self, category):
        current = self.category_filter.currentData() or ''
        target = '' if current == category else category
        for i in range(self.category_filter.count()):
            if self.category_filter.itemData(i) == target:
                self.category_filter.setCurrentIndex(i)
                return

    def _update_summary(self, records, active_records):
        selected_category = self.category_filter.currentData() or ''
        summary_records = active_records if selected_category else records
        count = len(summary_records)
        total = sum(record.get('duration_seconds') or 0 for record in summary_records)
        avg = total / count if count else 0
        self.count_value.setText(str(count))
        self.avg_value.setText(duration_text(avg))
        self.total_value.setText(duration_text(total))
        if summary_records:
            first = min(record['created_dt'] for record in summary_records if record.get('created_dt'))
            last = max(record['completed_dt'] for record in summary_records if record.get('completed_dt'))
            span_days = max(1, (last.date() - first.date()).days + 1)
            self.span_value.setText(f'{span_days} 天')
        else:
            self.span_value.setText('0 天')

    def _populate(self):
        self.list.clear()
        all_records = self._review_records()
        records = self._records_in_range(all_records)
        self._refresh_category_filter(records)
        active_records = self._active_records(records)
        selected_category = self.category_filter.currentData() or ''
        granularity = self.granularity_filter.currentData() or 'month'
        rank_order = self.rank_filter.currentData() or 'slow'

        self.trend_chart.set_records(records, selected_category, granularity, rank_order)
        self.category_chart.set_records(records, selected_category, granularity, rank_order)
        self.ranking_chart.set_records(records, selected_category, granularity, rank_order)
        self._update_summary(records, active_records)

        list_records = self._timeline_records_for_list(records, active_records)
        count_items = [record.get('item') for record in active_records if record.get('item')]
        shot_count = sum(1 for item in count_items if item.get('kind') == 'attachment')
        note_count = sum(1 for item in count_items if item.get('kind') == 'note')
        prefix = f'#{selected_category} · ' if selected_category else ''
        parts = []
        if shot_count:
            parts.append(tr('{count} 张归档照片', count=shot_count))
        if note_count:
            parts.append(tr('{count} 条归档备忘录', count=note_count))
        self.subtitle.setText(prefix + (' · '.join(parts) if parts else tr('暂无归档内容')))

        if not list_records:
            empty_text = tr('还没有归档内容\n\n归档照片或备忘录后会出现在这里')
            if selected_category:
                empty_text = tr('#{category} 下还没有归档内容', category=selected_category)
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
                tw.unarchive_requested.connect(self._unarchive_note)
                item_height = TimelineNoteItem.HEIGHT
            else:
                att = item.get('attachment')
                if not att:
                    continue
                tw = TimelineItem(note, att, self.storage.path_for(att))
                tw.open_requested.connect(self._open_image)
                tw.note_requested.connect(self._open_note)
                tw.unarchive_requested.connect(self._unarchive_attachment)
                item_height = TimelineItem.HEIGHT
            if selected_category and record.get('category') != selected_category:
                effect = QGraphicsOpacityEffect(tw)
                effect.setOpacity(0.34)
                tw.setGraphicsEffect(effect)
            it = QListWidgetItem()
            it.setFlags(Qt.NoItemFlags)
            it.setSizeHint(QSize(0, item_height))
            self.list.addItem(it)
            self.list.setItemWidget(it, tw)

    def _open_image(self, attachment_id):
        parent = self.parent()
        if parent is not None and hasattr(parent, '_open_image_viewer'):
            parent._open_image_viewer(attachment_id)
            return

    def _open_note(self, note_id):
        self.note_requested.emit(note_id)
        self.accept()

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


# ============ 文件追踪扫描 ============

class FtrackScanWorker(QThread):
    """单个文件的"重点扫描"：先按 ADS 标记，找不到改按文件名兜底。"""
    progress = Signal(str)
    phase_changed = Signal(str)
    finished_with_result = Signal(object)

    def __init__(self, tracking, name_fallback=None, scan_settings=None, parent=None):
        super().__init__(parent)
        self.tracking = tracking
        self.name_fallback = name_fallback
        self.scan_settings = scan_settings or {}
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

            # 2. Everything（如果可用）按 tag + name 定位
            if tag and name and ftrack.everything_mode(es_path) and self.scan_settings.get('use_everything', True):
                self.phase_changed.emit('用 Everything 查找带标签的文件')
                found_map = ftrack._scan_via_everything(
                    {tag: name},
                    drive_hints=[hint] if hint else None,
                    on_found=None,
                    cancel=self._is_cancelled,
                    progress=lambda d: self.progress.emit(d),
                    phase=lambda p: self.phase_changed.emit(p),
                    stream=ftrack.ADS_STREAM,
                    es_path=es_path,
                )
                if found_map.get(tag):
                    result['path'] = found_map[tag]
                    self.finished_with_result.emit(result)
                    return

            # 3. os.walk ADS 全盘扫描（兜底）
            if not self._cancel and tag:
                self.phase_changed.emit('按追踪标记全盘扫描')
                scan_roots = recovery_scan_roots(self.scan_settings, [hint] if hint else None)
                p = ftrack.scan_for_tag(
                    tag,
                    roots=scan_roots,
                    progress=lambda d: self.progress.emit(d),
                    cancel=self._is_cancelled,
                    drive_hints=[hint] if hint else None,
                )
                if p:
                    result['path'] = p
                    self.finished_with_result.emit(result)
                    return

            # 4. 按名兜底 (Everything 优先 / os.walk)
            if name and not self._cancel:
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
                result['candidates'] = cands or []

            # 5. 内容 hash 全盘兜底（覆盖跨盘复制、ADS 丢失、改名）
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
        except Exception:
            pass
        self.finished_with_result.emit(result)


class AutoRecoveryWorker(QThread):
    """启动后自动跑：用 Everything (如果可用) 一次性把所有失踪的找回。"""
    progress = Signal(str, int)  # (current_dir, dirs_scanned_count)
    found_one = Signal(str, str)  # (tracking_id, path)
    finished_clean = Signal(int)  # 已扫目录数

    def __init__(self, tag_to_name, tag_to_tracking=None, drive_hints=None, scan_settings=None, parent=None):
        super().__init__(parent)
        self.tag_to_name = dict(tag_to_name)
        self.tag_to_tracking = dict(tag_to_tracking or {})
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
            if remaining and not self._cancel:
                on_phase('按文件名快速验证剩余文件')
                for tag in list(remaining):
                    tracking = self.tag_to_tracking.get(tag, {})
                    name = self.tag_to_name.get(tag, '')
                    if not name or not tracking.get('content_hash'):
                        continue
                    paths = ftrack.find_nearby_name_candidates(
                        name,
                        roots=quick_roots,
                        limit=100,
                    )
                    if ftrack.everything_mode(es_path):
                        paths.extend(
                            ftrack.everything_search(
                                name,
                                exact_name=True,
                                drive_hint=None,
                                limit=500,
                                es_path=es_path,
                            ) or []
                        )
                    hash_matches = [
                        p for p in (paths or [])
                        if ftrack.path_matches_hash(p, tracking)
                    ]
                    if len(hash_matches) == 1:
                        found[tag] = hash_matches[0]
                        remaining.discard(tag)
                        on_found(tag, hash_matches[0])
                    if self._cancel:
                        break

            if remaining and not self._cancel and ftrack.everything_mode(es_path):
                on_phase(f'用 Everything ({ftrack.everything_mode(es_path)}) 加速查找')
                found_by_tag = ftrack._scan_via_everything(
                    {tag: self.tag_to_name.get(tag, '') for tag in remaining},
                    drive_hints=self.drive_hints,
                    on_found=on_found,
                    cancel=lambda: self._cancel,
                    progress=on_progress,
                    phase=on_phase,
                    stream=ftrack.ADS_STREAM,
                    es_path=es_path,
                )
                found.update(found_by_tag or {})
                remaining -= set((found_by_tag or {}).keys())

            if remaining and not self._cancel:
                on_phase('按追踪标记扫描剩余文件')
                found_by_tag = ftrack.scan_for_tags(
                    remaining,
                    roots=scan_roots,
                    drive_hints=self.drive_hints,
                    on_found=on_found,
                    cancel=lambda: self._cancel,
                    progress=on_progress,
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
        self.es_path_edit.setPlaceholderText('留空 = 自动检测（PATH + Everything 安装目录）')
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

        hint = QLabel('留空时自动扫描所有 NTFS 盘。指定后只在这些位置中查找（仅影响 os.walk 兜底；Everything 总是查询全盘索引）。')
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
            ed = ftrack._find_running_everything_dir()
            tip = f'\n    你的 Everything 装在: {ed}' if ed else ''
            text = ('❌ 无 Everything 可用\n'
                    '    建议：1) 启动 Everything.exe；或 2) 下载 es.exe 放到 PATH / 指定路径' + tip)
            color = '#FF3B30'
        self.es_status_label.setText(text)
        self.es_status_label.setStyleSheet(f'color: {color};')

    def _open_download_page(self):
        QDesktopServices.openUrl(QUrl(ftrack.EVERYTHING_DOWNLOAD_URL))

    def _browse_es(self):
        start = self.es_path_edit.text().strip()
        if not start:
            start = ftrack._find_running_everything_dir() or ''
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
        if sys.platform == 'win32':
            try:
                os.startfile(str(directory))
                return
            except Exception:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

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
        missing = []
        for source, default in DEFAULT_TEXTS.items():
            expected = set(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', source))
            if not expected:
                continue
            value = self._all_texts.get(source, default)
            actual = set(re.findall(r'\{([A-Za-z_][A-Za-z0-9_]*)\}', value))
            diff = sorted(expected - actual)
            if diff:
                missing.append(f'{source} -> {", ".join(diff)}')
        return missing

    def _save(self):
        missing = self._missing_placeholders()
        if missing:
            reply = QMessageBox.question(
                self,
                '占位符缺失',
                tr('下面这些文字缺少必要占位符，保存后动态数字或名称可能无法显示：\n\n{items}\n\n仍然保存吗？',
                   items='\n'.join(missing[:8])),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        try:
            save_text_config_values(self._all_texts)
            save_custom_qss_text(self.qss_edit.toPlainText())
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
            self._editors[action_id] = editor
            table.setCellWidget(row, 1, editor)

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
        layout.addWidget(QLabel(hint))

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
        ok_btn = QPushButton('选定')
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._accept_selected)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
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
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        kind = '文件夹' if self.is_folder else '文件'
        self.setToolTip(f"{attachment['original_name']} ({kind})\n双击打开 · 右键更多")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setFixedSize(36, 44)
        icon_label.setPixmap(self._build_icon())
        icon_label.setAlignment(Qt.AlignCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 2, 0, 2)
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

        text_layout.addWidget(name_label)
        text_layout.addWidget(size_label)
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
        pix = QPixmap(36, 44)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)

        back_color = QColor("#3F8FE0")
        front_color = QColor("#5AC8FA")

        painter.setBrush(back_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 12, 32, 28, 3, 3)
        painter.drawRoundedRect(2, 8, 16, 8, 2, 2)

        painter.setBrush(front_color)
        painter.drawRoundedRect(2, 16, 32, 24, 3, 3)

        painter.setBrush(QColor(255, 255, 255, 50))
        painter.drawRoundedRect(2, 16, 32, 5, 3, 3)

        painter.end()
        return pix

    def _build_file_icon(self):
        ext = self.file_path.suffix.lower()
        color = QColor(self.EXT_COLORS.get(ext, '#8E8E93'))

        pix = QPixmap(36, 44)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, 36, 44, 6, 6)

        painter.setBrush(QColor(255, 255, 255, 60))
        poly = QPolygonF([QPointF(36 - 10, 0), QPointF(36, 10), QPointF(36 - 10, 10)])
        painter.drawPolygon(poly)

        label = ext.lstrip('.').upper() if ext else 'FILE'
        if len(label) > 4:
            label = label[:4]
        painter.setPen(QColor("#FFFFFF"))
        font = QFont(painter.font())
        font.setPointSize(8)
        font.setWeight(QFont.Bold)
        painter.setFont(font)
        painter.drawText(pix.rect().adjusted(0, 8, 0, 0), Qt.AlignCenter, label)
        painter.end()

        return pix

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
            if self.attachment.get('tracking') and self.recover_resolver:
                self._scan_recover()
                return
            msg = '该文件夹已被移动或删除。' if self.is_folder else '该附件文件已被移动或删除。'
            QMessageBox.warning(self, '路径不存在', msg)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.file_path)))

    def _reveal_in_folder(self):
        if not self._ensure_path():
            return
        reveal_in_file_manager(self.file_path)


# ============ 附件栏 ============

class AttachmentBar(QWidget):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('attachment_bar')
        self.setFixedHeight(108)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 10, 36, 14)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel('附件')
        title.setObjectName('att_section_title')
        self.hint = QLabel('拖入文件或文件夹')
        self.hint.setObjectName('att_hint')
        self.add_btn = QPushButton('+')
        self.add_btn.setObjectName('att_add_btn')
        self.add_btn.setFixedSize(24, 24)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self.browse_file)
        header.addWidget(title)
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
        self.scroll_layout = QHBoxLayout(self.scroll_content)
        self.scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_layout.setSpacing(10)
        self.scroll_layout.addStretch()

        self.empty_label = QLabel('')
        self.empty_label.setObjectName('att_empty')
        self.empty_label.setAlignment(Qt.AlignCenter)

        self.scroll.setWidget(self.scroll_content)

        layout.addLayout(header)
        layout.addWidget(self.scroll)

    def set_attachments(self, attachments, path_resolver, on_delete, recover_resolver=None):
        while self.scroll_layout.count() > 0:
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget is self.empty_label:
                widget.setParent(None)
            elif widget:
                widget.deleteLater()

        if attachments:
            for att in attachments:
                try:
                    card = AttachmentCard(att, path_resolver(att), recover_resolver=recover_resolver)
                    card.delete_requested.connect(on_delete)
                    self.scroll_layout.addWidget(card)
                except Exception:
                    pass
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
        layout.setContentsMargins(40, 28, 40, 12)
        layout.setSpacing(6)

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
        time_row.addWidget(self.time_label)
        time_row.addStretch()

        self.category_combo = QComboBox()
        self.category_combo.setObjectName('note_category_combo')
        self.category_combo.setEditable(True)
        self.category_combo.setInsertPolicy(QComboBox.NoInsert)
        self.category_combo.lineEdit().setPlaceholderText(tr('分类'))
        self.category_combo.setToolTip(tr('分类'))
        self.category_combo.currentTextChanged.connect(self._on_category_changed)
        self.category_combo.lineEdit().textChanged.connect(self._on_category_changed)
        self.format_switch = TextFormatSwitch()
        self.format_switch.changed.connect(self._on_content_format_changed)
        time_row.addWidget(self.format_switch, 0, Qt.AlignRight)
        time_row.addWidget(self.category_combo, 0, Qt.AlignRight)

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

    def _build_format_toolbar(self):
        toolbar = QHBoxLayout()
        toolbar.setObjectName('format_toolbar')
        toolbar.setContentsMargins(0, 2, 0, 0)
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
        return toolbar

    def _format_button(self, text, tooltip):
        btn = QPushButton(text)
        btn.setObjectName('format_btn')
        btn.setFixedSize(30, 28)
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

class MainWindow(QMainWindow):
    def __init__(self, storage, account=None, account_manager=None):
        super().__init__()
        self.storage = storage
        self.account = account or {}
        self.account_manager = account_manager
        self.screenshot_board = self.storage.get_screenshot_board()
        self.current_note_id = None
        self.current_note_id = self.screenshot_board['id']
        self.workspace_mode = 'screenshot'
        self._suppress_auto_select = False
        self._capture_in_progress = False
        self._settings = QSettings('FRESH', 'FRESH')

        refresh_autostart_if_needed()

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

        # 文件追踪：实时监听已跟踪附件的父目录与文件本身，捕捉编辑保存
        self._tracked_watcher = QFileSystemWatcher(self)
        self._tracked_watcher.directoryChanged.connect(self._on_tracked_dir_changed)
        self._tracked_watcher.fileChanged.connect(self._on_tracked_file_changed)
        self._refresh_pending_dirs = set()
        self._refresh_dirs_timer = QTimer(self)
        self._refresh_dirs_timer.setSingleShot(True)
        self._refresh_dirs_timer.timeout.connect(self._flush_refresh_pending_dirs)

        # 剪贴板监听：用户剪切/复制了追踪文件 → 短延后跑一次恢复
        self._clipboard_trigger_timer = QTimer(self)
        self._clipboard_trigger_timer.setSingleShot(True)
        self._clipboard_trigger_timer.timeout.connect(self._on_clipboard_settled)
        try:
            QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)
        except Exception:
            pass
        self._recent_create_match_timer = QTimer(self)
        self._recent_create_match_timer.setSingleShot(True)
        self._recent_create_match_timer.timeout.connect(self._retry_recent_shell_creates)

        # 焦点监听：回到 FRESH 时跑一次恢复
        self._focus_trigger_timer = QTimer(self)
        self._focus_trigger_timer.setSingleShot(True)
        self._focus_trigger_timer.timeout.connect(self._on_focus_settled)
        self._last_focus_recovery = 0  # 上次基于焦点触发恢复的时间戳

        # 周期性轮询：每 20 秒检查一次是否有跟踪文件失踪，有就启动后台恢复
        # 兼容 QFileSystemWatcher 漏报、U 盘热插拔、跨盘剪切等场景
        self._recovery_poll_timer = QTimer(self)
        self._recovery_poll_timer.timeout.connect(self._poll_missing_attachments)
        self._recovery_poll_timer.start(20000)

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
        self._tag_next_batch()

    def _tag_next_batch(self):
        queue = getattr(self, '_tagging_queue', None)
        if queue is None:
            return
        if not queue:
            self._setup_tracking_watchers()
            self._tagging_queue = None
            # 打标完成后启动一次自动扫描，找回所有失踪文件
            QTimer.singleShot(500, self._start_auto_recovery)
            return
        batch = queue[:5]
        self._tagging_queue = queue[5:]
        for _note, att in batch:
            try:
                if not att.get('tracking'):
                    self.storage.ensure_tracking(att)
                else:
                    self.storage.refresh_tracking_if_changed(att)
            except Exception:
                pass
        QTimer.singleShot(80, self._tag_next_batch)

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
                dirs.add(str(p.parent))
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
        affected = False
        for _note, att in self.storage.all_external_attachments():
            if not att.get('tracking'):
                continue
            p = Path(att.get('original_path', ''))
            if str(p.parent) in dirs or str(p) in dirs:
                affected = True
                try:
                    self.storage.refresh_tracking_if_changed(att)
                except Exception:
                    pass
        if affected:
            # 自动同步：重建当前视图的预览/缩略图，无需用户手动重新搜索
            try:
                self._refresh_current_workspace()
            except Exception:
                pass
            # 重新挂监听（atomic save 后 watcher 会失效）
            self._setup_tracking_watchers()
        # 不管路径比较是否命中，都跑一次 recovery —— 它内部会跳过仍在原位的，
        # 跨盘剪切（如 D: → F:）唯一靠它兜底
        try:
            self._start_auto_recovery()
        except Exception:
            pass

    def _poll_missing_attachments(self):
        """周期性兜底：watcher 漏报 / 关 FRESH 之外操作时也能找回。"""
        try:
            # 先看看有没有失踪的，没的话连 worker 都不启动
            for _note, att in self.storage.all_external_attachments():
                tr = att.get('tracking') or {}
                if not tr.get('tracking_id'):
                    continue
                if self.storage.attachment_path_matches_tracking(att):
                    continue
                p = Path(att.get('original_path', ''))
                if not p.exists():
                    self._start_auto_recovery()
                    return
        except Exception:
            pass

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
        """Shell 通知回调：检查 path1 是否匹配某个跟踪附件，匹配就改成 path2。"""
        if not path1 and not path2:
            return
        try:
            old_norm = os.path.normcase(os.path.normpath(path1)) if path1 else ''
            new_norm = os.path.normcase(os.path.normpath(path2)) if path2 else ''
        except Exception:
            return

        # 重命名/移动：path1 -> path2
        if event_code in (SHCNE_RENAMEITEM, SHCNE_RENAMEFOLDER) and old_norm and new_norm:
            self._apply_shell_move(old_norm, new_norm)
            return

        # 跨盘剪切（尤其到 exFAT/FAT 移动硬盘）常见事件顺序是：
        # 先在目标盘 CREATE，复制完成后才在源盘 DELETE。先记住目标候选，
        # 等源路径删除时再用 hash / 类型验证并采纳。
        if event_code in (SHCNE_CREATE, SHCNE_MKDIR) and old_norm:
            self._note_shell_create(old_norm)
            if self._adopt_shell_created_path(old_norm):
                return
            self._try_match_pending_delete(old_norm)
            return

        # 删除事件：可能是剪切操作的源端被清理，先记下来；如果短时间内有
        # CREATE 同名的就当作移动；否则启动一次轻量 recovery 兜底。
        if event_code in (SHCNE_DELETE, SHCNE_RMDIR) and old_norm:
            self._note_shell_delete(old_norm)
            return

        # 文件被原地编辑（atomic save 等）→ 立刻刷新当前视图
        if event_code in (SHCNE_UPDATEITEM, SHCNE_UPDATEDIR) and old_norm:
            self._maybe_refresh_for_path(old_norm)

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
                return True
        if att.get('type') == 'folder':
            return p.is_dir()
        return False

    def _note_shell_create(self, new_norm):
        """记录最近创建的路径，用于处理“先复制到目标盘、后删除源文件”的剪切流程。"""
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

    def _adopt_shell_created_path(self, new_norm):
        """用新建路径直接修复已失效的引用附件。

        这覆盖一种真实场景：FRESH 里记录的 original_path 已经旧了，用户从
        当前真实位置剪切到 F: 时，DELETE 事件路径和记录路径对不上；此时只能
        从目标盘 CREATE 事件按文件名 + 内容 hash 反向匹配。
        """
        try:
            p = Path(new_norm)
        except Exception:
            return False
        if not p.exists():
            return False

        new_base = os.path.basename(new_norm).lower()
        matches = []
        for _note, att in self.storage.all_external_attachments():
            cur = att.get('original_path', '')
            if cur and os.path.normcase(os.path.normpath(cur)) == new_norm:
                continue
            try:
                if self.storage.attachment_path_matches_tracking(att):
                    continue
            except Exception:
                pass

            tracking = att.get('tracking') or {}
            expected = (att.get('original_name') or os.path.basename(cur or '')).lower()
            if expected and expected != new_base and not tracking.get('content_hash'):
                continue
            if self._tracking_identity_matches(att, new_norm):
                matches.append(att)

        if len(matches) != 1:
            return False

        att = matches[0]
        self.storage.adopt_external_path(att, new_norm)
        try:
            self._refresh_current_workspace()
        except Exception:
            pass
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
        should_retry = False
        for item in creates:
            if now - item.get('ts', 0) > SHELL_CREATE_MATCH_WINDOW_SECONDS:
                continue
            fresh.append(item)
            if self._adopt_shell_created_path(item.get('path', '')):
                continue
            should_retry = True
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
            if self._tracking_identity_matches(att, new_norm):
                candidates.append(new_norm)
        self._recent_shell_creates = fresh
        if len(candidates) == 1:
            return candidates[0]
        return ''

    def _apply_shell_move(self, old_norm, new_norm):
        """把 old_norm 命中的跟踪附件 original_path 改成 new_norm，刷新 UI。"""
        moved = []
        for _note, att in self.storage.all_external_attachments():
            cur = att.get('original_path', '')
            if not cur:
                continue
            cur_norm = os.path.normcase(os.path.normpath(cur))
            if cur_norm == old_norm:
                self.storage.adopt_external_path(att, new_norm)
                moved.append(att)
        if not moved:
            return
        # 即时刷新预览 + 把新父目录挂进 watcher
        try:
            self._refresh_current_workspace()
        except Exception:
            pass
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
        # 只关心跟踪过的路径
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
            if not self._tracking_identity_matches(tracked_att, new_norm):
                continue
            pending.pop(old_norm, None)
            self._apply_shell_move(old_norm, new_norm)
            return

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
                if cur and os.path.normcase(os.path.normpath(cur)) == old_norm:
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
                should_recover = True

        if should_recover:
            try:
                self._start_auto_recovery()
            except Exception:
                pass
        if keep_waiting:
            self._pending_recovery_timer.start(2500)

    def _maybe_refresh_for_path(self, norm_path):
        """如果某个跟踪附件位于该路径，刷新当前 workspace（缩略图重画）。"""
        for _note, att in self.storage.all_external_attachments():
            cur = att.get('original_path', '')
            if not cur:
                continue
            cur_norm = os.path.normcase(os.path.normpath(cur))
            if cur_norm == norm_path or os.path.dirname(cur_norm) == norm_path:
                try:
                    self._refresh_current_workspace()
                except Exception:
                    pass
                return

    # ============ 窗口状态 / 快捷键 ============

    def _restore_window_state(self):
        geometry = self._settings.value('main/geometry')
        if geometry:
            try:
                self.restoreGeometry(geometry)
            except Exception:
                pass

        view = self._settings.value('main/view', 'active')
        if view not in ('active', 'archived'):
            view = 'active'
        self.view_switch.set_view(view, emit=False)

        mode = self._settings.value('main/workspace_mode', 'screenshot')
        if mode == 'text':
            self.workspace_mode = 'text'
            self.workspace_switch.set_mode('text', emit=False)
            self.new_btn.setText('＋  新建')
            self.search_input.setPlaceholderText('搜索文字和文件')
            self.list_widget.setItemDelegate(NoteListDelegate(self.list_widget))
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
        self.new_btn.setText('＋  添加截图')
        self.search_input.setPlaceholderText('搜索截图')
        self.list_widget.setItemDelegate(ScreenshotListDelegate(self.list_widget))
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
            ('browse_image',    '选择图片文件',         'Ctrl+Alt+N',        self._browse_screenshot,             None),
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
            if att:
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
            if att:
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
                            self._open_image_viewer(att['id'])
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
        # 看剪贴板里的文件有没有命中已追踪
        tracked_paths = self._tracked_path_set()
        hit_names = []
        for url in mime.urls():
            p = url.toLocalFile()
            if not p:
                continue
            norm = os.path.normcase(os.path.normpath(p))
            if norm in tracked_paths:
                hit_names.append(os.path.basename(p))
        if not hit_names:
            return
        names_str = ', '.join(hit_names[:3]) + ('...' if len(hit_names) > 3 else '')
        self.statusBar().showMessage(
            tr('监听到 {names} 被复制/剪切，3 秒后自动定位新位置...', names=names_str),
            4000,
        )
        # 2.5s 后查一次（给粘贴留时间），再 8s 后兜底再查一次（用户慢慢操作的情况）
        self._clipboard_trigger_timer.start(2500)
        QTimer.singleShot(8000, self._on_clipboard_settled)

    def _on_clipboard_settled(self):
        # 跑一次轻量恢复 — 用 Everything 几乎是瞬间
        self._start_auto_recovery()

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
        if event.type() == QEvent.ActivationChange and self.isActiveWindow():
            # 切回 FRESH：30 秒内只触发一次，避免来回切换刷屏
            import time as _time
            now = _time.time()
            if now - self._last_focus_recovery > 30:
                self._last_focus_recovery = now
                self._focus_trigger_timer.start(400)

    def _on_focus_settled(self):
        # 切回 FRESH 时跑：1) 刷新所有路径仍在原位的追踪 (atomic save 检测)
        #               2) 对失踪的跑一次 Everything 恢复
        for _note, att in self.storage.all_external_attachments():
            if att.get('tracking'):
                try:
                    self.storage.refresh_tracking_if_changed(att)
                except Exception:
                    pass
        self._start_auto_recovery()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧栏
        sidebar = QWidget()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(280)

        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 16, 12, 12)
        sidebar_layout.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)
        self.new_btn = QPushButton('＋  添加截图')
        self.new_btn.setObjectName('new_button')
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.clicked.connect(self._new_primary_action)
        self.more_btn = QPushButton('⋯')
        self.more_btn.setObjectName('more_button')
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setFixedSize(36, 36)
        self.more_btn.setToolTip('更多')
        self.more_btn.clicked.connect(self._show_more_menu)
        top_row.addWidget(self.new_btn, 1)
        top_row.addWidget(self.more_btn)

        self.workspace_switch = ModeSwitch()
        self.workspace_switch.text_btn.setText('文字文件')
        self.workspace_switch.shot_btn.setText('全截图')
        self.workspace_switch.set_mode('screenshot', emit=False)
        self.workspace_switch.changed.connect(self._on_workspace_changed)

        self.search_input = QLineEdit()
        self.search_input.setObjectName('search_box')
        self.search_input.setPlaceholderText('搜索截图')
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(lambda _: self._refresh_current_workspace())
        self.search_input.installEventFilter(self)

        self.view_switch = ViewSwitch()
        self.view_switch.changed.connect(self._on_view_changed)

        self.archive_category_filter = QComboBox()
        self.archive_category_filter.setObjectName('timeline_category_filter')
        self.archive_category_filter.addItem('全部分类', '')
        self.archive_category_filter.currentIndexChanged.connect(lambda _: self._refresh_current_workspace())

        self.list_widget = QListWidget()
        self.list_widget.setObjectName('note_list')
        self.list_widget.setMouseTracking(True)
        self.list_widget.setItemDelegate(ScreenshotListDelegate(self.list_widget))
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
        self.timeline_btn = QPushButton('时间线')
        self.timeline_btn.setObjectName('timeline_btn')
        self.timeline_btn.setCursor(Qt.PointingHandCursor)
        self.timeline_btn.setFocusPolicy(Qt.NoFocus)
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
        self.screenshot_grid.file_dropped.connect(self._on_file_dropped)
        self.screenshot_grid.image_pasted.connect(self._on_image_pasted)
        self.screenshot_grid.open_requested.connect(self._open_image_viewer)
        self.screenshot_grid.delete_requested.connect(self._on_attachment_delete)
        self.screenshot_grid.archive_toggled.connect(self._on_attachment_archive_toggled)
        self.screenshot_grid.memo_changed.connect(self._on_attachment_memo_changed)

        self.attachment_bar = AttachmentBar()
        self.attachment_bar.file_dropped.connect(self._on_file_dropped)

        self.empty_state = EmptyState()
        self.empty_state.primary_action.connect(self._empty_primary_action)
        self.empty_state.secondary_action.connect(self._empty_secondary_action)

        self.right_stack = QStackedWidget()
        self.right_stack.setObjectName('right_stack')
        self.right_stack.addWidget(self.screenshot_grid)
        self.right_stack.addWidget(self.editor)
        self.right_stack.addWidget(self.empty_state)

        right_layout.addWidget(self.right_stack, 1)
        right_layout.addWidget(self.attachment_bar)

        main_layout.addWidget(sidebar)
        main_layout.addWidget(right, 1)

    # ---- 列表 ----
    def _refresh_current_workspace(self):
        if self.view_switch.current_view() == 'archived':
            self._populate_archive_items()
            return
        if self.workspace_mode == 'screenshot':
            self.search_input.setPlaceholderText('搜索截图')
            self._refresh_screenshot_board()
        else:
            self.search_input.setPlaceholderText('搜索文字和文件')
            self._populate_list()
            note = self.storage.get_note(self.current_note_id) if self.current_note_id else None
            if note and not note.get('deleted'):
                self._refresh_attachments_for(note)

    def _on_workspace_changed(self, mode):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now(refresh_list=False)
        self.workspace_mode = mode
        self.current_note_id = None
        self.list_widget.clearSelection()
        if self.view_switch.current_view() == 'archived':
            self.new_btn.setText('＋  添加截图' if mode == 'screenshot' else '＋  新建')
            self.search_input.setPlaceholderText('搜索归档内容')
            self.editor.clear()
            self.attachment_bar.set_attachments([], self.storage.path_for, lambda x: None)
            self.attachment_bar.setVisible(False)
            self._populate_archive_items()
            return
        if mode == 'screenshot':
            self.new_btn.setText('＋  添加截图')
            self.search_input.setPlaceholderText('搜索截图')
            self.list_widget.setItemDelegate(ScreenshotListDelegate(self.list_widget))
            self.current_note_id = self.screenshot_board['id']
            self._refresh_screenshot_board()
            return

        self.new_btn.setText('＋  新建')
        self.search_input.setPlaceholderText('搜索文字和文件')
        self.archive_category_filter.setVisible(False)
        self.list_widget.setItemDelegate(NoteListDelegate(self.list_widget))
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

    def _refresh_archive_category_filter(self):
        cur = self.archive_category_filter.currentData() or ''
        self.archive_category_filter.blockSignals(True)
        self.archive_category_filter.clear()
        self.archive_category_filter.addItem('全部分类', '')
        for category in self.storage.all_categories():
            self.archive_category_filter.addItem(category, category)
        idx = 0
        for i in range(self.archive_category_filter.count()):
            if self.archive_category_filter.itemData(i) == cur:
                idx = i
                break
        self.archive_category_filter.setCurrentIndex(idx)
        self.archive_category_filter.blockSignals(False)

    def _refresh_screenshot_board(self, preferred_attachment_id=None):
        if not hasattr(self, 'screenshot_grid'):
            return
        if self.view_switch.current_view() == 'archived':
            key = f'attachment:{preferred_attachment_id}' if preferred_attachment_id else ''
            self._populate_archive_items(selected_key=key)
            return
        self.search_input.setPlaceholderText('搜索截图')
        self.list_widget.setItemDelegate(ScreenshotListDelegate(self.list_widget))
        selected_id = preferred_attachment_id
        if not selected_id:
            item = self.list_widget.currentItem()
            current_att = item.data(Qt.UserRole) if item else None
            selected_id = current_att.get('id') if current_att else None
        view = self.view_switch.current_view()
        self._refresh_archive_category_filter()
        self.archive_category_filter.setVisible(view == 'archived')
        category = self.archive_category_filter.currentData() or '' if view == 'archived' else ''
        search = self.search_input.text().strip()
        items = self.storage.screenshot_items(view=view, category=category, search=search)
        active_count, archived_count = self.storage.screenshot_counts()
        self.view_switch.set_counts(active_count, self._archive_total_count())

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for att in items:
            item = QListWidgetItem()
            item.setText(att.get('archive_content') or att.get('memo') or att.get('original_name') or '截图')
            item.setData(Qt.UserRole, att)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        if selected_id and self._select_attachment_by_id(selected_id):
            pass
        elif self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        self.screenshot_grid.set_attachments(items, self.storage.path_for)
        self.right_stack.setCurrentWidget(self.screenshot_grid)
        self.attachment_bar.setVisible(False)
        self.current_note_id = self.screenshot_board['id']

    def _active_note_count(self):
        return sum(
            1 for note in self.storage.notes
            if not note.get('system') and not note.get('deleted') and not note.get('archived')
        )

    def _archive_total_count(self):
        return len(self.storage.all_timeline_items())

    def _populate_archive_items(self, selected_key=''):
        if not hasattr(self, 'list_widget'):
            return
        if not selected_key:
            item = self.list_widget.currentItem()
            selected_key = archive_item_key(item.data(Qt.UserRole)) if item else ''

        self.list_widget.setItemDelegate(ArchiveListDelegate(self.list_widget))
        self._refresh_archive_category_filter()
        self.archive_category_filter.setVisible(True)
        self.search_input.setPlaceholderText('搜索归档内容')

        category = self.archive_category_filter.currentData() or ''
        search = self.search_input.text().strip().lower()
        items = self.storage.all_timeline_items(category=category)
        if search:
            items = [item for item in items if search in archive_item_search_text(item)]

        active_count = self.storage.screenshot_counts()[0] if self.workspace_mode == 'screenshot' else self._active_note_count()
        self.view_switch.set_counts(active_count, self._archive_total_count())

        image_attachments = [
            item.get('attachment') for item in items
            if item.get('kind') == 'attachment' and is_image_attachment(item.get('attachment') or {})
        ]
        image_attachments = [att for att in image_attachments if att]
        self.screenshot_grid.set_attachments(image_attachments, self.storage.path_for)

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
        self.search_input.setPlaceholderText('搜索文字和文件')
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        self.list_widget.setItemDelegate(NoteListDelegate(self.list_widget))
        search = self.search_input.text().strip().lower()
        view = self.view_switch.current_view()
        self._refresh_archive_category_filter()
        self.archive_category_filter.setVisible(view == 'archived')
        category = self.archive_category_filter.currentData() or '' if view == 'archived' else ''
        active_count = 0
        archived_count = 0
        for note in self.storage.notes:
            if note.get('system'):
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
            and bool(self.archive_category_filter.currentData() or '')
        )
        return has_search or has_category

    def _sync_empty_state(self):
        if not hasattr(self, 'right_stack'):
            return
        if self.view_switch.current_view() != 'archived' and self.workspace_mode == 'screenshot':
            self.right_stack.setCurrentWidget(self.screenshot_grid)
            self.attachment_bar.setVisible(False)
            self.current_note_id = self.screenshot_board['id']
            return
        current_note = self.storage.get_note(self.current_note_id) if self.current_note_id else None
        has_current = bool(current_note and not current_note.get('deleted'))
        if has_current:
            self.right_stack.setCurrentWidget(self.editor)
            return

        filtered = self._has_active_filters()
        category = self.archive_category_filter.currentData() or '' if self.view_switch.current_view() == 'archived' else ''
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
        if self.archive_category_filter.currentIndex() > 0:
            self.archive_category_filter.blockSignals(True)
            self.archive_category_filter.setCurrentIndex(0)
            self.archive_category_filter.blockSignals(False)
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
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.UserRole)
            att = data.get('attachment') if isinstance(data, dict) and data.get('kind') == 'attachment' else data
            if att and att.get('id') == attachment_id:
                self.list_widget.setCurrentItem(item)
                return True
        return False

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
                if is_image_attachment(att):
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
                self._open_image_viewer(att['id'])
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
                self._open_image_viewer(att['id'])
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
                self.screenshot_grid.set_attachments(self._archive_image_attachments_from_list(), self.storage.path_for)
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
            view = menu.addAction('查看大图')
            open_note = menu.addAction('打开所属备忘录')
            unarchive = menu.addAction('取消归档照片')
            menu.addSeparator()
            delete = menu.addAction(tr('删除截图'))
            action = menu.exec(global_pos)
            if action == view:
                self._open_image_viewer(att.get('id'))
            elif action == open_note:
                self._load_note_by_id(note.get('id'))
            elif action == unarchive:
                self.storage.update_attachment(note.get('id'), att.get('id'), archived=False, archived_at='')
                self._refresh_current_workspace()
            elif action == delete:
                self._on_attachment_delete(att.get('id'))
            return

        note = data.get('note') or {}
        open_note = menu.addAction('打开备忘录')
        unarchive = menu.addAction('取消归档')
        menu.addSeparator()
        delete = menu.addAction('删除')
        action = menu.exec(global_pos)
        if action == open_note:
            self._load_note_by_id(note.get('id'))
        elif action == unarchive:
            self._toggle_archive(note.get('id'))
        elif action == delete:
            self._delete_note(note.get('id'))

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
            self._capture_screenshot_region()
        else:
            self.create_new_note()

    def _prepare_screenshot_workspace(self, clear_filters=False):
        if self.workspace_mode != 'screenshot' and self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        if self.workspace_mode != 'screenshot':
            self.workspace_mode = 'screenshot'
            self.workspace_switch.set_mode('screenshot', emit=False)
            self.new_btn.setText('＋  添加截图')
            self.search_input.setPlaceholderText('搜索截图')
            self.list_widget.setItemDelegate(ScreenshotListDelegate(self.list_widget))
            self.current_note_id = self.screenshot_board['id']
        if clear_filters:
            if self.view_switch.current_view() != 'active':
                self.view_switch.set_view('active', emit=False)
            if self.search_input.text():
                self.search_input.blockSignals(True)
                self.search_input.clear()
                self.search_input.blockSignals(False)
            if self.archive_category_filter.currentIndex() > 0:
                self.archive_category_filter.blockSignals(True)
                self.archive_category_filter.setCurrentIndex(0)
                self.archive_category_filter.blockSignals(False)
        self.archive_category_filter.setVisible(self.view_switch.current_view() == 'archived')
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
            pixmap, virtual = grab_virtual_desktop_pixmap()
            if pixmap is None or pixmap.isNull() or virtual.isEmpty():
                restore_after_capture()
                if quiet_failure and getattr(self, 'tray_icon', None):
                    self.tray_icon.showMessage('框选截图失败', '无法获取屏幕截图。', QSystemTrayIcon.Warning, 3000)
                else:
                    QMessageBox.warning(self, '框选截图失败', '无法获取屏幕截图。')
                return

            dlg = RegionCaptureOverlay(pixmap, virtual)
            accepted = dlg.exec() == QDialog.Accepted
            result_path = dlg.result_path
            restore_after_capture()
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
            self._add_attachment_to_current(file_path, copy=False)

    def _quick_new_text_note(self):
        self._show_window_from_tray()
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
        view = menu.addAction('查看大图')
        archive = menu.addAction('取消归档照片' if attachment.get('archived') else '归档照片')
        menu.addSeparator()
        delete = menu.addAction(tr('删除截图'))
        action = menu.exec(global_pos)
        if action == view:
            self._open_image_viewer(attachment['id'])
        elif action == archive:
            self._on_attachment_archive_toggled(attachment['id'])
        elif action == delete:
            self._on_attachment_delete(attachment['id'])

    def create_new_note(self):
        self.workspace_mode = 'text'
        self.workspace_switch.set_mode('text', emit=False)
        self.list_widget.setItemDelegate(NoteListDelegate(self.list_widget))
        self.new_btn.setText('＋  新建')
        self.search_input.setPlaceholderText('搜索文字和文件')
        self.archive_category_filter.setVisible(False)
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
        self._select_first_or_create()
        self._sync_empty_state()
        self.statusBar().showMessage(tr('已移到最近删除'), 4000)

    def _choose_archive_category(self, current=''):
        current = (current or '').strip()
        categories = self.storage.all_categories()
        if current and current not in categories:
            categories.append(current)
            categories.sort()
        if categories:
            index = categories.index(current) if current in categories else 0
            category, ok = QInputDialog.getItem(
                self,
                '归档分类',
                '选择或输入分类:',
                categories,
                index,
                True,
            )
        else:
            category, ok = QInputDialog.getText(
                self,
                '归档分类',
                '输入分类:',
                QLineEdit.Normal,
                current,
            )
        if not ok:
            return None
        category = (category or '').strip()
        if not category:
            QMessageBox.information(self, '需要分类', '请填写归档分类。')
            return None
        return category

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
            self._save_current_now()

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

    def _select_first_or_create(self):
        if self.list_widget.count() > 0:
            first = self.list_widget.item(0).data(Qt.UserRole)
            if isinstance(first, dict) and first.get('kind'):
                self._select_archive_item_by_key(archive_item_key(first))
            elif first and first.get('id'):
                self._select_note_by_id(first['id'])
        elif self.view_switch.current_view() == 'active':
            self.create_new_note()
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

    def _refresh_editor_categories(self):
        if hasattr(self, 'editor'):
            self.editor.set_categories(self.storage.all_categories())

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
            QTimer.singleShot(0, self._refresh_current_workspace)
            return scanned_path
        new_path, changed = self.storage.resolve_external_path(attachment, scan=False)
        if new_path and Path(new_path).exists():
            if changed:
                QTimer.singleShot(0, self._refresh_current_workspace)
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
        att_id = attachment['id']
        for s in self._targeted_scans:
            if s['att_id'] == att_id:
                if s.get('dlg'):
                    s['dlg'].raise_()
                return

        name = attachment.get('original_name', '')
        size_hint = tracking.get('size_snapshot') or attachment.get('size')

        worker = FtrackScanWorker(
            tracking, name_fallback=name,
            scan_settings=self.storage.scan_settings,
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
        found = result.get('path') if result else None
        if not found:
            candidates = (result or {}).get('candidates') or []
            if not candidates:
                QMessageBox.warning(self, '未找到', f'未在磁盘上找到与 "{name}" 匹配的文件。')
                return
            if len(candidates) == 1:
                found = candidates[0]
            else:
                picker = CandidatePickerDialog(candidates, name, size_hint=size_hint, parent=self)
                if picker.exec() != QDialog.Accepted:
                    return
                found = picker.selected_path
        self.storage.adopt_external_path(att, found)
        if note and note.get('id') == self.current_note_id:
            self._refresh_attachments_for(note)
        QMessageBox.information(self, '已找到', f'文件当前位置:\n{found}')

    def _start_auto_recovery(self):
        """启动后扫一遍所有失踪的 tracked 附件，找回所有的。"""
        self._ensure_scan_state()
        if self._auto_recovery_worker and self._auto_recovery_worker.isRunning():
            return
        tag_to_name = {}
        tag_to_att = {}
        tag_to_tracking = {}
        drive_hints = []
        changed_without_worker = False
        for _note, att in self.storage.all_external_attachments():
            tr = att.get('tracking') or {}
            tag = tr.get('tracking_id')
            if not tag:
                continue
            old_name = att.get('original_name', '')
            if self.storage.attachment_path_matches_tracking(att):
                if att.get('original_name', '') != old_name:
                    changed_without_worker = True
                continue
            new_path, changed = self.storage.resolve_external_path(att, scan=False)
            if new_path and Path(new_path).exists():
                if changed:
                    changed_without_worker = True
                continue
            tag_to_name[tag] = att.get('original_name', '')
            tag_to_att[tag] = att['id']
            tag_to_tracking[tag] = tr
            hint = tr.get('drive_hint')
            if hint and hint not in drive_hints:
                drive_hints.append(hint)
        if not tag_to_name:
            if changed_without_worker:
                try:
                    self._refresh_current_workspace()
                except Exception:
                    pass
                if hasattr(self, '_tracked_watcher'):
                    self._setup_tracking_watchers()
            return

        worker = AutoRecoveryWorker(
            tag_to_name, tag_to_tracking=tag_to_tracking, drive_hints=drive_hints,
            scan_settings=self.storage.scan_settings, parent=self,
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
            self._auto_recovery_worker = None
            self._auto_recovered_tags = set()
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
        att_id = tag_to_att.get(tag)
        if not att_id:
            return
        if not hasattr(self, '_auto_recovered_tags'):
            self._auto_recovered_tags = set()
        self._auto_recovered_tags.add(tag)
        note, att = self.storage.find_attachment(att_id)
        if not att:
            return
        self.storage.adopt_external_path(att, path)
        if note and note.get('id') == self.current_note_id:
            self._refresh_attachments_for(note)
        else:
            # 即使当前没看着这条笔记，也把新位置的父目录挂上监听，
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
        new_state = not bool(att.get('archived', False))
        archive_content = att.get('memo', '') or ''
        archive_category = att.get('archive_category', '') or ''
        if new_state:
            dlg = ArchivePhotoDialog(att, self.storage.path_for(att), self.storage.all_categories(), self)
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
        note, att = self.storage.find_attachment(attachment_id)
        if att and not att.get('deleted') and not (note and note.get('deleted')):
            path = self._path_for_opening_attachment(att)
            if not path:
                if att.get('tracking'):
                    self._start_targeted_scan(att)
                QMessageBox.warning(self, '图片不存在', '该图片已被移动或删除。')
                return
            dlg = ImageViewerDialog(str(path), self)
            dlg.exec()
            return
        if not self.current_note_id:
            return
        for note in self.storage.notes:
            if note.get('deleted'):
                continue
            if note['id'] != self.current_note_id:
                continue
            for att in note.get('attachments', []) or []:
                if att.get('deleted'):
                    continue
                if att.get('id') == attachment_id:
                    path = self._path_for_opening_attachment(att)
                    if not path:
                        if att.get('tracking'):
                            self._start_targeted_scan(att)
                        QMessageBox.warning(self, '图片不存在', '该图片已被移动或删除。')
                        return
                    dlg = ImageViewerDialog(str(path), self)
                    dlg.exec()
                    return

    def _on_file_dropped(self, file_path):
        self._add_attachment_to_current(file_path, copy=False)

    def _on_image_pasted(self, file_path):
        self._add_attachment_to_current(file_path, copy=True)

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

        attachment = self.storage.add_screenshot(file_path, copy=copy)
        if not attachment:
            QMessageBox.warning(self, '添加失败', '只能添加图片截图。')
            return
        self._refresh_screenshot_board(preferred_attachment_id=attachment.get('id'))

    def _on_attachment_delete(self, attachment_id):
        if self.view_switch.current_view() == 'archived':
            note, _att = self.storage.find_attachment(attachment_id)
            if note and not note.get('deleted'):
                self.storage.remove_attachment(note.get('id'), attachment_id)
                self._refresh_current_workspace()
                self.statusBar().showMessage(tr('截图已移到最近删除'), 4000)
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

        self.storage.remove_screenshot(attachment_id)
        self._refresh_screenshot_board(preferred_attachment_id=attachment_id)
        self.statusBar().showMessage(tr('截图已移到最近删除'), 4000)

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
        browse_screenshot_action = menu.addAction('选择图片文件...')
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

    def _show_scan_settings(self):
        dlg = ScanSettingsDialog(self.storage, parent=self)
        dlg.exec()

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

    def _switch_account(self, account, crypter):
        if not self.account_manager:
            return
        if self.save_timer.isActive():
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
        self.storage = Storage(
            app_dir=self.account_manager.account_dir(account),
            crypter=crypter,
            migrate_apple=False,
        )
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
        self.statusBar().showMessage(f'已进入 {account.get("name") or "我的账户"}', 3000)

    def _show_timeline(self):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        dlg = TimelineDialog(self.storage, self)
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
        for _note, att in self.storage.all_external_attachments():
            tr = att.get('tracking') or {}
            if not tr.get('tracking_id'):
                continue
            if self.storage.attachment_path_matches_tracking(att):
                continue
            p = Path(att.get('original_path', ''))
            if not p.exists():
                missing.append(att.get('original_name', '(未命名)'))
        if not missing:
            QMessageBox.information(self, '一切正常', '所有跟踪的文件都在原位，无需查找。')
            return
        preview = '\n'.join(missing[:8])
        more = f'\n... 共 {len(missing)} 个' if len(missing) > 8 else ''
        QMessageBox.information(
            self, '开始查找',
            f'有 {len(missing)} 个文件已被移动或暂时找不到，'
            f'正在后台扫描所有盘（含 U 盘 / 外接硬盘）寻找。\n\n{preview}{more}'
        )
        self._start_auto_recovery()

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
        self.list_widget.setItemDelegate(NoteListDelegate(self.list_widget))
        self.new_btn.setText('＋  新建')
        self.search_input.setPlaceholderText('搜索文字和文件')
        self.view_switch.set_view('archived', emit=False)
        self.archive_category_filter.setVisible(True)
        if self.search_input.text():
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
        self._refresh_archive_category_filter()
        if self.archive_category_filter.currentIndex() > 0:
            self.archive_category_filter.blockSignals(True)
            self.archive_category_filter.setCurrentIndex(0)
            self.archive_category_filter.blockSignals(False)

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
        if sys.platform == 'win32':
            try:
                os.startfile(str(directory))
                return
            except Exception:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

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
        dlg.setFixedWidth(390)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(12)

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
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
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

    def _write_backup_data(self, zf, scope):
        notes_payload = json.dumps(self.storage.notes, ensure_ascii=False, indent=2).encode('utf-8')
        zf.writestr('data.json', self.storage.crypter.encrypt_bytes(notes_payload))
        manifest = {
            'app': 'FRESH',
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
        zf.writestr(
            'backup_manifest.json',
            json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'),
        )

    def _backup_stored_names(self, include_files=False, include_images=False):
        if include_files and include_images:
            return None
        names = set()
        for note in self.storage.notes:
            for att in note.get('attachments', []) or []:
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

    def _write_backup_blob_dir(self, zf, source_dir, zip_prefix, stored_names=None):
        source_dir = Path(source_dir)
        if not source_dir.exists():
            return 0
        count = 0
        allowed_names = set(stored_names) if stored_names is not None else None
        for f in source_dir.iterdir():
            if not f.is_file() or f.name.startswith('.'):
                continue
            if allowed_names is not None and f.name not in allowed_names:
                continue
            try:
                blob = f.read_bytes()
                if not self.storage.crypter.is_encrypted(blob):
                    blob = self.storage.crypter.encrypt_bytes(blob)
                zf.writestr(f'{zip_prefix}/{f.name}', blob)
                count += 1
            except Exception:
                pass
        return count

    def _safe_archive_name(self, name, fallback='未命名'):
        value = (name or fallback or '未命名').replace('\\', '/').strip('/')
        if not value:
            return fallback
        return value.split('/')[-1] or fallback

    def _write_external_references(self, zf, include_folders=False, include_files=False, include_images=False):
        missing = []
        count = 0
        for note in self.storage.notes:
            for att in note.get('attachments', []) or []:
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
                    same_identity = self.storage.attachment_path_matches_tracking(att)
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

        default_name = f'fresh_backup_{scope["id"]}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip'
        file_path, _ = QFileDialog.getSaveFileName(
            self, '导出备份', default_name, 'Zip 压缩包 (*.zip)'
        )
        if not file_path:
            return

        try:
            missing = []
            local_count = 0
            trash_count = 0
            external_count = 0
            account_folder_count = 0
            with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                self._write_backup_data(zf, scope)
                include_files = bool(scope.get('include_files'))
                include_images = bool(scope.get('include_images'))
                include_folders = bool(scope.get('include_folders'))
                stored_names = self._backup_stored_names(
                    include_files=include_files,
                    include_images=include_images,
                )
                local_count = self._write_backup_blob_dir(
                    zf, self.storage.attachments_dir, 'attachments', stored_names
                )
                trash_count = self._write_backup_blob_dir(
                    zf, self.storage.trash_dir, 'trash', stored_names
                )

                external_count, missing = self._write_external_references(
                    zf,
                    include_folders=include_folders,
                    include_files=include_files,
                    include_images=include_images,
                )

                if scope.get('account_folder'):
                    account_folder_count = self._write_account_folder_snapshot(zf, file_path)

            included = ['加密文字数据']
            if local_count:
                included.append(f'本地附件/截图 {local_count} 个')
            if trash_count:
                included.append(f'最近删除附件 {trash_count} 个')
            if external_count:
                included.append(f'引用文件/文件夹内容 {external_count} 个')
            if account_folder_count:
                included.append(f'账户完整文件夹快照 {account_folder_count} 个文件')

            msg = f'{scope["label"]}已导出到:\n{file_path}\n\n包含: ' + ' · '.join(included)
            msg += '\n\n未打包的外部引用仍保留原路径和追踪记录。'
            if missing:
                preview = '\n'.join(missing[:5])
                more = f'\n... 共 {len(missing)} 个' if len(missing) > 5 else ''
                msg += f'\n\n以下 {len(missing)} 个引用源已不存在,未打包:\n{preview}{more}'
            QMessageBox.information(self, '导出成功', msg)
        except Exception as e:
            QMessageBox.critical(self, '导出失败', f'导出过程中出错:\n{e}')

    def _import_data(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, '导入备份', '', 'Zip 压缩包 (*.zip);;所有文件 (*.*)'
        )
        if not file_path:
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

        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()

        imported_dir = self.storage.app_dir / 'imported'

        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                if 'data.json' not in names:
                    raise ValueError('备份文件中缺少 data.json')
                with zf.open('data.json') as f:
                    raw_data = f.read()
                if self.storage.crypter.is_encrypted(raw_data):
                    raw_data = self.storage.crypter.decrypt_bytes(raw_data)
                imported_notes = json.loads(raw_data.decode('utf-8'))
                if not isinstance(imported_notes, list):
                    raise ValueError('备份文件格式错误')

                if mode == 'replace':
                    for f in self.storage.attachments_dir.iterdir():
                        if f.is_file():
                            try:
                                f.unlink()
                            except Exception:
                                pass
                    if imported_dir.exists():
                        shutil.rmtree(imported_dir, ignore_errors=True)
                    self.storage.notes = []

                imported_dir.mkdir(parents=True, exist_ok=True)

                # 解压 attachments/ (复制类型) —— 入库时重新加密
                for name in names:
                    if name.startswith('attachments/') and not name.endswith('/'):
                        rel = name[len('attachments/'):]
                        if not rel:
                            continue
                        target = self.storage.attachments_dir / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as src:
                            raw = src.read()
                        if self.storage.crypter.is_encrypted(raw):
                            payload = raw
                        else:
                            payload = self.storage.crypter.encrypt_bytes(raw)
                        target.write_bytes(payload)

                # 解压 external/<att_id>/... 到 imported/<att_id>/...
                external_present = set()
                for name in names:
                    if not name.startswith('external/'):
                        continue
                    parts = name.split('/', 2)
                    if len(parts) < 3 or not parts[1]:
                        continue
                    att_id, rest = parts[1], parts[2]
                    external_present.add(att_id)
                    if name.endswith('/'):
                        (imported_dir / att_id / rest).mkdir(parents=True, exist_ok=True)
                        continue
                    target = imported_dir / att_id / rest
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as src, open(target, 'wb') as dst:
                        dst.write(src.read())

                # 把已还原的引用类型附件路径,重定向到本地 imported 目录
                redirected = 0
                for note in imported_notes:
                    for att in note.get('attachments', []) or []:
                        t = att.get('type')
                        if t in ('file_ref', 'folder') and att.get('id') in external_present:
                            new_path = imported_dir / att['id'] / att.get('original_name', '')
                            att['original_path'] = str(new_path)
                            redirected += 1

                screenshot_board = self.storage.get_screenshot_board()
                existing_ids = {n['id'] for n in self.storage.notes}
                for note in imported_notes:
                    if note.get('id') == SCREENSHOT_BOARD_ID:
                        existing_att_ids = {
                            att.get('id')
                            for att in screenshot_board.get('attachments', []) or []
                        }
                        for att in note.get('attachments', []) or []:
                            if att.get('id') in existing_att_ids:
                                att['id'] = uuid.uuid4().hex
                            screenshot_board.setdefault('attachments', []).append(att)
                        screenshot_board['updated_at'] = datetime.now().isoformat()
                        continue
                    if mode == 'merge' and note.get('id') in existing_ids:
                        note['id'] = uuid.uuid4().hex
                    self.storage.notes.append(note)

                self.storage.sort_notes()
                self.storage.save()

                has_app = any(n.startswith('app/') for n in names)

            self.current_note_id = None
            self.editor.clear()
            self.screenshot_board = self.storage.get_screenshot_board()
            self.current_note_id = self.screenshot_board['id']
            self._refresh_screenshot_board()

            extra = ''
            if redirected:
                extra += f'\n· {redirected} 个引用文件/文件夹已还原到本地'
            if has_app:
                extra += '\n· 备份中包含软件源码 (位于 zip 内 app/ 目录,需手动解压使用)'
            QMessageBox.information(
                self, '导入成功',
                f'已导入 {len(imported_notes)} 条备忘录。{extra}'
            )
        except Exception as e:
            QMessageBox.critical(self, '导入失败', f'导入过程中出错:\n{e}')

    def _open_data_folder(self):
        path = self.storage.app_dir
        if sys.platform == 'win32':
            try:
                os.startfile(str(path))
                return
            except Exception:
                pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, event):
        if self.save_timer.isActive():
            self.save_timer.stop()
            self._save_current_now()
        self._save_window_state()
        # 关闭按钮 → 隐藏到托盘（除非用户主动选了退出）
        if not getattr(self, '_real_quit', False) and getattr(self, 'tray_icon', None) and self.tray_icon.isVisible():
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
        show_action.triggered.connect(self._show_window_from_tray)
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
        size = 64
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # 圆角方块底色
        painter.setBrush(QColor('#34C759'))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(2, 2, size - 4, size - 4, 12, 12)
        # F 字母
        painter.setPen(QColor('#FFFFFF'))
        font = QFont(painter.font())
        font.setPointSize(36)
        font.setWeight(QFont.Bold)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, 'F')
        painter.end()
        return QIcon(pix)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._show_window_from_tray()

    def _show_window_from_tray(self):
        if self.isMinimized():
            self.showNormal()
        else:
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
        sock.write(b'show')
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
        self.setFixedWidth(390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(16)

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
        self.setFixedWidth(390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(12)

        label = QLabel(title)
        label.setObjectName('account_title_small')
        layout.addWidget(label)

        self.password_edit = QLineEdit()
        self.password_edit.setObjectName('account_field')
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText('新密码')
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
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
        layout.addLayout(row)

    def _accept(self):
        password = self.password_edit.text()
        confirm = self.confirm_edit.text()
        if password != confirm:
            self.error_label.setText('两次输入不一致')
            self.confirm_edit.selectAll()
            self.confirm_edit.setFocus()
            return
        if len(password) < 6:
            self.error_label.setText('密码至少 6 位')
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
        self.setFixedWidth(390)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 24)
        layout.setSpacing(12)

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
        row.addWidget(cancel_btn)
        row.addWidget(ok_btn)
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
            if len(password) < 6:
                self.error_label.setText('密码至少 6 位')
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
        self.setFixedWidth(430)

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

    def _set_password(self):
        dlg = PasswordSetupDialog('修改密码' if self.manager.account_has_password(self.current_account) else '设置密码', self)
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self.current_account, self.current_crypter = self.manager.set_account_password(
                self.current_account,
                self.current_crypter,
                dlg.password,
            )
            self.accept()
        except AccountError as exc:
            QMessageBox.warning(self, '账户', str(exc))
        except Exception as exc:
            QMessageBox.critical(self, '账户', f'设置密码失败:\n{exc}')

    def _clear_password(self):
        reply = QMessageBox.question(
            self,
            '移除密码',
            '移除后，这个账户打开时不需要输入密码。',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.current_account, self.current_crypter = self.manager.clear_account_password(
                self.current_account,
                self.current_crypter,
            )
            self.accept()
        except AccountError as exc:
            QMessageBox.warning(self, '账户', str(exc))
        except Exception as exc:
            QMessageBox.critical(self, '账户', f'移除密码失败:\n{exc}')

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
    # 单实例：先用 QLockFile 抢锁，再尝试通知已有实例显示窗口
    runtime_dir = QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation) or tempfile.gettempdir()
    Path(runtime_dir).mkdir(parents=True, exist_ok=True)
    lock_file = QLockFile(str(Path(runtime_dir) / 'FRESH.lock'))
    lock_file.setStaleLockTime(0)
    if not lock_file.tryLock(100):
        # 已有实例：让它显示出来再退出
        _activate_running_instance()
        return

    app = QApplication(sys.argv)
    app.setApplicationName('FRESH')
    app.setOrganizationName('FRESH')
    ensure_custom_files()
    install_text_overrides(app)
    app.setStyleSheet(customized_stylesheet(STYLE))
    # 关闭窗口后不退出应用（保留在系统托盘）
    app.setQuitOnLastWindowClosed(False)

    account_manager = AccountManager()
    account, crypter = select_start_account(account_manager)
    if not account or not crypter:
        return

    storage = Storage(
        app_dir=account_manager.account_dir(account),
        crypter=crypter,
        migrate_apple=False,
    )
    window = MainWindow(storage, account=account, account_manager=account_manager)
    window.show()

    # 监听本地 socket，让后续启动的实例可以唤起窗口
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server = QLocalServer()
    server.listen(SINGLE_INSTANCE_KEY)

    def _on_new_connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        sock.readyRead.connect(lambda: sock.readAll())
        sock.disconnected.connect(sock.deleteLater)
        window._show_window_from_tray()

    server.newConnection.connect(_on_new_connection)
    app._single_instance_server = server  # 保活引用
    app._single_instance_lock = lock_file

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
