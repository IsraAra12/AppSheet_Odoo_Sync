from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cloudflare_worker" / "src"))

from rapyvet_api import (  # noqa: E402
    AsyncOdooService,
    CatalogResponse,
    CreateClientRequest,
    CreateOrderRequest,
    OrderLine,
    Seller,
    Settings,
    UpdateOrderRequest,
    dominio_clientes_odoo,
    hash_seller_password,
    verify_seller_password,
    whatsapp_summary,
)

IVA_16 = {
    "id": 1,
    "name": "IVA 16%",
    "amount": 16,
    "amount_type": "percent",
    "price_include": False,
    "include_base_amount": False,
    "is_base_affected": True,
    "sequence": 1,
    "children_tax_ids": [],
}


class FakeKV:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def put(self, key: str, value: str) -> None:
        self.values[key] = value


class FakeCloudflareOdooService(AsyncOdooService):
    def __init__(self, seller_auth_store: Any | None = None) -> None:
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
            ),
            seller_auth_store=seller_auth_store,
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
        if model == "ir.config_parameter" and method == "set_param":
            raise AssertionError("Cloudflare Worker should save seller keys in KV, not Odoo config.")
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

    async def test_seller_password_change_uses_kv_not_odoo_config(self) -> None:
        kv = FakeKV()
        self.service = FakeCloudflareOdooService(seller_auth_store=kv)
        seller = Seller(id=7, name="Robert Lucio", login="ventas@example.com")

        await self.service._write_seller_auth(
            seller,
            "1357",
            must_change_password=False,
        )

        key = "rapyvet.pedidos.seller_auth.v1.7"
        self.assertIn(key, kv.values)
        record = await self.service._read_seller_auth(seller.id)
        assert record is not None
        self.assertFalse(record["must_change_password"])
        self.assertTrue(
            verify_seller_password(
                "1357",
                record["password_hash"],
                secret=self.service.settings.seller_temp_secret,
                seller_id=seller.id,
            )
        )

    async def test_update_order_reports_updated_status(self) -> None:
        self.service = FakeCloudflareOdooService()
        written: dict[str, Any] = {}

        async def fake_call(model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
            if model == "sale.order" and method == "search_read":
                return [{"id": 99, "state": "draft"}]
            if model == "res.partner" and method == "search_read":
                return [{"id": 10, "name": "Cliente Demo", "commercial_partner_id": [10, "Cliente Demo"]}]
            if model == "product.product" and method == "search_read":
                return [{"id": 5}]
            if model == "sale.order" and method == "write":
                written.update(args[1])
                return True
            if model == "sale.order" and method == "read":
                return [{"id": 99, "name": "S00099", "state": "draft", "amount_untaxed": 100, "amount_tax": 16, "amount_total": 116}]
            raise AssertionError(f"Unexpected call: {model}.{method}")

        self.service._call = fake_call  # type: ignore[method-assign]
        result = await self.service.update_order(
            99,
            UpdateOrderRequest(customer_id=10, lines=[OrderLine(product_id=5, quantity=1, unit_price=100)]),
            seller=Seller(id=7, name="Vendedora Prueba", login="ventas@example.com"),
        )

        self.assertEqual(result.status, "Pedido actualizado")
        self.assertEqual(result.total, 116)
        self.assertEqual(written["order_line"][0], (5, 0, 0))

    async def test_new_client_is_created_as_person_with_is_company(self) -> None:
        self.service = FakeCloudflareOdooService()
        created: dict[str, Any] = {}

        async def fake_call(model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
            if model == "res.partner" and method == "search_read":
                return []
            if model == "res.partner" and method == "create":
                created.update(args[0])
                return 55
            if model == "res.partner" and method == "read":
                return [{"id": 55, "name": "Cliente Nuevo", "email": "nuevo@example.com", "street": "Calle 123", "zip": "64000", "vat": ""}]
            raise AssertionError(f"Unexpected call: {model}.{method}")

        self.service._call = fake_call  # type: ignore[method-assign]
        result = await self.service.create_client(
            CreateClientRequest(name="Cliente Nuevo", email="nuevo@example.com", street="Calle 123", postal_code="64000")
        )

        self.assertTrue(result["created"])
        self.assertIs(created["is_company"], False)
        self.assertNotIn("company_type", created)

    async def test_catalog_includes_taxes_for_prices_with_iva(self) -> None:
        self.service = FakeCloudflareOdooService()

        async def fake_call(model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
            if model == "res.partner":
                return []
            if model == "product.product":
                return [{"id": 5, "default_code": "NX1", "name": "NexGard", "list_price": 100, "categ_id": [1, "Antiparasitarios"], "taxes_id": [1]}]
            if model == "account.tax":
                return [IVA_16]
            raise AssertionError(f"Unexpected call: {model}.{method}")

        self.service._call = fake_call  # type: ignore[method-assign]
        catalog = await self.service.catalog(force=True)

        CatalogResponse(**catalog)
        self.assertEqual(catalog["products"][0]["tax_ids"], [1])
        self.assertEqual(catalog["taxes"][0]["amount"], 16.0)
        self.assertFalse(catalog["taxes"][0]["price_include"])

    async def test_catalog_still_loads_when_taxes_are_not_readable(self) -> None:
        self.service = FakeCloudflareOdooService()

        async def fake_call(model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
            if model == "account.tax":
                raise RuntimeError("Acceso denegado")
            return []

        self.service._call = fake_call  # type: ignore[method-assign]
        catalog = await self.service.catalog(force=True)
        self.assertEqual(catalog["taxes"], [])

    async def test_statement_uses_invoice_date(self) -> None:
        self.service = FakeCloudflareOdooService()

        async def fake_call(model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None) -> Any:
            if model == "res.partner" and method == "search_read":
                return [{"id": 10, "name": "Cliente Demo", "commercial_partner_id": [10, "Cliente Demo"]}]
            if model == "account.move.line" and method == "search_read":
                return [{
                    "id": 1,
                    "date": "2026-08-01",
                    "invoice_date": "2026-07-28",
                    "date_maturity": "2026-08-27",
                    "move_id": [3, "INV/2026/01170 (S01174)"],
                    "name": "",
                    "ref": "S01174",
                    "amount_residual": 5666.18,
                    "debit": 5666.18,
                    "credit": 0,
                    "currency_id": False,
                }]
            raise AssertionError(f"Unexpected call: {model}.{method}")

        self.service._call = fake_call  # type: ignore[method-assign]
        statement = await self.service.customer_statement(10)
        self.assertEqual(statement["lines"][0]["date"], "2026-07-28")
        self.assertEqual(statement["lines"][0]["document"], "INV/2026/01170 (S01174)")

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
