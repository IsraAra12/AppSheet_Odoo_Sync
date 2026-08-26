from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloudflare_worker" / "src"))

from rapyvet_api import (  # noqa: E402
    AsyncOdooService,
    CreateOrderRequest,
    OrderLine,
    Seller,
    Settings,
    dominio_clientes_odoo,
    hash_seller_password,
    verify_seller_password,
    whatsapp_summary,
)


class FakeCloudflareOdooService(AsyncOdooService):
    def __init__(self) -> None:
        super().__init__(
            Settings(
                odoo_url="https://odoo.example.com",
                odoo_db="db",
                odoo_user="user",
                odoo_password="password",
                access_pin="123456",
                session_secret="x" * 32,
                seller_temp_secret="temp-secret",
                frontend_origins=("http://localhost:3000",),
            )
        )
        self.created_values: dict[str, Any] | None = None

    async def _call(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        if model == "sale.order" and method == "search_read":
            return []
        if model == "res.partner" and method == "search_count":
            return 1
        if model == "product.product" and method == "search_read":
            return [{"id": 5}]
        if model == "sale.order" and method == "create":
            self.created_values = args[0]
            return 99
        if model == "sale.order" and method == "read":
            return [
                {
                    "id": 99,
                    "name": "S00099",
                    "state": "draft",
                    "amount_untaxed": 100,
                    "amount_tax": 16,
                    "amount_total": 116,
                }
            ]
        raise AssertionError(f"Unexpected call: {model}.{method}")


class CloudflareWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        service = getattr(self, "service", None)
        if service is not None:
            await service._http.aclose()

    async def test_order_payload_keeps_odoo_computed_fields(self) -> None:
        self.service = FakeCloudflareOdooService()
        result = await self.service.create_order(
            CreateOrderRequest(
                customer_id=10,
                lines=[OrderLine(product_id=5, quantity=2, unit_price=50)],
                idempotency_key="RV-12345678",
            ),
            seller=Seller(id=7, name="Vendedora Prueba", login="ventas@example.com"),
        )

        self.assertEqual(result.folio, "S00099")
        assert self.service.created_values is not None
        line = self.service.created_values["order_line"][0][2]
        self.assertNotIn("name", line)
        self.assertNotIn("product_uom", line)
        self.assertNotIn("tax_id", line)
        self.assertEqual(line["product_uom_qty"], 2)
        self.assertEqual(self.service.created_values["client_order_ref"], "RV-12345678")
        self.assertEqual(self.service.created_values["user_id"], 7)

    def test_worker_seller_hash_is_fast_and_seller_scoped(self) -> None:
        stored = hash_seller_password(
            "2468",
            secret="secret",
            seller_id=12,
            salt=b"1234567890123456",
        )
        self.assertTrue(
            verify_seller_password(
                "2468",
                stored,
                secret="secret",
                seller_id=12,
            )
        )
        self.assertFalse(
            verify_seller_password(
                "2468",
                stored,
                secret="secret",
                seller_id=13,
            )
        )

    def test_catalog_domain_includes_new_main_contacts(self) -> None:
        domain = dominio_clientes_odoo()
        self.assertIn(("customer_rank", ">", 0), domain)
        self.assertIn(("parent_id", "=", False), domain)
        self.assertIn(("type", "=", "contact"), domain)

    def test_whatsapp_message_still_includes_free_lines(self) -> None:
        message = whatsapp_summary(
            "Cliente Demo",
            CreateOrderRequest(
                customer_id=10,
                lines=[OrderLine(product_id=5, quantity=1, unit_price=0)],
                idempotency_key="RV-12345678",
            ),
            {5: "Medicamento Demo"},
            seller_name="Rosa",
        )
        self.assertIn("Cliente Demo", message)
        self.assertIn("Vendedor: Rosa", message)
        self.assertIn("1 x Medicamento Demo (GRATIS)", message)


if __name__ == "__main__":
    unittest.main()

