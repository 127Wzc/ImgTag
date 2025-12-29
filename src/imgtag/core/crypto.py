"""Cryptographic utilities for sensitive data encryption.

Provides AES encryption for S3 credentials and other sensitive configuration.
Uses Fernet (AES-128-CBC) with key derived from environment variable.
"""

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_fernet: Fernet | None = None


def get_encryption_key() -> bytes:
    """Derive encryption key from environment variable.
    
    Uses PBKDF2 to derive a secure key from the secret.
    Falls back to a default if IMGTAG_SECRET_KEY is not set.
    
    Returns:
        bytes: URL-safe base64 encoded 32-byte key for Fernet.
    """
    secret = os.environ.get("IMGTAG_SECRET_KEY", "imgtag-default-secret-change-me")
    salt = b"imgtag-credential-salt"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode()))


def get_fernet() -> Fernet:
    """Get or create Fernet cipher instance (singleton pattern).
    
    Returns:
        Fernet: Cipher instance for encrypt/decrypt operations.
    """
    global _fernet
    if _fernet is None:
        _fernet = Fernet(get_encryption_key())
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
