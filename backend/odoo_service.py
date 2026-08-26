from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import xmlrpc.client
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from backend.config import Settings
from backend.schemas import CreateClientRequest, CreateOrderRequest
from backend.security import (
    hash_seller_password,
    password_errors,
    verify_pin,
    verify_seller_password,
)
from rapyvet.customers import alta_cliente_odoo, dominio_clientes_odoo
from rapyvet.odoo_rpc import crear_proxy_odoo

SELLER_GROUP_XMLIDS = (
    "sales_team.group_sale_salesman",
    "sales_team.group_sale_salesman_all_leads",
    "sales_team.group_sale_manager",
)
SELLER_AUTH_KEY_PREFIX = "rapyvet.pedidos.seller_auth.v1"
STATE_LABELS: dict[str, str] = {
    "draft": "Presupuesto",
    "sent": "Presupuesto enviado",
    "sale": "Pedido de venta",
    "done": "Bloqueado / Entregado",
    "cancel": "Cancelado",
}



@dataclass(frozen=True)
class Seller:
    id: int
    name: str
    login: str
    email: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "login": self.login,
            "email": self.email,
        }


@dataclass(frozen=True)
class SellerAuthResult:
    seller: Seller
    must_change_password: bool


@dataclass(frozen=True)
class TemporarySellerKey:
    seller: Seller
    temporary_password: str
    status: str
    must_change_password: bool


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
        self._local_seller_auth: dict[int, dict[str, Any]] = {}


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

    def _seller_auth_key(self, seller_id: int) -> str:
        return f"{SELLER_AUTH_KEY_PREFIX}.{int(seller_id)}"

    def _seller_group_ids(self, proxy: Any) -> list[int]:
        group_ids: list[int] = []
        for xmlid in SELLER_GROUP_XMLIDS:
            try:
                group_id = self._call(
                    "ir.model.data",
                    "_xmlid_to_res_id",
                    [xmlid],
                    {"raise_if_not_found": False},
                    proxy=proxy,
                )
            except Exception:
                try:
                    group_id = self._call(
                        "ir.model.data",
                        "xmlid_to_res_id",
                        [xmlid],
                        {"raise_if_not_found": False},
                        proxy=proxy,
                    )
                except Exception:
                    continue
            if group_id:
                group_ids.append(int(group_id))
        return group_ids

    def _seller_domains(self, proxy: Any) -> list[list[Any]]:
        domains: list[list[Any]] = []
        group_ids = self._seller_group_ids(proxy)
        if group_ids:
            domains.append([("active", "=", True), ("groups_id", "in", group_ids)])
        domains.append([("active", "=", True)])
        return domains

    def list_sellers(self) -> list[Seller]:
        proxy = self._models()
        records: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for domain in self._seller_domains(proxy):
            try:
                records = self._call(
                    "res.users",
                    "search_read",
                    [domain],
                    {
                        "fields": ["id", "name", "login", "email"],
                        "order": "id asc",
                    },
                    proxy=proxy,
                )
                if records:
                    break
            except Exception as error:
                last_error = error
                continue
        if not records and last_error:
            raise RuntimeError("No fue posible consultar vendedores en Odoo.") from last_error

        sellers: list[Seller] = []
        seen: set[int] = set()
        for record in records:
            seller_id = int(record["id"])
            if seller_id in seen:
                continue
            login = str(record.get("login") or "").strip()
            if not login:
                continue
            sellers.append(
                Seller(
                    id=seller_id,
                    name=str(record.get("name") or login),
                    login=login,
                    email=str(record.get("email") or ""),
                )
            )
            seen.add(seller_id)
        return sellers

    def _find_seller(self, identifier: str) -> Seller | None:
        needle = identifier.strip()
        if not needle:
            return None
        sellers = self.list_sellers()
        if needle.isdigit():
            target_id = int(needle)
            for seller in sellers:
                if seller.id == target_id:
                    return seller
        needle_case = needle.casefold()
        for seller in sellers:
            if needle_case in {seller.login.casefold(), seller.email.casefold()}:
                return seller
        for seller in sellers:
            if needle_case == seller.name.casefold():
                return seller
        return None

    def _temporary_password(self, seller: Seller) -> str:
        material = f"{seller.id}:{seller.login.casefold()}".encode("utf-8")
        digest = hmac.new(
            self.settings.seller_temp_secret.encode("utf-8"),
            material,
            hashlib.sha256,
        ).digest()
        return f"{int.from_bytes(digest[:4], 'big') % 10_000:04d}"


    def _read_seller_auth(
        self,
        seller_id: int,
        *,
        proxy: Any | None = None,
    ) -> dict[str, Any] | None:
        if seller_id in self._local_seller_auth:
            return self._local_seller_auth[seller_id]
        try:
            raw = self._call(
                "ir.config_parameter",
                "get_param",
                [self._seller_auth_key(seller_id)],
                proxy=proxy,
            )
        except Exception:
            return None
        if not raw:
            return None
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _write_seller_auth(
        self,
        seller: Seller,
        password: str,
        *,
        must_change_password: bool,
        proxy: Any | None = None,
    ) -> None:
        record = {
            "seller_id": seller.id,
            "login": seller.login,
            "password_hash": hash_seller_password(
                password,
                secret=self.settings.seller_temp_secret,
                seller_id=seller.id,
            ),
            "must_change_password": must_change_password,
            "updated_at": int(time.time()),
        }
        self._call(
            "ir.config_parameter",
            "set_param",
            [self._seller_auth_key(seller.id), json.dumps(record, separators=(",", ":"))],
            proxy=proxy,
        )
        self._local_seller_auth[seller.id] = record


    def authenticate_seller(self, login: str, password: str) -> SellerAuthResult:
        proxy = self._models()
        seller = self._find_seller(login)
        if not seller:
            raise PermissionError("Usuario o clave incorrectos.")

        record = self._read_seller_auth(seller.id, proxy=proxy)
        if record and record.get("password_hash"):
            valid = verify_seller_password(
                password,
                str(record["password_hash"]),
                secret=self.settings.seller_temp_secret,
                seller_id=seller.id,
            )
            must_change = bool(record.get("must_change_password"))
        else:
            valid = verify_pin(password, self._temporary_password(seller))
            must_change = True

        if not valid:
            raise PermissionError("Usuario o clave incorrectos.")
        return SellerAuthResult(seller=seller, must_change_password=must_change)

    def change_seller_password(
        self,
        seller: Seller,
        current_password: str,
        new_password: str,
    ) -> SellerAuthResult:
        current_password = current_password.strip()
        new_password = new_password.strip()
        errors = password_errors(new_password)
        if errors:
            raise ValueError(" ".join(errors))
        if verify_pin(current_password, new_password):
            raise ValueError("El nuevo NIP debe ser diferente al temporal.")


        proxy = self._models()
        record = self._read_seller_auth(seller.id, proxy=proxy)
        if record and record.get("password_hash"):
            valid = verify_seller_password(
                current_password,
                str(record["password_hash"]),
                secret=self.settings.seller_temp_secret,
                seller_id=seller.id,
            )
        else:
            valid = verify_pin(current_password, self._temporary_password(seller))
        if not valid:
            raise PermissionError("La clave actual no coincide.")

        self._write_seller_auth(
            seller,
            new_password,
            must_change_password=False,
            proxy=proxy,
        )
        return SellerAuthResult(seller=seller, must_change_password=False)

    def temporary_seller_keys(self, *, reset_existing: bool = False) -> list[TemporarySellerKey]:
        proxy = self._models()
        result: list[TemporarySellerKey] = []
        for seller in self.list_sellers():
            temp_password = self._temporary_password(seller)
            record = self._read_seller_auth(seller.id, proxy=proxy)
            must_change = True
            status = "Clave temporal lista"
            password_to_show = temp_password

            if record and not reset_existing:
                must_change = bool(record.get("must_change_password"))
                if must_change:
                    status = "Clave temporal pendiente"
                else:
                    status = "Clave personalizada activa"
                    password_to_show = ""
            elif reset_existing:
                self._write_seller_auth(
                    seller,
                    temp_password,
                    must_change_password=True,
                    proxy=proxy,
                )
                status = "Clave temporal restablecida"

            result.append(
                TemporarySellerKey(
                    seller=seller,
                    temporary_password=password_to_show,
                    status=status,
                    must_change_password=must_change,
                )
            )
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

    def create_order(self, request: CreateOrderRequest, *, seller: Seller) -> OrderResult:
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
            "user_id": seller.id,
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

    def list_seller_orders(
        self,
        seller_id: int,
        *,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        proxy = self._models()
        records = self._call(
            "sale.order",
            "search_read",
            [[("user_id", "=", seller_id)]],
            {
                "fields": [
                    "id",
                    "name",
                    "partner_id",
                    "amount_total",
                    "state",
                    "date_order",
                    "client_order_ref",
                ],
                "limit": limit,
                "order": "id desc",
            },
            proxy=proxy,
        )
        orders: list[dict[str, Any]] = []
        for rec in records:
            partner = rec.get("partner_id")
            partner_id = partner[0] if isinstance(partner, (list, tuple)) and partner else 0
            partner_name = partner[1] if isinstance(partner, (list, tuple)) and len(partner) > 1 else "Cliente"
            state = str(rec.get("state") or "draft")
            orders.append({
                "id": int(rec["id"]),
                "folio": str(rec.get("name") or f"SO-{rec['id']}"),
                "customer_id": partner_id,
                "customer_name": partner_name,
                "amount_total": float(rec.get("amount_total") or 0.0),
                "state": state,
                "state_label": STATE_LABELS.get(state, state.capitalize()),
                "date_order": str(rec.get("date_order") or ""),
                "client_order_ref": str(rec.get("client_order_ref") or ""),
            })
        return orders



def whatsapp_summary(
    customer_name: str,
    request: CreateOrderRequest,
    products: dict[int, str],
    *,
    seller_name: str = "",
) -> str:
    rows = [customer_name]
    if seller_name:
        rows.append(f"Vendedor: {seller_name}")
    rows.append("")
    for line in request.lines:
        name = products.get(line.product_id, "Producto")
        suffix = " (GRATIS)" if line.unit_price == 0 else ""
        rows.append(f"{line.quantity} x {name}{suffix}")
    return "\n".join(rows)


def whatsapp_url(message: str) -> str:
    return f"https://wa.me/?text={quote(message, safe='')}"
