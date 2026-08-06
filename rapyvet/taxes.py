from __future__ import annotations

from typing import Any


def expandir_impuestos(
    tax_ids: list[int] | tuple[int, ...],
    impuestos_por_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Expande grupos y conserva el orden utilizado por Odoo."""

    salida: list[dict[str, Any]] = []
    vistos: set[int] = set()

    def agregar(tax_id: int) -> None:
        if tax_id in vistos:
            return
        vistos.add(tax_id)
        impuesto = impuestos_por_id.get(int(tax_id))
        if not impuesto:
            return
        if str(impuesto.get("amount_type") or "") == "group":
            for child_id in impuesto.get("children_tax_ids") or []:
                agregar(int(child_id))
        else:
            salida.append(impuesto)

    for item in tax_ids:
        agregar(int(item))

    salida.sort(
        key=lambda tax: (
            int(tax.get("sequence") or 0),
            int(tax.get("id") or 0),
        )
    )
    return salida


def _monto_impuesto(tipo: str, importe: float, base: float) -> float:
    if tipo == "fixed":
        return importe
    if tipo == "division":
        tasa = importe / 100.0
        return (base / (1.0 - tasa)) - base if 0.0 <= tasa < 1.0 else 0.0
    return base * (importe / 100.0)


def _calcular_montos_desde_base(
    base: float,
    impuestos: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], float]]:
    base_original = max(0.0, float(base))
    base_actual = base_original
    resultados: list[tuple[dict[str, Any], float]] = []

    for impuesto in impuestos:
        base_impuesto = (
            base_actual
            if bool(impuesto.get("is_base_affected", True))
            else base_original
        )
        monto = _monto_impuesto(
            str(impuesto.get("amount_type") or "percent"),
            float(impuesto.get("amount") or 0.0),
            base_impuesto,
        )
        resultados.append((impuesto, monto))
        if bool(impuesto.get("include_base_amount")):
            base_actual += monto

    return resultados


def calcular_impuestos(
    precio_odoo: float,
    tax_ids: list[int] | tuple[int, ...],
    impuestos_por_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Calcula un precio final local sin hacer una llamada remota por producto.

    Cuando existen impuestos incluidos, obtiene la base mediante una búsqueda
    numérica. Esto cubre porcentajes, divisiones, importes fijos y bases
    encadenadas, incluidos varios impuestos aplicados sobre la misma base.
    """

    precio = max(0.0, float(precio_odoo))
    impuestos = expandir_impuestos(tax_ids, impuestos_por_id)

    if not impuestos or precio == 0.0:
        return {
            "total_excluded": precio,
            "total_included": precio,
            "tax_amount": 0.0,
            "taxes": [],
        }

    hay_incluidos = any(bool(tax.get("price_include")) for tax in impuestos)
    base = precio

    if hay_incluidos:
        inferior = 0.0
        superior = max(precio, 1.0)

        def total_incluido_en_precio(base_candidata: float) -> float:
            montos = _calcular_montos_desde_base(base_candidata, impuestos)
            return base_candidata + sum(
                monto
                for impuesto, monto in montos
                if bool(impuesto.get("price_include"))
            )

        # Los impuestos válidos de Odoo producen una función monótona. Ochenta
        # iteraciones dejan un margen muy inferior a un centavo.
        for _ in range(80):
            candidata = (inferior + superior) / 2.0
            if total_incluido_en_precio(candidata) < precio:
                inferior = candidata
            else:
                superior = candidata
        base = (inferior + superior) / 2.0

    montos = _calcular_montos_desde_base(base, impuestos)
    total_impuestos = sum(monto for _, monto in montos)
    total_included = base + total_impuestos

    return {
        "total_excluded": base,
        "total_included": total_included,
        "tax_amount": total_impuestos,
        "taxes": [
            {
                "id": int(impuesto.get("id") or 0),
                "name": str(impuesto.get("name") or "Impuesto"),
                "amount": monto,
            }
            for impuesto, monto in montos
        ],
    }

