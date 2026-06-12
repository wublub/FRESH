"""本地数据存储 - JSON 文件 + 附件目录"""
import atexit
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import ftrack
from app_paths import resolve_data_root
from crypter import MAGIC, Crypter

SCREENSHOT_BOARD_ID = '__screenshot_board__'
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg', '.ico'}

DEFAULT_SCAN_SETTINGS = {
    'es_path': '',          # es.exe 手动路径，空 = 自动检测
    'use_everything': True, # 检测到 es.exe 时是否启用
    'scan_roots': [],       # 自定义扫描根目录列表，空 = 全部 NTFS 盘
}

# 本进程内仍在使用的解密缓存目录（切换账户等场景会同时存在多个 Storage）
_ACTIVE_CACHE_DIRS = set()


def is_attachment_image(attachment):
    if not attachment or attachment.get('type') == 'folder':
        return False
    return Path(attachment.get('original_name', '')).suffix.lower() in IMAGE_EXTS


def default_app_root() -> Path:
    return resolve_data_root()


class Storage:
    def __init__(self, app_dir=None, crypter=None):
        self.app_dir = Path(app_dir) if app_dir else default_app_root()
        self.attachments_dir = self.app_dir / 'attachments'
        self.trash_dir = self.app_dir / 'trash'
        self.data_file = self.app_dir / 'data.json'
        self.scan_settings_file = self.app_dir / 'scan_settings.json'
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        # 加密器：data.json 与 attachments 文件统一加密
        self.crypter = crypter or Crypter(self.app_dir)
        # 数据加载失败时进入只读保护：拒绝任何落盘，避免覆盖仅存的原始文件
        self.load_failed = False
        self.load_error = ''
        self.save_error = ''
        self.on_save_failed = None  # main 侧注入的回调：保存失败时提示用户
        self._defer_save = False
        self._dirty = False
        self._last_bak_time = 0.0
        # 临时解密缓存：UI 读图时透明使用，退出时清理。
        # 先清扫上次崩溃/被强杀留下的明文残留（被占用的文件会清理失败，留待下次）。
        self._sweep_stale_cache_dirs()
        self.cache_dir = Path(tempfile.mkdtemp(prefix='FRESH-cache-'))
        _ACTIVE_CACHE_DIRS.add(str(self.cache_dir))
        atexit.register(self._cleanup_cache_dir)
        self.notes = self._load()
        self.scan_settings = self._load_scan_settings()
        # 历史遗留：把现存明文文件加密；已软删除的本地文件移入 trash/
        self._migrate_orphan_screenshot_board_attachments()
        self._ensure_folder_tracking_markers()
        self._migrate_plain_attachments()
        self.secure_image_references()
        self._sweep_deleted_files_to_trash()

    @staticmethod
    def _sweep_stale_cache_dirs():
        try:
            tmp_root = Path(tempfile.gettempdir())
            for stale in tmp_root.glob('FRESH-cache-*'):
                if str(stale) in _ACTIVE_CACHE_DIRS:
                    continue
                if stale.is_dir():
                    shutil.rmtree(stale, ignore_errors=True)
        except Exception:
            pass

    def _cleanup_cache_dir(self):
        try:
            _ACTIVE_CACHE_DIRS.discard(str(self.cache_dir))
            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir, ignore_errors=True)
        except Exception:
            pass

    def _load_scan_settings(self):
        merged = dict(DEFAULT_SCAN_SETTINGS)
        if not self.scan_settings_file.exists():
            return merged
        try:
            with open(self.scan_settings_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged.update({k: v for k, v in data.items() if k in DEFAULT_SCAN_SETTINGS})
        except Exception:
            pass
        return merged

    def save_scan_settings(self, settings):
        merged = dict(DEFAULT_SCAN_SETTINGS)
        merged.update({k: v for k, v in (settings or {}).items() if k in DEFAULT_SCAN_SETTINGS})
        self.scan_settings = merged
        try:
            with open(self.scan_settings_file, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return merged

    def _load(self):
        if not self.data_file.exists():
            return []
        try:
            raw = self.data_file.read_bytes()
            if not raw:
                return []
            was_plain = not self.crypter.is_encrypted(raw)
            if was_plain and not getattr(self.crypter, 'accepts_plaintext', True):
                # 密码账户不存在合法明文，出现明文说明文件被篡改或损坏
                raise ValueError('数据文件为明文，可能被篡改或损坏')
            payload = raw if was_plain else self.crypter.decrypt_bytes(raw)
            data = json.loads(payload.decode('utf-8'))
            if not isinstance(data, list):
                raise ValueError('数据文件结构异常（根节点不是列表）')
            for note in data:
                if note.get('archived') and not note.get('archived_at'):
                    note['archived_at'] = note.get('updated_at') or note.get('created_at') or ''
                if note.get('deleted') and not note.get('deleted_at'):
                    note['deleted_at'] = note.get('updated_at') or note.get('created_at') or ''
                for _note, att, _parent, _container in self._iter_note_attachments(note):
                    if att.get('deleted') and not att.get('deleted_at'):
                        att['deleted_at'] = att.get('added_at') or note.get('updated_at') or note.get('created_at') or ''
            self.notes = data
            self.sort_notes()
            data = self.notes
            # 如果是从明文读入的，强制立刻加密落盘
            if was_plain:
                self.save()
            return data
        except Exception as exc:
            # 解密失败（密钥不符）/损坏/解析失败：进入只读保护。
            # 绝不能返回空列表继续正常运行——随后的任何一次 save() 都会
            # 用空数据覆盖掉本来可能修复的原始密文。
            self.load_failed = True
            self.load_error = str(exc)
            self._backup_corrupt_data_file()
            return []

    def _backup_corrupt_data_file(self):
        """把无法加载的 data.json 复制留底，原文件保持原样。"""
        try:
            stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            backup = self.data_file.with_name(f'data.corrupt-{stamp}.json')
            if not backup.exists():
                shutil.copy2(self.data_file, backup)
        except Exception:
            pass

    def save(self):
        if self.load_failed:
            # 只读保护：数据没有正确加载，拒绝覆盖磁盘上的原始文件
            return False
        if self._defer_save:
            self._dirty = True
            return True
        return self._write_data_file()

    def _write_data_file(self):
        try:
            payload = json.dumps(self.notes, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            blob = self.crypter.encrypt_bytes(payload)
            # 原子写：先写临时再替换；fsync 确保断电后不会留下截断文件
            tmp = self.data_file.with_suffix('.json.tmp')
            with open(tmp, 'wb') as fh:
                fh.write(blob)
                fh.flush()
                os.fsync(fh.fileno())
            # 周期性保留上一版备份，便于 data.json 意外损坏时找回
            now = time.monotonic()
            if self.data_file.exists() and now - self._last_bak_time > 60:
                try:
                    shutil.copy2(self.data_file, self.data_file.with_suffix('.json.bak'))
                    self._last_bak_time = now
                except Exception:
                    pass
            os.replace(tmp, self.data_file)
            self._dirty = False
            self.save_error = ''
            return True
        except Exception as exc:
            # 磁盘满/被锁定/权限问题：必须让用户知道，否则会以为已保存
            self.save_error = str(exc)
            callback = self.on_save_failed
            if callback:
                try:
                    callback(str(exc))
                except Exception:
                    pass
            return False

    @contextmanager
    def batch(self):
        """批量操作期间暂缓落盘，退出时统一写一次。

        用于"全部彻底删除"、多文件拖入等会触发大量 save() 的路径，
        避免 N 次全库序列化+加密+写盘。
        """
        if self._defer_save:
            yield self
            return
        self._defer_save = True
        try:
            yield self
        finally:
            self._defer_save = False
            if self._dirty:
                self.save()

    def create_note(self, category=''):
        now = datetime.now().isoformat()
        note = {
            'id': uuid.uuid4().hex,
            'title': '',
            'content': '',
            'content_format': 'rich',
            'mode': 'text',
            'attachments': [],
            'created_at': now,
            'updated_at': now,
        }
        category = (category or '').strip()
        if category:
            note['category'] = category
        self.notes.insert(0, note)
        self.sort_notes()
        self.save()
        return note

    def sort_notes(self):
        def timestamp(value):
            if not value:
                return 0
            try:
                return datetime.fromisoformat(value).timestamp()
            except Exception:
                return 0

        self.notes.sort(
            key=lambda n: (
                0 if n.get('pinned') else 1,
                -timestamp(n.get('pinned_at')),
                -timestamp(n.get('updated_at') or n.get('created_at')),
            )
        )

    def get_screenshot_board(self):
        for note in self.notes:
            if note.get('id') == SCREENSHOT_BOARD_ID:
                note['system'] = True
                note['mode'] = 'screenshot'
                note.setdefault('attachments', [])
                return note

        now = datetime.now().isoformat()
        note = {
            'id': SCREENSHOT_BOARD_ID,
            'title': '截图便签',
            'content': '',
            'mode': 'screenshot',
            'attachments': [],
            'system': True,
            'created_at': now,
            'updated_at': now,
        }
        self.notes.insert(0, note)
        self.save()
        return note

    def _migrate_orphan_screenshot_board_attachments(self):
        """Move legacy non-image full-screenshot items under a real screenshot.

        A previous build allowed files/folders to be added directly to the
        screenshot board. The current model treats those as child attachments of
        a selected screenshot, so keep old data usable instead of letting it
        behave like an independent board item.
        """
        board = None
        for note in self.notes:
            if note.get('id') == SCREENSHOT_BOARD_ID:
                board = note
                break
        if not board:
            return False

        attachments = board.get('attachments', []) or []
        orphans = [
            att for att in attachments
            if not att.get('deleted') and not is_attachment_image(att)
        ]
        if not orphans:
            return False

        candidates = [
            att for att in attachments
            if not att.get('deleted') and is_attachment_image(att)
        ]
        if not candidates:
            return False

        def timestamp(att):
            value = att.get('added_at') or ''
            try:
                return datetime.fromisoformat(value).timestamp()
            except Exception:
                return 0

        changed = False
        for orphan in list(orphans):
            before = timestamp(orphan)
            older = [
                candidate for candidate in candidates
                if candidate is not orphan and timestamp(candidate) <= before
            ]
            parent = max(older, key=timestamp) if older else max(
                [candidate for candidate in candidates if candidate is not orphan],
                key=timestamp,
                default=None,
            )
            if not parent:
                continue
            try:
                attachments.remove(orphan)
            except ValueError:
                continue
            parent.setdefault('attachments', []).append(orphan)
            changed = True

        if changed:
            board['updated_at'] = datetime.now().isoformat()
            self.save()
        return changed

    def _ensure_folder_tracking_markers(self):
        """Make folder attachments recoverable on exFAT/FAT by adding markers."""
        changed = False
        for _note, att, _parent, _container in self.iter_attachments(include_deleted=False):
            if att.get('type') != 'folder':
                continue
            p = Path(att.get('original_path', ''))
            if not p.exists() or not p.is_dir():
                continue
            tracking = att.get('tracking') or {}
            tag = tracking.get('tracking_id')
            if not tag:
                if self.ensure_tracking(att):
                    changed = True
                continue
            if ftrack.write_tracking_tag(str(p), tag):
                changed = True
        if changed:
            self.save()
        return changed

    def update_note(self, note_id, **kwargs):
        for note in self.notes:
            if note['id'] == note_id:
                changed = False
                for key, val in kwargs.items():
                    if note.get(key) != val:
                        note[key] = val
                        changed = True
                if changed:
                    note['updated_at'] = datetime.now().isoformat()
                    self.sort_notes()
                    self.save()
                return note
        return None

    def set_note_pinned(self, note_id, pinned):
        pinned = bool(pinned)
        for note in self.notes:
            if note['id'] == note_id:
                if note.get('system'):
                    return None
                if bool(note.get('pinned')) == pinned:
                    return note
                note['pinned'] = pinned
                note['pinned_at'] = datetime.now().isoformat() if pinned else ''
                self.sort_notes()
                self.save()
                return note
        return None

    def delete_note(self, note_id):
        for note in self.notes[:]:
            if note['id'] == note_id:
                if note.get('system'):
                    return False
                now = datetime.now().isoformat()
                note['deleted'] = True
                note['deleted_at'] = now
                note['updated_at'] = now
                # 把笔记下属本地文件附件移入 trash/
                for _note, att, _parent, _container in self._iter_note_attachments(note):
                    if att.get('type', 'file') == 'file' and not att.get('deleted'):
                        self._move_to_trash(att.get('stored_name'))
                self.sort_notes()
                self.save()
                return True
        return False

    def restore_note(self, note_id):
        for note in self.notes:
            if note['id'] == note_id and note.get('deleted'):
                note['deleted'] = False
                note['deleted_at'] = ''
                note['updated_at'] = datetime.now().isoformat()
                # 还原笔记时，把仍在 trash/ 的附件移回（未被单独标记 deleted 的）
                for _note, att, _parent, _container in self._iter_note_attachments(note):
                    if att.get('type', 'file') == 'file' and not att.get('deleted'):
                        self._restore_from_trash(att.get('stored_name'))
                self.sort_notes()
                self.save()
                return True
        return False

    def hard_delete_note(self, note_id):
        for note in self.notes[:]:
            if note['id'] == note_id:
                for _note, att, _parent, _container in self._iter_note_attachments(note):
                    if att.get('type', 'file') == 'file':
                        self._remove_attachment_file(att.get('stored_name'))
                        self._remove_trash_file(att.get('stored_name'))
                self.notes.remove(note)
                self.save()
                return True
        return False

    def add_attachment(self, note_id, source_path, copy=False):
        source = Path(source_path)
        if not source.exists():
            return None

        if source.is_dir():
            attachment = {
                'id': uuid.uuid4().hex,
                'original_name': source.name or str(source),
                'type': 'folder',
                'original_path': str(source.resolve()),
                'added_at': datetime.now().isoformat(),
            }
            attachment['tracking'] = ftrack.build_tracking(str(source.resolve()))
        elif source.is_file():
            encrypt_local_copy = copy or source.suffix.lower() in IMAGE_EXTS
            if encrypt_local_copy:
                ext = source.suffix
                stored_name = f"{uuid.uuid4().hex}{ext}"
                target = self.attachments_dir / stored_name
                try:
                    raw = source.read_bytes()
                    target.write_bytes(self.crypter.encrypt_bytes(raw))
                    size = len(raw)
                except Exception:
                    return None
                attachment = {
                    'id': uuid.uuid4().hex,
                    'original_name': source.name,
                    'type': 'file',
                    'stored_name': stored_name,
                    'size': size,
                    'added_at': datetime.now().isoformat(),
                }
            else:
                try:
                    size = source.stat().st_size
                except Exception:
                    size = 0
                attachment = {
                    'id': uuid.uuid4().hex,
                    'original_name': source.name,
                    'type': 'file_ref',
                    'original_path': str(source.resolve()),
                    'size': size,
                    'added_at': datetime.now().isoformat(),
                }
                attachment['tracking'] = ftrack.build_tracking(str(source.resolve()))
        else:
            return None

        for note in self.notes:
            if note['id'] == note_id:
                note.setdefault('attachments', []).append(attachment)
                note['updated_at'] = datetime.now().isoformat()
                self.sort_notes()
                self.save()
                return attachment
        return None

    def add_screenshot(self, source_path):
        source = Path(source_path)
        if not source.is_file() or source.suffix.lower() not in IMAGE_EXTS:
            return None
        board = self.get_screenshot_board()
        # 截图板的图片一律落为账户内加密副本
        return self.add_attachment(board['id'], source_path, copy=True)

    def add_child_attachment(self, parent_attachment_id, source_path, copy=False):
        source = Path(source_path)
        if not source.exists():
            return None

        note, parent = self.find_attachment(parent_attachment_id)
        if not note or not parent or parent.get('deleted'):
            return None
        if note.get('id') != SCREENSHOT_BOARD_ID:
            return None
        if not is_attachment_image(parent):
            return None

        if source.is_dir():
            attachment = {
                'id': uuid.uuid4().hex,
                'original_name': source.name or str(source),
                'type': 'folder',
                'original_path': str(source.resolve()),
                'added_at': datetime.now().isoformat(),
            }
            attachment['tracking'] = ftrack.build_tracking(str(source.resolve()))
        elif source.is_file():
            try:
                size = source.stat().st_size
            except Exception:
                size = 0
            attachment = {
                'id': uuid.uuid4().hex,
                'original_name': source.name,
                'type': 'file_ref',
                'original_path': str(source.resolve()),
                'size': size,
                'added_at': datetime.now().isoformat(),
            }
            attachment['tracking'] = ftrack.build_tracking(str(source.resolve()))
        else:
            return None

        parent.setdefault('attachments', []).append(attachment)
        note['updated_at'] = datetime.now().isoformat()
        self.sort_notes()
        self.save()
        return attachment

    def secure_image_references(self):
        """把仍能访问到的图片引用转成账户内加密副本；普通文件继续引用。"""
        changed = False
        for note in self.notes:
            for _note, att, parent, _container in self._iter_note_attachments(note, include_deleted=False):
                if parent is not None:
                    continue
                if att.get('type') != 'file_ref':
                    continue
                name = att.get('original_name') or att.get('original_path') or ''
                if Path(name).suffix.lower() not in IMAGE_EXTS:
                    continue
                source = Path(att.get('original_path', ''))
                if not source.exists() or not source.is_file():
                    continue
                try:
                    raw = source.read_bytes()
                except Exception:
                    continue
                stored_name = f"{uuid.uuid4().hex}{source.suffix}"
                target = self.attachments_dir / stored_name
                try:
                    target.write_bytes(self.crypter.encrypt_bytes(raw))
                except Exception:
                    continue
                att['type'] = 'file'
                att['stored_name'] = stored_name
                att['size'] = len(raw)
                att['original_name'] = att.get('original_name') or source.name
                att['secured_at'] = datetime.now().isoformat()
                att.pop('original_path', None)
                att.pop('tracking', None)
                changed = True
        if changed:
            self.save()
        return changed

    def get_note(self, note_id):
        for note in self.notes:
            if note['id'] == note_id:
                return note
        return None

    def _iter_note_attachments(self, note, include_deleted=True, parent=None, container=None):
        attachments = container if container is not None else note.get('attachments', []) or []
        for att in attachments:
            is_deleted = bool(att.get('deleted'))
            if include_deleted or not is_deleted:
                yield note, att, parent, attachments
            if is_deleted and not include_deleted:
                continue
            yield from self._iter_note_attachments(
                note,
                include_deleted=include_deleted,
                parent=att,
                container=att.get('attachments', []) or [],
            )

    def iter_attachments(self, include_deleted=True):
        for note in self.notes:
            for item in self._iter_note_attachments(note, include_deleted=include_deleted):
                yield item

    def update_attachment(self, note_id, attachment_id, **kwargs):
        for note in self.notes:
            if note['id'] != note_id:
                continue
            for _note, att, _parent, _container in self._iter_note_attachments(note):
                if att.get('id') != attachment_id:
                    continue
                changed = False
                for k, v in kwargs.items():
                    if att.get(k) != v:
                        att[k] = v
                        changed = True
                if changed:
                    note['updated_at'] = datetime.now().isoformat()
                    self.sort_notes()
                    self.save()
                return att
        return None

    def find_attachment(self, attachment_id):
        for note, att, _parent, _container in self.iter_attachments():
            if att.get('id') == attachment_id:
                return note, att
        return None, None

    def parent_attachment_id(self, attachment_id):
        for _note, att, parent, _container in self.iter_attachments():
            if att.get('id') == attachment_id:
                return parent.get('id') if parent else ''
        return ''

    def update_screenshot(self, attachment_id, **kwargs):
        note, att = self.find_attachment(attachment_id)
        if not note or not att:
            return None
        return self.update_attachment(note['id'], attachment_id, **kwargs)

    def remove_screenshot(self, attachment_id):
        note, att = self.find_attachment(attachment_id)
        if not note or not att:
            return False
        return self.remove_attachment(note['id'], attachment_id)

    def all_screenshot_attachments(self):
        result = []
        board = self.get_screenshot_board()
        if board.get('deleted'):
            return result
        for _note, att, parent, _container in self._iter_note_attachments(board, include_deleted=False):
            if parent is None and is_attachment_image(att):
                result.append(att)
        return result

    def all_image_attachments(self):
        return [
            att for att in self.all_screenshot_attachments()
            if Path(att.get('original_name', '')).suffix.lower() in IMAGE_EXTS
        ]

    def screenshot_items(self, view='active', category='', search=''):
        category = (category or '').strip()
        search = (search or '').strip().lower()
        items = []
        for att in self.all_screenshot_attachments():
            is_archived = bool(att.get('archived'))
            if view == 'active' and is_archived:
                continue
            if view == 'archived' and not is_archived:
                continue
            att_category = (att.get('archive_category') or att.get('category') or '').strip()
            if category and att_category != category:
                continue
            if search:
                text = ' '.join([
                    att.get('original_name', ''),
                    att.get('category', ''),
                    att.get('memo', ''),
                    att.get('archive_content', ''),
                    att.get('archive_category', ''),
                ]).lower()
                if search not in text:
                    continue
            items.append(att)
        items.sort(
            key=lambda att: att.get('archived_at') or att.get('added_at') or '',
            reverse=(view == 'archived')
        )
        return items

    def screenshot_counts(self):
        active = 0
        archived = 0
        for att in self.all_screenshot_attachments():
            if att.get('archived'):
                archived += 1
            else:
                active += 1
        return active, archived

    def all_archived_attachments(self):
        result = []
        for note in self.notes:
            if note.get('deleted'):
                continue
            for _note, att, _parent, _container in self._iter_note_attachments(note, include_deleted=False):
                if att.get('archived') and not att.get('deleted'):
                    result.append((note, att))
        result.sort(key=lambda x: x[1].get('archived_at', '') or '', reverse=True)
        return result

    def all_archived_notes(self):
        result = [
            note for note in self.notes
            if note.get('archived') and not note.get('system') and not note.get('deleted')
        ]
        result.sort(
            key=lambda n: n.get('archived_at') or n.get('updated_at') or n.get('created_at') or '',
            reverse=True
        )
        return result

    def all_timeline_items(self, category=''):
        category = (category or '').strip()
        items = []
        for note in self.notes:
            if note.get('deleted'):
                continue
            if note.get('archived') and not note.get('system'):
                note_category = (note.get('archive_category') or note.get('category') or '').strip()
                if not category or note_category == category:
                    items.append({
                        'kind': 'note',
                        'time': note.get('archived_at') or note.get('updated_at') or note.get('created_at') or '',
                        'note': note,
                    })
            for _note, att, _parent, _container in self._iter_note_attachments(note, include_deleted=False):
                if att.get('deleted'):
                    continue
                att_category = (att.get('archive_category') or att.get('category') or '').strip()
                if att.get('archived') and (not category or att_category == category):
                    items.append({
                        'kind': 'attachment',
                        'time': att.get('archived_at') or att.get('added_at') or note.get('updated_at') or '',
                        'note': note,
                        'attachment': att,
                    })
        items.sort(key=lambda item: item.get('time') or '', reverse=True)
        return items

    def all_categories(self):
        cats = set()
        for note in self.notes:
            if note.get('deleted'):
                continue
            c = (note.get('archive_category') or note.get('category') or '').strip()
            if c:
                cats.add(c)
            for _note, att, _parent, _container in self._iter_note_attachments(note, include_deleted=False):
                if att.get('deleted'):
                    continue
                c = (att.get('archive_category') or att.get('category') or '').strip()
                if c:
                    cats.add(c)
        return sorted(cats)

    def remove_attachment(self, note_id, attachment_id):
        for note in self.notes:
            if note['id'] == note_id:
                for _note, att, _parent, _container in self._iter_note_attachments(note):
                    if att['id'] == attachment_id:
                        now = datetime.now().isoformat()
                        att['deleted'] = True
                        att['deleted_at'] = now
                        note['updated_at'] = now
                        # 软删除：把本地文件移到 trash/ ，attachments/ 不再包含被删图片
                        if att.get('type', 'file') == 'file':
                            self._move_to_trash(att.get('stored_name'))
                        self.sort_notes()
                        self.save()
                        return True
        return False

    def restore_attachment(self, attachment_id):
        note, att = self.find_attachment(attachment_id)
        if not note or not att or not att.get('deleted'):
            return False
        att['deleted'] = False
        att['deleted_at'] = ''
        note['updated_at'] = datetime.now().isoformat()
        if att.get('type', 'file') == 'file':
            self._restore_from_trash(att.get('stored_name'))
        self.sort_notes()
        self.save()
        return True

    def hard_remove_attachment(self, note_id, attachment_id):
        for note in self.notes:
            if note['id'] == note_id:
                for _note, att, _parent, attachments in self._iter_note_attachments(note):
                    if att['id'] == attachment_id:
                        if att.get('type', 'file') == 'file':
                            self._remove_attachment_file(att.get('stored_name'))
                            self._remove_trash_file(att.get('stored_name'))
                        attachments.remove(att)
                        note['updated_at'] = datetime.now().isoformat()
                        self.sort_notes()
                        self.save()
                        return True
        return False

    def deleted_items(self):
        items = []
        for note in self.notes:
            if note.get('deleted') and not note.get('system'):
                items.append({
                    'kind': 'note',
                    'time': note.get('deleted_at') or note.get('updated_at') or note.get('created_at') or '',
                    'note': note,
                })
                continue
            if note.get('deleted'):
                continue
            for _note, att, _parent, _container in self._iter_note_attachments(note):
                if att.get('deleted'):
                    items.append({
                        'kind': 'attachment',
                        'time': att.get('deleted_at') or att.get('added_at') or note.get('updated_at') or '',
                        'note': note,
                        'attachment': att,
                    })
        items.sort(key=lambda item: item.get('time') or '', reverse=True)
        return items

    def path_for(self, attachment):
        t = attachment.get('type', 'file')
        if t in ('folder', 'file_ref'):
            return Path(attachment.get('original_path', ''))
        if t == 'screenshot_child':
            return Path('')
        stored_name = attachment.get('stored_name', '')
        attached = self.attachments_dir / stored_name
        enc_path = attached
        if not attached.exists():
            trashed = self.trash_dir / stored_name
            if trashed.exists():
                enc_path = trashed
            else:
                return attached  # 不存在，沿用旧行为
        return self._decrypted_cache_path(enc_path, stored_name)

    def _decrypted_cache_path(self, enc_path: Path, stored_name: str) -> Path:
        """把加密附件解密到临时缓存目录后，返回缓存路径。明文遗留文件直接返回原路径。"""
        cache = self.cache_dir / stored_name
        try:
            src_mtime = enc_path.stat().st_mtime
        except Exception:
            return enc_path
        # 缓存命中：只做 stat 比较，不再整文件读盘
        try:
            if cache.exists() and cache.stat().st_mtime >= src_mtime:
                return cache
        except Exception:
            pass
        try:
            with open(enc_path, 'rb') as fh:
                head = fh.read(len(MAGIC))
                if not head.startswith(MAGIC):
                    return enc_path
                blob = head + fh.read()
        except Exception:
            return enc_path
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(self.crypter.decrypt_bytes(blob))
            return cache
        except Exception:
            return enc_path

    def read_attachment_bytes(self, attachment) -> bytes:
        """直接拿到解密后的字节（不写临时文件）。供导出 / 二进制比较使用。"""
        t = attachment.get('type', 'file')
        if t != 'file':
            p = Path(attachment.get('original_path', ''))
            return p.read_bytes() if p.exists() else b''
        stored_name = attachment.get('stored_name', '')
        for base in (self.attachments_dir, self.trash_dir):
            p = base / stored_name
            if p.exists():
                blob = p.read_bytes()
                if self.crypter.is_encrypted(blob):
                    return self.crypter.decrypt_bytes(blob)
                return blob
        return b''

    def sync_external_attachment_name(self, attachment, path=None, save=True):
        """让外部引用附件的显示名跟随当前真实路径。"""
        if not attachment or attachment.get('type') not in ('folder', 'file_ref'):
            return False
        raw_path = path if path is not None else attachment.get('original_path', '')
        if not raw_path:
            return False
        try:
            p = Path(raw_path)
        except Exception:
            return False
        if not p.exists():
            return False
        new_name = p.name or str(p)
        if not new_name:
            return False

        note, att = self.find_attachment(attachment.get('id', ''))
        target = att or attachment
        if target.get('original_name') == new_name:
            return False
        target['original_name'] = new_name
        if save and att:
            self.save()
        return True

    def _tracking_matches_path(self, path, tracking):
        """判断当前路径是否仍是记录里的那个文件/文件夹。"""
        if not tracking:
            return False
        p = Path(path)
        if not p.exists():
            return False

        tag = tracking.get('tracking_id')
        if tag and ftrack.read_tracking_tag(str(p)) == tag:
            return True

        current = ftrack.get_file_info(str(p))
        if current and (
            current.get('volume_serial') == tracking.get('volume_serial')
            and current.get('file_id_high') == tracking.get('file_id_high')
            and current.get('file_id_low') == tracking.get('file_id_low')
        ):
            return True

        # F:/移动硬盘常见为 exFAT/FAT，ADS 不能保留，File ID 也可能不可用。
        # 对文件用已记录的 size + content hash 兜底，避免新路径已经正确但仍被判丢失。
        if p.is_file() and ftrack.path_matches_hash(str(p), tracking):
            return True
        return False

    def attachment_path_matches_tracking(self, attachment, save=True):
        """附件当前 original_path 是否还能和 tracking 对上。

        save=False 供后台线程（备份导出等）只读调用，避免在工作线程写盘。
        """
        tracking = attachment.get('tracking') or {}
        original_path = attachment.get('original_path', '')
        if not tracking:
            matched = Path(original_path).exists()
        else:
            matched = self._tracking_matches_path(original_path, tracking)
        if matched and save:
            self.sync_external_attachment_name(attachment, original_path)
        return matched

    def _quick_external_match(self, attachment, tracking):
        """在小范围内按同名 + tracking 身份快速找回，不触发全盘扫描。"""
        if not tracking:
            return None
        original_path = attachment.get('original_path', '')
        name = attachment.get('original_name') or Path(original_path).name
        if not name:
            return None
        roots = (self.scan_settings or {}).get('scan_roots') or []
        candidates = ftrack.find_nearby_name_candidates(
            name,
            original_path=original_path,
            roots=roots,
            limit=100,
        )
        matches = [
            Path(p)
            for p in candidates
            if self._tracking_matches_path(p, tracking)
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def adopt_external_path(self, attachment, new_path):
        new_path = str(Path(new_path).resolve())
        note, att = self.find_attachment(attachment['id'])
        if not note or not att:
            return Path(new_path)
        new_path_obj = Path(new_path)
        att['original_path'] = new_path
        att['original_name'] = new_path_obj.name or att.get('original_name', '')
        if att.get('type') == 'file_ref':
            try:
                att['size'] = new_path_obj.stat().st_size
            except Exception:
                pass
        self.save()
        try:
            self.rebuild_tracking_at_current_path(att)
        except Exception:
            pass
        return Path(new_path)

    def resolve_external_path(self, attachment, scan=False, progress=None, cancel=None):
        """对 file_ref / folder 类型的附件，尝试定位当前实际路径。

        优先用 NTFS File ID 快速定位；scan=True 时启用慢速全盘 ADS 标签扫描。
        定位成功后会自动把 original_path 改写为新路径并持久化。
        返回 (Path, recovered: bool)；找不到时返回 (原 Path, False)。
        如果原路径已被其他文件占用且找不回原对象，返回 (None, False)，避免误打开。
        """
        t = attachment.get('type', 'file')
        if t not in ('folder', 'file_ref'):
            return self.path_for(attachment), False

        original = Path(attachment.get('original_path', ''))
        tracking = attachment.get('tracking') or {}
        if original.exists():
            if not tracking or self._tracking_matches_path(original, tracking):
                changed = self.sync_external_attachment_name(attachment, original)
                return original, changed
            quick = self._quick_external_match(attachment, tracking)
            if quick:
                return self.adopt_external_path(attachment, quick), True
            found = ftrack.try_recover(tracking, scan=scan, progress=progress, cancel=cancel)
            if not found:
                return None, False
            new_path = str(Path(found).resolve())
            if new_path == str(original.resolve()):
                return None, False
            return self.adopt_external_path(attachment, new_path), True

        if not tracking:
            return original, False

        recovered = self._recover_external_in_original_parent(attachment, tracking)
        if recovered:
            return self.adopt_external_path(attachment, recovered), True

        quick = self._quick_external_match(attachment, tracking)
        if quick:
            return self.adopt_external_path(attachment, quick), True

        found = ftrack.try_recover(tracking, scan=scan, progress=progress, cancel=cancel)
        if not found:
            return original, False

        return self.adopt_external_path(attachment, found), True

    def ensure_tracking(self, attachment):
        """为已存在但缺少 tracking 字段的 file_ref/folder 补打标签。"""
        t = attachment.get('type', 'file')
        if t not in ('folder', 'file_ref'):
            return False
        if attachment.get('tracking'):
            return False
        p = Path(attachment.get('original_path', ''))
        if not p.exists():
            return False
        tr = ftrack.build_tracking(str(p.resolve()))
        if not tr:
            return False
        note, att = self.find_attachment(attachment['id'])
        if note and att:
            att['tracking'] = tr
            self.save()
            return True
        return False

    def rebuild_tracking_at_current_path(self, attachment):
        """采纳新路径后重建 tracking，并尽量沿用旧 tracking_id。"""
        t = attachment.get('type', 'file')
        if t not in ('folder', 'file_ref'):
            return False
        p = Path(attachment.get('original_path', ''))
        if not p.exists():
            return False

        old = attachment.get('tracking') or {}
        old_uuid = old.get('tracking_id', '')
        new_tr = ftrack.build_tracking(str(p.resolve()), tracking_id=old_uuid or None)
        if not new_tr:
            return False
        if old_uuid:
            if ftrack.write_tracking_tag(str(p), old_uuid):
                new_tr['tracking_id'] = old_uuid
            elif 'tracking_id' not in new_tr:
                new_tr['tracking_id'] = old_uuid

        note, att = self.find_attachment(attachment['id'])
        if note and att:
            att['tracking'] = new_tr
            self.save()
            return True
        attachment['tracking'] = new_tr
        return True

    def refresh_tracking_if_changed(self, attachment):
        """检测 atomic save：文件仍在 original_path，但 File ID 与记录不同。
        重新打标时**保留原 UUID**，并把它写到新文件的 ADS。
        返回 True 表示发生了刷新。"""
        t = attachment.get('type', 'file')
        if t not in ('folder', 'file_ref'):
            return False
        old = attachment.get('tracking') or {}
        if not old:
            return False
        p = Path(attachment.get('original_path', ''))
        if not p.exists():
            recovered = self._recover_external_in_original_parent(attachment, old)
            if recovered:
                self.adopt_external_path(attachment, recovered)
                return True
            return False
        name_changed = self.sync_external_attachment_name(attachment, p)
        current = ftrack.get_file_info(str(p))
        if not current:
            return name_changed

        same_id = (
            current.get('volume_serial') == old.get('volume_serial')
            and current.get('file_id_high') == old.get('file_id_high')
            and current.get('file_id_low') == old.get('file_id_low')
        )
        old_uuid = old.get('tracking_id', '')

        if same_id:
            # File ID 没变，但 ADS 可能被覆盖（部分编辑器会清掉 ADS）
            if old_uuid and ftrack.read_tracking_tag(str(p)) != old_uuid:
                ftrack.write_tracking_tag(str(p), old_uuid)
            return name_changed

        if old_uuid and ftrack.read_tracking_tag(str(p)) == old_uuid:
            new_tr = ftrack.build_tracking(str(p.resolve()), tracking_id=old_uuid or None)
            if not new_tr:
                return False
            new_tr['tracking_id'] = old_uuid
            note, att = self.find_attachment(attachment['id'])
            if note and att:
                att['tracking'] = new_tr
                self.save()
                return True
            return name_changed

        moved = ftrack.try_recover(old, scan=False)
        if moved:
            try:
                moved_path = str(Path(moved).resolve())
                if moved_path != str(p.resolve()):
                    self.adopt_external_path(attachment, moved_path)
                    return True
            except Exception:
                pass

        return name_changed

    def _recover_external_in_original_parent(self, attachment, tracking):
        """Handle same-folder rename without starting a disk scan."""
        original = Path(attachment.get('original_path', ''))
        parent = original.parent
        if not parent.exists() or not parent.is_dir():
            return None
        tag = (tracking or {}).get('tracking_id')
        att_type = attachment.get('type')
        try:
            children = list(parent.iterdir())
        except OSError:
            return None

        matches = []
        for child in children:
            try:
                if att_type == 'folder':
                    if not child.is_dir():
                        continue
                    if tag and ftrack.read_tracking_tag(str(child)) == tag:
                        matches.append(child)
                elif att_type == 'file_ref':
                    if not child.is_file():
                        continue
                    if tag and ftrack.read_tracking_tag(str(child)) == tag:
                        matches.append(child)
                    elif ftrack.path_matches_hash(str(child), tracking):
                        matches.append(child)
            except OSError:
                continue
        if len(matches) == 1:
            return matches[0]
        return None

    def all_external_attachments(self):
        """返回所有 file_ref / folder 类型的附件 (note, attachment) 列表。"""
        out = []
        for note in self.notes:
            if note.get('deleted'):
                continue
            for _note, att, _parent, _container in self._iter_note_attachments(note, include_deleted=False):
                if att.get('deleted'):
                    continue
                if att.get('type') in ('folder', 'file_ref'):
                    out.append((note, att))
        return out

    def get_attachment_path(self, stored_name):
        return self.attachments_dir / stored_name

    def _remove_attachment_file(self, stored_name):
        if not stored_name:
            return
        try:
            path = self.attachments_dir / stored_name
            if path.exists():
                path.unlink()
        except Exception:
            pass

    def _move_to_trash(self, stored_name):
        if not stored_name:
            return
        try:
            src = self.attachments_dir / stored_name
            if not src.exists():
                return
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            dst = self.trash_dir / stored_name
            if dst.exists():
                try:
                    dst.unlink()
                except Exception:
                    pass
            shutil.move(str(src), str(dst))
        except Exception:
            pass

    def _restore_from_trash(self, stored_name):
        if not stored_name:
            return
        try:
            src = self.trash_dir / stored_name
            if not src.exists():
                return
            self.attachments_dir.mkdir(parents=True, exist_ok=True)
            dst = self.attachments_dir / stored_name
            if dst.exists():
                return
            shutil.move(str(src), str(dst))
        except Exception:
            pass

    def _remove_trash_file(self, stored_name):
        if not stored_name:
            return
        try:
            path = self.trash_dir / stored_name
            if path.exists():
                path.unlink()
        except Exception:
            pass

    def _sweep_deleted_files_to_trash(self):
        """启动时把"已软删除但文件仍在 attachments/"的图片移到 trash/。"""
        try:
            for note in self.notes:
                note_deleted = bool(note.get('deleted'))
                for _note, att, _parent, _container in self._iter_note_attachments(note):
                    if att.get('type', 'file') != 'file':
                        continue
                    if not (att.get('deleted') or note_deleted):
                        continue
                    stored_name = att.get('stored_name')
                    if stored_name and (self.attachments_dir / stored_name).exists():
                        self._move_to_trash(stored_name)
        except Exception:
            pass

    def _migrate_plain_attachments(self):
        """启动时把 attachments/ 和 trash/ 中的明文文件加密。

        只读前 6 字节判断是否已加密，避免每次启动把几 GB 附件全部读入内存；
        全部迁移完成后写标记文件，之后启动直接跳过整个目录遍历。
        """
        if not getattr(self.crypter, 'accepts_plaintext', True):
            # 密码账户从创建起全部加密写入，不存在合法明文；
            # 把来历不明的明文"收编"加密反而会洗白被注入的文件
            return
        marker = self.app_dir / '.attachments_encrypted'
        if marker.exists():
            return
        complete = True
        for base in (self.attachments_dir, self.trash_dir):
            try:
                if not base.exists():
                    continue
                for f in base.iterdir():
                    if not f.is_file():
                        continue
                    if f.name.startswith('.'):
                        continue
                    if f.name.endswith('.enc.tmp'):
                        # 上次迁移中断留下的半成品
                        try:
                            f.unlink()
                        except Exception:
                            pass
                        continue
                    try:
                        with open(f, 'rb') as fh:
                            head = fh.read(len(MAGIC))
                    except Exception:
                        complete = False
                        continue
                    if not head:
                        continue  # 空文件
                    if head.startswith(MAGIC):
                        continue  # 已加密
                    try:
                        blob = f.read_bytes()
                        encrypted = self.crypter.encrypt_bytes(blob)
                        tmp = f.with_suffix(f.suffix + '.enc.tmp')
                        tmp.write_bytes(encrypted)
                        os.replace(tmp, f)
                    except Exception:
                        complete = False
            except Exception:
                complete = False
        if complete:
            try:
                marker.write_text(datetime.now().isoformat(), encoding='utf-8')
            except Exception:
                pass
