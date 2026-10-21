"""敏感数据加密；运行时密钥在启动自检提交后安装。"""

import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_fernet: Fernet | None = None
LEGACY_DEFAULT_SECRET = "imgtag-default-secret-change-me"


def derive_encryption_key(secret: str) -> bytes:
    """保持旧版派生算法，确保旧环境变量和旧默认密文可迁移。"""
    salt = b"imgtag-credential-salt"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def configure_encryption_key(key: bytes) -> None:
    """仅在数据库初始化或轮换事务提交后切换进程内密钥。"""
    global _fernet
    _fernet = Fernet(key)


def get_fernet() -> Fernet:
    """启动自检未完成时禁止提前使用环境变量密钥读写旧数据。"""
    if _fernet is None:
        raise RuntimeError("加密密钥尚未完成启动初始化")
    return _fernet


def encrypt(value: str) -> str:
    """Encrypt a string value.
    
    Args:
        value: Plain text string to encrypt.
        
    Returns:
        str: Base64-encoded encrypted string.
    """
    if not value:
        return ""
    return get_fernet().encrypt(value.encode()).decode()


def decrypt(encrypted: str) -> str:
    """Decrypt an encrypted string value.
    
    Args:
        encrypted: Base64-encoded encrypted string.
        
    Returns:
        str: Decrypted plain text string.
    """
    if not encrypted:
        return ""
    return get_fernet().decrypt(encrypted.encode()).decode()
