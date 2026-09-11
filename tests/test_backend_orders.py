from __future__ import annotations

import unittest
from typing import Any

from backend.config import Settings
from backend.odoo_service import OdooService, Seller
from backend.schemas import CatalogResponse, CreateOrderRequest, OrderLine


class FakeOdooService(OdooService):
    def __init__(self) -> None:
        super().__init__(
            Settings(
                odoo_url="https://odoo.example.com",
                odoo_db="db",
                odoo_user="user",
                odoo_password="password",
                access_pin="1234",
                session_secret="secret",
                seller_temp_secret="temp-secret",
                frontend_origins=("http://localhost:3000",),
            )
        )
        self.created_values: dict[str, Any] | None = None

    def _models(self) -> object:
        return object()

    def _call(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        *,
        proxy: Any | None = None,
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


class BackendOrderTests(unittest.TestCase):
    def test_order_lets_odoo_compute_description(self) -> None:
        service = FakeOdooService()
        result = service.create_order(
            CreateOrderRequest(
                customer_id=10,
                lines=[OrderLine(product_id=5, quantity=2, unit_price=50)],
                idempotency_key="RV-12345678",
            ),
            seller=Seller(id=7, name="Vendedora Prueba", login="ventas@example.com"),
        )

        self.assertEqual(result.folio, "S00099")
        assert service.created_values is not None
        line = service.created_values["order_line"][0][2]
        self.assertNotIn("name", line)
        self.assertNotIn("product_uom", line)
        self.assertNotIn("tax_id", line)
        self.assertEqual(line["product_uom_qty"], 2)
        self.assertEqual(service.created_values["client_order_ref"], "RV-12345678")
        self.assertEqual(service.created_values["user_id"], 7)

    def test_list_seller_orders(self) -> None:
        service = FakeOdooService()

        def custom_call(model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None, **_: Any) -> Any:
            if model == "sale.order" and method == "search_read":
                domain = args[0]
                self.assertEqual(domain, [("user_id", "=", 7)])
                return [
                    {
                        "id": 101,
                        "name": "S00101",
                        "partner_id": [20, "Veterinaria El Sol"],
                        "amount_total": 450.50,
                        "state": "sale",
                        "date_order": "2026-08-25 12:00:00",
                        "client_order_ref": "RV-12345678",
                    }
                ]
            return service._call(model, method, args, kwargs)

        service._call = custom_call  # type: ignore[assignment]
        orders = service.list_seller_orders(7)
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["folio"], "S00101")
        self.assertEqual(orders[0]["customer_name"], "Veterinaria El Sol")
        self.assertEqual(orders[0]["state_label"], "Pedido de venta")
        self.assertEqual(orders[0]["amount_total"], 450.50)

    def test_catalog_includes_taxes_for_prices_with_iva(self) -> None:
        service = FakeOdooService()

        def custom_call(model: str, method: str, args: list[Any], kwargs: dict[str, Any] | None = None, **_: Any) -> Any:
            if model == "res.partner":
                return []
            if model == "product.product":
                return [{"id": 5, "default_code": "NX1", "name": "NexGard", "list_price": 100, "taxes_id": [1]}]
            if model == "account.tax":
                return [{"id": 1, "name": "IVA 16%", "amount": 16, "amount_type": "percent", "children_tax_ids": []}]
            raise AssertionError(f"Unexpected call: {model}.{method}")

        service._call = custom_call  # type: ignore[assignment]
        catalog = service.catalog(force=True)

        CatalogResponse(**catalog)
        self.assertEqual(catalog["products"][0]["tax_ids"], [1])
        self.assertEqual(catalog["taxes"][0]["amount"], 16.0)
        self.assertTrue(catalog["taxes"][0]["is_base_affected"])


if __name__ == "__main__":

    unittest.main()
