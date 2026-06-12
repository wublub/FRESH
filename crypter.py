"""本地数据加密。"""
import base64
import ctypes
import hashlib
import os
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b'FENC1\n'  # 加密文件统一前缀，用来识别已加密 vs 历史明文
PASSWORD_KDF_ITERATIONS = 600_000
SALT_SIZE = 32
_FILE_ATTRIBUTE_HIDDEN = 0x02
_FILE_ATTRIBUTE_NORMAL = 0x80


class SaltFileError(Exception):
    """盐文件损坏或无法落盘。

    绝不能带着错误/临时的盐继续运行：用错误密钥加密落盘的数据
    在下次启动后将永久无法解密，所以这里必须中断并让上层提示用户。
    """


def _set_file_hidden(path: Path, hidden: bool) -> None:
    try:
        attr = _FILE_ATTRIBUTE_HIDDEN if hidden else _FILE_ATTRIBUTE_NORMAL
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attr)
    except Exception:
        pass


def _machine_id() -> str:
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography') as k:
            v, _ = winreg.QueryValueEx(k, 'MachineGuid')
            return str(v)
    except Exception:
        return os.getenv('COMPUTERNAME', 'unknown-machine')


def _user_id() -> str:
    return os.getenv('USERNAME', '') or os.getenv('USER', '') or 'unknown-user'


class Crypter:
    """本机绑定密钥加密器（无密码账户与历史数据使用）。"""

    # 历史版本存在明文数据，读取时允许明文回退以便迁移
    accepts_plaintext = True

    def __init__(self, app_dir: Path):
        self.app_dir = Path(app_dir)
        self.salt_file = self.app_dir / '.fkey'
        self._fernet = Fernet(self._derive_key())

    def _load_or_create_salt(self) -> bytes:
        if self.salt_file.exists():
            try:
                data = self.salt_file.read_bytes()
            except Exception as exc:
                raise SaltFileError(
                    f'无法读取密钥文件 {self.salt_file}（{exc}）。\n'
                    '为避免数据被错误密钥覆盖，已停止加载。请检查文件权限后重试。'
                ) from exc
            if len(data) >= SALT_SIZE:
                return data
            # 内容非法（半写/截断）：留底后报错。静默重建新盐会让旧数据永久无法解密。
            backup = self.salt_file.with_name(
                '.fkey.corrupt-' + datetime.now().strftime('%Y%m%d-%H%M%S')
            )
            try:
                _set_file_hidden(self.salt_file, False)
                os.replace(self.salt_file, backup)
            except Exception:
                backup = None
            raise SaltFileError(
                f'密钥文件 {self.salt_file} 已损坏'
                + (f'，原文件已备份为 {backup.name}' if backup else '')
                + '。\n请先从备份恢复密钥文件，再启动程序；直接重建密钥会导致旧数据永久无法解密。'
            )
        salt = os.urandom(SALT_SIZE)
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self._write_salt(salt)
        return salt

    def _write_salt(self, salt: bytes) -> None:
        tmp = self.salt_file.with_name('.fkey.tmp')
        try:
            if tmp.exists():
                _set_file_hidden(tmp, False)
            with open(tmp, 'wb') as fh:
                fh.write(salt)
                fh.flush()
                os.fsync(fh.fileno())
            if self.salt_file.exists():
                # Windows 对已存在的隐藏文件用 CREATE_ALWAYS 重写会报拒绝访问，先清属性
                _set_file_hidden(self.salt_file, False)
            os.replace(tmp, self.salt_file)
        except Exception as exc:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            raise SaltFileError(
                f'无法写入密钥文件 {self.salt_file}（{exc}）。\n'
                '为避免用临时密钥加密数据导致下次无法解密，已停止加载。'
            ) from exc
        _set_file_hidden(self.salt_file, True)

    def _derive_key(self) -> bytes:
        salt = self._load_or_create_salt()
        material = f'{_machine_id()}|{_user_id()}'.encode('utf-8') + b'|' + salt
        digest = hashlib.sha256(material).digest()
        return base64.urlsafe_b64encode(digest)

    def encrypt_bytes(self, data: bytes) -> bytes:
        return MAGIC + self._fernet.encrypt(data)

    def decrypt_bytes(self, blob: bytes) -> bytes:
        if not blob.startswith(MAGIC):
            # 历史明文：直接返回（仅本机密钥加密器保留该迁移路径）
            return blob
        return self._fernet.decrypt(blob[len(MAGIC):])

    def is_encrypted(self, blob: bytes) -> bool:
        return blob.startswith(MAGIC)


def derive_password_key(password: str, salt: bytes, iterations: int = PASSWORD_KDF_ITERATIONS) -> bytes:
    password_bytes = (password or '').encode('utf-8')
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=int(iterations or PASSWORD_KDF_ITERATIONS),
    )
    return base64.urlsafe_b64encode(kdf.derive(password_bytes))


class PasswordCrypter:
    """账户密码加密器。密钥只由用户密码和账户 salt 派生。"""

    # 密码账户从创建起全部加密写入，不存在合法明文
    accepts_plaintext = False

    def __init__(self, password: str, salt: bytes, iterations: int = PASSWORD_KDF_ITERATIONS):
        self.salt = salt
        self.iterations = int(iterations or PASSWORD_KDF_ITERATIONS)
        self._fernet = Fernet(derive_password_key(password, salt, self.iterations))

    def encrypt_bytes(self, data: bytes) -> bytes:
        return MAGIC + self._fernet.encrypt(data)

    def decrypt_bytes(self, blob: bytes) -> bytes:
        if not blob.startswith(MAGIC):
            # 密码账户创建起所有文件都是加密写入的，不存在合法明文。
            # 接受明文等于绕过 Fernet 的完整性校验（无密码者可整体替换注入）。
            raise InvalidToken('content is not encrypted')
        return self._fernet.decrypt(blob[len(MAGIC):])

    def is_encrypted(self, blob: bytes) -> bool:
        return blob.startswith(MAGIC)
