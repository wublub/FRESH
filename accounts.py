"""Password based local accounts for FRESH."""
import base64
import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from cryptography.fernet import InvalidToken

from crypter import Crypter, PASSWORD_KDF_ITERATIONS, PasswordCrypter
from storage import default_app_root


VERIFIER_PREFIX = 'FRESH_ACCOUNT_VERIFIER:'
MIN_PASSWORD_LENGTH = 10
_REKEY_TMP_SUFFIX = '.rekey-tmp'
_REKEY_COMMIT_FLAG = '.rekey-commit'

class AccountError(Exception):
    pass


class AccountManager:
    def __init__(self, app_root: Path | None = None):
        self.app_root = Path(app_root) if app_root else default_app_root()
        self.accounts_dir = self.app_root / 'accounts'
        self.index_file = self.app_root / 'accounts.json'
        self.app_root.mkdir(parents=True, exist_ok=True)
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        # 旧数据归档目录（import_legacy_into 成功后记录，供界面提示）
        self.last_legacy_archive = None
        self._index = self._load_index()
        self._recover_pending_rekeys()

    def _load_index(self):
        if not self.index_file.exists():
            return {'version': 1, 'accounts': []}
        try:
            data = json.loads(self.index_file.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                return {'version': 1, 'accounts': []}
            accounts = data.get('accounts')
            if not isinstance(accounts, list):
                data['accounts'] = []
            data.setdefault('version', 1)
            return data
        except Exception:
            return {'version': 1, 'accounts': []}

    def _save_index(self):
        self.app_root.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self._index, ensure_ascii=False, indent=2)
        tmp = self.index_file.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.index_file)

    def _recover_pending_rekeys(self):
        """启动时恢复上次中断的改密/清密迁移。

        无需任何密码：提交阶段只剩重命名（新密文已在 .rekey-tmp 里），
        直接续传；未到提交阶段则回滚，原文件从未被改动。
        """
        changed = False
        for account in self._index.get('accounts') or []:
            account_dir = self.accounts_dir / account.get('id', '')
            if not account_dir.exists():
                account.pop('pending_rekey', None)
                continue
            pending = account.get('pending_rekey')
            commit_flag = account_dir / _REKEY_COMMIT_FLAG
            tmps = list(account_dir.rglob(f'*{_REKEY_TMP_SUFFIX}'))
            if pending and commit_flag.exists():
                # 提交阶段被打断：完成剩余重命名，然后晋升新密钥参数
                for tmp in tmps:
                    try:
                        os.replace(tmp, tmp.with_name(tmp.name[:-len(_REKEY_TMP_SUFFIX)]))
                    except Exception:
                        pass
                self._promote_pending(account, pending)
                try:
                    commit_flag.unlink()
                except Exception:
                    pass
                changed = True
                continue
            if pending or tmps or commit_flag.exists():
                # 未进入提交阶段：原文件完好，安全回滚
                for tmp in tmps:
                    try:
                        tmp.unlink()
                    except Exception:
                        pass
                try:
                    if commit_flag.exists():
                        commit_flag.unlink()
                except Exception:
                    pass
                if pending:
                    account.pop('pending_rekey', None)
                    changed = True
        if changed:
            self._save_index()

    @staticmethod
    def _promote_pending(account, pending):
        if pending.get('kind') == 'password':
            account['salt'] = pending.get('salt', '')
            account['iterations'] = pending.get('iterations') or PASSWORD_KDF_ITERATIONS
            account['verifier'] = pending.get('verifier', '')
            account['password_set_at'] = datetime.now().isoformat()
        else:
            account.pop('salt', None)
            account.pop('iterations', None)
            account.pop('verifier', None)
            account['password_cleared_at'] = datetime.now().isoformat()
        account['updated_at'] = datetime.now().isoformat()
        account.pop('pending_rekey', None)

    def accounts(self):
        return list(self._index.get('accounts') or [])

    def has_accounts(self):
        return bool(self.accounts())

    def account_dir(self, account) -> Path:
        return self.accounts_dir / account['id']

    def account_has_password(self, account) -> bool:
        return bool(account.get('verifier') and account.get('salt'))

    def passwordless_accounts(self):
        return [dict(account) for account in self.accounts() if not self.account_has_password(account)]

    def crypter_for_account(self, account):
        if self.account_has_password(account):
            return None
        return Crypter(self.account_dir(account))

    def get_account(self, account_id: str):
        for account in self.accounts():
            if account.get('id') == account_id:
                return dict(account)
        return None

    def _replace_account(self, updated):
        accounts = self._index.setdefault('accounts', [])
        for idx, account in enumerate(accounts):
            if account.get('id') == updated.get('id'):
                accounts[idx] = updated
                self._save_index()
                return dict(updated)
        raise AccountError('账户不存在。')

    def legacy_data_exists(self):
        return (self.app_root / 'data.json').exists()

    def unlock(self, password: str):
        if not password:
            return None, None
        for account in self.accounts():
            if not self.account_has_password(account):
                continue
            try:
                salt = base64.urlsafe_b64decode(account.get('salt', '').encode('ascii'))
                iterations = int(account.get('iterations') or PASSWORD_KDF_ITERATIONS)
                crypter = PasswordCrypter(password, salt, iterations)
                verifier = base64.urlsafe_b64decode(account.get('verifier', '').encode('ascii'))
                plain = crypter.decrypt_bytes(verifier).decode('utf-8')
            except (InvalidToken, ValueError, TypeError, UnicodeDecodeError):
                continue
            except Exception:
                continue
            if plain == VERIFIER_PREFIX + account.get('id', ''):
                return dict(account), crypter
        return None, None

    def unlock_passwordless(self, account_id: str):
        account = self.get_account(account_id)
        if not account or self.account_has_password(account):
            return None, None
        return account, Crypter(self.account_dir(account))

    def create_account(self, name: str, password: str = '', import_legacy: bool = False):
        name = (name or '').strip() or '我的账户'
        has_password = bool(password)
        if has_password:
            if len(password or '') < MIN_PASSWORD_LENGTH:
                raise AccountError(f'密码至少需要 {MIN_PASSWORD_LENGTH} 个字符。')
            existing, _ = self.unlock(password)
            if existing:
                raise AccountError('这个密码已经属于一个账户。请为新账户设置不同密码。')

        account_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        account = {
            'id': account_id,
            'name': name,
            'created_at': now,
        }
        if has_password:
            salt = os.urandom(32)
            crypter = PasswordCrypter(password, salt, PASSWORD_KDF_ITERATIONS)
            verifier = crypter.encrypt_bytes((VERIFIER_PREFIX + account_id).encode('utf-8'))
            account.update({
                'salt': base64.urlsafe_b64encode(salt).decode('ascii'),
                'iterations': PASSWORD_KDF_ITERATIONS,
                'verifier': base64.urlsafe_b64encode(verifier).decode('ascii'),
            })
        else:
            crypter = Crypter(self.account_dir(account))
        target_dir = self.account_dir(account)
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            if import_legacy:
                self.import_legacy_into(account, crypter)
                account['legacy_imported_at'] = datetime.now().isoformat()
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

        self._index.setdefault('accounts', []).append(account)
        self._save_index()
        return dict(account), crypter

    def ensure_default_account(self):
        if self.has_accounts():
            first = self.accounts()[0]
            if self.account_has_password(first):
                return dict(first), None
            return dict(first), Crypter(self.account_dir(first))
        return self.create_account('我的账户', '', import_legacy=self.legacy_data_exists())

    def rename_account(self, account_id: str, name: str):
        account = self.get_account(account_id)
        if not account:
            raise AccountError('账户不存在。')
        account['name'] = (name or '').strip() or '我的账户'
        account['updated_at'] = datetime.now().isoformat()
        return self._replace_account(account)

    def delete_account(self, account_id: str):
        account = self.get_account(account_id)
        if not account:
            raise AccountError('账户不存在。')

        target_dir = self.account_dir(account).resolve()
        accounts_root = self.accounts_dir.resolve()
        try:
            target_dir.relative_to(accounts_root)
        except ValueError:
            raise AccountError('账户目录异常，已取消删除。')

        accounts = self._index.setdefault('accounts', [])
        self._index['accounts'] = [
            item for item in accounts
            if item.get('id') != account.get('id')
        ]
        self._save_index()
        shutil.rmtree(target_dir, ignore_errors=True)
        return dict(account)

    def set_account_password(self, account, old_crypter, new_password: str):
        if len(new_password or '') < MIN_PASSWORD_LENGTH:
            raise AccountError(f'密码至少需要 {MIN_PASSWORD_LENGTH} 个字符。')
        existing, _ = self.unlock(new_password)
        if existing and existing.get('id') != account.get('id'):
            raise AccountError('这个密码已经属于另一个账户。请设置不同密码。')

        account = self.get_account(account.get('id'))
        if not account:
            raise AccountError('账户不存在。')
        target_dir = self.account_dir(account)
        salt = os.urandom(32)
        new_crypter = PasswordCrypter(new_password, salt, PASSWORD_KDF_ITERATIONS)
        verifier = new_crypter.encrypt_bytes((VERIFIER_PREFIX + account['id']).encode('utf-8'))
        pending = {
            'kind': 'password',
            'salt': base64.urlsafe_b64encode(salt).decode('ascii'),
            'iterations': PASSWORD_KDF_ITERATIONS,
            'verifier': base64.urlsafe_b64encode(verifier).decode('ascii'),
            'started_at': datetime.now().isoformat(),
        }
        account = self._run_rekey(account, target_dir, old_crypter, new_crypter, pending)
        return account, new_crypter

    def clear_account_password(self, account, old_crypter):
        account = self.get_account(account.get('id'))
        if not account:
            raise AccountError('账户不存在。')
        if not self.account_has_password(account):
            return account, Crypter(self.account_dir(account))
        target_dir = self.account_dir(account)
        new_crypter = Crypter(target_dir)
        pending = {
            'kind': 'machine',
            'started_at': datetime.now().isoformat(),
        }
        account = self._run_rekey(account, target_dir, old_crypter, new_crypter, pending)
        return account, new_crypter

    def _run_rekey(self, account, target_dir: Path, old_crypter, new_crypter, pending):
        """两阶段重加密：

        1. 先把新密钥参数作为 pending_rekey 落盘（新 salt 绝不能只存在内存里，
           否则中途崩溃后已转换的文件在密码学上永久不可恢复）；
        2. 把所有文件加密成 .rekey-tmp 旁路副本，原文件保持原样，任何失败都
           能无损回滚；
        3. 提交阶段只做纯重命名（写 .rekey-commit 标记），崩溃后启动时无需
           密码即可续传，最后晋升 pending 为正式密钥参数。
        """
        account['pending_rekey'] = pending
        account = self._replace_account(account)
        try:
            self._reencrypt_account_files(target_dir, old_crypter, new_crypter)
        except Exception:
            account.pop('pending_rekey', None)
            self._replace_account(account)
            raise
        self._promote_pending(account, pending)
        account = self._replace_account(account)
        try:
            (target_dir / _REKEY_COMMIT_FLAG).unlink()
        except Exception:
            pass
        return account

    def _reencrypt_account_files(self, target_dir: Path, old_crypter, new_crypter):
        files = [target_dir / 'data.json']
        for dirname in ('attachments', 'trash'):
            folder = target_dir / dirname
            if folder.exists():
                files.extend(path for path in folder.iterdir() if path.is_file() and not path.name.startswith('.'))
        staged = []
        try:
            for path in files:
                if not path.exists() or not path.is_file():
                    continue
                if path.name.endswith(_REKEY_TMP_SUFFIX):
                    continue
                blob = path.read_bytes()
                plain = old_crypter.decrypt_bytes(blob) if old_crypter and old_crypter.is_encrypted(blob) else blob
                encrypted = new_crypter.encrypt_bytes(plain)
                tmp = path.with_name(path.name + _REKEY_TMP_SUFFIX)
                tmp.write_bytes(encrypted)
                staged.append((tmp, path))
        except Exception:
            # 准备阶段失败：原文件未动，清掉旁路副本即可完整回滚
            for tmp, _ in staged:
                try:
                    tmp.unlink()
                except Exception:
                    pass
            raise
        # 提交阶段：只剩重命名。标记文件让崩溃后的启动恢复能识别该阶段。
        commit_flag = target_dir / _REKEY_COMMIT_FLAG
        with open(commit_flag, 'w', encoding='utf-8') as fh:
            fh.write(datetime.now().isoformat())
            fh.flush()
            os.fsync(fh.fileno())
        for tmp, path in staged:
            os.replace(tmp, path)

    def import_legacy_into(self, account, crypter: PasswordCrypter):
        legacy_data = self.app_root / 'data.json'
        if not legacy_data.exists():
            return False

        target_dir = self.account_dir(account)
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / 'attachments').mkdir(parents=True, exist_ok=True)
        (target_dir / 'trash').mkdir(parents=True, exist_ok=True)

        legacy_crypter = Crypter(self.app_root)
        raw = legacy_data.read_bytes()
        payload = legacy_crypter.decrypt_bytes(raw) if legacy_crypter.is_encrypted(raw) else raw
        notes = json.loads(payload.decode('utf-8'))
        if not isinstance(notes, list):
            notes = []

        self._copy_legacy_blob_dir('attachments', legacy_crypter, crypter, target_dir)
        self._copy_legacy_blob_dir('trash', legacy_crypter, crypter, target_dir)
        scan_settings = self.app_root / 'scan_settings.json'
        if scan_settings.exists():
            try:
                shutil.copy2(scan_settings, target_dir / 'scan_settings.json')
            except Exception:
                pass

        encrypted = crypter.encrypt_bytes(json.dumps(notes, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        tmp = (target_dir / 'data.json').with_suffix('.json.tmp')
        tmp.write_bytes(encrypted)
        os.replace(tmp, target_dir / 'data.json')
        self._archive_legacy_data()
        return True

    def _archive_legacy_data(self):
        """导入完成后把 app_root 下的旧数据归档。

        旧副本只受本机密钥保护（盐就在旁边的 .fkey 里），原样留在原地会让
        之后设置的账户密码形同虚设；归档后由界面提示用户确认删除。
        """
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        archive_dir = self.app_root / f'legacy_backup_{stamp}'
        moved_any = False
        for name in ('data.json', 'attachments', 'trash'):
            src = self.app_root / name
            if not src.exists():
                continue
            try:
                archive_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(archive_dir / name))
                moved_any = True
            except Exception:
                pass
        if moved_any:
            self.last_legacy_archive = archive_dir

    def _copy_legacy_blob_dir(self, name: str, legacy_crypter: Crypter, crypter: PasswordCrypter, target_dir: Path):
        src_dir = self.app_root / name
        dst_dir = target_dir / name
        if not src_dir.exists():
            return
        for src in src_dir.iterdir():
            if not src.is_file() or src.name.startswith('.'):
                continue
            try:
                blob = src.read_bytes()
                plain = legacy_crypter.decrypt_bytes(blob) if legacy_crypter.is_encrypted(blob) else blob
                (dst_dir / src.name).write_bytes(crypter.encrypt_bytes(plain))
            except Exception:
                pass
