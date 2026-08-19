"""
Encrypts each user's stored Anthropic API key at rest.

Uses Fernet (symmetric, authenticated encryption) keyed off
VERILAB_ENCRYPTION_KEY. If that variable isn't set yet (first run), a key
is generated once and appended to .env so it persists across restarts,
the same pattern this project already uses for ANTHROPIC_API_KEY. Losing
this key makes previously stored user API keys unrecoverable, so it is
never regenerated once it exists.
"""

import os
from pathlib import Path

from cryptography.fernet import Fernet

ENV_PATH = Path(__file__).parent / ".env"
ENV_VAR = "VERILAB_ENCRYPTION_KEY"


def _load_or_create_key() -> bytes:
    key = os.environ.get(ENV_VAR)
    if key:
        return key.encode()

    key = Fernet.generate_key()
    with open(ENV_PATH, "a") as f:
        f.write(f"\n{ENV_VAR}={key.decode()}\n")
    os.environ[ENV_VAR] = key.decode()
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_api_key(plaintext_key: str) -> str:
    return _fernet.encrypt(plaintext_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    return _fernet.decrypt(encrypted_key.encode()).decode()


def mask_api_key(plaintext_key: str) -> str:
    if len(plaintext_key) <= 8:
        return "*" * len(plaintext_key)
    return plaintext_key[:6] + "*" * 10 + plaintext_key[-4:]
