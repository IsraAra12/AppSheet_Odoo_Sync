# Migración de RapyVet Pedidos

La nueva versión separa la interfaz de la conexión con Odoo:

```text
Teléfono / computadora
        │
        ▼
Cloudflare Pages Free
Next.js PWA + Motion
        │ HTTPS
        ▼
Google Cloud Run
FastAPI (escala a cero)
        │ XML-RPC
        ▼
Odoo SaaS 19.3 Enterprise
```

La aplicación de Streamlit puede seguir operando mientras se valida la PWA. No se debe retirar hasta completar las pruebas de aceptación con vendedores.

## Lo que ya incluye la PWA

- Diseño móvil primero con la paleta ciruela de RapyVet.
- Barra inferior con espacio fijo; no se comprime ni queda fuera de pantalla.
- Catálogo con desplazamiento independiente: el buscador no brinca al filtrar.
- Búsqueda local rápida por nombre o código.
- Carrito persistente durante 24 horas en el dispositivo.
- Venta normal, promociones y líneas gratuitas.
- Edición de cantidad y precio.
- Alta de clientes con nombre, correo, dirección, código postal y RFC opcional.
- Revisión antes del envío.
- Referencia idempotente para reintentar sin duplicar pedidos.
- Mensaje de WhatsApp después de que Odoo confirma el pedido.
- Instalación como app desde la pantalla de inicio del teléfono.
- Catálogo guardado para consulta cuando la señal se interrumpe.

## Seguridad

- Las credenciales de Odoo viven únicamente en Cloud Run.
- Cloudflare solo recibe la URL pública de la API.
- La API requiere un código de acceso y entrega sesiones firmadas de 12 horas.
- El origen permitido debe limitarse al dominio `pages.dev` final.
- El repositorio debe permanecer privado.
- `APP_SESSION_SECRET` debe ser una cadena aleatoria de al menos 32 caracteres.
- `APP_ACCESS_PIN` debe tener al menos 6 caracteres y compartirse solo con ventas.

## Prueba local

### API

Crear un archivo `.env` tomando `.env.example` como referencia y ejecutar:

```powershell
python -m venv .backend-venv
.\.backend-venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.backend-venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8080
```

### PWA

Crear `frontend/.env.local`:

```text
NEXT_PUBLIC_API_URL=http://localhost:8080
```

Después ejecutar:

```powershell
cd frontend
pnpm install
pnpm dev
```

Abrir `http://localhost:3000`.

## Publicar la API en Google Cloud Run

Cloud Run requiere una cuenta de facturación, aunque el consumo se mantenga dentro de la capa gratuita.

1. Crear o elegir un proyecto en Google Cloud.
2. Activar Cloud Run y Cloud Build.
3. Desplegar desde la raíz del repositorio usando el `Dockerfile` incluido.
4. Configurar:

   - Región: `us-central1`.
   - Autenticación de Cloud Run: permitir acceso público; la API aplica su propia sesión.
   - Instancias mínimas: `0`.
   - Instancias máximas: `1` durante el arranque.
   - Memoria: `512 MiB`.
   - CPU: `1`.

5. Agregar estas variables en Cloud Run, sin guardarlas en Git:

```text
ODOO_URL
ODOO_DB
ODOO_USER
ODOO_PASSWORD
APP_ACCESS_PIN
APP_SESSION_SECRET
FRONTEND_ORIGINS=https://NOMBRE.pages.dev
CONFIRM_ORDERS=false
CATALOG_CACHE_SECONDS=300
```

6. Comprobar `https://URL-DE-CLOUD-RUN/health`. Debe responder con estado `ok`.

El contenedor escucha automáticamente el puerto asignado por Cloud Run.

## Publicar la PWA en Cloudflare Pages

1. Crear un proyecto de Pages conectado al repositorio privado.
2. Usar estos valores:

| Opción | Valor |
|---|---|
| Carpeta raíz | `frontend` |
| Comando de instalación | `pnpm install --frozen-lockfile` |
| Comando de compilación | `pnpm build` |
| Carpeta de salida | `out` |
| Variable | `NEXT_PUBLIC_API_URL=https://URL-DE-CLOUD-RUN` |

3. Publicar y copiar el dominio `https://NOMBRE.pages.dev`.
4. Confirmar que ese dominio sea el valor exacto de `FRONTEND_ORIGINS` en Cloud Run.
5. Volver a desplegar Cloud Run si se modificó esa variable.

## Pruebas antes del cambio definitivo

- Ingreso con el código de acceso.
- Carga de todos los clientes, incluidos los recién creados sin pedidos.
- Alta de un cliente de prueba autorizada.
- Búsqueda continua de varios productos sin recuperar el texto anterior.
- Scroll del catálogo mientras el buscador permanece inmóvil.
- Agregar productos sin cambiar la posición del scroll.
- Promoción con una línea cobrada y otra gratuita.
- Edición de cantidades y precios.
- Pedido de prueba en Odoo con folio, impuestos y total correctos.
- Factura sin descripción duplicada.
- Reintento con la misma referencia sin duplicar el pedido.
- Apertura del mensaje de WhatsApp.
- Instalación en Android y iPhone.

Cuando todas las pruebas estén aprobadas, se comparte el enlace `pages.dev` con ventas y se conserva Streamlit como respaldo durante al menos una semana.
