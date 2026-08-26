# Nota rápida de continuidad — Migración RapyVet a Cloudflare $0

Contexto:
- El usuario pidió sacar la nueva app de pedidos hoy para vendedores, con costo $0 como prioridad.
- La opción elegida es Cloudflare Pages Free para frontend Next.js PWA + Cloudflare Workers Free para backend/API.
- Vercel Pro funcionaría bien, pero implica cuota mensual. Vercel Hobby queda como riesgo por uso comercial.

Estado actual actualizado:
- El proyecto está en `C:\Users\aarag\OneDrive\Documents\AppSheet_Odoo_Sync`.
- Frontend: `frontend/`, Next.js 16 con `output: "export"` en `frontend/next.config.ts`, listo para sitio estático.
- Backend actual: `backend/`, FastAPI normal con conexión Odoo por XML-RPC.
- Se empezó y avanzó la preparación serverless: `backend/security.py` ya fue actualizado para agregar hashes rápidos HMAC de NIP de vendedores:
  - `hash_seller_password(...)`
  - `verify_seller_password(...)`
- `backend/odoo_service.py` ya usa el hash HMAC nuevo y conserva compatibilidad con hashes PBKDF2 antiguos.
- Ya existe `cloudflare_worker/` con backend Cloudflare FastAPI/Python:
  - `cloudflare_worker/src/main.py`
  - `cloudflare_worker/src/rapyvet_api.py`
  - `cloudflare_worker/pyproject.toml`
  - `cloudflare_worker/wrangler.jsonc`
  - `cloudflare_worker/README.md`
- Ya existe `CLOUDFLARE_DEPLOY.md` con pasos de publicación.
- Worker publicado:
  - `https://rapyvet-pedidos-api.angelauriazul25.workers.dev`
- Frontend publicado:
  - `https://rapyvet-pedidos.pages.dev`
- Corrección publicada para Odoo SaaS 19.3:
  - Las claves/NIPs de vendedores ya no se guardan en `ir.config_parameter` de Odoo.
  - Ahora se guardan con hash en Cloudflare KV mediante el binding `RAPYVET_SELLER_AUTH`.
  - Esto corrige el error de primer inicio: “Odoo no pudo guardar la nueva clave”.
- Secretos cargados al Worker desde `.env` sin imprimir valores.
- Validaciones remotas realizadas:
  - `/health` del Worker: OK.
  - consulta segura de vendedores: OK, 4 vendedores.
  - login temporal por API: OK, devuelve sesión con cambio de NIP pendiente.
  - catálogo remoto con sesión firmada: OK, 321 clientes y 2,582 productos.
  - cambio de NIP en producción con vendedor ficticio: OK, sin modificar vendedores reales.

Por qué se hizo el cambio de hash:
- Cloudflare Workers Free tiene límite de CPU bajo.
- El hash PBKDF2 actual con 210,000 iteraciones puede ser pesado para login/cambio de NIP.
- Para NIPs de 4 dígitos, conviene usar HMAC con secreto de servidor, que es rápido y más estable en serverless.
- Debe conservarse soporte para hashes PBKDF2 viejos durante transición.

Siguiente paso inmediato:
1. Hacer prueba real de cambio de NIP de un vendedor autorizado.
2. Hacer prueba real de creación de pedido en Odoo con autorización explícita del usuario.
3. Mantener endpoints compatibles con el frontend:
   - `GET /health`
   - `POST /api/session`
   - `POST /api/session/change-password`
   - `POST /api/admin/sellers/temporary-keys`
   - `GET /api/catalog`
   - `POST /api/clients`
   - `POST /api/orders`
   - `GET /api/orders/history`
4. Probar:
   - backend tests existentes: ya pasaron 38/38;
   - build frontend: ya pasó;
   - flujo mock de pedido y WhatsApp: pruebas unitarias ya cubren el Worker;
   - antes de crear un pedido real en Odoo, pedir confirmación al usuario.

Variables necesarias en Cloudflare Worker:
- `ODOO_URL`
- `ODOO_DB`
- `ODOO_USER`
- `ODOO_PASSWORD`
- `APP_ACCESS_PIN`
- `APP_SESSION_SECRET`
- `APP_SELLER_TEMP_SECRET`
- `RAPYVET_SELLER_AUTH` como binding de Cloudflare KV
- `FRONTEND_ORIGINS`
- `ODOO_TIMEOUT_SECONDS`
- `CATALOG_CACHE_SECONDS`
- `CONFIRM_ORDERS`

Notas de despliegue:
- No pegar secretos en el chat.
- Configurar secretos desde panel Cloudflare o Wrangler.
- Frontend Cloudflare Pages debe compilar con:
  - root: `frontend`
  - build: `pnpm build`
  - output: `out`
  - variable pública: `NEXT_PUBLIC_API_URL=https://<worker-url>`
