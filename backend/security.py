"""Password hashing and signed session tokens, standard library first.

PBKDF2-HMAC-SHA256 from hashlib for passwords; PyJWT for tokens when it is
installed, otherwise an HMAC-signed token of the same shape. Both paths are
signed with the same secret, which is generated once and kept on disk.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SECRET_FILE = os.path.join(ROOT, "data", ".jwt_secret")
_ITERATIONS = 240_000
TOKEN_TTL_SECONDS = 12 * 60 * 60


def _secret() -> str:
    env = os.environ.get("NAVHRIDYA_SECRET") or os.environ.get("JWT_SECRET")
    if env:
        return env
    os.makedirs(os.path.dirname(_SECRET_FILE), exist_ok=True)
    if not os.path.exists(_SECRET_FILE):
        with open(_SECRET_FILE, "w", encoding="utf-8") as fh:
            fh.write(secrets.token_hex(32))
    with open(_SECRET_FILE, encoding="utf-8") as fh:
        return fh.read().strip()


# ------------------------------------------------------------------ passwords
def hash_password(raw: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(raw: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", raw.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------------- tokens
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def create_token(username: str) -> str:
    payload = {"sub": username, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    try:
        import jwt  # PyJWT
        return jwt.encode(payload, _secret(), algorithm="HS256")
    except Exception:
        head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        sig = hmac.new(_secret().encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
        return f"{head}.{body}.{_b64(sig)}"


def read_token(token: str) -> Optional[str]:
    """Return the username if the token is valid and unexpired, else None."""
    if not token:
        return None
    try:
        import jwt
        data = jwt.decode(token, _secret(), algorithms=["HS256"])
        return data.get("sub")
    except ImportError:
        pass
    except Exception:
        return None

    try:
        head, body, sig = token.split(".")
        expected = hmac.new(_secret().encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(sig), expected):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("sub")
    except Exception:
        return None
