from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol, TypedDict

from rapyvet.odoo_rpc import DEFAULT_ODOO_TIMEOUT_SECONDS, crear_proxy_odoo


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
RFC_RE = re.compile(r"^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$")


class ProxyOdoo(Protocol):
    def execute_kw(self, *args: Any, **kwargs: Any) -> Any: ...


class DatosCliente(TypedDict):
    name: str
    email: str
    street: str
    zip: str
    vat: str


class ResultadoAltaCliente(TypedDict):
    id: int
    name: str
    email: str
    street: str
    zip: str
    vat: str
    creado: bool


class ValidacionClienteError(ValueError):
    def __init__(self, errores: dict[str, str]) -> None:
        super().__init__("Los datos del cliente no son válidos.")
        self.errores = errores


class ConflictoClienteError(ValueError):
    """Evita unir por accidente correo y RFC de contactos diferentes."""


def dominio_clientes_odoo() -> list[Any]:
    """Incluye clientes históricos y contactos principales aún sin pedidos.

    Odoo mantiene ``customer_rank`` en cero para contactos recién creados hasta
    que adquieren actividad comercial. El segundo bloque del dominio permite
    que esos contactos principales aparezcan inmediatamente, sin incorporar
    direcciones secundarias nuevas ni registros archivados.
    """

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
) -> DatosCliente:
    """Limpia y valida los campos requeridos para un contacto de venta."""

    datos: DatosCliente = {
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


def _resultado(registro: dict[str, Any], *, creado: bool) -> ResultadoAltaCliente:
    return {
        "id": int(registro["id"]),
        "name": str(registro.get("name") or "Cliente"),
        "email": str(registro.get("email") or ""),
        "street": str(registro.get("street") or ""),
        "zip": str(registro.get("zip") or ""),
        "vat": str(registro.get("vat") or ""),
        "creado": bool(creado),
    }


def alta_cliente_odoo(
    *,
    url: str,
    db: str,
    uid: int,
    password: str,
    nombre: str,
    correo: str,
    direccion: str,
    codigo_postal: str,
    rfc: str = "",
    timeout: float = DEFAULT_ODOO_TIMEOUT_SECONDS,
    proxy_factory: Callable[..., ProxyOdoo] = crear_proxy_odoo,
) -> ResultadoAltaCliente:
    """Crea un cliente o recupera el contacto existente por correo/RFC.

    Buscar antes de crear hace que un reintento después de un timeout sea
    seguro: si Odoo alcanzó a crear el contacto, la siguiente ejecución lo
    encuentra y evita el duplicado.
    """

    datos = validar_datos_cliente(
        nombre=nombre,
        correo=correo,
        direccion=direccion,
        codigo_postal=codigo_postal,
        rfc=rfc,
    )
    models = proxy_factory(
        url,
        "/xmlrpc/2/object",
        timeout=timeout,
    )
    campos = ["id", "name", "email", "street", "zip", "vat", "customer_rank"]

    if datos["vat"]:
        dominio: list[Any] = [
            "|",
            ("email", "=ilike", datos["email"]),
            ("vat", "=ilike", datos["vat"]),
        ]
    else:
        dominio = [("email", "=ilike", datos["email"])]

    encontrados = models.execute_kw(
        db,
        int(uid),
        password,
        "res.partner",
        "search_read",
        [dominio],
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
        if datos["vat"]
        and normalizar_rfc(str(registro.get("vat") or "")) == datos["vat"]
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

        actualizacion: dict[str, Any] = {}
        if int(registro.get("customer_rank") or 0) < 1:
            actualizacion["customer_rank"] = 1
        for campo in ("email", "street", "zip", "vat"):
            if not registro.get(campo) and datos[campo]:
                actualizacion[campo] = datos[campo]
                registro[campo] = datos[campo]
        if actualizacion:
            models.execute_kw(
                db,
                int(uid),
                password,
                "res.partner",
                "write",
                [[int(registro["id"])], actualizacion],
            )
        return _resultado(registro, creado=False)

    valores: dict[str, Any] = {
        **datos,
        "customer_rank": 1,
        "company_type": "person",
        "type": "contact",
        "active": True,
    }
    if not datos["vat"]:
        valores.pop("vat")

    partner_id = int(
        models.execute_kw(
            db,
            int(uid),
            password,
            "res.partner",
            "create",
            [valores],
        )
    )
    registros = models.execute_kw(
        db,
        int(uid),
        password,
        "res.partner",
        "read",
        [[partner_id]],
        {"fields": campos},
    )
    registro = dict(registros[0]) if registros else {"id": partner_id, **datos}
    return _resultado(registro, creado=True)
