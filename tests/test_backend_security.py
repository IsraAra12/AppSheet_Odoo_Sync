from __future__ import annotations

import unittest

from backend.security import (
    LoginThrottle,
    create_session_token,
    hash_password,
    hash_seller_password,
    password_errors,
    read_session_token,
    verify_password,
    verify_pin,
    verify_seller_password,
    verify_session_token,
)


class BackendSecurityTests(unittest.TestCase):
    def test_pin_uses_exact_comparison(self) -> None:
        self.assertTrue(verify_pin("123456", "123456"))
        self.assertFalse(verify_pin("123457", "123456"))

    def test_session_is_signed_and_expires(self) -> None:
        token = create_session_token("secret", now=1_000)
        self.assertTrue(verify_session_token(token, "secret", now=1_001))
        self.assertFalse(verify_session_token(token, "other", now=1_001))
        self.assertFalse(verify_session_token(token, "secret", now=100_000))

    def test_session_carries_seller_identity(self) -> None:
        token = create_session_token(
            "secret",
            seller={
                "id": 7,
                "name": "Vendedora Prueba",
                "login": "ventas@example.com",
                "email": "ventas@example.com",
            },
            must_change_password=True,
            now=1_000,
        )
        session = read_session_token(token, "secret", now=1_001)
        assert session is not None
        self.assertEqual(session.seller.id, 7)
        self.assertEqual(session.seller.login, "ventas@example.com")
        self.assertTrue(session.must_change_password)

    def test_password_hashing_and_policy(self) -> None:
        stored = hash_password("2026", salt=b"1234567890123456")
        self.assertTrue(verify_password("2026", stored))
        self.assertFalse(verify_password("2027", stored))
        self.assertEqual(password_errors("2026"), [])
        self.assertEqual(password_errors("1234"), [])
        self.assertTrue(password_errors("123"))
        self.assertTrue(password_errors("12345"))
        self.assertTrue(password_errors("abcd"))

    def test_seller_password_hashing_keeps_legacy_support(self) -> None:
        seller_hash = hash_seller_password(
            "2026",
            secret="secret",
            seller_id=7,
            salt=b"1234567890123456",
        )
        self.assertTrue(
            verify_seller_password(
                "2026",
                seller_hash,
                secret="secret",
                seller_id=7,
            )
        )
        self.assertFalse(
            verify_seller_password(
                "2027",
                seller_hash,
                secret="secret",
                seller_id=7,
            )
        )
        self.assertFalse(
            verify_seller_password(
                "2026",
                seller_hash,
                secret="secret",
                seller_id=8,
            )
        )

        legacy_hash = hash_password("4321", salt=b"1234567890123456")
        self.assertTrue(
            verify_seller_password(
                "4321",
                legacy_hash,
                secret="secret",
                seller_id=7,
            )
        )


    def test_repeated_login_failures_are_limited_temporarily(self) -> None:
        throttle = LoginThrottle(attempts=2, window_seconds=60)
        self.assertTrue(throttle.allowed("device", now=100))
        throttle.failure("device", now=100)
        throttle.failure("device", now=101)
        self.assertFalse(throttle.allowed("device", now=102))
        self.assertTrue(throttle.allowed("device", now=162))


if __name__ == "__main__":
    unittest.main()
