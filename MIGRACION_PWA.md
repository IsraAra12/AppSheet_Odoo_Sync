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

- **Identificación por vendedor:** Acceso individual conectado con usuarios de ventas de Odoo (`res.users`).
- **Claves temporales y cambio obligatorio:** Claves de primer acceso gestionables por el administrador y forzado de cambio de clave segura al primer ingreso.
- **Atribución de ventas en Odoo:** Cada pedido creado asigna automáticamente el `user_id` del vendedor responsable.
- **Bandeja de pedidos pendientes (Offline Outbox):** Si se pierde la señal, el pedido se guarda localmente con estados claros (*Pendiente*, *Enviando*, *Confirmado*, *Requiere atención*) y se sincroniza automáticamente al recuperar conexión.
- **Historial de pedidos por vendedor:** Consulta directa en Odoo de los pedidos y cotizaciones asignados al vendedor activo, con folios (`S00XXX`), montos e importe acumulado.
- **Diseño móvil primero:** Paleta ciruela de RapyVet y navegación fluida.
- **Barra inferior con espacio fijo:** No se comprime ni queda fuera de pantalla.
- **Catálogo con desplazamiento independiente:** El buscador permanece fijo al filtrar.
- **Búsqueda local rápida:** Por nombre o código de producto.
- **Carrito persistente durante 24 horas** en el dispositivo.
- **Venta normal, promociones y líneas gratuitas** (1+1, 2+2, 4+1, 10+2, 11+1).
- **Edición de cantidad y precio.**
- **Alta de clientes en campo** con nombre, correo, dirección, código postal y RFC opcional.
- **Revisión antes del envío.**
- **Referencia idempotente** para reintentar sin duplicar pedidos.
- **Mensaje de WhatsApp** con el nombre del vendedor y detalle del pedido después de la confirmación en Odoo.
- **Instalación como PWA** desde la pantalla de inicio en Android y iPhone.
- **Catálogo guardado** para consulta cuando la señal se interrumpe.

## Seguridad y Acceso de Vendedores

- Las credenciales maestras de Odoo viven únicamente en Cloud Run.
- Cloudflare solo recibe la URL pública de la API.
- **Autenticación por Vendedor:** Los vendedores inician sesión con su usuario/correo de Odoo y su clave personal (hasheada con `PBKDF2-HMAC-SHA256`).
- **Claves Temporales:** El administrador puede ingresar con el `APP_ACCESS_PIN` en la pantalla de login para consultar o regenerar las claves temporales generadas con HMAC para cada vendedor.
- **Cambio Obligatorio:** Si un vendedor entra con clave temporal, la API restringe todas las operaciones hasta que defina su nueva contraseña personal de al menos 8 caracteres con letras y números.
- El origen permitido debe limitarse al dominio `pages.dev` final (`FRONTEND_ORIGINS`).
- `APP_SESSION_SECRET`: cadena aleatoria de al menos 32 caracteres para firmar los tokens de sesión.
- `APP_ACCESS_PIN`: clave de administración de al menos 6 caracteres.
- `APP_SELLER_TEMP_SECRET`: semilla para derivación determinista de claves temporales de vendedores.

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
APP_SELLER_TEMP_SECRET
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

- Ingreso del administrador para consultar claves temporales de vendedores.
- Primer ingreso de un vendedor con clave temporal y cambio obligatorio a clave personal.
- Carga de todos los clientes, incluidos los recién creados sin pedidos.
- Alta de un cliente de prueba autorizada en campo.
- Búsqueda continua de varios productos sin recuperar el texto anterior.
- Scroll del catálogo mientras el buscador permanece inmóvil.
- Promoción con una línea cobrada y otra gratuita.
- Edición de cantidades y precios.
- Captura de pedido sin señal: verificación de guardado en la Bandeja de pedidos.
- Sincronización automática de la bandeja al recuperar conexión.
- Verificación del pedido en Odoo con `user_id` del vendedor asignado, folio, impuestos y total correctos.
- Consulta del pedido recién creado en la pantalla de Historial de pedidos.
- Apertura del mensaje de WhatsApp con el nombre del vendedor.
- Instalación de la PWA en Android y iPhone.

Cuando todas las pruebas estén aprobadas, se comparte el enlace `pages.dev` con ventas y se conserva Streamlit como respaldo durante al menos una semana.

