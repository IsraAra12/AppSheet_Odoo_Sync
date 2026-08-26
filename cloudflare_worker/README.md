# RapyVet Pedidos API — Cloudflare Worker

Backend serverless para publicar la API de pedidos en Cloudflare Workers Free.

## Objetivo

- Evitar servidores que se duermen por inactividad.
- Mantener costo de plataforma en $0 dentro del uso normal de RapyVet.
- Conservar los mismos endpoints que consume el frontend Next.js PWA.

## Endpoints

- `GET /health`
- `POST /api/session`
- `POST /api/session/change-password`
- `POST /api/admin/sellers/temporary-keys`
- `GET /api/catalog`
- `POST /api/clients`
- `POST /api/orders`
- `GET /api/orders/history`

## Variables

Configurar como secretos en Cloudflare:

- `ODOO_URL`
- `ODOO_DB`
- `ODOO_USER`
- `ODOO_PASSWORD`
- `APP_ACCESS_PIN`
- `APP_SESSION_SECRET`
- `APP_SELLER_TEMP_SECRET`

Configurar como variables normales:

- `FRONTEND_ORIGINS`
- `ODOO_TIMEOUT_SECONDS`
- `CATALOG_CACHE_SECONDS`
- `CONFIRM_ORDERS`

## Comandos sugeridos

Desde esta carpeta:

```powershell
uv run pywrangler dev
uv run pywrangler deploy
```

Si todavía no está instalado `uv`/`pywrangler`, seguir la guía oficial de Python Workers de Cloudflare.

## Nota importante de Odoo

Este Worker usa XML-RPC sobre HTTP asíncrono para seguir siendo compatible con la configuración actual de Odoo. Cuando RapyVet tenga una API key de Odoo 19 lista para JSON-2, se puede migrar la capa de transporte sin cambiar el frontend.

