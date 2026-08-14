from __future__ import annotations

import ast
import pathlib
import unittest
from typing import Any
from urllib.parse import quote


RUTA_APP = pathlib.Path(__file__).parents[1] / "app.py"


def arbol_app() -> ast.Module:
    return ast.parse(RUTA_APP.read_text(encoding="utf-8"))


def funcion(nombre: str) -> ast.FunctionDef:
    return next(
        nodo
        for nodo in arbol_app().body
        if isinstance(nodo, ast.FunctionDef) and nodo.name == nombre
    )


def cargar_funciones(*nombres: str) -> dict[str, object]:
    funciones = [funcion(nombre) for nombre in nombres]
    modulo = ast.Module(body=funciones, type_ignores=[])
    espacio: dict[str, object] = {"Any": Any, "quote": quote}
    exec(compile(ast.fix_missing_locations(modulo), str(RUTA_APP), "exec"), espacio)
    return espacio


class FlujoEnvioMovilTests(unittest.TestCase):
    def test_solicitudes_no_llaman_rerun_dentro_del_callback(self) -> None:
        for nombre in ("solicitar_envio", "solicitar_nuevo_cliente"):
            llamadas_rerun = [
                nodo
                for nodo in ast.walk(funcion(nombre))
                if isinstance(nodo, ast.Call)
                and isinstance(nodo.func, ast.Attribute)
                and nodo.func.attr == "rerun"
            ]
            self.assertEqual(llamadas_rerun, [], nombre)

    def test_boton_movil_no_registra_callback_de_envio(self) -> None:
        render = funcion("render_navegacion_movil")
        boton_envio: ast.Call | None = None
        for nodo in ast.walk(render):
            if not isinstance(nodo, ast.Call):
                continue
            for palabra in nodo.keywords:
                if (
                    palabra.arg == "key"
                    and isinstance(palabra.value, ast.Constant)
                    and palabra.value.value == "mobile_bottom_checkout"
                ):
                    boton_envio = nodo
                    break

        self.assertIsNotNone(boton_envio)
        argumentos = {palabra.arg for palabra in boton_envio.keywords}
        self.assertNotIn("on_click", argumentos)

        reruns_app = [
            nodo
            for nodo in ast.walk(render)
            if isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Attribute)
            and nodo.func.attr == "rerun"
            and any(
                palabra.arg == "scope"
                and isinstance(palabra.value, ast.Constant)
                and palabra.value.value == "app"
                for palabra in nodo.keywords
            )
        ]
        self.assertTrue(reruns_app)


class WhatsAppPedidoTests(unittest.TestCase):
    def test_mensaje_y_enlace_se_generan_con_datos_del_pedido(self) -> None:
        funciones = cargar_funciones(
            "construir_mensaje_whatsapp",
            "crear_enlace_whatsapp",
        )
        construir = funciones["construir_mensaje_whatsapp"]
        crear_enlace = funciones["crear_enlace_whatsapp"]
        carrito = [
            {
                "cantidad": 2,
                "nombre_producto": "Vacuna múltiple",
                "precio_unitario": 125.0,
            },
            {
                "cantidad": 1,
                "nombre_producto": "Dosis promoción",
                "precio_unitario": 0.0,
            },
        ]

        mensaje = construir("Clínica San José", carrito)
        enlace = crear_enlace(mensaje)

        self.assertIn("Clínica San José", mensaje)
        self.assertIn("2 x Vacuna múltiple", mensaje)
        self.assertIn("1 x Dosis promoción (GRATIS)", mensaje)
        self.assertTrue(enlace.startswith("https://wa.me/?text="))
        self.assertIn("Cl%C3%ADnica%20San%20Jos%C3%A9", enlace)
        self.assertIn("%0A", enlace)


if __name__ == "__main__":
    unittest.main()
