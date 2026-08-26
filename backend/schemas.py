from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SessionRequest(BaseModel):
    login: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=4, max_length=128)

    @field_validator("login")
    @classmethod
    def clean_login(cls, value: str) -> str:
        return value.strip()


class Seller(BaseModel):
    id: int
    name: str
    login: str
    email: str = ""


class SessionResponse(BaseModel):
    token: str
    expires_in: int
    seller: Seller
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=4, max_length=128)
    new_password: str = Field(min_length=4, max_length=128)



class TemporarySellerKeysRequest(BaseModel):
    admin_pin: str = Field(min_length=6, max_length=128)
    reset_existing: bool = False


class TemporarySellerKey(BaseModel):
    seller: Seller
    temporary_password: str = ""
    status: str
    must_change_password: bool


class TemporarySellerKeysResponse(BaseModel):
    sellers: list[TemporarySellerKey]
    generated_at: int


class Client(BaseModel):
    id: int
    name: str
    email: str = ""
    phone: str = ""
    street: str = ""
    city: str = ""
    postal_code: str = ""
    vat: str = ""


class Product(BaseModel):
    id: int
    code: str
    name: str
    price: float
    category: str
    tax_ids: list[int]


class CatalogResponse(BaseModel):
    clients: list[Client]
    products: list[Product]
    refreshed_at: int


class CreateClientRequest(BaseModel):
    name: str = Field(min_length=3, max_length=160)
    email: str = Field(min_length=5, max_length=254)
    street: str = Field(min_length=5, max_length=240)
    postal_code: str = Field(pattern=r"^\d{5}$")
    vat: str = Field(default="", max_length=13)


class CreatedClient(Client):
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

