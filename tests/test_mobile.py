from __future__ import annotations

import unittest

from rapyvet.mobile import calcular_paginacion, cantidad_producto_en_carrito


class PaginacionMovilTests(unittest.TestCase):
    def test_catalogo_vacio_conserva_una_pagina_segura(self) -> None:
        self.assertEqual(
            calcular_paginacion(0, 99, 6),
            {"pagina": 0, "total_paginas": 1, "inicio": 0, "fin": 0},
        )

    def test_limita_paginas_fuera_de_rango(self) -> None:
        self.assertEqual(calcular_paginacion(16, -4, 6)["pagina"], 0)
        ultima = calcular_paginacion(16, 50, 6)
        self.assertEqual(ultima["pagina"], 2)
        self.assertEqual((ultima["inicio"], ultima["fin"]), (12, 16))

    def test_rechaza_tamano_de_pagina_invalido(self) -> None:
        with self.assertRaises(ValueError):
            calcular_paginacion(10, 0, 0)


class CantidadProductoMovilTests(unittest.TestCase):
    def test_suma_venta_y_promocion_del_mismo_producto(self) -> None:
        carrito = [
            {"product_id": 7, "cantidad": 2},
            {"product_id": 7, "cantidad": 3, "grupo_promocion": "promo"},
            {"product_id": 9, "cantidad": 10},
        ]
        self.assertEqual(cantidad_producto_en_carrito(carrito, 7), 5)

    def test_ignora_lineas_incompletas(self) -> None:
        carrito = [
            {"product_id": None, "cantidad": 2},
            {"product_id": 7, "cantidad": "invalida"},
        ]
        self.assertEqual(cantidad_producto_en_carrito(carrito, 7), 0)


if __name__ == "__main__":
    unittest.main()
