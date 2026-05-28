"""本地数据加密。"""
import base64
import ctypes
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

MAGIC = b'FENC1\n'  # 加密文件统一前缀，用来识别已加密 vs 历史明文
PASSWORD_KDF_ITERATIONS = 600_000


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
    """旧版本机密钥加密器。

    仍然保留，用于读取和迁移已经存在的旧数据。
    """

    def __init__(self, app_dir: Path):
        self.app_dir = Path(app_dir)
        self.salt_file = self.app_dir / '.fkey'
        self._fernet = Fernet(self._derive_key())

    def _load_or_create_salt(self) -> bytes:
        if self.salt_file.exists():
            try:
                data = self.salt_file.read_bytes()
                if len(data) >= 32:
                    return data
            except Exception:
                pass
        salt = os.urandom(32)
        self.app_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.salt_file.write_bytes(salt)
        except Exception:
            pass
        # 隐藏文件（Windows）
        try:
            ctypes.windll.kernel32.SetFileAttributesW(str(self.salt_file), 0x02)
        except Exception:
            pass
        return salt

    def _derive_key(self) -> bytes:
        salt = self._load_or_create_salt()
        material = f'{_machine_id()}|{_user_id()}'.encode('utf-8') + b'|' + salt
        digest = hashlib.sha256(material).digest()
        return base64.urlsafe_b64encode(digest)

    def encrypt_bytes(self, data: bytes) -> bytes:
        return MAGIC + self._fernet.encrypt(data)

    def decrypt_bytes(self, blob: bytes) -> bytes:
        if not blob.startswith(MAGIC):
            # 历史明文：直接返回
            return blob
        try:
            return self._fernet.decrypt(blob[len(MAGIC):])
        except InvalidToken:
            raise

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

    def __init__(self, password: str, salt: bytes, iterations: int = PASSWORD_KDF_ITERATIONS):
        self.salt = salt
        self.iterations = int(iterations or PASSWORD_KDF_ITERATIONS)
        self._fernet = Fernet(derive_password_key(password, salt, self.iterations))

    def encrypt_bytes(self, data: bytes) -> bytes:
        return MAGIC + self._fernet.encrypt(data)

    def decrypt_bytes(self, blob: bytes) -> bytes:
        if not blob.startswith(MAGIC):
            return blob
        try:
            return self._fernet.decrypt(blob[len(MAGIC):])
        except InvalidToken:
            raise

    def is_encrypted(self, blob: bytes) -> bool:
        return blob.startswith(MAGIC)
