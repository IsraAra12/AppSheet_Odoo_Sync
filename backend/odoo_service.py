from __future__ import annotations

import threading
import time
import xmlrpc.client
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from backend.config import Settings
from backend.schemas import CreateClientRequest, CreateOrderRequest
from rapyvet.customers import alta_cliente_odoo, dominio_clientes_odoo
from rapyvet.odoo_rpc import crear_proxy_odoo


@dataclass(frozen=True)
class OrderResult:
    id: int
    folio: str
    status: str
    subtotal: float
    tax: float
    total: float
    recovered: bool


class OdooService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._uid: int | None = None
        self._uid_lock = threading.Lock()
        self._catalog: tuple[float, dict[str, Any]] | None = None
        self._catalog_lock = threading.Lock()

    def _authenticate(self) -> int:
        if self._uid:
            return self._uid
        with self._uid_lock:
            if self._uid:
                return self._uid
            common = crear_proxy_odoo(
                self.settings.odoo_url,
                "/xmlrpc/2/common",
                timeout=self.settings.odoo_timeout_seconds,
            )
            uid = common.authenticate(
                self.settings.odoo_db,
                self.settings.odoo_user,
                self.settings.odoo_password,
                {},
            )
            if not uid:
                raise RuntimeError("Odoo rechazó las credenciales configuradas.")
            self._uid = int(uid)
            return self._uid

    def _models(self) -> Any:
        return crear_proxy_odoo(
            self.settings.odoo_url,
            "/xmlrpc/2/object",
            timeout=self.settings.odoo_timeout_seconds,
        )

    def _call(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
        *,
        proxy: Any | None = None,
    ) -> Any:
        return (proxy or self._models()).execute_kw(
            self.settings.odoo_db,
            self._authenticate(),
            self.settings.odoo_password,
            model,
            method,
            args,
            kwargs or {},
        )

    def catalog(self, *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if (
            not force
            and self._catalog
            and now - self._catalog[0] < self.settings.catalog_cache_seconds
        ):
            return self._catalog[1]

        with self._catalog_lock:
            now = time.time()
            if (
                not force
                and self._catalog
                and now - self._catalog[0] < self.settings.catalog_cache_seconds
            ):
                return self._catalog[1]

            proxy = self._models()
            clients_raw = self._call(
                "res.partner",
                "search_read",
                [dominio_clientes_odoo()],
                {
                    "fields": [
                        "id",
                        "name",
                        "email",
                        "phone",
                        "street",
                        "city",
                        "zip",
                        "vat",
                    ],
                    "order": "name asc",
                },
                proxy=proxy,
            )
            products_raw = self._call(
                "product.product",
                "search_read",
                [[("sale_ok", "=", True), ("active", "=", True)]],
                {
                    "fields": [
                        "id",
                        "default_code",
                        "name",
                        "list_price",
                        "categ_id",
                        "taxes_id",
                    ],
                    "order": "default_code asc, name asc",
                },
                proxy=proxy,
            )

            clients = [
                {
                    "id": int(item["id"]),
                    "name": str(item.get("name") or "Cliente"),
                    "email": str(item.get("email") or ""),
                    "phone": str(item.get("phone") or ""),
                    "street": str(item.get("street") or ""),
                    "city": str(item.get("city") or ""),
                    "postal_code": str(item.get("zip") or ""),
                    "vat": str(item.get("vat") or ""),
                }
                for item in clients_raw
            ]
            products = []
            for item in products_raw:
                category = item.get("categ_id") or []
                category_name = (
                    str(category[1])
                    if isinstance(category, (list, tuple)) and len(category) > 1
                    else "General"
                )
                products.append(
                    {
                        "id": int(item["id"]),
                        "code": str(item.get("default_code") or "S/C"),
                        "name": str(item.get("name") or "Producto"),
                        "price": float(item.get("list_price") or 0),
                        "category": category_name,
                        "tax_ids": [int(value) for value in item.get("taxes_id") or []],
                    }
                )

            result = {"clients": clients, "products": products, "refreshed_at": int(now)}
            self._catalog = (now, result)
            return result

    def create_client(self, request: CreateClientRequest) -> dict[str, Any]:
        result = alta_cliente_odoo(
            url=self.settings.odoo_url,
            db=self.settings.odoo_db,
            uid=self._authenticate(),
            password=self.settings.odoo_password,
            nombre=request.name,
            correo=request.email,
            direccion=request.street,
            codigo_postal=request.postal_code,
            rfc=request.vat,
            timeout=self.settings.odoo_timeout_seconds,
        )
        self._catalog = None
        return {
            "id": result["id"],
            "name": result["name"],
            "email": result["email"],
            "phone": "",
            "street": result["street"],
            "city": "",
            "postal_code": result["zip"],
            "vat": result["vat"],
            "created": result["creado"],
        }

    @staticmethod
    def _from_record(record: dict[str, Any], *, recovered: bool) -> OrderResult:
        state = str(record.get("state") or "")
        status = (
            "Pedido recuperado"
            if recovered and state in {"sale", "done"}
            else "Cotización recuperada"
            if recovered
            else "Pedido confirmado"
            if state in {"sale", "done"}
            else "Cotización creada"
        )
        return OrderResult(
            id=int(record["id"]),
            folio=str(record.get("name") or record["id"]),
            status=status,
            subtotal=float(record.get("amount_untaxed") or 0),
            tax=float(record.get("amount_tax") or 0),
            total=float(record.get("amount_total") or 0),
            recovered=recovered,
        )

    def create_order(self, request: CreateOrderRequest) -> OrderResult:
        proxy = self._models()
        result_fields = [
            "id",
            "name",
            "state",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
        ]

        def find_existing(check_proxy: Any) -> dict[str, Any] | None:
            records = self._call(
                "sale.order",
                "search_read",
                [[("client_order_ref", "=", request.idempotency_key)]],
                {"fields": result_fields, "limit": 1, "order": "id desc"},
                proxy=check_proxy,
            )
            return dict(records[0]) if records else None

        existing = find_existing(proxy)
        if existing:
            return self._from_record(existing, recovered=True)

        customer_exists = self._call(
            "res.partner",
            "search_count",
            [[("id", "=", request.customer_id), ("active", "=", True)]],
            proxy=proxy,
        )
        if not customer_exists:
            raise ValueError("El cliente ya no está disponible en Odoo.")

        product_ids = sorted({line.product_id for line in request.lines})
        available = self._call(
            "product.product",
            "search_read",
            [[
                ("id", "in", product_ids),
                ("active", "=", True),
                ("sale_ok", "=", True),
            ]],
            {"fields": ["id"]},
            proxy=proxy,
        )
        available_ids = {int(item["id"]) for item in available}
        if any(product_id not in available_ids for product_id in product_ids):
            raise ValueError(
                "Uno o más productos ya no están disponibles. Actualiza el catálogo."
            )

        # Odoo completa descripción, unidad e impuestos. En particular, no se
        # envía `name`, porque Odoo 19.3 lo duplicaría al generar la factura.
        order_lines = [
            (
                0,
                0,
                {
                    "product_id": line.product_id,
                    "product_uom_qty": line.quantity,
                    "price_unit": line.unit_price,
                },
            )
            for line in request.lines
        ]
        values: dict[str, Any] = {
            "partner_id": request.customer_id,
            "order_line": order_lines,
            "origin": f"RapyVet Pedidos PWA | {request.idempotency_key}",
            "client_order_ref": request.idempotency_key,
        }
        if request.note:
            values["note"] = request.note

        try:
            order_id = int(
                self._call("sale.order", "create", [values], proxy=proxy)
            )
        except (TimeoutError, OSError, xmlrpc.client.ProtocolError):
            for attempt in range(3):
                if attempt:
                    time.sleep(0.4 * attempt)
                try:
                    recovered = find_existing(self._models())
                    if recovered:
                        return self._from_record(recovered, recovered=True)
                except Exception:
                    continue
            raise

        if self.settings.confirm_orders:
            self._call(
                "sale.order",
                "action_confirm",
                [[order_id]],
                proxy=proxy,
            )

        records = self._call(
            "sale.order",
            "read",
            [[order_id]],
            {"fields": result_fields},
            proxy=proxy,
        )
        record = dict(records[0]) if records else {"id": order_id}
        return self._from_record(record, recovered=False)


def whatsapp_summary(customer_name: str, request: CreateOrderRequest, products: dict[int, str]) -> str:
    rows = [customer_name, ""]
    for line in request.lines:
        name = products.get(line.product_id, "Producto")
        suffix = " (GRATIS)" if line.unit_price == 0 else ""
        rows.append(f"{line.quantity} x {name}{suffix}")
    return "\n".join(rows)


def whatsapp_url(message: str) -> str:
    return f"https://wa.me/?text={quote(message, safe='')}"
