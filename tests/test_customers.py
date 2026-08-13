from __future__ import annotations

import unittest

from rapyvet.customers import (
    ConflictoClienteError,
    ValidacionClienteError,
    alta_cliente_odoo,
    dominio_clientes_odoo,
    validar_datos_cliente,
)


class ProxyFalso:
    def __init__(self, existentes: list[dict[str, object]] | None = None) -> None:
        self.existentes = existentes or []
        self.llamadas: list[tuple[str, object]] = []

    def execute_kw(
        self,
        _db: str,
        _uid: int,
        _password: str,
        _modelo: str,
        metodo: str,
        argumentos: object,
        opciones: object | None = None,
    ) -> object:
        self.llamadas.append((metodo, argumentos))
        if metodo == "search_read":
            return self.existentes
        if metodo == "write":
            return True
        if metodo == "create":
            return 321
        if metodo == "read":
            return [
                {
                    "id": 321,
                    "name": "Clínica de Campo",
                    "email": "campo@example.com",
                    "street": "Av. Central 100, Centro",
                    "zip": "64000",
                    "vat": "CACO800101AB1",
                    "customer_rank": 1,
                }
            ]
        raise AssertionError(f"Método inesperado: {metodo} {opciones}")


def alta(proxy: ProxyFalso, **cambios: str):
    datos = {
        "nombre": "Clínica de Campo",
        "correo": "campo@example.com",
        "direccion": "Av. Central 100, Centro",
        "codigo_postal": "64000",
        "rfc": "CACO800101AB1",
    }
    datos.update(cambios)
    return alta_cliente_odoo(
        url="https://odoo.example.com",
        db="db",
        uid=7,
        password="secret",
        proxy_factory=lambda *_args, **_kwargs: proxy,
        **datos,
    )


class ValidacionClienteTests(unittest.TestCase):
    def test_limpia_datos_y_rfc(self) -> None:
        datos = validar_datos_cliente(
            nombre="  Clínica   Norte ",
            correo=" VENTAS@EXAMPLE.COM ",
            direccion=" Calle  1,  Centro ",
            codigo_postal=" 64000 ",
            rfc="cno-800101-ab1",
        )
        self.assertEqual(datos["name"], "Clínica Norte")
        self.assertEqual(datos["email"], "ventas@example.com")
        self.assertEqual(datos["zip"], "64000")
        self.assertEqual(datos["vat"], "CNO800101AB1")

    def test_reporta_todos_los_campos_invalidos(self) -> None:
        with self.assertRaises(ValidacionClienteError) as contexto:
            validar_datos_cliente(
                nombre="A",
                correo="correo-invalido",
                direccion="x",
                codigo_postal="123",
                rfc="INVALIDO",
            )
        self.assertEqual(
            set(contexto.exception.errores),
            {"nombre", "correo", "direccion", "codigo_postal", "rfc"},
        )


class AltaClienteOdooTests(unittest.TestCase):
    def test_crea_cliente_con_campos_de_odoo(self) -> None:
        proxy = ProxyFalso()
        resultado = alta(proxy)

        self.assertTrue(resultado["creado"])
        llamada_create = next(args for metodo, args in proxy.llamadas if metodo == "create")
        valores = llamada_create[0]
        self.assertEqual(valores["customer_rank"], 1)
        self.assertEqual(valores["street"], "Av. Central 100, Centro")
        self.assertEqual(valores["zip"], "64000")
        self.assertEqual(valores["vat"], "CACO800101AB1")

    def test_recupera_duplicado_y_lo_habilita_como_cliente(self) -> None:
        proxy = ProxyFalso(
            [
                {
                    "id": 88,
                    "name": "Clínica existente",
                    "email": "campo@example.com",
                    "street": "",
                    "zip": "",
                    "vat": "CACO800101AB1",
                    "customer_rank": 0,
                }
            ]
        )
        resultado = alta(proxy)

        self.assertFalse(resultado["creado"])
        self.assertEqual(resultado["id"], 88)
        self.assertNotIn("create", [metodo for metodo, _ in proxy.llamadas])
        llamada_write = next(args for metodo, args in proxy.llamadas if metodo == "write")
        self.assertEqual(llamada_write[1]["customer_rank"], 1)
        self.assertEqual(llamada_write[1]["street"], "Av. Central 100, Centro")

    def test_rfc_vacio_no_se_envia_a_odoo(self) -> None:
        proxy = ProxyFalso()
        alta(proxy, rfc="")
        llamada_create = next(args for metodo, args in proxy.llamadas if metodo == "create")
        self.assertNotIn("vat", llamada_create[0])

    def test_bloquea_correo_y_rfc_de_contactos_diferentes(self) -> None:
        proxy = ProxyFalso(
            [
                {
                    "id": 10,
                    "name": "Contacto por correo",
                    "email": "campo@example.com",
                    "street": "Calle 1",
                    "zip": "64000",
                    "vat": "OTRO800101AB1",
                    "customer_rank": 1,
                },
                {
                    "id": 11,
                    "name": "Contacto por RFC",
                    "email": "otro@example.com",
                    "street": "Calle 2",
                    "zip": "64000",
                    "vat": "CACO800101AB1",
                    "customer_rank": 1,
                },
            ]
        )

        with self.assertRaises(ConflictoClienteError):
            alta(proxy)
        self.assertNotIn("create", [metodo for metodo, _ in proxy.llamadas])


class CatalogoClientesOdooTests(unittest.TestCase):
    def test_incluye_clientes_historicos_y_contactos_principales_nuevos(self) -> None:
        self.assertEqual(
            dominio_clientes_odoo(),
            [
                ("active", "=", True),
                "|",
                ("customer_rank", ">", 0),
                "&",
                ("parent_id", "=", False),
                ("type", "=", "contact"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
