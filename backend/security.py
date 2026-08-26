from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


SESSION_TTL_SECONDS = 12 * 60 * 60
PASSWORD_ITERATIONS = 210_000
SELLER_HASH_ALGORITHM = "hmac_sha256"
SELLER_HASH_VERSION = "v1"


@dataclass(frozen=True)
class SessionSeller:
    id: int
    name: str
    login: str
    email: str = ""


@dataclass(frozen=True)
class SessionData:
    seller: SessionSeller
    must_change_password: bool
    expires_at: int


class LoginThrottle:
    """Límite pequeño en memoria para frenar intentos repetidos de acceso."""

    def __init__(self, *, attempts: int = 5, window_seconds: int = 300) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        failures = self._failures[key]
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
            return deque()
        return failures

    def allowed(self, key: str, *, now: float | None = None) -> bool:
        current = float(now if now is not None else time.time())
        with self._lock:
            return len(self._prune(key, current)) < self.attempts

    def failure(self, key: str, *, now: float | None = None) -> None:
        current = float(now if now is not None else time.time())
        with self._lock:
            failures = self._prune(key, current)
            if key not in self._failures:
                self._failures[key] = failures
            failures.append(current)

    def success(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def verify_pin(provided: str, configured: str) -> bool:
    return hmac.compare_digest(
        str(provided).strip().encode("utf-8"),
        str(configured).strip().encode("utf-8"),
    )


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    raw_salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        raw_salt,
        PASSWORD_ITERATIONS,
    )
    return (
        f"pbkdf2_sha256${PASSWORD_ITERATIONS}$"
        f"{_encode(raw_salt)}${_encode(digest)}"
    )


def verify_password(provided: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_digest = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            provided.encode("utf-8"),
            _decode(encoded_salt),
            int(iterations),
        )
        return hmac.compare_digest(digest, _decode(encoded_digest))
    except (ValueError, TypeError, OSError, binascii.Error):
        return False


def hash_seller_password(
    password: str,
    *,
    secret: str,
    seller_id: int,
    salt: bytes | None = None,
) -> str:
    """Genera un hash rápido y seguro para NIPs de vendedores.

    Los NIPs son de 4 dígitos, así que la seguridad real viene del secreto de
    servidor. Este formato evita cálculos pesados en runtimes serverless como
    Cloudflare Workers, donde PBKDF2 con muchas iteraciones puede exceder CPU.
    """

    raw_salt = salt or os.urandom(16)
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{int(seller_id)}:{_encode(raw_salt)}:{password}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return (
        f"{SELLER_HASH_ALGORITHM}${SELLER_HASH_VERSION}$"
        f"{_encode(raw_salt)}${_encode(digest)}"
    )


def verify_seller_password(
    provided: str,
    stored_hash: str,
    *,
    secret: str,
    seller_id: int,
) -> bool:
    """Valida hashes nuevos HMAC y conserva soporte para hashes PBKDF2 antiguos."""

    try:
        algorithm, version, encoded_salt, encoded_digest = stored_hash.split("$", 3)
    except (ValueError, TypeError):
        return verify_password(provided, stored_hash)

    if algorithm != SELLER_HASH_ALGORITHM:
        return verify_password(provided, stored_hash)
    if version != SELLER_HASH_VERSION:
        return False

    expected = hmac.new(
        secret.encode("utf-8"),
        f"{int(seller_id)}:{encoded_salt}:{provided}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    try:
        return hmac.compare_digest(expected, _decode(encoded_digest))
    except binascii.Error:
        return False


def password_errors(password: str) -> list[str]:
    errors: list[str] = []
    cleaned = password.strip()
    if len(cleaned) != 4 or not cleaned.isdigit():
        errors.append("El NIP debe ser exactamente de 4 dígitos numéricos.")
    return errors



def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session_token(
    secret: str,
    *,
    seller: Mapping[str, Any] | None = None,
    must_change_password: bool = False,
    now: int | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "iat": issued_at,
        "exp": issued_at + SESSION_TTL_SECONDS,
        "aud": "rapyvet-pedidos",
    }
    if seller:
        payload["seller"] = {
            "id": int(seller["id"]),
            "name": str(seller["name"]),
            "login": str(seller["login"]),
            "email": str(seller.get("email") or ""),
        }
        payload["must_change_password"] = bool(must_change_password)
    encoded = _encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_encode(signature)}"


def read_session_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
) -> SessionData | None:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(supplied_signature), expected):
            return None
        payload: dict[str, Any] = json.loads(_decode(encoded))
        current = int(now if now is not None else time.time())
        if not (
            payload.get("aud") == "rapyvet-pedidos"
            and int(payload.get("iat", 0)) <= current + 30
            and int(payload.get("exp", 0)) > current
        ):
            return None
        seller = payload.get("seller")
        if not isinstance(seller, dict):
            return None
        return SessionData(
            seller=SessionSeller(
                id=int(seller["id"]),
                name=str(seller["name"]),
                login=str(seller["login"]),
                email=str(seller.get("email") or ""),
            ),
            must_change_password=bool(payload.get("must_change_password")),
            expires_at=int(payload["exp"]),
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error):
        return None


def verify_session_token(
    token: str,
    secret: str,
    *,
    now: int | None = None,
) -> bool:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected = hmac.new(
            secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_decode(supplied_signature), expected):
            return False
        payload: dict[str, Any] = json.loads(_decode(encoded))
        current = int(now if now is not None else time.time())
        return (
            payload.get("aud") == "rapyvet-pedidos"
            and int(payload.get("iat", 0)) <= current + 30
            and int(payload.get("exp", 0)) > current
        )
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False
