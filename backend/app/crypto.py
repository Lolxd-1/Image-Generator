"""Fernet encryption for API keys stored at rest, plus a display-safe hint."""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.errors import AppError


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.FERNET_KEY
    return Fernet(key.encode("utf-8") if isinstance(key, str) else key)


def encrypt(plain: str) -> str:
    """Encrypt a plaintext secret. Returns urlsafe-base64 ciphertext."""
    return _fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a Fernet token. Raises validation_failed on a corrupt/rotated
    token — never re-raises the underlying cryptography error, which could
    otherwise leak ciphertext or key material in a traceback."""
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        raise AppError(
            "validation_failed",
            "Stored key could not be decrypted; it may be corrupt or the encryption key changed.",
            status=400,
        )


def key_hint(plain: str) -> str:
    """Last-4-chars hint used by the UI. Never store or return more than this."""
    return "…" + plain[-4:]
