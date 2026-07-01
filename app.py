from __future__ import annotations

import html
import os
import uuid
import xmlrpc.client
from typing import Any
from urllib.parse import quote

import streamlit as st


# =============================================================================
# CONFIGURACIÓN GENERAL
# =============================================================================

st.set_page_config(
    page_title="RapyVet | Pedidos",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={
        "About": "RapyVet · Captura móvil de pedidos conectada con Odoo",
    },
)

# False: crea una cotización en borrador.
# True: crea la cotización y la confirma automáticamente.
CONFIRMAR_AUTOMATICAMENTE = False

PROMOCIONES_RAPIDAS = (
    "Personalizada",
    "1+1",
    "2+1",
    "2+2",
    "4+1",
    "10+2",
    "11+1",
)


# =============================================================================
# ESTADO DE STREAMLIT
# =============================================================================


def inicializar_estado() -> None:
    valores = {
        "carrito": [],
        "resultado_pedido": None,
        "mostrar_balloons": False,
        "cliente_id": None,
        "producto_id": None,
        "ultimo_producto_id": None,
        "cantidad_normal": 1,
        "precio_normal": 0.0,
        "preset_promocion": "1+1",
        "cantidad_cobrada": 1,
        "cantidad_gratis": 1,
        "precio_promocion": 0.0,
        "nota_pedido": "",
    }

    for clave, valor in valores.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


inicializar_estado()


# =============================================================================
# TEMA AUTOMÁTICO Y CSS RESPONSIVO
# =============================================================================


def obtener_tipo_tema() -> str:
    """Detecta el tema activo de Streamlit con compatibilidad de respaldo."""

    try:
        tipo = str(st.context.theme.type).lower()
        return "dark" if tipo == "dark" else "light"
    except Exception:
        return "light"


def aplicar_estilos() -> None:
    tema = obtener_tipo_tema()
    oscuro = tema == "dark"

    if oscuro:
        colores = {
            "fondo": "#08111F",
            "fondo_2": "#0B1728",
            "superficie": "#101E31",
            "superficie_2": "#14253A",
            "superficie_3": "#192C43",
            "texto": "#F6FAFD",
            "secundario": "#A7B7C9",
            "borde": "#29415D",
            "acento": "#35D0BA",
            "acento_fuerte": "#0EA5A4",
            "acento_suave": "rgba(53, 208, 186, .13)",
            "azul": "#38BDF8",
            "peligro": "#FB7185",
            "gratis": "#F9A8D4",
            "sombra": "rgba(0, 0, 0, .36)",
            "hero_1": "#0F766E",
            "hero_2": "#075985",
        }
    else:
        colores = {
            "fondo": "#F3F7FA",
            "fondo_2": "#EAF4F4",
            "superficie": "#FFFFFF",
            "superficie_2": "#F7FAFC",
            "superficie_3": "#EEF5F7",
            "texto": "#102033",
            "secundario": "#607184",
            "borde": "#D9E4EC",
            "acento": "#0F766E",
            "acento_fuerte": "#0D9488",
            "acento_suave": "rgba(15, 118, 110, .10)",
            "azul": "#0369A1",
            "peligro": "#BE123C",
            "gratis": "#BE185D",
            "sombra": "rgba(15, 23, 42, .09)",
            "hero_1": "#0F766E",
            "hero_2": "#0369A1",
        }

    st.markdown(
        f"""
        <style>
            :root {{
                --rv-bg: {colores['fondo']};
                --rv-bg-2: {colores['fondo_2']};
                --rv-surface: {colores['superficie']};
                --rv-surface-2: {colores['superficie_2']};
                --rv-surface-3: {colores['superficie_3']};
                --rv-text: {colores['texto']};
                --rv-muted: {colores['secundario']};
                --rv-border: {colores['borde']};
                --rv-primary: {colores['acento']};
                --rv-primary-strong: {colores['acento_fuerte']};
                --rv-primary-soft: {colores['acento_suave']};
                --rv-blue: {colores['azul']};
                --rv-danger: {colores['peligro']};
                --rv-free: {colores['gratis']};
                --rv-shadow: {colores['sombra']};
                color-scheme: {tema};
            }}

            html {{
                scroll-behavior: smooth;
                -webkit-text-size-adjust: 100%;
            }}

            body {{
                overscroll-behavior-y: contain;
            }}

            [data-testid="stAppViewContainer"] {{
                background:
                    radial-gradient(
                        circle at 6% -2%,
                        var(--rv-primary-soft),
                        transparent 27rem
                    ),
                    linear-gradient(
                        180deg,
                        var(--rv-bg-2) 0,
                        var(--rv-bg) 24rem,
                        var(--rv-bg) 100%
                    );
                color: var(--rv-text);
            }}

            [data-testid="stHeader"] {{
                background: transparent;
            }}

            [data-testid="stAppViewBlockContainer"] {{
                max-width: 1120px;
                padding-top: 1rem;
                padding-bottom: calc(5rem + env(safe-area-inset-bottom));
            }}

            p, label, h1, h2, h3, h4, h5, h6,
            [data-testid="stMarkdownContainer"] {{
                color: var(--rv-text);
            }}

            .rv-hero {{
                position: relative;
                overflow: hidden;
                margin-bottom: .9rem;
                padding: clamp(1.15rem, 3vw, 1.85rem);
                border: 1px solid rgba(255, 255, 255, .16);
                border-radius: 1.65rem;
                background:
                    linear-gradient(
                        128deg,
                        {colores['hero_1']} 0%,
                        {colores['hero_2']} 100%
                    );
                box-shadow: 0 1.3rem 3rem var(--rv-shadow);
                isolation: isolate;
            }}

            .rv-hero::before,
            .rv-hero::after {{
                content: "";
                position: absolute;
                z-index: -1;
                border-radius: 999px;
                background: rgba(255, 255, 255, .10);
            }}

            .rv-hero::before {{
                width: 18rem;
                height: 18rem;
                top: -10rem;
                right: -3rem;
            }}

            .rv-hero::after {{
                width: 10rem;
                height: 10rem;
                right: 10rem;
                bottom: -7rem;
            }}

            .rv-hero-grid {{
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 1rem;
            }}

            .rv-kicker {{
                margin: 0 0 .3rem 0;
                color: rgba(255,255,255,.78) !important;
                font-size: .74rem;
                font-weight: 800;
                letter-spacing: .09em;
                text-transform: uppercase;
            }}

            .rv-title {{
                margin: 0;
                color: white !important;
                font-size: clamp(1.65rem, 5vw, 2.45rem);
                font-weight: 900;
                letter-spacing: -.055em;
                line-height: 1.05;
            }}

            .rv-subtitle {{
                max-width: 44rem;
                margin: .55rem 0 0 0;
                color: rgba(255,255,255,.88) !important;
                font-size: clamp(.9rem, 2.2vw, 1rem);
                line-height: 1.55;
            }}

            .rv-auto-theme {{
                flex: 0 0 auto;
                display: inline-flex;
                align-items: center;
                gap: .38rem;
                padding: .5rem .72rem;
                border: 1px solid rgba(255,255,255,.2);
                border-radius: 999px;
                background: rgba(255,255,255,.12);
                color: white !important;
                font-size: .73rem;
                font-weight: 800;
                white-space: nowrap;
                backdrop-filter: blur(.5rem);
            }}

            .rv-pills {{
                display: flex;
                flex-wrap: wrap;
                gap: .42rem;
                margin-top: .95rem;
            }}

            .rv-pill {{
                padding: .34rem .65rem;
                border: 1px solid rgba(255,255,255,.18);
                border-radius: 999px;
                background: rgba(255,255,255,.11);
                color: white !important;
                font-size: .72rem;
                font-weight: 750;
            }}

            .rv-status-strip {{
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: .65rem;
                margin: .9rem 0;
            }}

            .rv-status-item {{
                min-width: 0;
                padding: .75rem .85rem;
                border: 1px solid var(--rv-border);
                border-radius: 1rem;
                background: var(--rv-surface);
                background: color-mix(in srgb, var(--rv-surface) 92%, transparent);
                box-shadow: 0 .45rem 1.3rem var(--rv-shadow);
            }}

            .rv-status-label {{
                margin: 0;
                color: var(--rv-muted) !important;
                font-size: .68rem;
                font-weight: 800;
                letter-spacing: .06em;
                text-transform: uppercase;
            }}

            .rv-status-value {{
                overflow: hidden;
                margin: .15rem 0 0 0;
                color: var(--rv-text) !important;
                font-size: .9rem;
                font-weight: 830;
                text-overflow: ellipsis;
                white-space: nowrap;
            }}

            .rv-steps {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: .5rem;
                margin: .8rem 0 1rem 0;
            }}

            .rv-step {{
                display: flex;
                align-items: center;
                gap: .55rem;
                min-width: 0;
                padding: .62rem .72rem;
                border: 1px solid var(--rv-border);
                border-radius: .9rem;
                background: var(--rv-surface);
                color: var(--rv-muted) !important;
                font-size: .78rem;
                font-weight: 760;
            }}

            .rv-step-number {{
                display: inline-grid;
                flex: 0 0 auto;
                width: 1.55rem;
                height: 1.55rem;
                place-items: center;
                border-radius: 999px;
                background: var(--rv-surface-3);
                color: var(--rv-muted) !important;
                font-size: .72rem;
                font-weight: 900;
            }}

            .rv-step-active {{
                border-color: var(--rv-primary);
                color: var(--rv-text) !important;
                box-shadow: 0 0 0 .18rem var(--rv-primary-soft);
            }}

            .rv-step-active .rv-step-number,
            .rv-step-done .rv-step-number {{
                background: var(--rv-primary);
                color: white !important;
            }}

            .rv-step-done {{
                color: var(--rv-text) !important;
            }}

            .rv-section-title {{
                display: flex;
                align-items: center;
                gap: .55rem;
                margin: 0;
                font-size: 1.03rem;
                font-weight: 880;
                letter-spacing: -.02em;
            }}

            .rv-section-copy {{
                margin: .24rem 0 .85rem 0;
                color: var(--rv-muted) !important;
                font-size: .86rem;
                line-height: 1.45;
            }}

            .rv-product-preview {{
                margin: .75rem 0 .85rem 0;
                padding: .82rem .9rem;
                border: 1px solid var(--rv-border);
                border-radius: 1rem;
                background: var(--rv-surface-2);
            }}

            .rv-product-name {{
                margin: 0;
                font-size: .94rem;
                font-weight: 850;
                line-height: 1.3;
            }}

            .rv-product-meta {{
                margin: .22rem 0 0 0;
                color: var(--rv-muted) !important;
                font-size: .78rem;
            }}

            .rv-promo-preview {{
                margin-top: .75rem;
                padding: .8rem .9rem;
                border: 1px solid var(--rv-border);
                border-left: .28rem solid var(--rv-primary);
                border-radius: .95rem;
                background: var(--rv-surface-2);
            }}

            .rv-promo-preview strong {{
                color: var(--rv-primary) !important;
            }}

            .rv-promo-preview p {{
                margin: .12rem 0;
                color: var(--rv-muted) !important;
                font-size: .79rem;
                line-height: 1.45;
            }}

            .rv-cart-heading {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: .8rem;
                margin: 1.1rem 0 .6rem 0;
            }}

            .rv-cart-count {{
                padding: .33rem .62rem;
                border-radius: 999px;
                background: var(--rv-primary-soft);
                color: var(--rv-primary) !important;
                font-size: .73rem;
                font-weight: 850;
            }}

            .rv-empty {{
                padding: 2.25rem 1rem;
                border: 1px dashed var(--rv-border);
                border-radius: 1.25rem;
                background: var(--rv-surface-2);
                text-align: center;
            }}

            .rv-empty-icon {{
                display: inline-grid;
                width: 3.2rem;
                height: 3.2rem;
                place-items: center;
                border-radius: 1rem;
                background: var(--rv-primary-soft);
                font-size: 1.55rem;
            }}

            .rv-empty-title {{
                margin-top: .65rem;
                font-weight: 880;
            }}

            .rv-empty-copy {{
                max-width: 35rem;
                margin: .28rem auto 0 auto;
                color: var(--rv-muted) !important;
                font-size: .85rem;
                line-height: 1.5;
            }}

            .rv-line-head {{
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: .8rem;
                margin-bottom: .55rem;
            }}

            .rv-line-title {{
                margin: 0;
                font-size: .97rem;
                font-weight: 860;
                line-height: 1.3;
            }}

            .rv-line-meta {{
                margin: .2rem 0 0 0;
                color: var(--rv-muted) !important;
                font-size: .76rem;
            }}

            .rv-badge {{
                flex: 0 0 auto;
                padding: .3rem .58rem;
                border-radius: 999px;
                background: var(--rv-primary-soft);
                color: var(--rv-primary) !important;
                font-size: .67rem;
                font-weight: 900;
                letter-spacing: .035em;
                text-transform: uppercase;
            }}

            .rv-badge-free {{
                background: var(--rv-surface-3);
                background: color-mix(in srgb, var(--rv-free) 13%, transparent);
                color: var(--rv-free) !important;
            }}

            .rv-promotion-head {{
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: .9rem;
                margin-bottom: .8rem;
                padding-bottom: .72rem;
                border-bottom: 1px solid var(--rv-border);
            }}

            .rv-promotion-kicker {{
                margin: 0 0 .15rem 0;
                color: var(--rv-primary) !important;
                font-size: .69rem;
                font-weight: 900;
                letter-spacing: .07em;
                text-transform: uppercase;
            }}

            .rv-promotion-title {{
                margin: 0;
                font-size: 1.02rem;
                font-weight: 880;
                line-height: 1.3;
            }}

            .rv-promotion-code {{
                margin: .2rem 0 0 0;
                color: var(--rv-muted) !important;
                font-size: .75rem;
            }}

            .rv-promotion-badge {{
                flex: 0 0 auto;
                min-width: 3.6rem;
                padding: .45rem .7rem;
                border-radius: .9rem;
                background: linear-gradient(
                    135deg,
                    var(--rv-primary),
                    var(--rv-blue)
                );
                color: white !important;
                font-size: .92rem;
                font-weight: 900;
                text-align: center;
                box-shadow: 0 .45rem 1.1rem var(--rv-shadow);
            }}

            .rv-subline {{
                height: 100%;
                padding: .8rem;
                border: 1px solid var(--rv-border);
                border-radius: 1rem;
                background: var(--rv-surface-2);
            }}

            .rv-subline-label {{
                margin: 0 0 .55rem 0;
                color: var(--rv-muted) !important;
                font-size: .69rem;
                font-weight: 900;
                letter-spacing: .055em;
                text-transform: uppercase;
            }}

            .rv-subtotal {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: .7rem;
                margin-top: .65rem;
                padding: .64rem .72rem;
                border-radius: .8rem;
                background: var(--rv-primary-soft);
            }}

            .rv-subtotal-label {{
                color: var(--rv-muted) !important;
                font-size: .72rem;
            }}

            .rv-subtotal-value {{
                color: var(--rv-primary) !important;
                font-size: .98rem;
                font-weight: 900;
            }}

            .rv-summary-total {{
                margin: .75rem 0;
                padding: 1rem;
                border: 1px solid var(--rv-border);
                border-radius: 1.1rem;
                background:
                    linear-gradient(
                        135deg,
                        var(--rv-primary-soft),
                        transparent
                    ),
                    var(--rv-surface-2);
            }}

            .rv-summary-total-label {{
                margin: 0;
                color: var(--rv-muted) !important;
                font-size: .72rem;
                font-weight: 850;
                letter-spacing: .06em;
                text-transform: uppercase;
            }}

            .rv-summary-total-value {{
                margin: .1rem 0 0 0;
                color: var(--rv-primary) !important;
                font-size: clamp(1.65rem, 6vw, 2.25rem);
                font-weight: 920;
                letter-spacing: -.045em;
            }}

            div[data-testid="stVerticalBlockBorderWrapper"] {{
                border-color: var(--rv-border) !important;
                border-radius: 1.25rem !important;
                background: var(--rv-surface);
                background: color-mix(
                    in srgb,
                    var(--rv-surface) 96%,
                    transparent
                );
                box-shadow: 0 .6rem 1.8rem var(--rv-shadow);
            }}

            div[data-testid="stMetric"] {{
                min-height: 5.3rem;
                padding: .8rem .88rem;
                border: 1px solid var(--rv-border);
                border-radius: 1rem;
                background: var(--rv-surface-2);
            }}

            div[data-testid="stMetric"] label {{
                color: var(--rv-muted) !important;
                font-size: .74rem;
            }}

            div[data-testid="stMetricValue"] {{
                color: var(--rv-primary) !important;
                font-weight: 900;
            }}

            div[data-baseweb="select"] > div,
            div[data-baseweb="input"] > div,
            div[data-baseweb="textarea"] > div,
            textarea {{
                min-height: 2.85rem;
                border-color: var(--rv-border) !important;
                background-color: var(--rv-surface-2) !important;
                color: var(--rv-text) !important;
                transition: border-color .16s ease, box-shadow .16s ease;
            }}

            div[data-baseweb="select"] > div:focus-within,
            div[data-baseweb="input"] > div:focus-within,
            div[data-baseweb="textarea"] > div:focus-within {{
                border-color: var(--rv-primary) !important;
                box-shadow: 0 0 0 .2rem var(--rv-primary-soft) !important;
            }}

            input, textarea {{
                color: var(--rv-text) !important;
                caret-color: var(--rv-primary) !important;
            }}

            input::placeholder,
            textarea::placeholder {{
                color: var(--rv-muted) !important;
                opacity: .78;
            }}

            div[data-baseweb="popover"],
            ul[role="listbox"] {{
                border-color: var(--rv-border) !important;
                background: var(--rv-surface) !important;
                color: var(--rv-text) !important;
            }}

            li[role="option"] {{
                color: var(--rv-text) !important;
            }}

            div[data-testid="stButton"] > button {{
                min-height: 2.85rem;
                border-radius: .85rem;
                border-color: var(--rv-border);
                font-weight: 820;
                transition: transform .13s ease, box-shadow .13s ease;
                touch-action: manipulation;
            }}

            div[data-testid="stButton"] > button:hover {{
                transform: translateY(-1px);
            }}

            button[kind="primary"] {{
                border: 0 !important;
                background: linear-gradient(
                    135deg,
                    var(--rv-primary),
                    var(--rv-blue)
                ) !important;
                color: white !important;
                box-shadow: 0 .55rem 1.25rem var(--rv-shadow);
            }}

            button[kind="secondary"] {{
                background: var(--rv-surface-2) !important;
                color: var(--rv-text) !important;
            }}

            button:focus-visible {{
                outline: .2rem solid var(--rv-primary) !important;
                outline-offset: .15rem;
            }}

            [data-testid="stTabs"] [data-baseweb="tab-list"] {{
                gap: .4rem;
                padding: .25rem;
                border-radius: .95rem;
                background: var(--rv-surface-2);
            }}

            [data-testid="stTabs"] [data-baseweb="tab"] {{
                min-height: 2.55rem;
                border-radius: .75rem;
                font-weight: 780;
            }}

            [data-testid="stExpander"] {{
                border-color: var(--rv-border) !important;
                border-radius: .9rem !important;
                background: var(--rv-surface-2);
            }}

            [data-testid="stAlertContainer"] {{
                border-radius: 1rem;
            }}

            hr {{
                border-color: var(--rv-border) !important;
            }}

            @media (max-width: 840px) {{
                [data-testid="stAppViewBlockContainer"] {{
                    padding-top: .65rem;
                    padding-left: .75rem;
                    padding-right: .75rem;
                }}

                .rv-hero {{
                    border-radius: 1.3rem;
                }}

                .rv-hero-grid {{
                    flex-direction: column;
                }}

                .rv-status-strip {{
                    grid-template-columns: 1fr;
                }}

                .rv-steps {{
                    grid-template-columns: 1fr;
                }}

                div[data-testid="stHorizontalBlock"] {{
                    flex-wrap: wrap;
                    gap: .65rem;
                }}

                div[data-testid="column"] {{
                    min-width: 100% !important;
                    flex: 1 1 100% !important;
                }}

                div[data-testid="stMetric"] {{
                    min-height: auto;
                }}
            }}

            @media (max-width: 520px) {{
                [data-testid="stAppViewBlockContainer"] {{
                    padding-left: .58rem;
                    padding-right: .58rem;
                }}

                .rv-hero {{
                    padding: 1rem;
                    border-radius: 1.1rem;
                }}

                .rv-auto-theme {{
                    white-space: normal;
                }}

                .rv-pills {{
                    gap: .32rem;
                }}

                .rv-pill {{
                    font-size: .67rem;
                }}

                input, textarea {{
                    font-size: 16px !important;
                }}

                div[data-testid="stButton"] > button {{
                    min-height: 3rem;
                }}
            }}

            @media (prefers-reduced-motion: reduce) {{
                html {{
                    scroll-behavior: auto;
                }}

                *, *::before, *::after {{
                    animation-duration: .01ms !important;
                    animation-iteration-count: 1 !important;
                    transition-duration: .01ms !important;
                }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


aplicar_estilos()


# =============================================================================
# CONFIGURACIÓN SEGURA DE ODOO
# =============================================================================


def obtener_configuracion() -> tuple[str, str, str, str]:
    """Obtiene credenciales desde secrets.toml o variables de entorno."""

    try:
        secretos = st.secrets.get("odoo", {})
    except Exception:
        secretos = {}

    url = str(secretos.get("url") or os.getenv("ODOO_URL", "")).rstrip("/")
    db = str(secretos.get("db") or os.getenv("ODOO_DB", ""))
    usuario = str(secretos.get("user") or os.getenv("ODOO_USER", ""))
    password = str(secretos.get("password") or os.getenv("ODOO_PASSWORD", ""))

    faltantes = [
        nombre
        for nombre, valor in {
            "ODOO_URL": url,
            "ODOO_DB": db,
            "ODOO_USER": usuario,
            "ODOO_PASSWORD": password,
        }.items()
        if not valor
    ]

    if faltantes:
        st.error(
            "Falta configurar: "
            + ", ".join(faltantes)
            + ". Agrega los valores en `.streamlit/secrets.toml`."
        )
        st.stop()

    return url, db, usuario, password


URL, DB, USER, PASSWORD = obtener_configuracion()


# =============================================================================
# CONEXIÓN CON ODOO
# =============================================================================


@st.cache_data(ttl=600, show_spinner=False)
def cargar_datos_odoo(
    url: str,
    db: str,
    usuario: str,
    password: str,
) -> tuple[int, list[dict[str, Any]], list[dict[str, Any]]]:
    common = xmlrpc.client.ServerProxy(
        f"{url}/xmlrpc/2/common",
        allow_none=True,
    )

    uid = common.authenticate(db, usuario, password, {})

    if not uid:
        raise RuntimeError("Odoo rechazó las credenciales proporcionadas.")

    models = xmlrpc.client.ServerProxy(
        f"{url}/xmlrpc/2/object",
        allow_none=True,
    )

    clientes = models.execute_kw(
        db,
        uid,
        password,
        "res.partner",
        "search_read",
        [[("customer_rank", ">", 0), ("active", "=", True)]],
        {
            "fields": ["id", "name", "city", "vat", "email", "phone"],
            "order": "name asc",
        },
    )

    productos = models.execute_kw(
        db,
        uid,
        password,
        "product.product",
        "search_read",
        [[("sale_ok", "=", True), ("active", "=", True)]],
        {
            "fields": ["id", "default_code", "name", "list_price"],
            "order": "default_code asc, name asc",
        },
    )

    return int(uid), clientes, productos


def crear_pedido_odoo(
    uid: int,
    cliente_id: int,
    carrito: list[dict[str, Any]],
    nota: str,
) -> tuple[int, str, str]:
    """
    Crea la orden con los campos mínimos necesarios.

    No se envía product_uom ni product_uom_id. Odoo determina la unidad de
    medida a partir del producto y se evita el error de campos incompatibles.
    """

    models = xmlrpc.client.ServerProxy(
        f"{URL}/xmlrpc/2/object",
        allow_none=True,
    )

    lineas_odoo: list[tuple[int, int, dict[str, Any]]] = []

    for linea in carrito:
        cantidad = int(linea["cantidad"])
        precio = float(linea["precio_unitario"])
        valores_linea: dict[str, Any] = {
            "product_id": int(linea["product_id"]),
            "product_uom_qty": cantidad,
            "price_unit": precio,
        }

        lineas_odoo.append((0, 0, valores_linea))

    valores_orden: dict[str, Any] = {
        "partner_id": int(cliente_id),
        "order_line": lineas_odoo,
        "origin": "RapyVet | Captura móvil de pedidos",
    }

    if nota.strip():
        valores_orden["note"] = nota.strip()

    sale_order_id = models.execute_kw(
        DB,
        uid,
        PASSWORD,
        "sale.order",
        "create",
        [valores_orden],
    )

    estado = "Cotización creada"

    if CONFIRMAR_AUTOMATICAMENTE:
        models.execute_kw(
            DB,
            uid,
            PASSWORD,
            "sale.order",
            "action_confirm",
            [[sale_order_id]],
        )
        estado = "Pedido confirmado"

    folio = str(sale_order_id)

    try:
        registro = models.execute_kw(
            DB,
            uid,
            PASSWORD,
            "sale.order",
            "read",
            [[sale_order_id]],
            {"fields": ["name", "state"]},
        )

        if registro:
            folio = str(registro[0].get("name") or folio)
    except Exception:
        pass

    return int(sale_order_id), folio, estado


# =============================================================================
# FUNCIONES GENERALES
# =============================================================================


def moneda(valor: float) -> str:
    return f"${valor:,.2f}"


def texto_seguro(valor: Any) -> str:
    return html.escape(str(valor or ""))


def construir_mensaje_whatsapp(
    nombre_cliente: str,
    carrito: list[dict[str, Any]],
) -> str:
    """
    Genera un mensaje breve para compartir en el grupo de WhatsApp.

    Solo incluye el nombre del cliente y los productos. Las líneas gratuitas
    se identifican claramente, pero no se muestran precios, folio ni total.
    """

    lineas_mensaje = [str(nombre_cliente).strip() or "Cliente", ""]

    for linea in carrito:
        nombre = str(
            linea.get("nombre_producto")
            or "Producto sin nombre"
        ).strip()
        cantidad = max(1, int(linea.get("cantidad") or 1))
        precio = float(linea.get("precio_unitario") or 0.0)
        parte_promocion = str(
            linea.get("parte_promocion") or ""
        ).lower()
        tipo = str(linea.get("tipo") or "").lower()

        es_gratis = (
            precio == 0.0
            or parte_promocion == "gratis"
            or tipo in {"gratis", "promocion_gratis"}
        )

        texto_linea = f"{cantidad} x {nombre}"
        if es_gratis:
            texto_linea += " (GRATIS)"

        lineas_mensaje.append(texto_linea)

    return "\n".join(lineas_mensaje).strip()


def crear_enlace_whatsapp(mensaje: str) -> str:
    """Abre WhatsApp con el texto listo para elegir el grupo."""

    return (
        "https://api.whatsapp.com/send?text="
        + quote(mensaje, safe="")
    )


def crear_linea_carrito(
    producto: dict[str, Any],
    cantidad: int,
    precio_unitario: float,
    tipo: str,
    grupo_promocion: str | None = None,
    parte_promocion: str | None = None,
) -> dict[str, Any]:
    return {
        "linea_id": uuid.uuid4().hex,
        "product_id": int(producto["id"]),
        "nombre_producto": str(producto.get("name") or "Producto sin nombre"),
        "codigo": str(producto.get("default_code") or "S/C"),
        "precio_lista": float(producto.get("list_price") or 0.0),
        "cantidad": max(1, int(cantidad)),
        "precio_unitario": max(0.0, float(precio_unitario)),
        "tipo": tipo,
        "grupo_promocion": grupo_promocion,
        "parte_promocion": parte_promocion,
    }


def agregar_linea_normal(
    producto: dict[str, Any],
    cantidad: int,
    precio_unitario: float,
) -> None:
    st.session_state.carrito.append(
        crear_linea_carrito(
            producto=producto,
            cantidad=cantidad,
            precio_unitario=precio_unitario,
            tipo="venta",
        )
    )


def agregar_promocion(
    producto: dict[str, Any],
    cantidad_cobrada: int,
    cantidad_gratis: int,
    precio_unitario: float,
) -> None:
    """Agrega exactamente dos líneas del mismo producto."""

    cobradas = max(1, int(cantidad_cobrada))
    gratis = max(1, int(cantidad_gratis))
    precio = max(0.0, float(precio_unitario))
    grupo = uuid.uuid4().hex

    st.session_state.carrito.extend(
        [
            crear_linea_carrito(
                producto=producto,
                cantidad=cobradas,
                precio_unitario=precio,
                tipo="promocion_cobrada",
                grupo_promocion=grupo,
                parte_promocion="cobrada",
            ),
            crear_linea_carrito(
                producto=producto,
                cantidad=gratis,
                precio_unitario=0.0,
                tipo="promocion_gratis",
                grupo_promocion=grupo,
                parte_promocion="gratis",
            ),
        ]
    )

def buscar_linea(linea_id: str) -> dict[str, Any] | None:
    return next(
        (
            linea
            for linea in st.session_state.carrito
            if str(linea["linea_id"]) == linea_id
        ),
        None,
    )


def lineas_del_grupo(grupo_id: str) -> list[dict[str, Any]]:
    return [
        linea
        for linea in st.session_state.carrito
        if linea.get("grupo_promocion") == grupo_id
    ]


def limpiar_widgets_linea(linea_id: str) -> None:
    prefijos = (
        "cantidad_",
        "precio_",
    )
    for prefijo in prefijos:
        st.session_state.pop(f"{prefijo}{linea_id}", None)


def eliminar_linea(linea_id: str) -> None:
    st.session_state.carrito = [
        linea
        for linea in st.session_state.carrito
        if str(linea["linea_id"]) != linea_id
    ]
    limpiar_widgets_linea(linea_id)


def duplicar_linea(linea_id: str) -> None:
    linea = buscar_linea(linea_id)
    if not linea:
        return

    nueva = dict(linea)
    nueva.update(
        {
            "linea_id": uuid.uuid4().hex,
            "grupo_promocion": None,
            "parte_promocion": None,
            "tipo": "venta",
            "cantidad": int(
                st.session_state.get(
                    f"cantidad_{linea_id}",
                    linea["cantidad"],
                )
            ),
            "precio_unitario": float(
                st.session_state.get(
                    f"precio_{linea_id}",
                    linea["precio_unitario"],
                )
            ),
        }
    )
    st.session_state.carrito.append(nueva)


def hacer_linea_gratis(linea_id: str) -> None:
    linea = buscar_linea(linea_id)
    if not linea:
        return

    linea["precio_unitario"] = 0.0
    linea["tipo"] = "gratis"
    st.session_state[f"precio_{linea_id}"] = 0.0


def eliminar_promocion(grupo_id: str) -> None:
    ids = [
        str(linea["linea_id"])
        for linea in st.session_state.carrito
        if linea.get("grupo_promocion") == grupo_id
    ]

    st.session_state.carrito = [
        linea
        for linea in st.session_state.carrito
        if linea.get("grupo_promocion") != grupo_id
    ]

    for linea_id in ids:
        limpiar_widgets_linea(linea_id)



def duplicar_promocion(grupo_id: str) -> None:
    originales = lineas_del_grupo(grupo_id)
    if len(originales) != 2:
        return

    nuevo_grupo = uuid.uuid4().hex

    for linea in originales:
        linea_id = str(linea["linea_id"])
        nueva = dict(linea)
        nueva.update(
            {
                "linea_id": uuid.uuid4().hex,
                "grupo_promocion": nuevo_grupo,
                "cantidad": int(
                    st.session_state.get(
                        f"cantidad_{linea_id}",
                        linea["cantidad"],
                    )
                ),
                "precio_unitario": (
                    0.0
                    if linea.get("parte_promocion") == "gratis"
                    else float(
                        st.session_state.get(
                            f"precio_{linea_id}",
                            linea["precio_unitario"],
                        )
                    )
                ),
            }
        )
        st.session_state.carrito.append(nueva)


def vaciar_carrito() -> None:
    for linea in st.session_state.carrito:
        limpiar_widgets_linea(str(linea["linea_id"]))

    st.session_state.carrito = []


def reiniciar_pedido() -> None:
    vaciar_carrito()

    claves = (
        "cliente_id",
        "producto_id",
        "ultimo_producto_id",
        "cantidad_normal",
        "precio_normal",
        "preset_promocion",
        "cantidad_cobrada",
        "cantidad_gratis",
        "precio_promocion",
        "nota_pedido",
        "resultado_pedido",
        "mostrar_balloons",
    )

    for clave in claves:
        st.session_state.pop(clave, None)

    inicializar_estado()


def aplicar_preset_promocion() -> None:
    valor = str(st.session_state.get("preset_promocion", "Personalizada"))
    if valor == "Personalizada" or "+" not in valor:
        return

    cobradas, gratis = valor.split("+", maxsplit=1)
    st.session_state.cantidad_cobrada = int(cobradas)
    st.session_state.cantidad_gratis = int(gratis)


def validar_carrito(carrito: list[dict[str, Any]]) -> list[str]:
    errores: list[str] = []

    if not carrito:
        return ["El carrito está vacío."]

    for indice, linea in enumerate(carrito, start=1):
        if int(linea.get("cantidad", 0)) < 1:
            errores.append(f"La línea {indice} tiene una cantidad inválida.")
        if float(linea.get("precio_unitario", -1)) < 0:
            errores.append(f"La línea {indice} tiene un precio inválido.")

    grupos = {
        str(linea["grupo_promocion"])
        for linea in carrito
        if linea.get("grupo_promocion")
    }

    for grupo in grupos:
        lineas = [
            linea
            for linea in carrito
            if str(linea.get("grupo_promocion")) == grupo
        ]
        cobradas = [
            linea
            for linea in lineas
            if linea.get("parte_promocion") == "cobrada"
        ]
        gratis = [
            linea
            for linea in lineas
            if linea.get("parte_promocion") == "gratis"
        ]

        if len(lineas) != 2 or len(cobradas) != 1 or len(gratis) != 1:
            errores.append(
                "Hay una promoción incompleta. Debe contener una línea "
                "cobrada y una línea gratis."
            )
            continue

        if float(gratis[0].get("precio_unitario", -1)) != 0.0:
            errores.append("Una línea de promoción gratis no tiene precio $0.00.")

    return errores


def elementos_visuales_carrito() -> list[tuple[str, list[dict[str, Any]]]]:
    """Agrupa promociones visualmente sin alterar sus dos líneas internas."""

    elementos: list[tuple[str, list[dict[str, Any]]]] = []
    grupos_vistos: set[str] = set()

    for linea in st.session_state.carrito:
        grupo = linea.get("grupo_promocion")

        if grupo:
            grupo = str(grupo)
            if grupo in grupos_vistos:
                continue
            grupos_vistos.add(grupo)
            elementos.append(("promocion", lineas_del_grupo(grupo)))
        else:
            elementos.append(("linea", [linea]))

    return elementos


# =============================================================================
# ENCABEZADO
# =============================================================================


tema_actual = obtener_tipo_tema()
icono_tema = "🌙" if tema_actual == "dark" else "☀️"
nombre_tema = "Oscuro" if tema_actual == "dark" else "Claro"

st.markdown(
    f"""
    <div class="rv-hero">
        <div class="rv-hero-grid">
            <div>
                <p class="rv-kicker">Captura de pedidos</p>
                <h1 class="rv-title">🐾 RapyVet Pedidos</h1>
                <p class="rv-subtitle">
                    Agrega productos, configura promociones y envía la orden a
                    Odoo desde teléfono, tableta o computadora.
                </p>
            </div>
            <span class="rv-auto-theme">
                {icono_tema} Tema automático · {nombre_tema}
            </span>
        </div>
        <div class="rv-pills">
            <span class="rv-pill">Dos líneas por promoción</span>
            <span class="rv-pill">Precios editables</span>
            <span class="rv-pill">Productos repetidos</span>
            <span class="rv-pill">Diseño responsivo</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# CARGA DE DATOS
# =============================================================================


try:
    with st.spinner("Conectando con Odoo..."):
        uid, lista_clientes, lista_productos = cargar_datos_odoo(
            URL,
            DB,
            USER,
            PASSWORD,
        )
except xmlrpc.client.Fault as error:
    st.error("Odoo rechazó la solicitud al cargar los datos.")
    with st.expander("Ver detalle técnico"):
        st.code(error.faultString)
    st.stop()
except xmlrpc.client.ProtocolError as error:
    st.error(
        "No fue posible comunicarse con Odoo. "
        f"Código HTTP: {error.errcode}"
    )
    st.stop()
except Exception as error:
    st.error("No fue posible cargar los datos de Odoo.")
    with st.expander("Ver detalle técnico"):
        st.code(str(error))
    st.stop()


clientes_por_id = {
    int(cliente["id"]): cliente
    for cliente in lista_clientes
}

productos_por_id = {
    int(producto["id"]): producto
    for producto in lista_productos
}

if not clientes_por_id:
    st.warning("No se encontraron clientes activos en Odoo.")
    st.stop()

if not productos_por_id:
    st.warning("No se encontraron productos disponibles para venta.")
    st.stop()


# =============================================================================
# FUNCIONES QUE DEPENDEN DE LOS DATOS CARGADOS
# =============================================================================


def etiqueta_cliente(cliente_id: int) -> str:
    cliente = clientes_por_id[cliente_id]
    nombre = cliente.get("name") or "Cliente sin nombre"
    ciudad = cliente.get("city") or "Sin ciudad"
    return f"{nombre} · {ciudad}"


def etiqueta_producto(producto_id: int) -> str:
    producto = productos_por_id[producto_id]
    codigo = producto.get("default_code") or "S/C"
    nombre = producto.get("name") or "Producto sin nombre"
    precio = float(producto.get("list_price") or 0.0)
    return f"{codigo} — {nombre} · {moneda(precio)}"


def sincronizar_producto_seleccionado() -> None:
    producto_id = st.session_state.get("producto_id")
    if producto_id is None:
        return

    producto = productos_por_id.get(int(producto_id))
    if not producto:
        return

    precio = float(producto.get("list_price") or 0.0)
    st.session_state.precio_normal = precio
    st.session_state.precio_promocion = precio
    st.session_state.cantidad_normal = 1
    st.session_state.cantidad_cobrada = 1
    st.session_state.cantidad_gratis = 1
    st.session_state.preset_promocion = "1+1"
    st.session_state.ultimo_producto_id = int(producto_id)


# =============================================================================
# RESULTADO DEL PEDIDO
# =============================================================================


if st.session_state.get("mostrar_balloons"):
    st.balloons()
    st.session_state.mostrar_balloons = False

resultado = st.session_state.get("resultado_pedido")

if resultado:
    with st.container(border=True):
        st.success(f"✅ {resultado['estado']} correctamente en Odoo")
        st.markdown(f"## {texto_seguro(resultado['folio'])}")
        st.markdown(f"**Cliente:** {texto_seguro(resultado['cliente'])}")

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Líneas", resultado["lineas"])
        r2.metric("Unidades", resultado["unidades"])
        r3.metric("Bonificadas", resultado["unidades_gratis"])
        r4.metric("Total", moneda(resultado["total"]))

        st.caption(
            "El total final puede variar si Odoo aplica impuestos, "
            "redondeos o reglas fiscales adicionales."
        )

        st.divider()
        st.markdown("### 📲 Compartir en WhatsApp")
        st.caption(
            "Abre WhatsApp, selecciona el grupo de pedidos y envía el texto."
        )

        enlace_whatsapp = str(resultado.get("enlace_whatsapp") or "")
        texto_whatsapp = str(resultado.get("texto_whatsapp") or "")

        if enlace_whatsapp:
            st.link_button(
                "🟢 Abrir WhatsApp",
                enlace_whatsapp,
                type="primary",
                use_container_width=True,
            )

        with st.expander("Ver o copiar el mensaje", expanded=False):
            st.code(texto_whatsapp, language=None)

        st.button(
            "➕ Capturar otro pedido",
            use_container_width=True,
            on_click=reiniciar_pedido,
        )

    st.stop()


# =============================================================================
# ESTADO Y NAVEGACIÓN VISUAL
# =============================================================================


cliente_actual = st.session_state.get("cliente_id")
cliente_nombre = "Sin seleccionar"
if cliente_actual:
    cliente_nombre = str(
        clientes_por_id[int(cliente_actual)].get("name") or "Cliente"
    )

cantidad_lineas = len(st.session_state.carrito)

st.markdown(
    f"""
    <div class="rv-status-strip">
        <div class="rv-status-item">
            <p class="rv-status-label">Conexión</p>
            <p class="rv-status-value">● Odoo conectado</p>
        </div>
        <div class="rv-status-item">
            <p class="rv-status-label">Cliente</p>
            <p class="rv-status-value">{texto_seguro(cliente_nombre)}</p>
        </div>
        <div class="rv-status-item">
            <p class="rv-status-label">Carrito</p>
            <p class="rv-status-value">{cantidad_lineas} líneas</p>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

paso_1 = "rv-step-done" if cliente_actual else "rv-step-active"
paso_2 = (
    "rv-step-done"
    if st.session_state.carrito
    else ("rv-step-active" if cliente_actual else "")
)
paso_3 = "rv-step-active" if cliente_actual and st.session_state.carrito else ""

st.markdown(
    f"""
    <div class="rv-steps">
        <div class="rv-step {paso_1}">
            <span class="rv-step-number">1</span>
            Seleccionar cliente
        </div>
        <div class="rv-step {paso_2}">
            <span class="rv-step-number">2</span>
            Agregar productos
        </div>
        <div class="rv-step {paso_3}">
            <span class="rv-step-number">3</span>
            Revisar y enviar
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =============================================================================
# CLIENTE Y AGREGADOR DE PRODUCTOS
# =============================================================================


col_cliente, col_producto = st.columns([.85, 1.15], gap="large")

with col_cliente:
    with st.container(border=True):
        st.markdown(
            '<p class="rv-section-title">👤 Cliente</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="rv-section-copy">Busca por nombre o ciudad.</p>',
            unsafe_allow_html=True,
        )

        cliente_id = st.selectbox(
            "Selecciona el cliente",
            options=list(clientes_por_id.keys()),
            index=None,
            placeholder="Escribe para buscar...",
            format_func=etiqueta_cliente,
            key="cliente_id",
        )

        if cliente_id:
            cliente = clientes_por_id[int(cliente_id)]
            detalles = []

            if cliente.get("city"):
                detalles.append(f"📍 {cliente['city']}")
            if cliente.get("vat"):
                detalles.append(f"RFC: {cliente['vat']}")
            if cliente.get("phone"):
                detalles.append(f"📞 {cliente['phone']}")
            if cliente.get("email"):
                detalles.append(f"✉️ {cliente['email']}")

            if detalles:
                st.caption(" · ".join(detalles))

        st.divider()

        if st.button(
            "↻ Actualizar clientes y productos",
            use_container_width=True,
        ):
            cargar_datos_odoo.clear()
            st.rerun()

with col_producto:
    with st.container(border=True):
        st.markdown(
            '<p class="rv-section-title">➕ Agregar producto</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="rv-section-copy">'
            "Puedes repetir el mismo producto y editar cada precio."
            "</p>",
            unsafe_allow_html=True,
        )

        producto_id = st.selectbox(
            "Buscar producto",
            options=list(productos_por_id.keys()),
            index=None,
            placeholder="Código o nombre del producto...",
            format_func=etiqueta_producto,
            key="producto_id",
            on_change=sincronizar_producto_seleccionado,
        )

        producto_seleccionado: dict[str, Any] | None = None

        if producto_id is not None:
            producto_seleccionado = productos_por_id[int(producto_id)]
            precio_lista = float(producto_seleccionado.get("list_price") or 0.0)

            if st.session_state.ultimo_producto_id != int(producto_id):
                sincronizar_producto_seleccionado()

            st.markdown(
                f"""
                <div class="rv-product-preview">
                    <p class="rv-product-name">
                        {texto_seguro(producto_seleccionado.get('name'))}
                    </p>
                    <p class="rv-product-meta">
                        Código {texto_seguro(producto_seleccionado.get('default_code') or 'S/C')}
                        · Precio de lista {moneda(precio_lista)}
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        producto_valido = producto_seleccionado is not None
        tab_venta, tab_promocion = st.tabs(
            ["🧾 Venta normal", "🎁 Promoción"]
        )

        with tab_venta:
            venta_col1, venta_col2 = st.columns(2)

            with venta_col1:
                cantidad_normal = st.number_input(
                    "Cantidad",
                    min_value=1,
                    step=1,
                    key="cantidad_normal",
                )

            with venta_col2:
                precio_normal = st.number_input(
                    "Precio unitario",
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                    key="precio_normal",
                )

            subtotal_normal = int(cantidad_normal) * float(precio_normal)
            st.caption(f"Subtotal de esta línea: {moneda(subtotal_normal)}")

            if st.button(
                "Agregar venta al carrito",
                type="primary",
                use_container_width=True,
                disabled=not producto_valido,
                key="agregar_venta",
            ):
                if producto_seleccionado:
                    agregar_linea_normal(
                        producto=producto_seleccionado,
                        cantidad=int(cantidad_normal),
                        precio_unitario=float(precio_normal),
                    )
                    st.toast("Producto agregado", icon="✅")
                    st.rerun()

        with tab_promocion:
            preset = st.selectbox(
                "Promoción rápida",
                options=PROMOCIONES_RAPIDAS,
                key="preset_promocion",
                on_change=aplicar_preset_promocion,
                help=(
                    "Selecciona una combinación frecuente o elige "
                    "Personalizada y escribe las cantidades."
                ),
            )

            promo_col1, promo_col2 = st.columns(2)

            with promo_col1:
                cantidad_cobrada = st.number_input(
                    "Unidades cobradas",
                    min_value=1,
                    step=1,
                    key="cantidad_cobrada",
                    help="Cantidad que tendrá precio.",
                )

            with promo_col2:
                cantidad_gratis = st.number_input(
                    "Unidades gratis",
                    min_value=1,
                    step=1,
                    key="cantidad_gratis",
                    help="Cantidad que se enviará a $0.00.",
                )

            precio_promocion = st.number_input(
                "Precio unitario de la parte cobrada",
                min_value=0.0,
                step=0.01,
                format="%.2f",
                key="precio_promocion",
            )

            combinacion = f"{int(cantidad_cobrada)}+{int(cantidad_gratis)}"
            total_entregado = int(cantidad_cobrada) + int(cantidad_gratis)
            subtotal_promocion = int(cantidad_cobrada) * float(precio_promocion)

            st.markdown(
                f"""
                <div class="rv-promo-preview">
                    <p><strong>Promoción {combinacion}</strong></p>
                    <p>
                        Línea cobrada: {int(cantidad_cobrada)} ×
                        {moneda(float(precio_promocion))}
                    </p>
                    <p>
                        Línea gratis: {int(cantidad_gratis)} × $0.00
                    </p>
                    <p>
                        Entregas {total_entregado} unidades ·
                        Total {moneda(subtotal_promocion)}
                    </p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button(
                f"Agregar {combinacion} como dos líneas",
                type="primary",
                use_container_width=True,
                disabled=not producto_valido,
                key="agregar_promocion",
            ):
                if producto_seleccionado:
                    agregar_promocion(
                        producto=producto_seleccionado,
                        cantidad_cobrada=int(cantidad_cobrada),
                        cantidad_gratis=int(cantidad_gratis),
                        precio_unitario=float(precio_promocion),
                    )
                    st.toast(
                        f"Promoción {combinacion} agregada en dos líneas",
                        icon="🎁",
                    )
                    st.rerun()


# =============================================================================
# CARRITO VISUAL
# =============================================================================


cabecera_col, vaciar_col = st.columns([5, 1])

with cabecera_col:
    st.markdown(
        f"""
        <div class="rv-cart-heading">
            <h2 style="margin:0;font-size:1.35rem;">🛒 Carrito</h2>
            <span class="rv-cart-count">{len(st.session_state.carrito)} líneas</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

with vaciar_col:
    st.button(
        "Vaciar carrito",
        use_container_width=True,
        disabled=not bool(st.session_state.carrito),
        on_click=vaciar_carrito,
    )


if not st.session_state.carrito:
    st.markdown(
        """
        <div class="rv-empty">
            <div class="rv-empty-icon">🛒</div>
            <div class="rv-empty-title">Tu pedido todavía está vacío</div>
            <div class="rv-empty-copy">
                Selecciona un producto y agrégalo como venta normal o promoción.
                Las promociones se verán como una tarjeta, pero se enviarán a
                Odoo como dos líneas: cobrada y gratis.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    for tipo_elemento, lineas in elementos_visuales_carrito():
        if tipo_elemento == "linea":
            linea = lineas[0]
            linea_id = str(linea["linea_id"])
            clave_cantidad = f"cantidad_{linea_id}"
            clave_precio = f"precio_{linea_id}"

            st.session_state.setdefault(clave_cantidad, int(linea["cantidad"]))
            st.session_state.setdefault(
                clave_precio,
                float(linea["precio_unitario"]),
            )

            with st.container(border=True):
                precio_actual = float(st.session_state[clave_precio])
                es_gratis = precio_actual == 0.0
                badge = "Gratis" if es_gratis else "Venta"
                clase = "rv-badge rv-badge-free" if es_gratis else "rv-badge"

                st.markdown(
                    f"""
                    <div class="rv-line-head">
                        <div>
                            <p class="rv-line-title">
                                {texto_seguro(linea['nombre_producto'])}
                            </p>
                            <p class="rv-line-meta">
                                {texto_seguro(linea['codigo'])} · Lista
                                {moneda(float(linea['precio_lista']))}
                            </p>
                        </div>
                        <span class="{clase}">{badge}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                edit_col1, edit_col2 = st.columns(2)

                with edit_col1:
                    cantidad = st.number_input(
                        "Cantidad",
                        min_value=1,
                        step=1,
                        key=clave_cantidad,
                    )

                with edit_col2:
                    precio = st.number_input(
                        "Precio unitario",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key=clave_precio,
                    )

                linea["cantidad"] = int(cantidad)
                linea["precio_unitario"] = float(precio)
                linea["tipo"] = "gratis" if float(precio) == 0.0 else "venta"

                subtotal = int(cantidad) * float(precio)

                st.markdown(
                    f"""
                    <div class="rv-subtotal">
                        <span class="rv-subtotal-label">Subtotal</span>
                        <span class="rv-subtotal-value">{moneda(subtotal)}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                a1, a2, a3 = st.columns(3)
                with a1:
                    st.button(
                        "Duplicar",
                        key=f"duplicar_{linea_id}",
                        use_container_width=True,
                        on_click=duplicar_linea,
                        args=(linea_id,),
                    )
                with a2:
                    st.button(
                        "Hacer gratis",
                        key=f"gratis_{linea_id}",
                        use_container_width=True,
                        on_click=hacer_linea_gratis,
                        args=(linea_id,),
                    )
                with a3:
                    st.button(
                        "Eliminar",
                        key=f"eliminar_{linea_id}",
                        use_container_width=True,
                        on_click=eliminar_linea,
                        args=(linea_id,),
                    )

        else:
            if len(lineas) != 2:
                st.error("Se encontró una promoción incompleta en el carrito.")
                continue

            grupo_id = str(lineas[0]["grupo_promocion"])
            cobrada = next(
                (
                    linea
                    for linea in lineas
                    if linea.get("parte_promocion") == "cobrada"
                ),
                lineas[0],
            )
            gratis = next(
                (
                    linea
                    for linea in lineas
                    if linea.get("parte_promocion") == "gratis"
                ),
                lineas[1],
            )

            id_cobrada = str(cobrada["linea_id"])
            id_gratis = str(gratis["linea_id"])
            key_cantidad_cobrada = f"cantidad_{id_cobrada}"
            key_precio_cobrada = f"precio_{id_cobrada}"
            key_cantidad_gratis = f"cantidad_{id_gratis}"

            st.session_state.setdefault(
                key_cantidad_cobrada,
                int(cobrada["cantidad"]),
            )
            st.session_state.setdefault(
                key_precio_cobrada,
                float(cobrada["precio_unitario"]),
            )
            st.session_state.setdefault(
                key_cantidad_gratis,
                int(gratis["cantidad"]),
            )

            cantidad_cobrada_actual = int(st.session_state[key_cantidad_cobrada])
            cantidad_gratis_actual = int(st.session_state[key_cantidad_gratis])
            combinacion_actual = (
                f"{cantidad_cobrada_actual}+{cantidad_gratis_actual}"
            )

            with st.container(border=True):
                st.markdown(
                    f"""
                    <div class="rv-promotion-head">
                        <div>
                            <p class="rv-promotion-kicker">Promoción · dos líneas</p>
                            <p class="rv-promotion-title">
                                {texto_seguro(cobrada['nombre_producto'])}
                            </p>
                            <p class="rv-promotion-code">
                                {texto_seguro(cobrada['codigo'])} · Lista
                                {moneda(float(cobrada['precio_lista']))}
                            </p>
                        </div>
                        <span class="rv-promotion-badge">
                            {combinacion_actual}
                        </span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                promo_izq, promo_der = st.columns(2)

                with promo_izq:
                    st.markdown(
                        '<div class="rv-subline-label">Línea cobrada</div>',
                        unsafe_allow_html=True,
                    )
                    cantidad_cobrada_editada = st.number_input(
                        "Unidades cobradas",
                        min_value=1,
                        step=1,
                        key=key_cantidad_cobrada,
                    )
                    precio_cobrado_editado = st.number_input(
                        "Precio unitario cobrado",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key=key_precio_cobrada,
                    )
                    subtotal_cobrado = (
                        int(cantidad_cobrada_editada)
                        * float(precio_cobrado_editado)
                    )
                    st.markdown(
                        f"""
                        <div class="rv-subtotal">
                            <span class="rv-subtotal-label">Subtotal</span>
                            <span class="rv-subtotal-value">
                                {moneda(subtotal_cobrado)}
                            </span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                with promo_der:
                    st.markdown(
                        '<div class="rv-subline-label">Línea gratis</div>',
                        unsafe_allow_html=True,
                    )
                    cantidad_gratis_editada = st.number_input(
                        "Unidades gratis",
                        min_value=1,
                        step=1,
                        key=key_cantidad_gratis,
                    )
                    st.number_input(
                        "Precio unitario gratis",
                        min_value=0.0,
                        value=0.0,
                        format="%.2f",
                        disabled=True,
                        key=f"precio_gratis_visual_{id_gratis}",
                    )
                    st.markdown(
                        """
                        <div class="rv-subtotal">
                            <span class="rv-subtotal-label">Subtotal</span>
                            <span class="rv-subtotal-value">$0.00</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                cobrada["cantidad"] = int(cantidad_cobrada_editada)
                cobrada["precio_unitario"] = float(precio_cobrado_editado)

                gratis["cantidad"] = int(cantidad_gratis_editada)
                gratis["precio_unitario"] = 0.0

                ac1, ac2 = st.columns(2)
                with ac1:
                    st.button(
                        "Duplicar promoción",
                        key=f"duplicar_grupo_{grupo_id}",
                        use_container_width=True,
                        on_click=duplicar_promocion,
                        args=(grupo_id,),
                    )
                with ac2:
                    st.button(
                        "Eliminar promoción",
                        key=f"eliminar_grupo_{grupo_id}",
                        use_container_width=True,
                        on_click=eliminar_promocion,
                        args=(grupo_id,),
                    )


# =============================================================================
# RESUMEN Y ENVÍO
# =============================================================================


carrito = st.session_state.carrito

total_lineas = len(carrito)
total_unidades = sum(int(linea["cantidad"]) for linea in carrito)
unidades_gratis = sum(
    int(linea["cantidad"])
    for linea in carrito
    if float(linea["precio_unitario"]) == 0.0
)
total_pedido = sum(
    int(linea["cantidad"]) * float(linea["precio_unitario"])
    for linea in carrito
)
total_promociones = len(
    {
        linea.get("grupo_promocion")
        for linea in carrito
        if linea.get("grupo_promocion")
    }
)

with st.container(border=True):
    st.markdown(
        '<p class="rv-section-title">🚀 Revisar y enviar</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="rv-section-copy">'
        "Confirma el cliente, las cantidades y los precios antes de crear la orden."
        "</p>",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Líneas en Odoo", total_lineas)
    m2.metric("Unidades", total_unidades)
    m3.metric("Bonificadas", unidades_gratis)
    m4.metric("Promociones", total_promociones)

    st.markdown(
        f"""
        <div class="rv-summary-total">
            <p class="rv-summary-total-label">Total estimado del pedido</p>
            <p class="rv-summary-total-value">{moneda(total_pedido)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    nota = st.text_area(
        "Notas generales del pedido",
        placeholder="Instrucciones de entrega o información adicional...",
        max_chars=700,
        key="nota_pedido",
    )

    cliente_elegido = st.session_state.get("cliente_id")
    errores_carrito = validar_carrito(carrito) if carrito else []
    listo_para_enviar = bool(
        cliente_elegido
        and carrito
        and not errores_carrito
    )

    if not cliente_elegido:
        st.info("Selecciona un cliente para poder enviar el pedido.")
    elif not carrito:
        st.info("Agrega al menos un producto al carrito.")
    elif errores_carrito:
        st.warning("Corrige el carrito antes de enviar el pedido:")
        for error in errores_carrito:
            st.write(f"• {error}")

    enviar = st.button(
        "🚀 Crear pedido en Odoo",
        type="primary",
        use_container_width=True,
        disabled=not listo_para_enviar,
    )


if enviar:
    with st.spinner("Creando el pedido en Odoo..."):
        try:
            _, folio, estado = crear_pedido_odoo(
                uid=uid,
                cliente_id=int(st.session_state.cliente_id),
                carrito=st.session_state.carrito,
                nota=nota,
            )

            cliente = clientes_por_id[int(st.session_state.cliente_id)]
            nombre_cliente = str(cliente.get("name") or "Cliente")

            # Copiamos las líneas antes de cambiar de pantalla para conservar
            # exactamente lo que se envió a Odoo.
            carrito_enviado = [
                dict(linea)
                for linea in st.session_state.carrito
            ]

            texto_whatsapp = construir_mensaje_whatsapp(
                nombre_cliente=nombre_cliente,
                carrito=carrito_enviado,
            )

            st.session_state.resultado_pedido = {
                "folio": folio,
                "estado": estado,
                "cliente": nombre_cliente,
                "lineas": total_lineas,
                "unidades": total_unidades,
                "unidades_gratis": unidades_gratis,
                "total": total_pedido,
                "texto_whatsapp": texto_whatsapp,
                "enlace_whatsapp": crear_enlace_whatsapp(texto_whatsapp),
            }
            st.session_state.mostrar_balloons = True
            st.rerun()

        except xmlrpc.client.Fault as error:
            st.error(
                "Odoo rechazó el pedido. Revisa los datos y vuelve a intentarlo."
            )
            with st.expander("Ver detalle técnico"):
                st.code(error.faultString)
        except xmlrpc.client.ProtocolError as error:
            st.error(
                "Error de comunicación con Odoo. "
                f"Código HTTP: {error.errcode}"
            )
        except Exception as error:
            st.error("No se pudo registrar el pedido en Odoo.")
            with st.expander("Ver detalle técnico"):
                st.code(str(error))
