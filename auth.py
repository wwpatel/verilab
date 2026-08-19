"""
Password hashing and session management for the authenticated product.

Passwords: PBKDF2-HMAC-SHA256 with a random salt per user (stdlib only,
no extra dependency). Never stored or logged in plain text.

Sessions: a random opaque token in an httponly cookie, looked up against a
sessions table in SQLite. Real sign-out means deleting that row, not just
clearing a client-side value.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException, Request

import db

SESSION_COOKIE = "verilab_session"
PBKDF2_ITERATIONS = 260_000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, digest_hex = password_hash.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return hmac.compare_digest(expected.hex(), digest_hex)


def create_session_for_user(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    db.create_session(token, user_id, now_iso())
    return token


def get_current_user(request: Request) -> "db.sqlite3.Row":
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in.")
    session = db.get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired or invalid, please sign in again.")
    user = db.get_user_by_id(session["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user


def is_https_request(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
