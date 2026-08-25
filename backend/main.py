from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from backend.config import ConfigurationError, Settings, get_settings
from backend.odoo_service import OdooService, whatsapp_summary, whatsapp_url
from backend.schemas import (
    CatalogResponse,
    CreateClientRequest,
    CreateOrderRequest,
    CreatedClient,
    OrderResponse,
    SessionRequest,
    SessionResponse,
)
from backend.security import (
    SESSION_TTL_SECONDS,
    LoginThrottle,
    create_session_token,
    verify_pin,
    verify_session_token,
)
from rapyvet.customers import ConflictoClienteError, ValidacionClienteError


logger = logging.getLogger("rapyvet.api")
login_throttle = LoginThrottle()


@lru_cache(maxsize=1)
def service() -> OdooService:
    return OdooService(get_settings())


def allowed_origins() -> list[str]:
    try:
        return list(get_settings().frontend_origins)
    except ConfigurationError:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]


app = FastAPI(
    title="RapyVet Pedidos API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def require_session(authorization: str | None = Header(default=None)) -> Settings:
    settings = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión requerida.")
    token = authorization.removeprefix("Bearer ").strip()
    if not verify_session_token(token, settings.session_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="La sesión venció.")
    return settings


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rapyvet-pedidos-api"}


@app.post("/api/session", response_model=SessionResponse)
def create_session(payload: SessionRequest, request: Request) -> SessionResponse:
    settings = get_settings()
    source = request.client.host if request.client else "unknown"
    if not login_throttle.allowed(source):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera unos minutos antes de volver a intentar.",
        )
    if not verify_pin(payload.pin, settings.access_pin):
        login_throttle.failure(source)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Código incorrecto.")
    login_throttle.success(source)
    return SessionResponse(
        token=create_session_token(settings.session_secret),
        expires_in=SESSION_TTL_SECONDS,
    )


@app.get(
    "/api/catalog",
    response_model=CatalogResponse,
    dependencies=[Depends(require_session)],
)
def catalog(refresh: bool = Query(default=False)) -> dict[str, object]:
    try:
        return service().catalog(force=refresh)
    except Exception as error:
        logger.exception("No fue posible cargar el catálogo")
        raise HTTPException(status_code=502, detail="No fue posible consultar Odoo.") from error


@app.post(
    "/api/clients",
    response_model=CreatedClient,
    dependencies=[Depends(require_session)],
)
def create_client(request: CreateClientRequest) -> dict[str, object]:
    try:
        return service().create_client(request)
    except ValidacionClienteError as error:
        raise HTTPException(status_code=422, detail=error.errores) from error
    except ConflictoClienteError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        logger.exception("No fue posible crear el cliente")
        raise HTTPException(status_code=502, detail="Odoo no pudo crear el cliente.") from error


@app.post(
    "/api/orders",
    response_model=OrderResponse,
    dependencies=[Depends(require_session)],
)
def create_order(request: CreateOrderRequest) -> OrderResponse:
    try:
        catalog_data = service().catalog()
        client_names = {
            int(item["id"]): str(item["name"])
            for item in catalog_data["clients"]
        }
        product_names = {
            int(item["id"]): str(item["name"])
            for item in catalog_data["products"]
        }
        result = service().create_order(request)
        message = whatsapp_summary(
            client_names.get(request.customer_id, "Cliente"),
            request,
            product_names,
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
        logger.exception("No fue posible crear el pedido")
        raise HTTPException(
            status_code=502,
            detail=(
                "No recibimos confirmación de Odoo. Conserva el pedido y vuelve a intentar; "
                "la referencia de seguridad evita duplicados."
            ),
        ) from error
