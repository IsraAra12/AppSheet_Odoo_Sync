from __future__ import annotations

import unittest

from backend.security import LoginThrottle, create_session_token, verify_pin, verify_session_token


class BackendSecurityTests(unittest.TestCase):
    def test_pin_uses_exact_comparison(self) -> None:
        self.assertTrue(verify_pin("123456", "123456"))
        self.assertFalse(verify_pin("123457", "123456"))

    def test_session_is_signed_and_expires(self) -> None:
        token = create_session_token("secret", now=1_000)
        self.assertTrue(verify_session_token(token, "secret", now=1_001))
        self.assertFalse(verify_session_token(token, "other", now=1_001))
        self.assertFalse(verify_session_token(token, "secret", now=100_000))

    def test_repeated_login_failures_are_limited_temporarily(self) -> None:
        throttle = LoginThrottle(attempts=2, window_seconds=60)
        self.assertTrue(throttle.allowed("device", now=100))
        throttle.failure("device", now=100)
        throttle.failure("device", now=101)
        self.assertFalse(throttle.allowed("device", now=102))
        self.assertTrue(throttle.allowed("device", now=162))


if __name__ == "__main__":
    unittest.main()
