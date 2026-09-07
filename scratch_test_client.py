import sys
sys.path.append('.')
from backend.config import get_settings
from rapyvet.customers import alta_cliente_odoo
from backend.odoo_service import OdooService

settings = get_settings()
odoo = OdooService(settings)
uid = odoo._authenticate()

try:
    print(alta_cliente_odoo(
        url=settings.odoo_url,
        db=settings.odoo_db,
        uid=uid,
        password=settings.odoo_password,
        nombre="Test Client 123",
        correo="testclient123@example.com",
        direccion="Test Street 123, Test City",
        codigo_postal="12345",
        rfc=""
    ))
except Exception as e:
    import traceback
    traceback.print_exc()
