from __future__ import annotations

from typing import Any, TypedDict


class PaginacionCatalogo(TypedDict):
    pagina: int
    total_paginas: int
    inicio: int
    fin: int


def calcular_paginacion(
    total_productos: int,
    pagina: int,
    productos_por_pagina: int,
) -> PaginacionCatalogo:
    """Normaliza la página y devuelve un intervalo seguro para el catálogo."""

    por_pagina = int(productos_por_pagina)
    if por_pagina <= 0:
        raise ValueError("productos_por_pagina debe ser mayor que cero")

    total = max(0, int(total_productos))
    total_paginas = max(1, (total + por_pagina - 1) // por_pagina)
    pagina_segura = min(max(0, int(pagina)), total_paginas - 1)
    inicio = pagina_segura * por_pagina
    fin = min(inicio + por_pagina, total)
    return {
        "pagina": pagina_segura,
        "total_paginas": total_paginas,
        "inicio": inicio,
        "fin": fin,
    }


def cantidad_producto_en_carrito(
    carrito: list[dict[str, Any]],
    producto_id: int,
) -> int:
    """Cuenta unidades normales y promocionales de un producto en el carrito."""

    total = 0
    for linea in carrito:
        try:
            if int(linea.get("product_id")) != int(producto_id):
                continue
            total += max(0, int(linea.get("cantidad") or 0))
        except (TypeError, ValueError):
            continue
    return total
