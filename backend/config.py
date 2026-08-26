from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

_secrets_path = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
if _secrets_path.exists():
    try:
        import toml
        _sec = toml.load(str(_secrets_path)).get("odoo", {})
        if not os.getenv("ODOO_URL") and _sec.get("url"):
            os.environ["ODOO_URL"] = str(_sec["url"])
        if not os.getenv("ODOO_DB") and _sec.get("db"):
            os.environ["ODOO_DB"] = str(_sec["db"])
        if not os.getenv("ODOO_USER") and _sec.get("user"):
            os.environ["ODOO_USER"] = str(_sec["user"])
        if not os.getenv("ODOO_PASSWORD") and _sec.get("password"):
            os.environ["ODOO_PASSWORD"] = str(_sec["password"])
    except Exception:
        pass

class ConfigurationError(RuntimeError):
    """Indica que falta una variable necesaria para operar la API."""


def _required(name: str) -> str:
    value = str(os.getenv(name, "")).strip()
    if not value:
        raise ConfigurationError(f"Falta configurar la variable {name}.")
    return value


def _boolean(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, str(default))).strip().lower()
    return raw in {"1", "true", "yes", "si", "sí", "on"}



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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    origins = tuple(
        item.strip().rstrip("/")
        for item in os.getenv(
            "FRONTEND_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if item.strip()
    )
    access_pin = _required("APP_ACCESS_PIN")
    session_secret = _required("APP_SESSION_SECRET")
    if len(access_pin) < 6:
        raise ConfigurationError("APP_ACCESS_PIN debe contener al menos 6 caracteres.")
    if len(session_secret) < 32:
        raise ConfigurationError("APP_SESSION_SECRET debe contener al menos 32 caracteres.")

    return Settings(
        odoo_url=_required("ODOO_URL").rstrip("/"),
        odoo_db=_required("ODOO_DB"),
        odoo_user=_required("ODOO_USER"),
        odoo_password=_required("ODOO_PASSWORD"),
        access_pin=access_pin,
        session_secret=session_secret,
        seller_temp_secret=os.getenv("APP_SELLER_TEMP_SECRET", session_secret),
        frontend_origins=origins,
        odoo_timeout_seconds=float(os.getenv("ODOO_TIMEOUT_SECONDS", "30")),
        catalog_cache_seconds=int(os.getenv("CATALOG_CACHE_SECONDS", "300")),
        confirm_orders=_boolean("CONFIRM_ORDERS", False),
    )
