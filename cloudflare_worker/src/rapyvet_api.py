from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import time
import xmlrpc.client
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, field_validator


SESSION_TTL_SECONDS = 12 * 60 * 60
SELLER_AUTH_KEY_PREFIX = "rapyvet.pedidos.seller_auth.v1"
SELLER_HASH_ALGORITHM = "hmac_sha256"
SELLER_HASH_VERSION = "v1"
SELLER_GROUP_XMLIDS = (
    "sales_team.group_sale_salesman",
    "sales_team.group_sale_salesman_all_leads",
    "sales_team.group_sale_manager",
)
STATE_LABELS: dict[str, str] = {
    "draft": "Presupuesto",
    "sent": "Presupuesto enviado",
    "sale": "Pedido de venta",
    "done": "Bloqueado / Entregado",
    "cancel": "Cancelado",
}
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")


class ConfigurationError(RuntimeError):
    pass


class ValidacionClienteError(ValueError):
    def __init__(self, errores: dict[str, str]) -> None:
        super().__init__("Los datos del cliente no son válidos.")
        self.errores = errores


class ConflictoClienteError(ValueError):
    pass


class OdooRpcError(RuntimeError):
    pass


class SessionRequest(BaseModel):
    login: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=4, max_length=128)

    @field_validator("login")
    @classmethod
    def clean_login(cls, value: str) -> str:
        return value.strip()


class SellerModel(BaseModel):
    id: int
    name: str
    login: str
    email: str = ""


class SessionResponse(BaseModel):
    token: str
    expires_in: int
    seller: SellerModel
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=4, max_length=128)
    new_password: str = Field(min_length=4, max_length=128)


class TemporarySellerKeysRequest(BaseModel):
    admin_pin: str = Field(min_length=6, max_length=128)
    reset_existing: bool = False


class TemporarySellerKeyModel(BaseModel):
    seller: SellerModel
    temporary_password: str = ""
    status: str
    must_change_password: bool


class TemporarySellerKeysResponse(BaseModel):
    sellers: list[TemporarySellerKeyModel]
    generated_at: int


class ClientModel(BaseModel):
    id: int
    name: str
    email: str = ""
    phone: str = ""
    street: str = ""
    city: str = ""
    postal_code: str = ""
    vat: str = ""


class ProductModel(BaseModel):
    id: int
    code: str
    name: str
    price: float
    category: str
    tax_ids: list[int]


class CatalogResponse(BaseModel):
    clients: list[ClientModel]
    products: list[ProductModel]
    refreshed_at: int


class CreateClientRequest(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    email: str = Field(min_length=5, max_length=254)
    street: str = Field(min_length=5, max_length=240)
    postal_code: str = Field(pattern=r"^\d{5}$")
    vat: str = Field(default="", max_length=13)


class CreatedClient(ClientModel):
    created: bool


class OrderLine(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=9999)
    unit_price: float = Field(ge=0, le=10_000_000)


class CreateOrderRequest(BaseModel):
    customer_id: int = Field(gt=0)
    lines: list[OrderLine] = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=2000)
    idempotency_key: str = Field(
        pattern=r"^RV-[a-zA-Z0-9-]{8,36}$",
        max_length=40,
    )

    @field_validator("note")
    @classmethod
    def clean_note(cls, value: str) -> str:
        return value.strip()


class OrderResponse(BaseModel):
    id: int
    folio: str
    status: str
    subtotal: float
    tax: float
    total: float
    recovered: bool
    whatsapp_message: str
    whatsapp_url: str


class SellerOrderSummary(BaseModel):
    id: int
    folio: str
    customer_id: int
    customer_name: str
    amount_total: float
    state: str
    state_label: str
    date_order: str
    client_order_ref: str = ""


class SellerOrdersResponse(BaseModel):
    orders: list[SellerOrderSummary]
    total: int


@dataclass(frozen=True)
class Settings:
    odoo_url: str
    odoo_db: str
    odoo_user: str
    odoo_password: str
    access_pin: str
    session_secret: str
    seller_temp_secret: str
    frontend_origins: tuple[str, ...]
    odoo_timeout_seconds: float = 30.0
    catalog_cache_seconds: int = 300
    confirm_orders: bool = False

    def cache_key(self) -> str:
        fingerprint = hmac.new(
            self.session_secret.encode("utf-8"),
            f"{self.odoo_url}|{self.odoo_db}|{self.odoo_user}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()[:16]
        return fingerprint


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


@dataclass(frozen=True)
class AuthenticatedSession:
    settings: Settings
    seller: Seller
    must_change_password: bool


class LoginThrottle:
    def __init__(self, *, attempts: int = 5, window_seconds: int = 300) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

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
        return len(self._prune(key, current)) < self.attempts

    def failure(self, key: str, *, now: float | None = None) -> None:
        current = float(now if now is not None else time.time())
        failures = self._prune(key, current)
        if key not in self._failures:
            self._failures[key] = failures
        failures.append(current)

    def success(self, key: str) -> None:
        self._failures.pop(key, None)


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _env_value(env: Any, name: str, default: str = "") -> str:
    value: Any = None
    if env is not None:
        try:
            value = getattr(env, name)
        except Exception:
            value = None
        if value is None:
            try:
                value = env[name]
            except Exception:
                value = None
    if value is None:
        value = os.getenv(name, default)
    if value is None:
        return default
    return str(value).strip()


def _required(env: Any, name: str) -> str:
    value = _env_value(env, name)
    if not value:
        raise ConfigurationError(f"Falta configurar la variable {name}.")
    return value


def _boolean(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


def settings_from_request(request: Request) -> Settings:
    env = request.scope.get("env")
    origins = tuple(
        item.strip().rstrip("/")
        for item in _env_value(
            env,
            "FRONTEND_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if item.strip()
    )
    access_pin = _required(env, "APP_ACCESS_PIN")
    session_secret = _required(env, "APP_SESSION_SECRET")
    if len(access_pin) < 6:
        raise ConfigurationError("APP_ACCESS_PIN debe contener al menos 6 caracteres.")
    if len(session_secret) < 32:
        raise ConfigurationError("APP_SESSION_SECRET debe contener al menos 32 caracteres.")

    return Settings(
        odoo_url=_required(env, "ODOO_URL").rstrip("/"),
        odoo_db=_required(env, "ODOO_DB"),
        odoo_user=_required(env, "ODOO_USER"),
        odoo_password=_required(env, "ODOO_PASSWORD"),
        access_pin=access_pin,
        session_secret=session_secret,
        seller_temp_secret=_env_value(env, "APP_SELLER_TEMP_SECRET", session_secret),
        frontend_origins=origins,
        odoo_timeout_seconds=float(_env_value(env, "ODOO_TIMEOUT_SECONDS", "30")),
        catalog_cache_seconds=int(_env_value(env, "CATALOG_CACHE_SECONDS", "300")),
        confirm_orders=_boolean(_env_value(env, "CONFIRM_ORDERS", "false")),
    )


def verify_pin(provided: str, configured: str) -> bool:
    return hmac.compare_digest(
        str(provided).strip().encode("utf-8"),
        str(configured).strip().encode("utf-8"),
    )


def hash_seller_password(
    password: str,
    *,
    secret: str,
    seller_id: int,
    salt: bytes | None = None,
) -> str:
    raw_salt = salt or os.urandom(16)
    encoded_salt = _encode(raw_salt)
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{int(seller_id)}:{encoded_salt}:{password}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return (
        f"{SELLER_HASH_ALGORITHM}${SELLER_HASH_VERSION}$"
        f"{encoded_salt}${_encode(digest)}"
    )


def verify_legacy_pbkdf2(provided: str, stored_hash: str) -> bool:
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


def verify_seller_password(
    provided: str,
    stored_hash: str,
    *,
    secret: str,
    seller_id: int,
) -> bool:
    try:
        algorithm, version, encoded_salt, encoded_digest = stored_hash.split("$", 3)
    except (ValueError, TypeError):
        return False

    if algorithm == "pbkdf2_sha256":
        return verify_legacy_pbkdf2(provided, stored_hash)
    if algorithm != SELLER_HASH_ALGORITHM or version != SELLER_HASH_VERSION:
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
    cleaned = password.strip()
    if len(cleaned) != 4 or not cleaned.isdigit():
        return ["El NIP debe ser exactamente de 4 dígitos numéricos."]
    return []


def create_session_token(
    secret: str,
    *,
    seller: Mapping[str, Any],
    must_change_password: bool = False,
    now: int | None = None,
) -> str:
    issued_at = int(now if now is not None else time.time())
    payload = {
        "iat": issued_at,
        "exp": issued_at + SESSION_TTL_SECONDS,
        "aud": "rapyvet-pedidos",
        "seller": {
            "id": int(seller["id"]),
            "name": str(seller["name"]),
            "login": str(seller["login"]),
            "email": str(seller.get("email") or ""),
        },
        "must_change_password": bool(must_change_password),
    }
    encoded = _encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded}.{_encode(signature)}"


def read_session_token(token: str, secret: str, *, now: int | None = None) -> SessionData | None:
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


def dominio_clientes_odoo() -> list[Any]:
    return [
        ("active", "=", True),
        "|",
        ("customer_rank", ">", 0),
        "&",
        ("parent_id", "=", False),
        ("type", "=", "contact"),
    ]


def normalizar_rfc(valor: str) -> str:
    return re.sub(r"[\s-]+", "", str(valor or "").upper())


def validar_datos_cliente(
    *,
    nombre: str,
    correo: str,
    direccion: str,
    codigo_postal: str,
    rfc: str = "",
) -> dict[str, str]:
    datos = {
        "name": " ".join(str(nombre or "").split()),
        "email": str(correo or "").strip().lower(),
        "street": " ".join(str(direccion or "").split()),
        "zip": re.sub(r"\s+", "", str(codigo_postal or "")),
        "vat": normalizar_rfc(rfc),
    }
    errores: dict[str, str] = {}
    if len(datos["name"]) < 3:
        errores["nombre"] = "Escribe el nombre completo del cliente."
    elif len(datos["name"]) > 160:
        errores["nombre"] = "El nombre no puede superar 160 caracteres."
    if not EMAIL_RE.fullmatch(datos["email"]):
        errores["correo"] = "Escribe un correo válido, por ejemplo nombre@dominio.com."
    if len(datos["street"]) < 5:
        errores["direccion"] = "Escribe calle, número y colonia."
    elif len(datos["street"]) > 240:
        errores["direccion"] = "La dirección no puede superar 240 caracteres."
    if not re.fullmatch(r"\d{5}", datos["zip"]):
        errores["codigo_postal"] = "El código postal debe contener 5 dígitos."
    if datos["vat"] and not RFC_RE.fullmatch(datos["vat"]):
        errores["rfc"] = "El RFC debe tener 12 o 13 caracteres con formato válido."
    if errores:
        raise ValidacionClienteError(errores)
    return datos


def _client_result(record: dict[str, Any], *, created: bool) -> dict[str, Any]:
    return {
        "id": int(record["id"]),
        "name": str(record.get("name") or "Cliente"),
        "email": str(record.get("email") or ""),
        "phone": str(record.get("phone") or ""),
        "street": str(record.get("street") or ""),
        "city": str(record.get("city") or ""),
        "postal_code": str(record.get("zip") or ""),
        "vat": str(record.get("vat") or ""),
        "created": bool(created),
    }


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


class AsyncOdooService:
    def __init__(self, settings: Settings, seller_auth_store: Any | None = None) -> None:
        self.settings = settings
        self.seller_auth_store = seller_auth_store
        self._uid: int | None = None
        self._catalog: tuple[float, dict[str, Any]] | None = None
        self._local_seller_auth: dict[int, dict[str, Any]] = {}
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.odoo_timeout_seconds),
            follow_redirects=True,
            headers={"User-Agent": "rapyvet-pedidos-cloudflare/2.0"},
        )

    async def _xmlrpc(self, endpoint: str, method: str, params: list[Any]) -> Any:
        payload = xmlrpc.client.dumps(
            tuple(params),
            methodname=method,
            allow_none=True,
        ).encode("utf-8")
        url = f"{self.settings.odoo_url}/{endpoint.lstrip('/')}"
        try:
            response = await self._http.post(
                url,
                content=payload,
                headers={"Content-Type": "text/xml"},
            )
            response.raise_for_status()
            values, _method = xmlrpc.client.loads(response.content)
        except xmlrpc.client.Fault as error:
            raise OdooRpcError(error.faultString) from error
        except httpx.HTTPStatusError as error:
            raise OdooRpcError(f"Odoo respondió HTTP {error.response.status_code}.") from error
        except xmlrpc.client.Error as error:
            raise OdooRpcError(str(error)) from error
        return values[0] if values else None

    async def _authenticate(self) -> int:
        if self._uid:
            return self._uid
        uid = await self._xmlrpc(
            "/xmlrpc/2/common",
            "authenticate",
            [
                self.settings.odoo_db,
                self.settings.odoo_user,
                self.settings.odoo_password,
                {},
            ],
        )
        if not uid:
            raise RuntimeError("Odoo rechazó las credenciales configuradas.")
        self._uid = int(uid)
        return self._uid

    async def _call(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        return await self._xmlrpc(
            "/xmlrpc/2/object",
            "execute_kw",
            [
                self.settings.odoo_db,
                await self._authenticate(),
                self.settings.odoo_password,
                model,
                method,
                args,
                kwargs or {},
            ],
        )

    async def catalog(self, *, force: bool = False) -> dict[str, Any]:
        now = time.time()
        if (
            not force
            and self._catalog
            and now - self._catalog[0] < self.settings.catalog_cache_seconds
        ):
            return self._catalog[1]

        clients_raw = await self._call(
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
        )
        products_raw = await self._call(
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

    async def _read_seller_auth_from_kv(self, seller_id: int) -> dict[str, Any] | None:
        if self.seller_auth_store is None:
            return None
        try:
            raw = await self.seller_auth_store.get(self._seller_auth_key(seller_id))
        except Exception:
            return None
        if not raw:
            return None
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            self._local_seller_auth[seller_id] = data
            return data
        return None

    async def _write_seller_auth_to_kv(
        self,
        seller: Seller,
        record: dict[str, Any],
    ) -> bool:
        if self.seller_auth_store is None:
            return False
        await self.seller_auth_store.put(
            self._seller_auth_key(seller.id),
            json.dumps(record, separators=(",", ":")),
        )
        return True

    async def _seller_group_ids(self) -> list[int]:
        group_ids: list[int] = []
        for xmlid in SELLER_GROUP_XMLIDS:
            try:
                group_id = await self._call(
                    "ir.model.data",
                    "_xmlid_to_res_id",
                    [xmlid],
                    {"raise_if_not_found": False},
                )
            except Exception:
                try:
                    group_id = await self._call(
                        "ir.model.data",
                        "xmlid_to_res_id",
                        [xmlid],
                        {"raise_if_not_found": False},
                    )
                except Exception:
                    continue
            if group_id:
                group_ids.append(int(group_id))
        return group_ids

    async def _seller_domains(self) -> list[list[Any]]:
        group_ids = await self._seller_group_ids()
        domains: list[list[Any]] = []
        if group_ids:
            domains.append([("active", "=", True), ("groups_id", "in", group_ids)])
        domains.append([("active", "=", True)])
        return domains

    async def list_sellers(self) -> list[Seller]:
        records: list[dict[str, Any]] = []
        last_error: Exception | None = None
        for domain in await self._seller_domains():
            try:
                records = await self._call(
                    "res.users",
                    "search_read",
                    [domain],
                    {
                        "fields": ["id", "name", "login", "email"],
                        "order": "id asc",
                    },
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

    async def _find_seller(self, identifier: str) -> Seller | None:
        needle = identifier.strip()
        if not needle:
            return None
        sellers = await self.list_sellers()
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

    async def _read_seller_auth(self, seller_id: int) -> dict[str, Any] | None:
        if seller_id in self._local_seller_auth:
            return self._local_seller_auth[seller_id]

        kv_record = await self._read_seller_auth_from_kv(seller_id)
        if kv_record:
            return kv_record

        try:
            raw = await self._call(
                "ir.config_parameter",
                "get_param",
                [self._seller_auth_key(seller_id)],
            )
        except Exception:
            return None
        if not raw:
            return None
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict):
            self._local_seller_auth[seller_id] = data
            return data
        return None

    async def _write_seller_auth(
        self,
        seller: Seller,
        password: str,
        *,
        must_change_password: bool,
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
        if not await self._write_seller_auth_to_kv(seller, record):
            await self._call(
                "ir.config_parameter",
                "set_param",
                [self._seller_auth_key(seller.id), json.dumps(record, separators=(",", ":"))],
            )
        self._local_seller_auth[seller.id] = record

    async def authenticate_seller(self, login: str, password: str) -> SellerAuthResult:
        seller = await self._find_seller(login)
        if not seller:
            raise PermissionError("Usuario o clave incorrectos.")

        record = await self._read_seller_auth(seller.id)
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

    async def change_seller_password(
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
            raise ValueError("El nuevo NIP debe ser diferente al actual.")

        record = await self._read_seller_auth(seller.id)
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

        await self._write_seller_auth(
            seller,
            new_password,
            must_change_password=False,
        )
        return SellerAuthResult(seller=seller, must_change_password=False)

    async def temporary_seller_keys(self, *, reset_existing: bool = False) -> list[TemporarySellerKey]:
        result: list[TemporarySellerKey] = []
        for seller in await self.list_sellers():
            temp_password = self._temporary_password(seller)
            record = await self._read_seller_auth(seller.id)
            must_change = True
            status_text = "Clave temporal lista"
            password_to_show = temp_password

            if record and not reset_existing:
                must_change = bool(record.get("must_change_password"))
                if must_change:
                    status_text = "Clave temporal pendiente"
                else:
                    status_text = "Clave personalizada activa"
                    password_to_show = ""
            elif reset_existing:
                await self._write_seller_auth(
                    seller,
                    temp_password,
                    must_change_password=True,
                )
                status_text = "Clave temporal restablecida"

            result.append(
                TemporarySellerKey(
                    seller=seller,
                    temporary_password=password_to_show,
                    status=status_text,
                    must_change_password=must_change,
                )
            )
        return result

    async def create_client(self, request: CreateClientRequest) -> dict[str, Any]:
        datos = validar_datos_cliente(
            nombre=request.name,
            correo=request.email,
            direccion=request.street,
            codigo_postal=request.postal_code,
            rfc=request.vat,
        )
        campos = ["id", "name", "email", "phone", "street", "city", "zip", "vat", "customer_rank"]
        if datos["vat"]:
            domain: list[Any] = [
                "|",
                ("email", "=ilike", datos["email"]),
                ("vat", "=ilike", datos["vat"]),
            ]
        else:
            domain = [("email", "=ilike", datos["email"])]

        encontrados = await self._call(
            "res.partner",
            "search_read",
            [domain],
            {"fields": campos, "limit": 10, "order": "id desc"},
        )

        existentes = [dict(registro) for registro in encontrados]
        por_correo = [
            registro
            for registro in existentes
            if str(registro.get("email") or "").strip().lower() == datos["email"]
        ]
        por_rfc = [
            registro
            for registro in existentes
            if datos["vat"] and normalizar_rfc(str(registro.get("vat") or "")) == datos["vat"]
        ]

        if por_correo and por_rfc:
            ids_correo = {int(registro["id"]) for registro in por_correo}
            coincidencias = [
                registro
                for registro in por_rfc
                if int(registro["id"]) in ids_correo
            ]
            if not coincidencias:
                raise ConflictoClienteError(
                    "El correo y el RFC pertenecen a contactos diferentes en Odoo."
                )
            candidatos = coincidencias
        else:
            candidatos = por_correo or por_rfc

        if candidatos:
            registro = dict(candidatos[0])
            correo_existente = str(registro.get("email") or "").strip().lower()
            rfc_existente = normalizar_rfc(str(registro.get("vat") or ""))
            if correo_existente and correo_existente != datos["email"]:
                raise ConflictoClienteError(
                    "El RFC ya está registrado con un correo diferente en Odoo."
                )
            if datos["vat"] and rfc_existente and rfc_existente != datos["vat"]:
                raise ConflictoClienteError(
                    "El correo ya está registrado con un RFC diferente en Odoo."
                )

            updates: dict[str, Any] = {}
            if int(registro.get("customer_rank") or 0) < 1:
                updates["customer_rank"] = 1
            for field in ("email", "street", "zip", "vat"):
                if not registro.get(field) and datos[field]:
                    updates[field] = datos[field]
                    registro[field] = datos[field]
            if updates:
                await self._call(
                    "res.partner",
                    "write",
                    [[int(registro["id"])], updates],
                )
            self._catalog = None
            return _client_result(registro, created=False)

        values: dict[str, Any] = {
            **datos,
            "customer_rank": 1,
            "company_type": "person",
            "type": "contact",
            "active": True,
        }
        if not datos["vat"]:
            values.pop("vat")

        partner_id = int(await self._call("res.partner", "create", [values]))
        registros = await self._call(
            "res.partner",
            "read",
            [[partner_id]],
            {"fields": campos},
        )
        registro = dict(registros[0]) if registros else {"id": partner_id, **datos}
        self._catalog = None
        return _client_result(registro, created=True)

    @staticmethod
    def _from_record(record: dict[str, Any], *, recovered: bool) -> OrderResult:
        state = str(record.get("state") or "")
        status_text = (
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
            status=status_text,
            subtotal=float(record.get("amount_untaxed") or 0),
            tax=float(record.get("amount_tax") or 0),
            total=float(record.get("amount_total") or 0),
            recovered=recovered,
        )

    async def names_for_order(self, request: CreateOrderRequest) -> tuple[str, dict[int, str]]:
        client_records = await self._call(
            "res.partner",
            "read",
            [[request.customer_id]],
            {"fields": ["name"]},
        )
        product_ids = sorted({line.product_id for line in request.lines})
        product_records = await self._call(
            "product.product",
            "read",
            [product_ids],
            {"fields": ["name"]},
        )
        customer_name = (
            str(client_records[0].get("name") or "Cliente")
            if client_records
            else "Cliente"
        )
        product_names = {
            int(item["id"]): str(item.get("name") or "Producto")
            for item in product_records
        }
        return customer_name, product_names

    async def create_order(self, request: CreateOrderRequest, *, seller: Seller) -> OrderResult:
        result_fields = [
            "id",
            "name",
            "state",
            "amount_untaxed",
            "amount_tax",
            "amount_total",
        ]

        async def find_existing() -> dict[str, Any] | None:
            records = await self._call(
                "sale.order",
                "search_read",
                [[("client_order_ref", "=", request.idempotency_key)]],
                {"fields": result_fields, "limit": 1, "order": "id desc"},
            )
            return dict(records[0]) if records else None

        existing = await find_existing()
        if existing:
            return self._from_record(existing, recovered=True)

        customer_exists = await self._call(
            "res.partner",
            "search_count",
            [[("id", "=", request.customer_id), ("active", "=", True)]],
        )
        if not customer_exists:
            raise ValueError("El cliente ya no está disponible en Odoo.")

        product_ids = sorted({line.product_id for line in request.lines})
        available = await self._call(
            "product.product",
            "search_read",
            [[
                ("id", "in", product_ids),
                ("active", "=", True),
                ("sale_ok", "=", True),
            ]],
            {"fields": ["id"]},
        )
        available_ids = {int(item["id"]) for item in available}
        if any(product_id not in available_ids for product_id in product_ids):
            raise ValueError(
                "Uno o más productos ya no están disponibles. Actualiza el catálogo."
            )

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
            order_id = int(await self._call("sale.order", "create", [values]))
        except (httpx.TimeoutException, httpx.TransportError):
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(0.4 * attempt)
                try:
                    recovered = await find_existing()
                    if recovered:
                        return self._from_record(recovered, recovered=True)
                except Exception:
                    continue
            raise

        if self.settings.confirm_orders:
            await self._call("sale.order", "action_confirm", [[order_id]])

        records = await self._call(
            "sale.order",
            "read",
            [[order_id]],
            {"fields": result_fields},
        )
        record = dict(records[0]) if records else {"id": order_id}
        return self._from_record(record, recovered=False)

    async def list_seller_orders(self, seller_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
        records = await self._call(
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
        )
        orders: list[dict[str, Any]] = []
        for rec in records:
            partner = rec.get("partner_id")
            partner_id = partner[0] if isinstance(partner, (list, tuple)) and partner else 0
            partner_name = (
                partner[1]
                if isinstance(partner, (list, tuple)) and len(partner) > 1
                else "Cliente"
            )
            state = str(rec.get("state") or "draft")
            orders.append(
                {
                    "id": int(rec["id"]),
                    "folio": str(rec.get("name") or f"SO-{rec['id']}"),
                    "customer_id": partner_id,
                    "customer_name": partner_name,
                    "amount_total": float(rec.get("amount_total") or 0.0),
                    "state": state,
                    "state_label": STATE_LABELS.get(state, state.capitalize()),
                    "date_order": str(rec.get("date_order") or ""),
                    "client_order_ref": str(rec.get("client_order_ref") or ""),
                }
            )
        return orders


_service_cache: dict[str, AsyncOdooService] = {}
_login_throttle = LoginThrottle()


def seller_auth_store_from_request(request: Request) -> Any | None:
    env = request.scope.get("env")
    if env is None:
        return None
    try:
        return getattr(env, "RAPYVET_SELLER_AUTH")
    except Exception:
        pass
    try:
        return env["RAPYVET_SELLER_AUTH"]
    except Exception:
        return None


def service_for(settings: Settings, seller_auth_store: Any | None = None) -> AsyncOdooService:
    key = settings.cache_key()
    existing = _service_cache.get(key)
    if existing:
        if existing.seller_auth_store is None and seller_auth_store is not None:
            existing.seller_auth_store = seller_auth_store
        return existing
    service = AsyncOdooService(settings, seller_auth_store=seller_auth_store)
    _service_cache[key] = service
    return service


def _origin_matches(origin: str, allowed: str) -> bool:
    allowed = allowed.rstrip("/")
    if allowed == "*":
        return True
    if origin == allowed:
        return True
    if allowed.startswith("https://*."):
        suffix = allowed.removeprefix("https://*")
        return origin.startswith("https://") and origin.endswith(suffix)
    if allowed.startswith("http://*."):
        suffix = allowed.removeprefix("http://*")
        return origin.startswith("http://") and origin.endswith(suffix)
    return False


def _allowed_origin(request: Request, origin: str | None) -> str | None:
    if not origin:
        return None
    try:
        settings = settings_from_request(request)
        allowed = settings.frontend_origins
    except Exception:
        allowed = ("http://localhost:3000", "http://127.0.0.1:3000")
    clean_origin = origin.rstrip("/")
    if any(_origin_matches(clean_origin, item) for item in allowed):
        return clean_origin
    return None


app = FastAPI(
    title="RapyVet Pedidos API",
    version="2.0.0-cloudflare",
    docs_url=None,
    redoc_url=None,
)


@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    origin = _allowed_origin(request, request.headers.get("origin"))
    if request.method == "OPTIONS":
        response = Response(status_code=204)
    else:
        response = await call_next(request)
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization,Content-Type"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


def _session_response(settings: Settings, seller: Seller, *, must_change_password: bool) -> SessionResponse:
    return SessionResponse(
        token=create_session_token(
            settings.session_secret,
            seller=seller.as_dict(),
            must_change_password=must_change_password,
        ),
        expires_in=SESSION_TTL_SECONDS,
        seller=SellerModel(**seller.as_dict()),
        must_change_password=must_change_password,
    )


def _read_authorization_session(
    request: Request,
    authorization: str | None,
    *,
    allow_pending_password: bool,
) -> AuthenticatedSession:
    settings = settings_from_request(request)
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión requerida.")
    token = authorization.removeprefix("Bearer ").strip()
    session = read_session_token(token, settings.session_secret)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión venció.")
    if session.must_change_password and not allow_pending_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debes cambiar tu clave temporal antes de continuar.",
        )
    return AuthenticatedSession(
        settings=settings,
        seller=Seller(
            id=session.seller.id,
            name=session.seller.name,
            login=session.seller.login,
            email=session.seller.email,
        ),
        must_change_password=session.must_change_password,
    )


def require_session(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedSession:
    return _read_authorization_session(
        request,
        authorization,
        allow_pending_password=False,
    )


def require_password_change_session(
    request: Request,
    authorization: str | None = Header(default=None),
) -> AuthenticatedSession:
    return _read_authorization_session(
        request,
        authorization,
        allow_pending_password=True,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "rapyvet-pedidos-api-cloudflare"}


@app.post("/api/session", response_model=SessionResponse)
async def create_session(payload: SessionRequest, request: Request) -> SessionResponse:
    settings = settings_from_request(request)
    source_host = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    source = f"{source_host}:{payload.login.casefold()}"
    if not _login_throttle.allowed(source):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera unos minutos antes de volver a intentar.",
        )
    try:
        result = await service_for(settings, seller_auth_store_from_request(request)).authenticate_seller(
            payload.login,
            payload.password,
        )
    except PermissionError as error:
        _login_throttle.failure(source)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="No fue posible validar el vendedor en Odoo.") from error
    _login_throttle.success(source)
    return _session_response(settings, result.seller, must_change_password=result.must_change_password)


@app.post("/api/session/change-password", response_model=SessionResponse)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_password_change_session),
) -> SessionResponse:
    try:
        result = await service_for(session.settings, seller_auth_store_from_request(request)).change_seller_password(
            session.seller,
            payload.current_password,
            payload.new_password,
        )
        return _session_response(session.settings, result.seller, must_change_password=False)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="No pudimos guardar la nueva clave. Inténtalo de nuevo.",
        ) from error


@app.post("/api/admin/sellers/temporary-keys", response_model=TemporarySellerKeysResponse)
async def temporary_seller_keys(
    payload: TemporarySellerKeysRequest,
    request: Request,
) -> dict[str, object]:
    settings = settings_from_request(request)
    if not verify_pin(payload.admin_pin, settings.access_pin):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clave de administrador incorrecta.")
    try:
        keys = await service_for(settings, seller_auth_store_from_request(request)).temporary_seller_keys(
            reset_existing=payload.reset_existing
        )
        return {
            "sellers": [
                {
                    "seller": SellerModel(**item.seller.as_dict()),
                    "temporary_password": item.temporary_password,
                    "status": item.status,
                    "must_change_password": item.must_change_password,
                }
                for item in keys
            ],
            "generated_at": int(time.time()),
        }
    except Exception as error:
        raise HTTPException(status_code=502, detail="No fue posible consultar vendedores en Odoo.") from error


@app.get("/api/catalog", response_model=CatalogResponse)
async def catalog(
    request: Request,
    refresh: bool = Query(default=False),
    session: AuthenticatedSession = Depends(require_session),
) -> dict[str, object]:
    try:
        return await service_for(session.settings, seller_auth_store_from_request(request)).catalog(force=refresh)
    except Exception as error:
        raise HTTPException(status_code=502, detail="No fue posible consultar Odoo.") from error


@app.post("/api/clients", response_model=CreatedClient)
async def create_client(
    payload: CreateClientRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> dict[str, object]:
    try:
        return await service_for(session.settings, seller_auth_store_from_request(request)).create_client(payload)
    except ValidacionClienteError as error:
        raise HTTPException(status_code=422, detail=error.errores) from error
    except ConflictoClienteError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Odoo no pudo crear el cliente.") from error


@app.post("/api/orders", response_model=OrderResponse)
async def create_order(
    payload: CreateOrderRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> OrderResponse:
    svc = service_for(session.settings, seller_auth_store_from_request(request))
    try:
        customer_name, product_names = await svc.names_for_order(payload)
        result = await svc.create_order(payload, seller=session.seller)
        message = whatsapp_summary(
            customer_name,
            payload,
            product_names,
            seller_name=session.seller.name,
        )
        return OrderResponse(
            id=result.id,
            folio=result.folio,
            status=result.status,
            subtotal=result.subtotal,
            tax=result.tax,
            total=result.total,
            recovered=result.recovered,
            whatsapp_message=message,
            whatsapp_url=whatsapp_url(message),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "No recibimos confirmación de Odoo. Conserva el pedido y vuelve a intentar; "
                "la referencia de seguridad evita duplicados."
            ),
        ) from error


@app.get("/api/orders/history", response_model=SellerOrdersResponse)
async def order_history(
    request: Request,
    limit: int = Query(default=30, ge=1, le=100),
    session: AuthenticatedSession = Depends(require_session),
) -> dict[str, object]:
    try:
        orders = await service_for(session.settings, seller_auth_store_from_request(request)).list_seller_orders(
            session.seller.id,
            limit=limit,
        )
        return {"orders": orders, "total": len(orders)}
    except Exception as error:
        raise HTTPException(
            status_code=502,
            detail="No fue posible consultar el historial de pedidos en Odoo.",
        ) from error
