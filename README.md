# RapyVet Pedidos - Captura de pedidos

Aplicación interna para capturar pedidos desde teléfono, tableta o computadora y registrarlos directamente en Odoo.

## Nueva versión PWA en transición

El proyecto ya incorpora la nueva arquitectura acordada:

- `frontend/`: Next.js PWA con Motion, preparada para Cloudflare Pages.
- `backend/`: FastAPI, preparada para Google Cloud Run y conectada con Odoo.
- `app.py`: versión Streamlit que permanece activa como respaldo durante la migración.

La guía de publicación y el plan de cambio están en [MIGRACION_PWA.md](MIGRACION_PWA.md).

La aplicación utiliza dos interfaces independientes:

- **Móvil:** catálogo y carrito en pantallas separadas, con barra inferior fija.
- **Escritorio:** cliente y producto en columnas, formulario de venta/promoción y carrito completo.

Ambas interfaces comparten el mismo cliente, carrito, promociones, notas, conexión con Odoo y mensaje para WhatsApp.

---

## Funciones principales

- **Identificación por vendedor:** Acceso individual conectado con Odoo (`res.users`), claves temporales y cambio obligatorio en primer ingreso.
- **Atribución en Odoo:** Asignación automática de `user_id` del vendedor a cada pedido y en el mensaje de WhatsApp.
- **Bandeja de pedidos offline:** Almacenamiento local seguro cuando no hay señal, con reintentos y sincronización automática.
- **Historial de pedidos:** Consulta directa en Odoo de pedidos anteriores asignados al vendedor activo.
- **Consulta clientes y productos activos en Odoo.**
- **Búsqueda de productos en tiempo real en móvil.**
- **Venta rápida al precio de lista.**
- **Edición manual de cantidades y precios.**
- **Productos repetidos en el mismo pedido.**
- **Promociones personalizadas** como `1+1`, `2+2`, `4+1`, `10+2` o `11+1`.
- **Cada promoción genera exactamente dos líneas:**
  - Una línea con precio.
  - Una línea del mismo producto a `$0.00`.
- **Carrito editable.**
- **Creación de cotización o pedido en Odoo.**
- **Mensaje sencillo para compartir por WhatsApp.**
- **Tema adaptativo y diseño móvil primero.**
- **Interfaz móvil y de escritorio optimizadas.**
- **Revisión final del cliente, productos y total antes de enviar.**
- **Referencia de seguridad (Idempotencia)** para recuperar reintentos sin duplicar pedidos.
- **Conexiones con timeout** para evitar pantallas bloqueadas indefinidamente.
- **Clientes recientes al inicio del selector.**
- **Alta rápida de clientes en Odoo** desde teléfono, tableta o computadora.
- **Movimiento visual accesible**, con reducción automática de animaciones cuando el dispositivo lo solicita.

---

## Alta de clientes en campo

El botón `＋ Nuevo cliente` abre un formulario sin abandonar el pedido. Al guardar, el cliente se crea en `res.partner`, se actualiza el catálogo y queda seleccionado automáticamente.

| Campo de la aplicación | Campo de Odoo | Regla |
|---|---|---|
| Nombre | `name` | Obligatorio |
| Correo | `email` | Obligatorio y con formato válido |
| Dirección | `street` | Obligatorio |
| Código postal | `zip` | Obligatorio, 5 dígitos |
| RFC | `vat` | Opcional, 12 o 13 caracteres |

Antes de crear el contacto, la aplicación busca coincidencias por correo o RFC. Esto evita duplicados si se repite un intento por una conexión inestable. Si encuentra un contacto existente, lo habilita como cliente y conserva los datos que ya tenga en Odoo.

El usuario configurado para la conexión necesita permisos de lectura, creación y edición sobre contactos (`res.partner`).

---


## Interfaz móvil

En pantallas de `820 px` o menos se muestra la experiencia móvil.

### Productos

- Selector de cliente que se compacta después de elegirlo para liberar espacio.
- Alta o cambio de cliente sin abandonar el pedido.
- Buscador de productos en tiempo real.
- Botón para limpiar la búsqueda y regresar al catálogo completo.
- Filtros por categoría y recientes.
- Botón `+ Agregar` para una venta normal.
- Botón de regalo para abrir una promoción.
- Indicador de unidades que ya están en el carrito.
- Seis productos por página.

### Carrito

- Cantidad y subtotal por producto.
- Controles táctiles `-`, cantidad y `+` en una sola fila.
- Botón de eliminación inmediata cuando solo queda una unidad.
- Edición de precio bajo demanda.
- Promociones agrupadas visualmente.
- Promociones rápidas presentadas como botones táctiles amplios.
- Total y creación del pedido.
- Revisión final compacta para evitar desplazamiento innecesario.

### Barra inferior fija

La barra inferior permanece visible durante el desplazamiento y permite cambiar entre:

- `Productos`
- `Carrito`

Cuando el carrito está abierto también muestra el botón para crear el pedido.
Al cambiar entre Productos y Carrito, la nueva pantalla vuelve automáticamente al inicio para evitar quedar a mitad del contenido anterior.

---

## Interfaz de escritorio

En pantallas mayores de `820 px` se muestra la interfaz de escritorio.

- Encabezado y estado de conexión.
- Indicador de pasos.
- Cliente y producto en columnas.
- Selector de producto por código o nombre.
- Pestañas de venta normal y promoción.
- Cantidad y precio editables antes de agregar.
- Carrito completo debajo.
- Edición, eliminación y duplicado de líneas.
- Notas del pedido y botón de envío.

---

## Forzar una interfaz

La aplicación detecta el ancho real de la pantalla con `window.screen.width`.

Puedes forzar una vista mediante la URL:

```text
http://localhost:8501/?ui=desktop
http://localhost:8501/?ui=mobile
```

En Streamlit Cloud:

```text
https://TU-APP.streamlit.app/?ui=desktop
https://TU-APP.streamlit.app/?ui=mobile
```

El parámetro solo cambia la presentación. El carrito y los datos son los mismos.

---

## Cómo funcionan las promociones

Ejemplo: promoción `10+2`.

Odoo recibe exactamente dos líneas:

| Producto | Cantidad | Precio unitario |
|---|---:|---:|
| Producto seleccionado | 10 | Precio normal o editado |
| Mismo producto | 2 | $0.00 |

El campo de descripción de la línea no se sobrescribe, por lo que Odoo conserva el nombre original del producto en cotizaciones y facturas.

---

## Mensaje para WhatsApp

Después de crear el pedido, la aplicación genera un texto breve:

```text
Veterinaria San José

10 x NexGard
2 x NexGard (GRATIS)
4 x Royal Canin
```

WhatsApp normal requiere que el vendedor seleccione el grupo y confirme el envío manualmente.

---

## Estructura del proyecto

```text
rapyvet-pedidos/
├── app.py
├── backend/
│   ├── main.py
│   ├── odoo_service.py
│   └── requirements.txt
├── frontend/
│   ├── app/
│   ├── components/
│   ├── public/
│   └── package.json
├── rapyvet/
├── tests/
├── Dockerfile
├── MIGRACION_PWA.md
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/
│   ├── config.toml
│   └── secrets.example.toml
└── docs/
    └── Manual_RapyVet_Pedidos.pdf
```

El archivo real `.streamlit/secrets.toml` no debe subirse a GitHub.

---

## Requisitos

- Python 3.10 o superior.
- Acceso a internet.
- Credenciales válidas de Odoo.
- Permisos para consultar clientes, productos y pedidos.
- GitHub Desktop para administrar el repositorio.
- Streamlit Community Cloud para publicación gratuita.

Dependencias actuales:

```txt
streamlit==1.61.1
streamlit-keyup==0.3.0
streamlit-js-eval==1.0.0
```

---

## Instalación local en Windows

### PowerShell, sin activar el entorno

```powershell
cd "C:\ruta\del\proyecto"

python -m venv .venv

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

.\.venv\Scripts\python.exe -m streamlit run app.py
```

Abre:

```text
http://localhost:8501
```

### PowerShell, activando el entorno

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m streamlit run app.py
```

### CMD

```bat
cd C:\ruta\del\proyecto
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

---

## Configuración de Odoo

Crea:

```text
.streamlit/secrets.toml
```

Contenido:

```toml
[odoo]
url = "https://rapyvet.odoo.com"
db = "rapyvet"
user = "TU_CORREO"
password = "TU_CLAVE_O_API_KEY"
```

El archivo `.gitignore` debe contener:

```gitignore
.streamlit/secrets.toml
.env
.venv/
__pycache__/
*.pyc
```

Nunca guardes la contraseña dentro de `app.py`.

---

## Publicar con GitHub Desktop

1. Abre GitHub Desktop.
2. Selecciona **File > Add Local Repository**.
3. Elige la carpeta del proyecto.
4. Revisa que `secrets.toml` no aparezca entre los archivos.
5. Escribe un resumen, por ejemplo:

```text
Publicar RapyVet Pedidos
```

6. Presiona **Commit to main**.
7. Presiona **Publish repository**.
8. Mantén el repositorio privado.
9. En actualizaciones futuras usa **Push origin**.

---

## Publicar en Streamlit Community Cloud

1. Entra a Streamlit Community Cloud.
2. Inicia sesión con GitHub.
3. Selecciona **Create app**.
4. Configura:
   - Repository: tu repositorio.
   - Branch: `main`.
   - Main file path: `app.py`.
5. En **Advanced settings > Secrets** agrega:

```toml
[odoo]
url = "https://rapyvet.odoo.com"
db = "rapyvet"
user = "TU_CORREO"
password = "TU_CLAVE_O_API_KEY"
```

6. Presiona **Deploy**.

Cuando actualices el repositorio con **Push origin**, Streamlit Cloud volverá a desplegar la app.

---

## Flujo de uso

1. Selecciona el cliente.
2. Busca o selecciona el producto.
3. Agrega una venta normal o promoción.
4. Revisa el carrito.
5. Ajusta cantidades o precios si es necesario.
6. Crea el pedido en Odoo.
7. Abre WhatsApp y comparte el resumen en el grupo correspondiente.

---

## Seguridad

- Mantén el repositorio privado.
- No publiques `.streamlit/secrets.toml`.
- Si `secrets.toml` llegó a versionarse, agregarlo a `.gitignore` no basta:
  rota la clave de Odoo, retira el archivo del índice y sanea el historial.
- Usa una clave de Odoo con los permisos mínimos necesarios.
- Cambia inmediatamente cualquier clave expuesta.
- Comparte la URL de la app solo con personal autorizado.
- Verifica en Odoo antes de repetir un envío que mostró error.

---

## Solución de problemas

### `ModuleNotFoundError` al iniciar la aplicación

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### La computadora muestra la interfaz móvil

Abre:

```text
http://localhost:8501/?ui=desktop
```

y actualiza con `Ctrl + F5`.

### El teléfono muestra la interfaz de escritorio

Abre:

```text
http://localhost:8501/?ui=mobile
```

### Error de campo `product_uom`

La aplicación no debe enviar `product_uom`. Las líneas utilizan:

```python
{
    "product_id": producto_id,
    "product_uom_qty": cantidad,
    "price_unit": precio,
}
```

### El diálogo de promoción se abre nuevamente

La solicitud para abrir la promoción debe consumirse antes de mostrar el diálogo. La versión actual ya incluye esta corrección.

### El pedido podría haberse duplicado

Antes de volver a enviar:

1. Busca el cliente o folio en Odoo.
2. Confirma si el pedido fue creado.
3. Repite el envío únicamente si no existe.

---

## Pruebas recomendadas antes de publicar

Las pruebas automáticas de impuestos, conexión e idempotencia se ejecutan con:

```powershell
python -m unittest discover -s tests -v
```

### Móvil

- Barra inferior fija.
- Cambio entre Productos y Carrito.
- Búsqueda sin Enter.
- Agregar venta normal.
- Agregar promoción.
- Cerrar el diálogo de promoción.
- Editar cantidad y precio.
- Crear pedido.
- Abrir WhatsApp.

### Escritorio

- Detección automática.
- Selector de cliente.
- Selector de producto.
- Venta normal y promoción.
- Carrito completo.
- Notas.
- Creación del pedido.

### Odoo

- Cliente correcto.
- Dos líneas por promoción.
- Línea gratuita en `$0.00`.
- Nombre original del producto.
- Sin conceptos adicionales en factura.

---

## Documentación

El manual visual para usuarios y administradores está disponible en:

```text
docs/Manual_RapyVet_Pedidos.pdf
```

---

## Uso interno

Proyecto desarrollado para uso interno de RapyVet. No distribuir públicamente sin autorización.
