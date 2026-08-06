from __future__ import annotations

import ast
import pathlib
import unittest
from typing import Any


class LoggerFalso:
    def info(self, *_args: object, **_kwargs: object) -> None:
        pass

    def warning(self, *_args: object, **_kwargs: object) -> None:
        pass


class ProxyFalso:
    def __init__(self, existentes: list[dict[str, object]]) -> None:
        self.existentes = existentes
        self.llamadas: list[tuple[str, str, object]] = []

    def execute_kw(
        self,
        _db: str,
        _uid: int,
        _password: str,
        modelo: str,
        metodo: str,
        argumentos: object,
        opciones: object | None = None,
    ) -> object:
        self.llamadas.append((modelo, metodo, argumentos))
        if metodo == "search_read":
            return self.existentes
        if metodo == "create":
            return 99
        if metodo == "read":
            return [
                {
                    "id": 99,
                    "name": "S00099",
                    "state": "draft",
                    "amount_untaxed": 100.0,
                    "amount_tax": 16.0,
                    "amount_total": 116.0,
                }
            ]
        if metodo == "action_confirm":
            return True
        raise AssertionError(f"Llamada inesperada: {modelo}.{metodo}")


def cargar_funcion_crear_pedido(proxy: ProxyFalso):
    ruta_app = pathlib.Path(__file__).parents[1] / "app.py"
    arbol = ast.parse(ruta_app.read_text(encoding="utf-8"))
    funcion = next(
        nodo
        for nodo in arbol.body
        if isinstance(nodo, ast.FunctionDef) and nodo.name == "crear_pedido_odoo"
    )
    modulo = ast.Module(body=[funcion], type_ignores=[])
    espacio: dict[str, object] = {
        "Any": Any,
        "URL": "https://odoo.example.com",
        "DB": "db",
        "PASSWORD": "password",
        "ODOO_TIMEOUT_SEGUNDOS": 15.0,
        "CONFIRMAR_AUTOMATICAMENTE": False,
        "logger": LoggerFalso(),
        "crear_proxy_odoo": lambda *_args, **_kwargs: proxy,
    }
    exec(compile(ast.fix_missing_locations(modulo), str(ruta_app), "exec"), espacio)
    return espacio["crear_pedido_odoo"]


class IdempotenciaPedidoTests(unittest.TestCase):
    def test_recupera_pedido_existente_sin_crear_otro(self) -> None:
        proxy = ProxyFalso(
            [
                {
                    "id": 42,
                    "name": "S00042",
                    "state": "draft",
                    "amount_untaxed": 50.0,
                    "amount_tax": 8.0,
                    "amount_total": 58.0,
                }
            ]
        )
        crear = cargar_funcion_crear_pedido(proxy)

        resultado = crear(7, 10, [], "", "RV-123456")

        self.assertEqual(resultado[0], 42)
        self.assertEqual(resultado[1], "S00042")
        self.assertNotIn("create", [metodo for _, metodo, _ in proxy.llamadas])

    def test_nuevo_pedido_guarda_la_referencia(self) -> None:
        proxy = ProxyFalso([])
        crear = cargar_funcion_crear_pedido(proxy)
        carrito = [
            {
                "product_id": 5,
                "cantidad": 2,
                "precio_unitario": 100.0,
            }
        ]

        resultado = crear(7, 10, carrito, "Entregar temprano", "RV-abcdef")

        self.assertEqual(resultado[0], 99)
        llamada_create = next(
            argumentos
            for _, metodo, argumentos in proxy.llamadas
            if metodo == "create"
        )
        valores = llamada_create[0]
        self.assertEqual(valores["client_order_ref"], "RV-abcdef")
        self.assertIn("RV-abcdef", valores["origin"])
        self.assertEqual(valores["partner_id"], 10)


if __name__ == "__main__":
    unittest.main()

