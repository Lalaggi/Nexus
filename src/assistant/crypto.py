"""At-rest encryption for sensitive values stored in SQLite.

The database holds chat transcripts, tool output, notes, and API keys. Encrypting
individual fields means a database file that is copied, backed up, or committed
by accident is not readable without the key. The key lives outside the project
directory (or in ``ASSISTANT_ENCRYPTION_KEY``), so it is not swept up with the
database in a normal ``git add``.
"""

from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"


class EncryptionError(RuntimeError):
    """Raised when encrypted data cannot be read with the configured key."""


def _fernet_key(secret: str) -> bytes:
    """Accept either a Fernet key or a plain passphrase."""
    raw = secret.strip()
    if not raw:
        raise EncryptionError("The encryption key is empty.")
    candidate = raw.encode("ascii", "ignore")
    try:
        Fernet(candidate)
        return candidate
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


def _read_or_create_key(path: Path) -> bytes:
    if path.exists():
        return _fernet_key(path.read_text(encoding="utf-8"))

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    key = Fernet.generate_key()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        # Another process won the race; use the key it wrote.
        return _fernet_key(path.read_text(encoding="utf-8"))
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key.decode("ascii"))
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key


class Cipher:
    """Small wrapper around Fernet with a recognizable ciphertext prefix."""

    def __init__(self, key: bytes | str):
        key_bytes = _fernet_key(key) if isinstance(key, str) else key
        self._fernet = Fernet(key_bytes)
        # Fail early (and clearly) if the key is malformed.
        self._fernet.decrypt(self._fernet.encrypt(b"assistant-encryption-probe"))

    @staticmethod
    def is_encrypted(value: str | None) -> bool:
        return bool(value and value.startswith(PREFIX))

    def encrypt(self, value: str | None) -> str:
        if not value:
            return value or ""
        if self.is_encrypted(value):
            return value
        token = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{PREFIX}{token}"

    def decrypt(self, value: str | None) -> str:
        if not value:
            return value or ""
        if not self.is_encrypted(value):
            # Databases created before encryption was introduced are read
            # transparently; connect() migrates them in place.
            return value
        try:
            raw = self._fernet.decrypt(value[len(PREFIX) :].encode("ascii"))
        except (InvalidToken, ValueError) as exc:
            raise EncryptionError(
                "Encrypted data could not be read. The encryption key is missing or "
                "does not match this database."
            ) from exc
        return raw.decode("utf-8")


@lru_cache(maxsize=1)
def get_cipher() -> Cipher:
    from .config import CONFIG

    if CONFIG.encryption_key.strip():
        return Cipher(_fernet_key(CONFIG.encryption_key))
    return Cipher(_read_or_create_key(CONFIG.secret_key_path))
