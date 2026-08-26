# Despliegue RapyVet $0 — Cloudflare Pages + Workers

## Arquitectura

- Frontend: Cloudflare Pages Free.
- Backend/API: Cloudflare Workers Free con Python + FastAPI.
- Odoo: se mantiene como sistema principal de clientes, productos y pedidos.
- WhatsApp: se genera desde la app como enlace, sin costo adicional.

URLs actuales:

- App: `https://rapyvet-pedidos.pages.dev`
- API: `https://rapyvet-pedidos-api.angelauriazul25.workers.dev`

## Frontend

Proyecto: `frontend`

Configuración en Cloudflare Pages:

- Framework preset: Next.js o None/static.
- Build command: `pnpm build`
- Output directory: `out`
- Root directory: `frontend`
- Variable pública:
  - `NEXT_PUBLIC_API_URL=https://rapyvet-pedidos-api.angelauriazul25.workers.dev`

El frontend ya está configurado con `output: "export"` en `frontend/next.config.ts`.

## Backend

Proyecto: `cloudflare_worker`

Comando de despliegue:

```powershell
cd cloudflare_worker
uv run pywrangler deploy
```

Variables secretas necesarias:

```text
ODOO_URL
ODOO_DB
ODOO_USER
ODOO_PASSWORD
APP_ACCESS_PIN
APP_SESSION_SECRET
APP_SELLER_TEMP_SECRET
```

Variables normales:

```text
FRONTEND_ORIGINS=https://<frontend>.pages.dev,http://localhost:3000,http://127.0.0.1:3000
ODOO_TIMEOUT_SECONDS=30
CATALOG_CACHE_SECONDS=300
CONFIRM_ORDERS=false
```

## Flujo de salida a producción

1. Publicar Worker.
2. Probar `GET /health`.
3. Configurar `NEXT_PUBLIC_API_URL` en Cloudflare Pages apuntando al Worker.
4. Publicar frontend.
5. Probar login de vendedor.
6. Generar/restablecer claves temporales si es necesario.
7. Probar catálogo de clientes/productos.
8. Probar alta de cliente.
9. Probar creación de pedido en Odoo con confirmación del usuario.
10. Probar botón/mensaje de WhatsApp.

## Para mantener costo $0

- No activar Vercel Pro.
- No activar Observability Plus.
- No usar Render para backend.
- No agregar servicios con tarjeta o upgrades.
- En Cloudflare, quedarse en Workers Free y Pages Free.
