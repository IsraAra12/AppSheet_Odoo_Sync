from __future__ import annotations

import unittest

from rapyvet.odoo_rpc import (
    TimeoutSafeTransport,
    TimeoutTransport,
    crear_proxy_odoo,
)


class OdooRpcTests(unittest.TestCase):
    def test_https_usa_transporte_seguro_con_timeout(self) -> None:
        proxy = crear_proxy_odoo(
            "https://odoo.example.com",
            "/xmlrpc/2/object",
            timeout=7,
        )
        self.assertIsInstance(proxy("transport"), TimeoutSafeTransport)
        self.assertEqual(proxy("transport").timeout, 7)

    def test_http_usa_transporte_con_timeout(self) -> None:
        proxy = crear_proxy_odoo(
            "http://localhost:8069",
            "/xmlrpc/2/common",
            timeout=3,
        )
        self.assertIsInstance(proxy("transport"), TimeoutTransport)
        self.assertEqual(proxy("transport").timeout, 3)

    def test_rechaza_url_sin_protocolo(self) -> None:
        with self.assertRaises(ValueError):
            crear_proxy_odoo("odoo.example.com", "/xmlrpc/2/object")


if __name__ == "__main__":
    unittest.main()

