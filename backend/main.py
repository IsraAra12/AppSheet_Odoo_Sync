from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware

from backend.config import ConfigurationError, Settings, get_settings
from backend.odoo_service import OdooService, whatsapp_summary, whatsapp_url
from backend.odoo_service import Seller as OdooSeller
from backend.schemas import (
    CatalogResponse,
    ChangePasswordRequest,
    CreateClientRequest,
    CreateOrderRequest,
    CustomerStatementResponse,
    CreatedClient,
    OrderDetailResponse,
    OrderResponse,
    Seller,
    SellerOrdersResponse,
    SellerOrderSummary,
    SessionRequest,
    SessionResponse,
    TemporarySellerKeysRequest,
    TemporarySellerKeysResponse,
    UpdateOrderRequest,
)
from backend.security import (
    SESSION_TTL_SECONDS,
    LoginThrottle,
    create_session_token,
    read_session_token,
    verify_pin,
)
from rapyvet.customers import ConflictoClienteError, ValidacionClienteError


logger = logging.getLogger("rapyvet.api")
login_throttle = LoginThrottle()


@dataclass(frozen=True)
class AuthenticatedSession:
    settings: Settings
    seller: OdooSeller
    must_change_password: bool


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
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


def _session_response(seller: OdooSeller, *, must_change_password: bool) -> SessionResponse:
    settings = get_settings()
    return SessionResponse(
        token=create_session_token(
            settings.session_secret,
            seller=seller.as_dict(),
            must_change_password=must_change_password,
        ),
        expires_in=SESSION_TTL_SECONDS,
        seller=Seller(**seller.as_dict()),
        must_change_password=must_change_password,
    )


def _read_authorization_session(
    authorization: str | None,
    *,
    allow_pending_password: bool,
) -> AuthenticatedSession:
    settings = get_settings()
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
        seller=OdooSeller(
            id=session.seller.id,
            name=session.seller.name,
            login=session.seller.login,
            email=session.seller.email,
        ),
        must_change_password=session.must_change_password,
    )


def require_session(authorization: str | None = Header(default=None)) -> AuthenticatedSession:
    return _read_authorization_session(authorization, allow_pending_password=False)


def require_password_change_session(
    authorization: str | None = Header(default=None),
) -> AuthenticatedSession:
    return _read_authorization_session(authorization, allow_pending_password=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "rapyvet-pedidos-api"}


@app.post("/api/session", response_model=SessionResponse)
def create_session(payload: SessionRequest, request: Request) -> SessionResponse:
    source_host = request.client.host if request.client else "unknown"
    source = f"{source_host}:{payload.login.casefold()}"
    if not login_throttle.allowed(source):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera unos minutos antes de volver a intentar.",
        )
    try:
        result = service().authenticate_seller(payload.login, payload.password)
    except PermissionError as error:
        login_throttle.failure(source)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except Exception as error:
        logger.exception("No fue posible validar vendedor")
        raise HTTPException(status_code=502, detail="No fue posible validar el vendedor en Odoo.") from error
    login_throttle.success(source)
    return _session_response(result.seller, must_change_password=result.must_change_password)


@app.post("/api/session/change-password", response_model=SessionResponse)
def change_password(
    payload: ChangePasswordRequest,
    session: AuthenticatedSession = Depends(require_password_change_session),
) -> SessionResponse:
    try:
        result = service().change_seller_password(
            session.seller,
            payload.current_password,
            payload.new_password,
        )
        return _session_response(result.seller, must_change_password=False)
    except PermissionError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("No fue posible cambiar clave de vendedor")
        raise HTTPException(status_code=502, detail="Odoo no pudo guardar la nueva clave.") from error


@app.post("/api/admin/sellers/temporary-keys", response_model=TemporarySellerKeysResponse)
def temporary_seller_keys(payload: TemporarySellerKeysRequest) -> dict[str, object]:
    settings = get_settings()
    if not verify_pin(payload.admin_pin, settings.access_pin):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clave de administrador incorrecta.")
    try:
        keys = service().temporary_seller_keys(reset_existing=payload.reset_existing)
        return {
            "sellers": [
                {
                    "seller": Seller(**item.seller.as_dict()),
                    "temporary_password": item.temporary_password,
                    "status": item.status,
                    "must_change_password": item.must_change_password,
                }
                for item in keys
            ],
            "generated_at": int(time.time()),
        }
    except Exception as error:
        logger.exception("No fue posible generar claves temporales")
        raise HTTPException(status_code=502, detail="No fue posible consultar vendedores en Odoo.") from error


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
)
def create_client(
    request: CreateClientRequest,
    _session: AuthenticatedSession = Depends(require_session),
) -> dict[str, object]:
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
)
def create_order(
    request: CreateOrderRequest,
    session: AuthenticatedSession = Depends(require_session),
) -> OrderResponse:
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
        result = service().create_order(request, seller=session.seller)
        message = whatsapp_summary(
            client_names.get(request.customer_id, "Cliente"),
            request,
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
        logger.exception("No fue posible crear el pedido")
        raise HTTPException(
            status_code=502,
            detail=(
                "No recibimos confirmación de Odoo. Conserva el pedido y vuelve a intentar; "
                "la referencia de seguridad evita duplicados."
            ),
        ) from error


@app.get(
    "/api/orders/history",
    response_model=SellerOrdersResponse,
)
def order_history(
    limit: int = Query(default=30, ge=1, le=100),
    session: AuthenticatedSession = Depends(require_session),
) -> dict[str, object]:
    try:
        orders = service().list_seller_orders(session.seller.id, limit=limit)
        return {
            "orders": orders,
            "total": len(orders),
        }
    except Exception as error:
        logger.exception("No fue posible consultar historial de pedidos")
        raise HTTPException(
            status_code=502,
            detail="No fue posible consultar el historial de pedidos en Odoo.",
        ) from error


@app.get(
    "/api/clients/{customer_id}/statement",
    response_model=CustomerStatementResponse,
)
def customer_statement(
    customer_id: int,
    _session: AuthenticatedSession = Depends(require_session),
) -> dict[str, object]:
    try:
        return service().customer_statement(customer_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        logger.exception("No fue posible consultar el estado de cuenta")
        raise HTTPException(
            status_code=502,
            detail="No fue posible consultar el estado de cuenta en Odoo.",
        ) from error


@app.get(
    "/api/orders/{order_id}",
    response_model=OrderDetailResponse,
)
def order_detail(
    order_id: int,
    session: AuthenticatedSession = Depends(require_session),
) -> dict[str, object]:
    try:
        return service().order_detail(order_id, seller=session.seller)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        logger.exception("No fue posible consultar el detalle del pedido")
        raise HTTPException(
            status_code=502,
            detail="No fue posible consultar el pedido en Odoo.",
        ) from error


@app.patch(
    "/api/orders/{order_id}",
    response_model=OrderResponse,
)
def update_order(
    order_id: int,
    request: UpdateOrderRequest,
    session: AuthenticatedSession = Depends(require_session),
) -> OrderResponse:
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
        result = service().update_order(order_id, request, seller=session.seller)
        message = whatsapp_summary(
            client_names.get(request.customer_id, "Cliente"),
            request,
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
        logger.exception("No fue posible actualizar el pedido")
        raise HTTPException(
            status_code=502,
            detail="Odoo no pudo actualizar el pedido. El pedido original no se confirmó ni se aplicaron pagos.",
        ) from error
