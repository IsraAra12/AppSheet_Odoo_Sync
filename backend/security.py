from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque
from typing import Any


SESSION_TTL_SECONDS = 12 * 60 * 60


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


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session_token(secret: str, *, now: int | None = None) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "iat": issued_at,
        "exp": issued_at + SESSION_TTL_SECONDS,
        "aud": "rapyvet-pedidos",
    }
    encoded = _encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_encode(signature)}"


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
