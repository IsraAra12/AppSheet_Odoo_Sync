from __future__ import annotations

import unittest

from rapyvet.taxes import calcular_impuestos


def impuesto(
    tax_id: int,
    amount: float,
    *,
    price_include: bool = False,
    amount_type: str = "percent",
    sequence: int = 1,
) -> dict[str, object]:
    return {
        "id": tax_id,
        "name": f"Impuesto {tax_id}",
        "amount": amount,
        "amount_type": amount_type,
        "price_include": price_include,
        "sequence": sequence,
        "include_base_amount": False,
        "is_base_affected": True,
        "children_tax_ids": [],
    }


class CalculoImpuestosTests(unittest.TestCase):
    def test_porcentaje_excluido(self) -> None:
        resultado = calcular_impuestos(100, [1], {1: impuesto(1, 16)})
        self.assertAlmostEqual(resultado["total_excluded"], 100)
        self.assertAlmostEqual(resultado["tax_amount"], 16)
        self.assertAlmostEqual(resultado["total_included"], 116)

    def test_porcentaje_incluido_separa_base_e_impuesto(self) -> None:
        resultado = calcular_impuestos(
            116,
            [1],
            {1: impuesto(1, 16, price_include=True)},
        )
        self.assertAlmostEqual(resultado["total_excluded"], 100, places=6)
        self.assertAlmostEqual(resultado["tax_amount"], 16, places=6)
        self.assertAlmostEqual(resultado["total_included"], 116, places=6)

    def test_varios_porcentajes_incluidos_comparten_base(self) -> None:
        impuestos = {
            1: impuesto(1, 16, price_include=True),
            2: impuesto(2, 8, price_include=True, sequence=2),
        }
        resultado = calcular_impuestos(124, [1, 2], impuestos)
        self.assertAlmostEqual(resultado["total_excluded"], 100, places=6)
        self.assertAlmostEqual(resultado["tax_amount"], 24, places=6)
        self.assertAlmostEqual(resultado["total_included"], 124, places=6)

    def test_impuesto_fijo_excluido(self) -> None:
        resultado = calcular_impuestos(
            100,
            [1],
            {1: impuesto(1, 5, amount_type="fixed")},
        )
        self.assertAlmostEqual(resultado["total_included"], 105)


if __name__ == "__main__":
    unittest.main()

