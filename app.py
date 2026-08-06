from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import time
import unicodedata
import uuid
import xmlrpc.client
from typing import Any
from urllib.parse import quote

import streamlit as st
from st_keyup import st_keyup
from streamlit_js_eval import streamlit_js_eval

from rapyvet.odoo_rpc import crear_proxy_odoo
from rapyvet.taxes import calcular_impuestos as calcular_impuestos_locales


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

st.set_page_config(
    page_title="RapyVet Pedidos",
    page_icon="🐾",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "RapyVet · Interfaz móvil y escritorio conectada con Odoo"},
)

CONFIRMAR_AUTOMATICAMENTE = False
PRODUCTOS_POR_PAGINA = 6
COLUMNAS_CATALOGO = 3
PROMOCIONES_RAPIDAS = ("1+1", "2+1", "2+2", "4+1", "10+2", "11+1", "Otra")
ODOO_TIMEOUT_SEGUNDOS = 15.0

logger = logging.getLogger("rapyvet.pedidos")

# Borrador persistente en el navegador. Se elimina después de crear el pedido
# o al iniciar uno nuevo. El vencimiento evita recuperar pedidos antiguos.
BORRADOR_LOCAL_KEY = "rapyvet_pedido_borrador_v1"
BORRADOR_LOCAL_VERSION = 1
BORRADOR_LOCAL_TTL_SEGUNDOS = 24 * 60 * 60


# =============================================================================
# ESTADO
# =============================================================================


def inicializar_estado() -> None:
    valores: dict[str, Any] = {
        "carrito": [],
        "cliente_id": None,
        "resultado_pedido": None,
        "mostrar_balloons": False,
        "producto_promocion_id": None,
        "productos_recientes": [],
        "clientes_recientes": [],
        "busqueda_pos": "",
        "busqueda_widget_version": 0,
        "categoria_pos": "Todas",
        "vista_pos": "Todos",
        "pagina_catalogo": 0,
        "notificacion_pendiente": None,
        "nota_pedido": "",
        "desktop_nota_pedido": "",
        "mobile_nota_pedido": "",
        "mobile_tab": "Productos",
        "enviar_pedido": False,
        "confirmar_envio": False,
        "envio_en_progreso": False,
        "pedido_token": f"RV-{uuid.uuid4().hex}",
        # Estado exclusivo de la interfaz de escritorio clásica.
        "desktop_producto_id": None,
        "desktop_ultimo_producto_id": None,
        "desktop_cantidad_normal": 1,
        "desktop_precio_normal": 0.0,
        "desktop_preset_promocion": "1+1",
        "desktop_cantidad_cobrada": 1,
        "desktop_cantidad_gratis": 1,
        "desktop_precio_promocion": 0.0,
        "desktop_limpiar_producto": False,
        # Control del borrador guardado en localStorage.
        "borrador_local_cargado": False,
        "borrador_local_disponible": True,
        "borrador_local_pendiente": None,
        "borrador_local_huella": "",
        "borrador_local_eliminar": False,
        "borrador_local_restaurado": False,
    }

    for clave, valor in valores.items():
        if clave not in st.session_state:
            st.session_state[clave] = valor


inicializar_estado()

# Limpia el formulario de escritorio en el siguiente rerun. Streamlit no
# permite cambiar la clave de un widget después de haberlo creado en la misma
# ejecución, por eso se procesa aquí, antes de renderizar el selector.
if st.session_state.get("desktop_limpiar_producto", False):
    st.session_state.desktop_producto_id = None
    st.session_state.desktop_ultimo_producto_id = None
    st.session_state.desktop_cantidad_normal = 1
    st.session_state.desktop_precio_normal = 0.0
    st.session_state.desktop_preset_promocion = "1+1"
    st.session_state.desktop_cantidad_cobrada = 1
    st.session_state.desktop_cantidad_gratis = 1
    st.session_state.desktop_precio_promocion = 0.0
    st.session_state.desktop_limpiar_producto = False

if st.session_state.notificacion_pendiente:
    aviso = st.session_state.notificacion_pendiente
    st.toast(aviso["texto"], icon=aviso.get("icono", "✅"))
    st.session_state.notificacion_pendiente = None


# =============================================================================
# ESTILOS — ESCRITORIO + EXPERIENCIA MÓVIL NATIVA
# =============================================================================

st.markdown(
    """
    <style>
        :root {
            --rv-bg: #f3f6f8;
            --rv-surface: #ffffff;
            --rv-surface-soft: #f7fafb;
            --rv-text: #17212b;
            --rv-muted: #667482;
            --rv-border: #dce4e9;
            --rv-primary: #0f766e;
            --rv-primary-hover: #0a625c;
            --rv-primary-soft: #e4f5f2;
            --rv-promo-soft: #fff2d1;
            --rv-promo-text: #7a5200;
            --rv-danger: #b42318;
            --rv-shadow: 0 12px 34px rgba(25, 42, 58, .08);
            color-scheme: light;
        }

        @media (prefers-color-scheme: dark) {
            :root {
                --rv-bg: #071018;
                --rv-surface: #0d1822;
                --rv-surface-soft: #14212c;
                --rv-text: #f3f7fa;
                --rv-muted: #9caab7;
                --rv-border: #293a49;
                --rv-primary: #45d5c3;
                --rv-primary-hover: #69dfd1;
                --rv-primary-soft: rgba(69, 213, 195, .14);
                --rv-promo-soft: rgba(255, 190, 68, .14);
                --rv-promo-text: #ffd27a;
                --rv-danger: #ff918a;
                --rv-shadow: 0 16px 42px rgba(0, 0, 0, .32);
                color-scheme: dark;
            }
        }

        html {
            scroll-behavior: smooth;
            -webkit-text-size-adjust: 100%;
        }

        [data-testid="stAppViewContainer"] {
            background: var(--rv-bg);
            color: var(--rv-text);
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        /*
         * streamlit-js-eval se renderiza dentro de un iframe invisible.
         * Algunas versiones de Streamlit reservan cerca de 150 px para ese
         * componente aunque no muestre contenido. Colapsamos exclusivamente
         * ese iframe sin afectar el buscador st_keyup ni otros componentes.
         */
        iframe[title*="streamlit_js_eval"],
        iframe[src*="streamlit_js_eval"] {
            display: block !important;
            width: 1px !important;
            height: 1px !important;
            min-height: 1px !important;
            max-height: 1px !important;
            border: 0 !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }

        div[data-testid="stCustomComponentV1"]:has(
            iframe[title*="streamlit_js_eval"]
        ),
        div[data-testid="stCustomComponentV1"]:has(
            iframe[src*="streamlit_js_eval"]
        ),
        div[data-testid="stElementContainer"]:has(
            iframe[title*="streamlit_js_eval"]
        ),
        div[data-testid="stElementContainer"]:has(
            iframe[src*="streamlit_js_eval"]
        ) {
            height: 1px !important;
            min-height: 1px !important;
            max-height: 1px !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }

        [data-testid="stAppViewBlockContainer"] {
            max-width: 1480px;
            padding-top: .15rem;
            padding-bottom: 3rem;
        }

        p, label, h1, h2, h3, h4,
        [data-testid="stMarkdownContainer"] {
            color: var(--rv-text);
        }

        .rv-topbar,
        .rv-mobile-appbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .8rem;
            margin-bottom: .65rem;
            padding: .75rem .85rem;
            border: 1px solid var(--rv-border);
            border-radius: 1rem;
            background: var(--rv-surface);
            box-shadow: var(--rv-shadow);
        }

        .rv-brand {
            display: flex;
            align-items: center;
            gap: .65rem;
            min-width: 0;
        }

        .rv-brand-icon {
            display: grid;
            flex: 0 0 auto;
            width: 2.45rem;
            height: 2.45rem;
            place-items: center;
            border-radius: .82rem;
            background: var(--rv-primary);
            color: #fff;
            font-size: 1.15rem;
        }

        .rv-brand-title {
            margin: 0;
            font-size: 1.04rem;
            font-weight: 950;
            letter-spacing: -.035em;
        }

        .rv-brand-copy {
            margin: .05rem 0 0;
            color: var(--rv-muted) !important;
            font-size: .69rem;
        }

        .rv-top-stats,
        .rv-mobile-status {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            gap: .35rem;
            flex-wrap: wrap;
        }

        .rv-pill {
            padding: .32rem .54rem;
            border: 1px solid var(--rv-border);
            border-radius: 999px;
            background: var(--rv-surface-soft);
            font-size: .68rem;
            font-weight: 850;
            white-space: nowrap;
        }

        .rv-online-dot {
            display: inline-block;
            width: .48rem;
            height: .48rem;
            margin-right: .25rem;
            border-radius: 999px;
            background: #22c55e;
            box-shadow: 0 0 0 3px rgba(34, 197, 94, .15);
            vertical-align: .02rem;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--rv-border);
            border-radius: 1rem;
            background: var(--rv-surface);
            box-shadow: 0 4px 16px rgba(20, 35, 50, .04);
        }

        .rv-section-title {
            margin: 0;
            font-size: 1rem;
            font-weight: 950;
            letter-spacing: -.025em;
        }

        .rv-section-copy {
            margin: .12rem 0 .55rem;
            color: var(--rv-muted) !important;
            font-size: .73rem;
            line-height: 1.4;
        }

        .rv-product-card {
            min-height: 4.65rem;
            padding: .55rem .62rem .24rem;
            border-radius: .78rem;
            background: linear-gradient(145deg, var(--rv-surface-soft), var(--rv-surface));
        }

        .rv-product-code {
            margin: 0;
            color: var(--rv-primary) !important;
            font-size: .61rem;
            font-weight: 950;
            letter-spacing: .06em;
            text-transform: uppercase;
        }

        .rv-product-name {
            display: -webkit-box;
            overflow: hidden;
            min-height: 1.9rem;
            margin: .1rem 0 0;
            font-size: .76rem;
            font-weight: 900;
            line-height: 1.22;
            -webkit-box-orient: vertical;
            -webkit-line-clamp: 2;
        }

        .rv-product-price {
            margin: .2rem 0 0;
            color: var(--rv-muted) !important;
            font-size: .7rem;
            font-weight: 850;
        }

        .rv-tax-note {
            margin: .12rem 0 0;
            color: var(--rv-primary) !important;
            font-size: .62rem;
            font-weight: 850;
            line-height: 1.25;
        }

        .rv-tax-note-none {
            color: var(--rv-muted) !important;
        }

        .rv-mobile-page-title {
            margin: .1rem 0 .12rem;
            font-size: 1.25rem;
            font-weight: 950;
            letter-spacing: -.04em;
        }

        .rv-mobile-page-copy {
            margin: 0 0 .72rem;
            color: var(--rv-muted) !important;
            font-size: .78rem;
            line-height: 1.45;
        }

        .rv-mobile-client-label,
        .rv-mobile-filter-label {
            margin: 0 0 .28rem;
            color: var(--rv-muted) !important;
            font-size: .66rem;
            font-weight: 900;
            letter-spacing: .05em;
            text-transform: uppercase;
        }

        .rv-mobile-product-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: .16rem .8rem;
            align-items: center;
            padding: .05rem .02rem .45rem;
        }

        .rv-mobile-product-row .rv-product-code {
            grid-column: 1;
            grid-row: 1;
        }

        .rv-mobile-product-row .rv-product-name {
            grid-column: 1;
            grid-row: 2;
            min-height: 0;
            margin-top: .08rem;
            font-size: .86rem;
            line-height: 1.28;
            -webkit-line-clamp: 2;
        }

        .rv-mobile-product-row .rv-product-price {
            grid-column: 2;
            grid-row: 1 / span 2;
            margin: 0;
            color: var(--rv-primary) !important;
            font-size: .9rem;
            font-weight: 950;
            white-space: nowrap;
        }

        .rv-results {
            margin: .42rem 0 .35rem;
            color: var(--rv-muted) !important;
            font-size: .69rem;
            font-weight: 780;
        }

        .rv-cart-line {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: .6rem;
            align-items: center;
        }

        .rv-cart-name {
            overflow: hidden;
            margin: 0;
            font-size: .84rem;
            font-weight: 900;
            line-height: 1.25;
            text-overflow: ellipsis;
        }

        .rv-cart-detail {
            margin: .12rem 0 0;
            color: var(--rv-muted) !important;
            font-size: .69rem;
            line-height: 1.35;
        }

        .rv-cart-subtotal {
            margin: 0;
            font-size: .82rem;
            font-weight: 950;
            white-space: nowrap;
        }

        .rv-promo-chip,
        .rv-free-chip {
            display: inline-block;
            margin-left: .28rem;
            padding: .1rem .36rem;
            border-radius: 999px;
            font-size: .58rem;
            font-weight: 950;
            vertical-align: .08rem;
        }

        .rv-promo-chip {
            background: var(--rv-promo-soft);
            color: var(--rv-promo-text) !important;
        }

        .rv-free-chip {
            background: var(--rv-primary-soft);
            color: var(--rv-primary) !important;
        }

        .rv-qty-display {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 2.75rem;
            border: 1px solid var(--rv-border);
            border-radius: .78rem;
            background: var(--rv-surface-soft);
            font-size: .9rem;
            font-weight: 950;
        }

        .rv-total-box {
            margin-top: .65rem;
            padding: .8rem .88rem;
            border-radius: .95rem;
            background: var(--rv-primary-soft);
        }

        .rv-total-label {
            margin: 0;
            color: var(--rv-muted) !important;
            font-size: .65rem;
            font-weight: 900;
            letter-spacing: .055em;
            text-transform: uppercase;
        }

        .rv-total-value {
            margin: .08rem 0 0;
            font-size: 1.45rem;
            font-weight: 950;
            letter-spacing: -.04em;
        }

        .rv-empty {
            padding: 1.7rem .8rem;
            text-align: center;
        }

        .rv-empty-icon { font-size: 1.75rem; }
        .rv-empty-title { margin-top: .28rem; font-size: .87rem; font-weight: 900; }
        .rv-empty-copy {
            max-width: 21rem;
            margin: .14rem auto 0;
            color: var(--rv-muted) !important;
            font-size: .71rem;
            line-height: 1.4;
        }

        .rv-page-status {
            display: flex;
            min-height: 2.5rem;
            align-items: center;
            justify-content: center;
            color: var(--rv-muted);
            font-size: .7rem;
            font-weight: 850;
            text-align: center;
        }

        .rv-loading {
            max-width: 22rem;
            margin: 25vh auto 0;
            padding: 1rem;
            color: var(--rv-muted);
            text-align: center;
        }

        .rv-mobile-bottom-summary {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .75rem;
            padding: .1rem .18rem .28rem;
        }

        .rv-mobile-bottom-copy {
            margin: 0;
            color: var(--rv-muted) !important;
            font-size: .68rem;
            font-weight: 800;
        }

        .rv-mobile-bottom-total {
            margin: 0;
            font-size: .94rem;
            font-weight: 950;
            white-space: nowrap;
        }

        div[data-testid="stButton"] > button {
            min-height: 2.65rem;
            border-radius: .72rem;
            font-weight: 850;
        }

        button[kind="primary"] {
            background: var(--rv-primary);
            border-color: var(--rv-primary);
        }

        button[kind="primary"]:hover {
            background: var(--rv-primary-hover);
            border-color: var(--rv-primary-hover);
        }

        .rv-desktop-cart-wrap {
            position: sticky;
            top: .55rem;
        }

        /* El key de st.container crea la clase st-key-... de forma estable. */
        .st-key-rv_mobile_search_area {
            position: sticky;
            top: 0;
            z-index: 80;
            margin: 0 -.12rem .55rem;
            padding: .55rem .12rem .45rem;
            background: color-mix(in srgb, var(--rv-bg) 94%, transparent);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
        }

        .st-key-rv_mobile_bottom_bar {
            padding: .42rem .5rem calc(.38rem + env(safe-area-inset-bottom));
            border: 1px solid var(--rv-border);
            border-radius: 1.2rem 1.2rem .9rem .9rem;
            background: color-mix(in srgb, var(--rv-surface) 96%, transparent);
            box-shadow: 0 -10px 34px rgba(0, 0, 0, .22);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }

        .st-key-rv_mobile_bottom_bar [data-testid="stVerticalBlock"] {
            gap: .34rem;
        }

        .st-key-rv_mobile_bottom_bar div[data-testid="stButton"] > button {
            min-height: 3.12rem;
            border-radius: .88rem;
            font-size: .8rem;
            font-weight: 950;
        }

        .st-key-rv_mobile_client_card {
            margin-bottom: .65rem;
        }

        .st-key-rv_mobile_client_card > div {
            padding: .74rem !important;
        }

        [class*="st-key-rv_mobile_product_card_"] > div,
        .st-key-rv_mobile_cart_card > div {
            padding: .68rem !important;
        }

        @media (max-width: 820px) {
            [data-testid="stAppViewBlockContainer"] {
                max-width: 100%;
                padding: .12rem .62rem 9.4rem;
            }

            [data-testid="stToolbar"] { display: none !important; }
            [data-testid="stHeader"] { height: 0 !important; }

            /* Streamlit apila columnas en pantallas angostas. En estos tres
               controles la disposición horizontal ahorra varios gestos y
               mantiene juntas las acciones relacionadas. */
            .st-key-rv_mobile_client_card [data-testid="stHorizontalBlock"],
            [class*="st-key-rv_mobile_product_card_"] [data-testid="stHorizontalBlock"],
            .st-key-rv_mobile_bottom_bar [data-testid="stHorizontalBlock"] {
                flex-wrap: nowrap !important;
                align-items: stretch !important;
            }

            .st-key-rv_mobile_client_card [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            [class*="st-key-rv_mobile_product_card_"] [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            .st-key-rv_mobile_bottom_bar [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"] {
                width: auto !important;
                min-width: 0 !important;
                flex: 1 1 0 !important;
            }

            .st-key-rv_mobile_client_card [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:last-child,
            [class*="st-key-rv_mobile_product_card_"] [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:last-child {
                flex: 0 0 3.25rem !important;
            }

            .rv-mobile-appbar {
                margin-bottom: .55rem;
                padding: .62rem .68rem;
                border-radius: .92rem;
                box-shadow: 0 8px 24px rgba(0, 0, 0, .12);
            }

            .rv-brand-icon {
                width: 2.25rem;
                height: 2.25rem;
                border-radius: .72rem;
            }

            .rv-brand-title { font-size: .98rem; }
            .rv-brand-copy { display: none; }
            .rv-mobile-status .rv-pill { padding: .26rem .44rem; font-size: .62rem; }

            div[data-testid="stVerticalBlockBorderWrapper"] {
                border-radius: .92rem;
            }

            div[data-testid="stButton"] > button {
                min-height: 2.95rem;
                font-size: .81rem;
            }

            [data-testid="stDialog"] > div {
                width: calc(100vw - .7rem) !important;
                max-width: calc(100vw - .7rem) !important;
                border-radius: 1rem !important;
            }

            input, textarea, [data-baseweb="select"] {
                font-size: 16px !important;
            }

            .rv-total-value { font-size: 1.58rem; }
        }


        /* ================================================================
           INTERFAZ EXCLUSIVA DE ESCRITORIO
           Se renderiza solo cuando el navegador mide más de 820 px.
           ================================================================ */
        @media (min-width: 821px) {
            .rv-classic-hero {
                position: relative;
                overflow: hidden;
                margin-bottom: .85rem;
                padding: 1.35rem 1.55rem;
                border: 1px solid rgba(255,255,255,.14);
                border-radius: 1.35rem;
                background: linear-gradient(128deg, #0f766e 0%, #0369a1 100%);
                box-shadow: var(--rv-shadow);
            }

            .rv-classic-hero::after {
                content: "";
                position: absolute;
                width: 18rem;
                height: 18rem;
                top: -11rem;
                right: -4rem;
                border-radius: 999px;
                background: rgba(255,255,255,.10);
            }

            .rv-classic-hero-grid {
                position: relative;
                z-index: 1;
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
            }

            .rv-classic-kicker {
                margin: 0 0 .2rem;
                color: rgba(255,255,255,.76) !important;
                font-size: .7rem;
                font-weight: 900;
                letter-spacing: .09em;
                text-transform: uppercase;
            }

            .rv-classic-title {
                margin: 0;
                color: #fff !important;
                font-size: 2rem;
                font-weight: 950;
                letter-spacing: -.05em;
                line-height: 1.05;
            }

            .rv-classic-subtitle {
                max-width: 48rem;
                margin: .45rem 0 0;
                color: rgba(255,255,255,.88) !important;
                font-size: .9rem;
            }

            .rv-classic-pills {
                position: relative;
                z-index: 1;
                display: flex;
                flex-wrap: wrap;
                gap: .38rem;
                margin-top: .8rem;
            }

            .rv-classic-pill {
                padding: .3rem .58rem;
                border: 1px solid rgba(255,255,255,.18);
                border-radius: 999px;
                background: rgba(255,255,255,.11);
                color: #fff !important;
                font-size: .68rem;
                font-weight: 800;
            }

            .rv-classic-status-grid {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: .65rem;
                margin: .75rem 0;
            }

            .rv-classic-status-card {
                min-width: 0;
                padding: .72rem .82rem;
                border: 1px solid var(--rv-border);
                border-radius: .95rem;
                background: var(--rv-surface);
                box-shadow: 0 .35rem 1.1rem var(--rv-shadow);
            }

            .rv-classic-status-label {
                margin: 0;
                color: var(--rv-muted) !important;
                font-size: .64rem;
                font-weight: 900;
                letter-spacing: .06em;
                text-transform: uppercase;
            }

            .rv-classic-status-value {
                overflow: hidden;
                margin: .12rem 0 0;
                color: var(--rv-text) !important;
                font-size: .86rem;
                font-weight: 900;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .rv-classic-steps {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: .5rem;
                margin: 0 0 .85rem;
            }

            .rv-classic-step {
                display: flex;
                align-items: center;
                gap: .48rem;
                padding: .55rem .66rem;
                border: 1px solid var(--rv-border);
                border-radius: .8rem;
                background: var(--rv-surface);
                color: var(--rv-muted) !important;
                font-size: .73rem;
                font-weight: 800;
            }

            .rv-classic-step-number {
                display: grid;
                flex: 0 0 auto;
                width: 1.45rem;
                height: 1.45rem;
                place-items: center;
                border-radius: 999px;
                background: var(--rv-surface-soft);
                color: var(--rv-muted) !important;
                font-size: .68rem;
                font-weight: 950;
            }

            .rv-classic-step.active {
                border-color: var(--rv-primary);
                color: var(--rv-text) !important;
                box-shadow: 0 0 0 .16rem var(--rv-primary-soft);
            }

            .rv-classic-step.done {
                color: var(--rv-text) !important;
            }

            .rv-classic-step.active .rv-classic-step-number,
            .rv-classic-step.done .rv-classic-step-number {
                background: var(--rv-primary);
                color: #fff !important;
            }

            .rv-classic-section-title {
                margin: 0;
                font-size: 1.04rem;
                font-weight: 950;
                letter-spacing: -.025em;
            }

            .rv-classic-section-copy {
                margin: .2rem 0 .75rem;
                color: var(--rv-muted) !important;
                font-size: .78rem;
            }

            .rv-classic-product-preview {
                margin: .65rem 0;
                padding: .75rem .82rem;
                border: 1px solid var(--rv-border);
                border-radius: .85rem;
                background: var(--rv-surface-soft);
            }

            .rv-classic-product-name {
                margin: 0;
                color: var(--rv-text) !important;
                font-size: .9rem;
                font-weight: 900;
            }

            .rv-classic-product-meta {
                margin: .18rem 0 0;
                color: var(--rv-muted) !important;
                font-size: .72rem;
            }

            .rv-classic-promo-preview {
                margin: .65rem 0;
                padding: .72rem .8rem;
                border: 1px solid var(--rv-border);
                border-left: .25rem solid var(--rv-primary);
                border-radius: .85rem;
                background: var(--rv-surface-soft);
                color: var(--rv-muted) !important;
                font-size: .74rem;
                line-height: 1.45;
            }

            .rv-classic-cart-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                margin: 1rem 0 .55rem;
            }

            .rv-classic-cart-title {
                margin: 0;
                color: var(--rv-text) !important;
                font-size: 1.28rem;
                font-weight: 950;
                letter-spacing: -.035em;
            }

            .rv-classic-cart-chip {
                padding: .36rem .64rem;
                border: 1px solid var(--rv-border);
                border-radius: 999px;
                background: var(--rv-surface-soft);
                color: var(--rv-primary) !important;
                font-size: .72rem;
                font-weight: 950;
                white-space: nowrap;
            }
        }
    </style>
    """,
    unsafe_allow_html=True,
)


# Detecta el dispositivo y recupera el borrador en una sola comunicación con
# el navegador. La versión anterior necesitaba dos ciclos de carga separados.
_clave_borrador_js = json.dumps(BORRADOR_LOCAL_KEY)
_estado_navegador_crudo = streamlit_js_eval(
    js_expressions=(
        "(() => {"
        "let width = window.screen.width;"
        "try { width = window.parent.innerWidth || width; } catch (_) {}"
        "try {"
        f"const value = window.localStorage.getItem({_clave_borrador_js});"
        "return JSON.stringify({width: width, value: value, error: null});"
        "} catch (error) {"
        "return JSON.stringify({width: width, value: null, error: String(error)});"
        "}"
        "})()"
    ),
    key="rv_browser_bootstrap_v1",
)

if _estado_navegador_crudo is None:
    st.markdown(
        '<div class="rv-loading">Preparando la interfaz…</div>',
        unsafe_allow_html=True,
    )
    st.stop()

try:
    _estado_navegador = json.loads(str(_estado_navegador_crudo))
except (TypeError, ValueError, json.JSONDecodeError):
    _estado_navegador = {"width": None, "value": None, "error": "invalid"}

ancho_dispositivo = _estado_navegador.get("width")


def obtener_modo_forzado() -> str:
    """Permite forzar la interfaz con ?ui=desktop o ?ui=mobile."""

    try:
        valor = st.query_params.get("ui", "")
    except Exception:
        return ""

    if isinstance(valor, list):
        valor = valor[0] if valor else ""

    valor = str(valor).strip().lower()
    return valor if valor in {"desktop", "mobile"} else ""


MODO_FORZADO = obtener_modo_forzado()

if MODO_FORZADO == "mobile":
    ES_MOVIL = True
elif MODO_FORZADO == "desktop":
    ES_MOVIL = False
else:
    try:
        ES_MOVIL = int(float(ancho_dispositivo)) <= 820
    except (TypeError, ValueError):
        # Si el navegador no devuelve un valor válido, se prioriza escritorio
        # para no mostrar una interfaz móvil comprimida en una computadora.
        ES_MOVIL = False


# =============================================================================
# BORRADOR LOCAL DEL NAVEGADOR
# =============================================================================


def _expresion_guardar_borrador_local(valor_json: str) -> str:
    clave = json.dumps(BORRADOR_LOCAL_KEY)
    valor = json.dumps(valor_json, ensure_ascii=False)
    return (
        "(() => {"
        "try {"
        f"window.localStorage.setItem({clave}, {valor});"
        "return true;"
        "} catch (error) { return false; }"
        "})()"
    )


def _expresion_eliminar_borrador_local() -> str:
    clave = json.dumps(BORRADOR_LOCAL_KEY)
    return (
        "(() => {"
        "try {"
        f"window.localStorage.removeItem({clave});"
        "return true;"
        "} catch (error) { return false; }"
        "})()"
    )


def _contenido_borrador_actual() -> dict[str, Any]:
    """Devuelve únicamente datos JSON necesarios para recuperar el pedido."""

    lineas: list[dict[str, Any]] = []
    campos_linea = (
        "linea_id",
        "product_id",
        "nombre_producto",
        "codigo",
        "cantidad",
        "precio_unitario",
        "precio_final_unitario",
        "impuestos_unitarios",
        "tiene_impuestos",
        "texto_impuestos",
        "tipo",
        "grupo_promocion",
        "parte_promocion",
    )

    for linea in st.session_state.get("carrito", []):
        if not isinstance(linea, dict):
            continue
        lineas.append(
            {
                campo: linea.get(campo)
                for campo in campos_linea
            }
        )

    cliente_id = st.session_state.get("cliente_id")
    try:
        cliente_id = int(cliente_id) if cliente_id is not None else None
    except (TypeError, ValueError):
        cliente_id = None

    return {
        "version": BORRADOR_LOCAL_VERSION,
        "cliente_id": cliente_id,
        "carrito": lineas,
        "nota_pedido": str(st.session_state.get("nota_pedido") or ""),
        "pedido_token": str(st.session_state.get("pedido_token") or ""),
    }


def _huella_borrador(contenido: dict[str, Any]) -> str:
    serializado = json.dumps(
        contenido,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def guardar_borrador_en_navegador(component_key: str) -> None:
    """Guarda solo cuando cambia el cliente, carrito o nota."""

    if not st.session_state.get("borrador_local_cargado", False):
        return
    if not st.session_state.get("borrador_local_disponible", True):
        return
    if st.session_state.get("borrador_local_pendiente") is not None:
        return

    contenido = _contenido_borrador_actual()
    hay_datos = bool(
        contenido["cliente_id"]
        or contenido["carrito"]
        or str(contenido["nota_pedido"]).strip()
    )
    debe_eliminar = bool(
        st.session_state.get("borrador_local_eliminar", False)
        or st.session_state.get("resultado_pedido")
        or not hay_datos
    )

    if debe_eliminar:
        if st.session_state.get("borrador_local_huella") != "__eliminado__":
            streamlit_js_eval(
                js_expressions=_expresion_eliminar_borrador_local(),
                want_output=False,
                key=component_key,
            )
            st.session_state.borrador_local_huella = "__eliminado__"
        st.session_state.borrador_local_eliminar = False
        return

    huella = _huella_borrador(contenido)
    if huella == st.session_state.get("borrador_local_huella"):
        return

    paquete = {
        **contenido,
        "updated_at": time.time(),
    }
    paquete_json = json.dumps(
        paquete,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    streamlit_js_eval(
        js_expressions=_expresion_guardar_borrador_local(paquete_json),
        want_output=False,
        key=component_key,
    )
    st.session_state.borrador_local_huella = huella


def cargar_borrador_del_navegador() -> None:
    """Lee localStorage una vez al iniciar una nueva sesión de Streamlit."""

    if st.session_state.get("borrador_local_cargado", False):
        return

    st.session_state.borrador_local_cargado = True

    try:
        envoltura = _estado_navegador
        if isinstance(envoltura, dict) and envoltura.get("error"):
            st.session_state.borrador_local_disponible = False
            return
        valor = envoltura.get("value") if isinstance(envoltura, dict) else None
        paquete = json.loads(valor) if valor else None
    except (TypeError, ValueError, json.JSONDecodeError):
        paquete = None
        st.session_state.borrador_local_eliminar = True

    if not isinstance(paquete, dict):
        return

    try:
        version = int(paquete.get("version") or 0)
        actualizado = float(paquete.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        st.session_state.borrador_local_eliminar = True
        return

    vigente = 0 <= (time.time() - actualizado) <= BORRADOR_LOCAL_TTL_SEGUNDOS
    if version != BORRADOR_LOCAL_VERSION or not vigente:
        st.session_state.borrador_local_eliminar = True
        return

    if not isinstance(paquete.get("carrito", []), list):
        st.session_state.borrador_local_eliminar = True
        return

    st.session_state.borrador_local_pendiente = paquete


cargar_borrador_del_navegador()


# =============================================================================
# CONFIGURACIÓN Y ODOO
# =============================================================================


def obtener_configuracion() -> tuple[str, str, str, str]:
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


@st.cache_data(ttl=600, show_spinner=False)
def cargar_datos_odoo(
    url: str,
    db: str,
    usuario: str,
    password: str,
) -> tuple[
    int,
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    inicio = time.perf_counter()
    common = crear_proxy_odoo(
        url,
        "/xmlrpc/2/common",
        timeout=ODOO_TIMEOUT_SEGUNDOS,
    )
    uid = common.authenticate(db, usuario, password, {})

    if not uid:
        raise RuntimeError("Odoo rechazó las credenciales proporcionadas.")

    models = crear_proxy_odoo(
        url,
        "/xmlrpc/2/object",
        timeout=ODOO_TIMEOUT_SEGUNDOS,
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
            "fields": ["id", "default_code", "name", "list_price", "categ_id", "taxes_id"],
            "order": "default_code asc, name asc",
        },
    )

    # El índice se construye una sola vez dentro del resultado cacheado. Así el
    # buscador no normaliza nuevamente todo el catálogo en cada pulsación.
    for cliente in clientes:
        cliente["_busqueda"] = normalizar(
            " ".join(
                str(cliente.get(campo) or "")
                for campo in ("name", "city", "vat", "email", "phone")
            )
        )

    for producto in productos:
        codigo_normalizado = normalizar(producto.get("default_code") or "")
        nombre_normalizado = normalizar(producto.get("name") or "")
        producto["_codigo_normalizado"] = codigo_normalizado
        producto["_nombre_normalizado"] = nombre_normalizado
        producto["_busqueda"] = f"{codigo_normalizado} {nombre_normalizado}"

    try:
        impuestos = models.execute_kw(
            db,
            uid,
            password,
            "account.tax",
            "search_read",
            [[("active", "=", True)]],
            {
                "fields": [
                    "id",
                    "name",
                    "amount",
                    "amount_type",
                    "price_include",
                    "sequence",
                    "include_base_amount",
                    "is_base_affected",
                    "children_tax_ids",
                ],
                "order": "sequence asc, id asc",
            },
        )
    except Exception:
        # compute_all sigue siendo el cálculo principal. Esta lista solamente
        # se usa como respaldo cuando el usuario no puede ejecutar ese método.
        impuestos = []

    logger.info(
        "Catálogo Odoo cargado: %s clientes, %s productos, %s impuestos en %.2fs",
        len(clientes),
        len(productos),
        len(impuestos),
        time.perf_counter() - inicio,
    )
    return int(uid), clientes, productos, impuestos


def crear_pedido_odoo(
    uid: int,
    cliente_id: int,
    carrito: list[dict[str, Any]],
    nota: str,
    pedido_token: str,
) -> tuple[int, str, str, float, float, float]:
    models = crear_proxy_odoo(
        URL,
        "/xmlrpc/2/object",
        timeout=ODOO_TIMEOUT_SEGUNDOS,
    )
    token = str(pedido_token).strip()[:40]
    if not token.startswith("RV-"):
        raise ValueError("La referencia interna del pedido no es válida.")

    campos_resultado = [
        "id",
        "name",
        "state",
        "amount_untaxed",
        "amount_tax",
        "amount_total",
    ]

    # La misma referencia se conserva después de un timeout. Antes de crear se
    # busca una orden previa para que reintentar recupere el resultado en lugar
    # de duplicar el pedido.
    existentes = models.execute_kw(
        DB,
        uid,
        PASSWORD,
        "sale.order",
        "search_read",
        [[("client_order_ref", "=", token)]],
        {
            "fields": campos_resultado,
            "limit": 1,
            "order": "id desc",
        },
    )

    if existentes:
        registro_existente = existentes[0]
        sale_order_id = int(registro_existente["id"])
        logger.warning(
            "Pedido recuperado por referencia idempotente %s (Odoo id=%s)",
            token,
            sale_order_id,
        )
        return (
            sale_order_id,
            str(registro_existente.get("name") or sale_order_id),
            (
                "Pedido recuperado"
                if str(registro_existente.get("state") or "") in {"sale", "done"}
                else "Cotización recuperada"
            ),
            float(registro_existente.get("amount_untaxed") or 0.0),
            float(registro_existente.get("amount_tax") or 0.0),
            float(registro_existente.get("amount_total") or 0.0),
        )

    lineas_odoo = [
        (
            0,
            0,
            {
                "product_id": int(linea["product_id"]),
                "product_uom_qty": int(linea["cantidad"]),
                "price_unit": float(linea["precio_unitario"]),
            },
        )
        for linea in carrito
    ]

    valores: dict[str, Any] = {
        "partner_id": int(cliente_id),
        "order_line": lineas_odoo,
        "origin": f"RapyVet Pedidos | {token}",
        "client_order_ref": token,
    }

    if nota.strip():
        valores["note"] = nota.strip()

    sale_order_id = models.execute_kw(
        DB,
        uid,
        PASSWORD,
        "sale.order",
        "create",
        [valores],
    )
    logger.info("Pedido creado con referencia %s (Odoo id=%s)", token, sale_order_id)

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
            {
                "fields": [
                    *campos_resultado,
                ]
            },
        )

        if registro:
            folio = str(registro[0].get("name") or folio)
            amount_untaxed = float(registro[0].get("amount_untaxed") or 0.0)
            amount_tax = float(registro[0].get("amount_tax") or 0.0)
            amount_total = float(registro[0].get("amount_total") or 0.0)
        else:
            amount_untaxed = 0.0
            amount_tax = 0.0
            amount_total = 0.0
    except Exception:
        amount_untaxed = 0.0
        amount_tax = 0.0
        amount_total = 0.0

    return (
        int(sale_order_id),
        folio,
        estado,
        amount_untaxed,
        amount_tax,
        amount_total,
    )


# =============================================================================
# FUNCIONES GENERALES
# =============================================================================


def moneda(valor: float) -> str:
    return f"${valor:,.2f}"


def seguro(valor: Any) -> str:
    return html.escape(str(valor or ""))


def normalizar(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def categoria_producto(producto: dict[str, Any]) -> str:
    categoria = producto.get("categ_id")
    if isinstance(categoria, (list, tuple)) and len(categoria) >= 2:
        return str(categoria[1])
    return "Sin categoría"


def crear_linea(
    producto: dict[str, Any],
    cantidad: int,
    precio: float,
    *,
    tipo: str = "venta",
    grupo_promocion: str | None = None,
    parte_promocion: str | None = None,
) -> dict[str, Any]:
    precio_odoo = max(0.0, float(precio))
    detalle = detalle_precio_producto(producto, precio_odoo)
    precio_final = 0.0 if precio_odoo == 0.0 else float(detalle["precio_final"])

    return {
        "linea_id": uuid.uuid4().hex,
        "product_id": int(producto["id"]),
        "nombre_producto": str(producto.get("name") or "Producto"),
        "codigo": str(producto.get("default_code") or "S/C"),
        "cantidad": max(1, int(cantidad)),
        # price_unit real que se envía a Odoo.
        "precio_unitario": precio_odoo,
        # Precio que ve el vendedor, siempre con impuestos aplicados.
        "precio_final_unitario": precio_final,
        "impuestos_unitarios": (
            0.0 if precio_odoo == 0.0 else float(detalle["impuestos"])
        ),
        "tiene_impuestos": bool(detalle["tiene_impuestos"]),
        "texto_impuestos": str(detalle["texto_impuestos"]),
        "tipo": tipo,
        "grupo_promocion": grupo_promocion,
        "parte_promocion": parte_promocion,
    }


def registrar_reciente(producto_id: int) -> None:
    recientes = [
        int(pid)
        for pid in st.session_state.productos_recientes
        if int(pid) != int(producto_id)
    ]
    st.session_state.productos_recientes = [int(producto_id), *recientes][:12]


def limpiar_claves_edicion(linea_ids: list[str]) -> None:
    for clave in list(st.session_state.keys()):
        if any(linea_id in clave for linea_id in linea_ids) and clave.startswith(
            ("desktop_", "mobile_")
        ):
            del st.session_state[clave]


def agregar_venta_rapida(producto_id: int) -> None:
    producto = productos_por_id[int(producto_id)]
    precio_lista = float(producto.get("list_price") or 0.0)

    # Si ya existe la misma venta al precio de lista, aumenta su cantidad.
    existente = next(
        (
            linea
            for linea in st.session_state.carrito
            if int(linea["product_id"]) == int(producto_id)
            and not linea.get("grupo_promocion")
            and abs(float(linea["precio_unitario"]) - precio_lista) < 0.0001
        ),
        None,
    )

    if existente:
        existente["cantidad"] = int(existente["cantidad"]) + 1
        limpiar_claves_edicion([str(existente["linea_id"])])
    else:
        st.session_state.carrito.append(crear_linea(producto, 1, precio_lista))

    registrar_reciente(int(producto_id))
    # Conserva la búsqueda actual para poder seguir agregando productos
    # relacionados sin volver a escribir el término.
    st.session_state.notificacion_pendiente = {
        "texto": f"{producto.get('name') or 'Producto'} agregado",
        "icono": "✅",
    }


def abrir_promocion(producto_id: int) -> None:
    st.session_state.producto_promocion_id = int(producto_id)


def agregar_promocion(
    producto: dict[str, Any],
    cantidad_cobrada: int,
    cantidad_gratis: int,
    precio: float,
) -> None:
    grupo = uuid.uuid4().hex
    st.session_state.carrito.extend(
        [
            crear_linea(
                producto,
                cantidad_cobrada,
                precio,
                tipo="promocion_cobrada",
                grupo_promocion=grupo,
                parte_promocion="cobrada",
            ),
            crear_linea(
                producto,
                cantidad_gratis,
                0.0,
                tipo="promocion_gratis",
                grupo_promocion=grupo,
                parte_promocion="gratis",
            ),
        ]
    )


def cambiar_cantidad(linea_id: str, diferencia: int) -> None:
    linea = next(
        (x for x in st.session_state.carrito if str(x["linea_id"]) == str(linea_id)),
        None,
    )
    if not linea:
        return
    linea["cantidad"] = max(1, int(linea["cantidad"]) + int(diferencia))


def eliminar_linea(linea_id: str) -> None:
    st.session_state.carrito = [
        linea
        for linea in st.session_state.carrito
        if str(linea["linea_id"]) != str(linea_id)
    ]


def eliminar_promocion(grupo_id: str) -> None:
    ids = [
        str(linea["linea_id"])
        for linea in st.session_state.carrito
        if str(linea.get("grupo_promocion")) == str(grupo_id)
    ]
    st.session_state.carrito = [
        linea
        for linea in st.session_state.carrito
        if str(linea.get("grupo_promocion")) != str(grupo_id)
    ]


def vaciar_carrito() -> None:
    st.session_state.carrito = []


def reiniciar_pedido() -> None:
    st.session_state.borrador_local_eliminar = True
    vaciar_carrito()
    st.session_state.cliente_id = None
    st.session_state.resultado_pedido = None
    st.session_state.nota_pedido = ""
    st.session_state.desktop_nota_pedido = ""
    st.session_state.mobile_nota_pedido = ""
    st.session_state.confirmar_envio = False
    st.session_state.envio_en_progreso = False
    st.session_state.pedido_token = f"RV-{uuid.uuid4().hex}"
    limpiar_busqueda_catalogo()
    st.session_state.categoria_pos = "Todas"
    st.session_state.vista_pos = "Todos"


def sincronizar_nota_pedido(origen: str) -> None:
    """Mantiene la nota sincronizada entre carrito de escritorio y móvil."""
    clave_origen = f"{origen}_nota_pedido"
    nota = str(st.session_state.get(clave_origen, ""))

    st.session_state.nota_pedido = nota

    for destino in ("desktop", "mobile"):
        clave_destino = f"{destino}_nota_pedido"
        if clave_destino != clave_origen:
            st.session_state[clave_destino] = nota


def construir_mensaje_whatsapp(
    nombre_cliente: str,
    carrito: list[dict[str, Any]],
) -> str:
    lineas = [nombre_cliente.strip() or "Cliente", ""]
    for linea in carrito:
        texto = f"{int(linea['cantidad'])} x {linea['nombre_producto']}"
        if float(linea["precio_unitario"]) == 0.0:
            texto += " (GRATIS)"
        lineas.append(texto)
    return "\n".join(lineas).strip()


def crear_enlace_whatsapp(mensaje: str) -> str:
    return f"https://wa.me/?text={quote(mensaje, safe='')}"


def resetear_catalogo() -> None:
    st.session_state.pagina_catalogo = 0


def limpiar_busqueda_catalogo() -> None:
    """Limpia el buscador y fuerza un campo nuevo en el componente keyup."""
    st.session_state.busqueda_pos = ""
    st.session_state.busqueda_widget_version = (
        int(st.session_state.busqueda_widget_version) + 1
    )
    st.session_state.pagina_catalogo = 0

    # Elimina estados antiguos del componente para no acumular claves en la sesión.
    for clave in list(st.session_state.keys()):
        if str(clave).startswith("busqueda_pos_input_"):
            del st.session_state[clave]


def solicitar_envio() -> None:
    if st.session_state.get("envio_en_progreso", False):
        return
    st.session_state.confirmar_envio = True


def cambiar_tab_movil(destino: str) -> None:
    st.session_state.mobile_tab = destino


# =============================================================================
# CARGA DE DATOS
# =============================================================================

try:
    with st.spinner("Conectando con Odoo..."):
        uid, lista_clientes, lista_productos, lista_impuestos = cargar_datos_odoo(URL, DB, USER, PASSWORD)
except xmlrpc.client.Fault as error:
    st.error(f"Odoo devolvió un error: {error.faultString}")
    st.stop()
except Exception as error:
    st.error(f"No fue posible cargar los datos de Odoo: {error}")
    st.stop()

clientes_por_id = {int(c["id"]): c for c in lista_clientes}
productos_por_id = {int(p["id"]): p for p in lista_productos}
impuestos_por_id = {int(t["id"]): t for t in lista_impuestos}

if not clientes_por_id:
    st.warning("No se encontraron clientes activos en Odoo.")
    st.stop()

if not productos_por_id:
    st.warning("No se encontraron productos disponibles para venta.")
    st.stop()


def detalle_precio_producto(
    producto: dict[str, Any],
    precio_odoo: float | None = None,
) -> dict[str, Any]:
    """Devuelve precio final con impuestos sin alterar price_unit de Odoo."""

    precio = max(
        0.0,
        float(
            producto.get("list_price")
            if precio_odoo is None
            else precio_odoo
        ),
    )
    tax_ids = tuple(int(x) for x in (producto.get("taxes_id") or []))
    nombres = [
        str(impuestos_por_id[tax_id].get("name") or "Impuesto")
        for tax_id in tax_ids
        if tax_id in impuestos_por_id
    ]

    if not tax_ids:
        return {
            "precio_odoo": precio,
            "precio_sin_impuestos": precio,
            "precio_final": precio,
            "impuestos": 0.0,
            "tiene_impuestos": False,
            "texto_impuestos": "Sin impuestos",
        }

    # El catálogo usa el esquema fiscal ya descargado. Antes se hacía una
    # llamada XML-RPC por cada producto/precio visible, lo que convertía cada
    # página y cada edición en una cadena de esperas contra Odoo.
    calculo = calcular_impuestos_locales(
        precio,
        tax_ids,
        impuestos_por_id,
    )

    texto = " · ".join(nombres) if nombres else "Impuestos incluidos"
    return {
        "precio_odoo": precio,
        "precio_sin_impuestos": float(calculo["total_excluded"]),
        "precio_final": float(calculo["total_included"]),
        "impuestos": float(calculo["tax_amount"]),
        "tiene_impuestos": True,
        "texto_impuestos": f"{texto} · precio final",
    }


def actualizar_precio_linea(
    linea: dict[str, Any],
    nuevo_precio_odoo: float,
) -> None:
    """Actualiza el price_unit de Odoo y su equivalente final visible."""

    producto = productos_por_id.get(int(linea["product_id"]))
    precio = max(0.0, float(nuevo_precio_odoo))
    linea["precio_unitario"] = precio

    if precio == 0.0 or not producto:
        linea["precio_final_unitario"] = 0.0
        linea["impuestos_unitarios"] = 0.0
        return

    detalle = detalle_precio_producto(producto, precio)
    linea["precio_final_unitario"] = float(detalle["precio_final"])
    linea["impuestos_unitarios"] = float(detalle["impuestos"])
    linea["tiene_impuestos"] = bool(detalle["tiene_impuestos"])
    linea["texto_impuestos"] = str(detalle["texto_impuestos"])


def precio_final_linea(linea: dict[str, Any]) -> float:
    if float(linea.get("precio_unitario") or 0.0) == 0.0:
        return 0.0
    if "precio_final_unitario" not in linea:
        actualizar_precio_linea(linea, float(linea["precio_unitario"]))
    return float(linea.get("precio_final_unitario") or 0.0)


def restaurar_borrador_local_si_corresponde() -> None:
    """Valida el borrador contra los clientes y productos actuales de Odoo."""

    paquete = st.session_state.get("borrador_local_pendiente")
    if not isinstance(paquete, dict):
        return

    st.session_state.borrador_local_pendiente = None

    # Nunca mezcla un borrador con un carrito que ya existe en esta sesión.
    if st.session_state.carrito or st.session_state.resultado_pedido:
        return

    cliente_id = paquete.get("cliente_id")
    try:
        cliente_id = int(cliente_id) if cliente_id is not None else None
    except (TypeError, ValueError):
        cliente_id = None

    if cliente_id not in clientes_por_id:
        cliente_id = None

    lineas_restauradas: list[dict[str, Any]] = []
    for original in paquete.get("carrito", []):
        if not isinstance(original, dict):
            continue

        try:
            producto_id = int(original.get("product_id"))
            cantidad = max(1, int(original.get("cantidad") or 1))
            precio = max(0.0, float(original.get("precio_unitario") or 0.0))
        except (TypeError, ValueError):
            continue

        producto = productos_por_id.get(producto_id)
        if not producto:
            continue

        tipo = str(original.get("tipo") or "venta")
        if tipo not in {
            "venta",
            "gratis",
            "promocion_cobrada",
            "promocion_gratis",
        }:
            tipo = "venta"

        parte = original.get("parte_promocion")
        parte = str(parte) if parte in {"cobrada", "gratis"} else None
        grupo = original.get("grupo_promocion")
        grupo = str(grupo) if grupo else None

        # Una línea marcada como gratuita siempre vuelve con precio cero.
        if parte == "gratis" or tipo in {"gratis", "promocion_gratis"}:
            precio = 0.0

        linea = crear_linea(
            producto,
            cantidad,
            precio,
            tipo=tipo,
            grupo_promocion=grupo,
            parte_promocion=parte,
        )

        linea_id = str(original.get("linea_id") or "").strip()
        if linea_id:
            linea["linea_id"] = linea_id[:80]

        lineas_restauradas.append(linea)

    nota = str(paquete.get("nota_pedido") or "")[:4000]
    pedido_token = str(paquete.get("pedido_token") or "").strip()
    if not pedido_token.startswith("RV-") or len(pedido_token) > 40:
        pedido_token = f"RV-{uuid.uuid4().hex}"
    st.session_state.cliente_id = cliente_id
    st.session_state.carrito = lineas_restauradas
    st.session_state.nota_pedido = nota
    st.session_state.desktop_nota_pedido = nota
    st.session_state.mobile_nota_pedido = nota
    st.session_state.pedido_token = pedido_token
    st.session_state.borrador_local_restaurado = bool(
        cliente_id or lineas_restauradas or nota.strip()
    )

    if st.session_state.borrador_local_restaurado:
        st.toast("Pedido en curso recuperado", icon="↩️")


restaurar_borrador_local_si_corresponde()

# Migra carritos que permanecieron en session_state al actualizar la aplicación.
for _linea_existente in st.session_state.carrito:
    precio_final_linea(_linea_existente)

# Primera escritura del ciclo. Recupera cambios realizados justo antes de un
# st.rerun() explícito y evita perderlos si la ejecución anterior terminó antes.
guardar_borrador_en_navegador("rv_borrador_local_guardado_pre_v1")


# =============================================================================
# CATÁLOGO Y CARRITO
# =============================================================================


def etiqueta_cliente(cliente_id: int) -> str:
    cliente = clientes_por_id[cliente_id]
    nombre = cliente.get("name") or "Cliente sin nombre"
    ciudad = cliente.get("city") or "Sin ciudad"
    reciente = "★ " if int(cliente_id) in st.session_state.clientes_recientes else ""
    return f"{reciente}{nombre} · {ciudad}"


def opciones_clientes() -> list[int]:
    """Coloca clientes usados recientemente al inicio del selector."""

    recientes = [
        int(cliente_id)
        for cliente_id in st.session_state.clientes_recientes
        if int(cliente_id) in clientes_por_id
    ]
    return [
        *recientes,
        *(
            cliente_id
            for cliente_id in clientes_por_id
            if cliente_id not in recientes
        ),
    ]



def etiqueta_producto_desktop(producto_id: int) -> str:
    producto = productos_por_id[int(producto_id)]
    codigo = str(producto.get("default_code") or "S/C")
    nombre = str(producto.get("name") or "Producto")
    return f"{codigo} — {nombre}"


def sincronizar_producto_desktop() -> None:
    producto_id = st.session_state.get("desktop_producto_id")
    if producto_id is None:
        return

    producto = productos_por_id.get(int(producto_id))
    if not producto:
        return

    precio = float(producto.get("list_price") or 0.0)
    st.session_state.desktop_ultimo_producto_id = int(producto_id)
    st.session_state.desktop_cantidad_normal = 1
    st.session_state.desktop_precio_normal = precio
    st.session_state.desktop_preset_promocion = "1+1"
    st.session_state.desktop_cantidad_cobrada = 1
    st.session_state.desktop_cantidad_gratis = 1
    st.session_state.desktop_precio_promocion = precio


def aplicar_preset_desktop() -> None:
    valor = str(st.session_state.get("desktop_preset_promocion") or "Otra")
    if valor == "Otra" or "+" not in valor:
        return

    cobradas, gratis = valor.split("+", maxsplit=1)
    st.session_state.desktop_cantidad_cobrada = int(cobradas)
    st.session_state.desktop_cantidad_gratis = int(gratis)


def agregar_venta_desktop(
    producto_id: int,
    cantidad: int,
    precio: float,
) -> None:
    producto = productos_por_id[int(producto_id)]
    st.session_state.carrito.append(
        crear_linea(producto, int(cantidad), float(precio))
    )
    registrar_reciente(int(producto_id))
    # Conserva el producto seleccionado después de agregarlo.
    st.session_state.notificacion_pendiente = {
        "texto": f"{producto.get('name') or 'Producto'} agregado al carrito",
        "icono": "✅",
    }


def agregar_promocion_desktop(
    producto_id: int,
    cantidad_cobrada: int,
    cantidad_gratis: int,
    precio: float,
) -> None:
    producto = productos_por_id[int(producto_id)]
    agregar_promocion(
        producto,
        int(cantidad_cobrada),
        int(cantidad_gratis),
        float(precio),
    )
    registrar_reciente(int(producto_id))
    # Conserva el producto seleccionado después de agregarlo.
    st.session_state.notificacion_pendiente = {
        "texto": (
            f"Promoción {int(cantidad_cobrada)}+{int(cantidad_gratis)} de "
            f"{producto.get('name') or 'producto'} agregada"
        ),
        "icono": "🎁",
    }


def filtrar_productos() -> list[int]:
    consulta = normalizar(st.session_state.busqueda_pos)
    categoria = st.session_state.categoria_pos
    vista = st.session_state.vista_pos

    if vista == "Recientes":
        candidatos = [
            int(pid)
            for pid in st.session_state.productos_recientes
            if int(pid) in productos_por_id
        ]
    else:
        candidatos = list(productos_por_id.keys())

    terminos = consulta.split()
    resultados: list[tuple[int, str, int]] = []

    for producto_id in candidatos:
        producto = productos_por_id[producto_id]
        if categoria != "Todas" and categoria_producto(producto) != categoria:
            continue

        codigo = str(producto.get("_codigo_normalizado") or "")
        nombre = str(producto.get("_nombre_normalizado") or "")
        combinado = str(producto.get("_busqueda") or f"{codigo} {nombre}")

        if terminos and not all(termino in combinado for termino in terminos):
            continue

        if consulta and consulta == codigo:
            prioridad = 0
        elif consulta and codigo.startswith(consulta):
            prioridad = 1
        elif consulta and nombre.startswith(consulta):
            prioridad = 2
        else:
            prioridad = 3

        resultados.append((prioridad, nombre, int(producto_id)))

    resultados.sort(key=lambda item: (item[0], item[1]))
    return [producto_id for _, _, producto_id in resultados]


def elementos_carrito() -> list[tuple[str, list[dict[str, Any]]]]:
    salida: list[tuple[str, list[dict[str, Any]]]] = []
    grupos_vistos: set[str] = set()

    for linea in st.session_state.carrito:
        grupo = linea.get("grupo_promocion")
        if not grupo:
            salida.append(("linea", [linea]))
            continue
        if str(grupo) in grupos_vistos:
            continue
        grupos_vistos.add(str(grupo))
        lineas = [
            item
            for item in st.session_state.carrito
            if str(item.get("grupo_promocion")) == str(grupo)
        ]
        salida.append(("promocion", lineas))

    return salida


def totales_carrito() -> tuple[int, int, int, float]:
    lineas = len(st.session_state.carrito)
    unidades = sum(int(x["cantidad"]) for x in st.session_state.carrito)
    gratis = sum(
        int(x["cantidad"])
        for x in st.session_state.carrito
        if float(x["precio_unitario"]) == 0.0
    )
    total = sum(
        int(x["cantidad"]) * precio_final_linea(x)
        for x in st.session_state.carrito
    )
    return lineas, unidades, gratis, total


def render_carrito(
    prefijo: str,
    *,
    mostrar_vaciar: bool = True,
    mostrar_envio: bool = True,
) -> None:
    elementos = elementos_carrito()

    if not elementos:
        st.markdown(
            """
            <div class="rv-empty">
                <div class="rv-empty-icon">🛒</div>
                <div class="rv-empty-title">Tu carrito está vacío</div>
                <div class="rv-empty-copy">Abre Productos y toca “Agregar”. El carrito se actualizará al instante.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if prefijo == "mobile":
            return
    else:
        if mostrar_vaciar:
            if st.button(
                "Vaciar carrito",
                key=f"{prefijo}_vaciar",
                use_container_width=True,
            ):
                vaciar_carrito()
                st.rerun()

        for tipo_elemento, lineas in elementos:
            if tipo_elemento == "linea":
                linea = lineas[0]
                linea_id = str(linea["linea_id"])
                cantidad = int(linea["cantidad"])
                precio_odoo = float(linea["precio_unitario"])
                precio = precio_final_linea(linea)
                subtotal = cantidad * precio
                chip = (
                    '<span class="rv-free-chip">GRATIS</span>'
                    if precio == 0.0
                    else ""
                )

                with st.container(border=True):
                    st.markdown(
                        f"""
                        <div class="rv-cart-line">
                            <div>
                                <p class="rv-cart-name">{seguro(linea['nombre_producto'])}{chip}</p>
                                <p class="rv-cart-detail">{cantidad} × {moneda(precio)} · {seguro(linea['codigo'])}</p>
                                <p class="rv-tax-note {'rv-tax-note-none' if not linea.get('tiene_impuestos') else ''}">{seguro(linea.get('texto_impuestos') or 'Sin impuestos')}</p>
                            </div>
                            <p class="rv-cart-subtotal">{moneda(subtotal)}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    if prefijo == "mobile":
                        menos, numero, mas = st.columns([1, 1.4, 1])
                    else:
                        menos, numero, mas = st.columns([1, 1.15, 1])

                    with menos:
                        st.button(
                            "−",
                            key=f"{prefijo}_minus_{linea_id}",
                            use_container_width=True,
                            on_click=cambiar_cantidad,
                            args=(linea_id, -1),
                        )
                    with numero:
                        st.markdown(
                            f'<div class="rv-qty-display">{cantidad}</div>',
                            unsafe_allow_html=True,
                        )
                    with mas:
                        st.button(
                            "+",
                            key=f"{prefijo}_plus_{linea_id}",
                            use_container_width=True,
                            on_click=cambiar_cantidad,
                            args=(linea_id, 1),
                        )

                    with st.popover("Editar precio o eliminar", use_container_width=True):
                        with st.form(f"{prefijo}_form_{linea_id}"):
                            nueva_cantidad = st.number_input(
                                "Cantidad",
                                min_value=1,
                                value=cantidad,
                                step=1,
                                key=f"{prefijo}_qty_{linea_id}_{cantidad}_{precio_odoo:.2f}",
                            )
                            nuevo_precio = st.number_input(
                                "Precio configurado en Odoo",
                                min_value=0.0,
                                value=precio_odoo,
                                step=0.01,
                                format="%.2f",
                                key=f"{prefijo}_price_{linea_id}_{cantidad}_{precio_odoo:.2f}",
                            )
                            guardar = st.form_submit_button(
                                "Guardar cambios",
                                type="primary",
                                use_container_width=True,
                            )
                            if guardar:
                                linea["cantidad"] = int(nueva_cantidad)
                                actualizar_precio_linea(linea, float(nuevo_precio))
                                st.rerun()

                        if st.button(
                            "Eliminar producto",
                            key=f"{prefijo}_delete_{linea_id}",
                            use_container_width=True,
                        ):
                            eliminar_linea(linea_id)
                            st.rerun()

            else:
                if len(lineas) != 2:
                    st.error("Promoción incompleta")
                    continue

                cobrada = next(
                    (x for x in lineas if x.get("parte_promocion") == "cobrada"),
                    lineas[0],
                )
                gratis = next(
                    (x for x in lineas if x.get("parte_promocion") == "gratis"),
                    lineas[1],
                )
                grupo_id = str(cobrada["grupo_promocion"])
                paid_id = str(cobrada["linea_id"])
                free_id = str(gratis["linea_id"])
                combinacion = f"{int(cobrada['cantidad'])}+{int(gratis['cantidad'])}"
                precio_cobrado_final = precio_final_linea(cobrada)
                subtotal = int(cobrada["cantidad"]) * precio_cobrado_final

                with st.container(border=True):
                    st.markdown(
                        f"""
                        <div class="rv-cart-line">
                            <div>
                                <p class="rv-cart-name">{seguro(cobrada['nombre_producto'])}<span class="rv-promo-chip">{combinacion}</span></p>
                                <p class="rv-cart-detail">{cobrada['cantidad']} cobradas · {gratis['cantidad']} gratis · {moneda(precio_cobrado_final)} final c/u</p>
                                <p class="rv-tax-note {'rv-tax-note-none' if not cobrada.get('tiene_impuestos') else ''}">{seguro(cobrada.get('texto_impuestos') or 'Sin impuestos')}</p>
                            </div>
                            <p class="rv-cart-subtotal">{moneda(subtotal)}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    with st.popover("Editar promoción", use_container_width=True):
                        with st.form(f"{prefijo}_promo_form_{grupo_id}"):
                            c1, c2 = st.columns(2)
                            with c1:
                                cobradas = st.number_input(
                                    "Cobradas",
                                    min_value=1,
                                    value=int(cobrada["cantidad"]),
                                    step=1,
                                    key=f"{prefijo}_paid_{grupo_id}_{int(cobrada['cantidad'])}_{int(gratis['cantidad'])}_{float(cobrada['precio_unitario']):.2f}",
                                )
                            with c2:
                                gratuitas = st.number_input(
                                    "Gratis",
                                    min_value=1,
                                    value=int(gratis["cantidad"]),
                                    step=1,
                                    key=f"{prefijo}_free_{grupo_id}_{int(cobrada['cantidad'])}_{int(gratis['cantidad'])}_{float(cobrada['precio_unitario']):.2f}",
                                )
                            precio = st.number_input(
                                "Precio configurado en Odoo",
                                min_value=0.0,
                                value=float(cobrada["precio_unitario"]),
                                step=0.01,
                                format="%.2f",
                                key=f"{prefijo}_promo_price_{grupo_id}_{int(cobrada['cantidad'])}_{int(gratis['cantidad'])}_{float(cobrada['precio_unitario']):.2f}",
                            )
                            guardar = st.form_submit_button(
                                "Guardar promoción",
                                type="primary",
                                use_container_width=True,
                            )
                            if guardar:
                                cobrada["cantidad"] = int(cobradas)
                                actualizar_precio_linea(cobrada, float(precio))
                                gratis["cantidad"] = int(gratuitas)
                                actualizar_precio_linea(gratis, 0.0)
                                st.rerun()

                        if st.button(
                            "Eliminar promoción",
                            key=f"{prefijo}_delete_group_{grupo_id}",
                            use_container_width=True,
                        ):
                            eliminar_promocion(grupo_id)
                            st.rerun()

    lineas, unidades, gratis, total = totales_carrito()
    st.markdown(
        f"""
        <div class="rv-total-box">
            <p class="rv-total-label">Total estimado</p>
            <p class="rv-total-value">{moneda(total)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(f"{lineas} líneas · {unidades} unidades · {gratis} gratis")

    clave_nota = f"{prefijo}_nota_pedido"
    if clave_nota not in st.session_state:
        st.session_state[clave_nota] = str(
            st.session_state.get("nota_pedido", "")
        )

    with st.expander("Notas del pedido"):
        st.text_area(
            "Notas generales",
            placeholder="Instrucciones de entrega...",
            max_chars=700,
            key=clave_nota,
            on_change=sincronizar_nota_pedido,
            args=(prefijo,),
        )

    if mostrar_envio:
        listo = bool(st.session_state.cliente_id and st.session_state.carrito)
        if not st.session_state.cliente_id:
            st.info("Selecciona el cliente para crear el pedido.")

        st.button(
            "Crear pedido en Odoo",
            type="primary",
            use_container_width=True,
            disabled=not listo or st.session_state.get("envio_en_progreso", False),
            key=f"{prefijo}_enviar",
            on_click=solicitar_envio,
        )


# =============================================================================
# DIÁLOGOS
# =============================================================================


@st.dialog("Agregar promoción", on_dismiss="rerun")
def dialogo_promocion(producto_id: int) -> None:
    producto = productos_por_id[int(producto_id)]
    nombre = str(producto.get("name") or "Producto")
    codigo = str(producto.get("default_code") or "S/C")
    precio_lista = float(producto.get("list_price") or 0.0)
    detalle_lista = detalle_precio_producto(producto, precio_lista)

    st.markdown(f"### {seguro(nombre)}")
    st.caption(
        f"{codigo} · Precio final {moneda(float(detalle_lista['precio_final']))} · "
        f"{detalle_lista['texto_impuestos']}"
    )

    preset = st.radio(
        "Promoción",
        PROMOCIONES_RAPIDAS,
        horizontal=True,
        key=f"promo_preset_{producto_id}",
    )

    if preset == "Otra":
        valor_cobradas, valor_gratis = 1, 1
    else:
        parte_1, parte_2 = preset.split("+")
        valor_cobradas, valor_gratis = int(parte_1), int(parte_2)

    c1, c2 = st.columns(2)
    with c1:
        cobradas = st.number_input(
            "Cobradas",
            min_value=1,
            value=valor_cobradas,
            step=1,
            key=f"promo_paid_{producto_id}_{preset}",
        )
    with c2:
        gratis = st.number_input(
            "Gratis",
            min_value=1,
            value=valor_gratis,
            step=1,
            key=f"promo_free_{producto_id}_{preset}",
        )

    precio = st.number_input(
        "Precio configurado en Odoo",
        min_value=0.0,
        value=precio_lista,
        step=0.01,
        format="%.2f",
        key=f"promo_price_{producto_id}",
    )

    combinacion = f"{int(cobradas)}+{int(gratis)}"
    detalle_promocion = detalle_precio_producto(producto, float(precio))
    st.info(
        f"Se crearán 2 líneas: {int(cobradas)} con precio final "
        f"{moneda(float(detalle_promocion['precio_final']))} y "
        f"{int(gratis)} a $0.00."
    )

    if st.button(
        f"Agregar promoción {combinacion}",
        type="primary",
        use_container_width=True,
        key=f"promo_add_{producto_id}_{combinacion}",
    ):
        agregar_promocion(producto, int(cobradas), int(gratis), float(precio))
        registrar_reciente(int(producto_id))
        st.session_state.producto_promocion_id = None
        # El diálogo se cierra, pero el buscador conserva el término actual.
        st.session_state.notificacion_pendiente = {
            "texto": f"Promoción {combinacion} de {nombre} agregada",
            "icono": "🎁",
        }
        st.rerun()


@st.dialog("Carrito", width="large")
def dialogo_carrito_movil() -> None:
    render_carrito("mobile", mostrar_vaciar=True, mostrar_envio=False)


@st.dialog("Revisar y confirmar", width="large", on_dismiss="rerun")
def dialogo_confirmar_pedido() -> None:
    """Última revisión legible antes de realizar una escritura en Odoo."""

    cliente_id = st.session_state.get("cliente_id")
    if not cliente_id or not st.session_state.carrito:
        st.error("Selecciona un cliente y agrega al menos un producto.")
        return

    cliente = clientes_por_id[int(cliente_id)]
    elementos = elementos_carrito()
    lineas, unidades, gratis, total = totales_carrito()

    st.markdown(f"### {seguro(cliente.get('name') or 'Cliente')}")
    detalles_cliente = [
        str(cliente.get(campo) or "").strip()
        for campo in ("city", "phone", "email")
        if str(cliente.get(campo) or "").strip()
    ]
    if detalles_cliente:
        st.caption(" · ".join(detalles_cliente))

    c1, c2, c3 = st.columns(3)
    c1.metric("Productos", len(elementos))
    c2.metric("Unidades", unidades)
    c3.metric("Total estimado", moneda(total))

    lineas_cero_no_promocion = [
        linea
        for linea in st.session_state.carrito
        if float(linea.get("precio_unitario") or 0.0) == 0.0
        and linea.get("parte_promocion") != "gratis"
    ]
    if lineas_cero_no_promocion:
        st.warning(
            "Hay productos normales con precio $0.00. Confirma que realmente "
            "deban enviarse gratis."
        )

    with st.expander("Productos del pedido", expanded=True):
        for tipo_elemento, grupo in elementos:
            if tipo_elemento == "promocion":
                cobrada = next(
                    (x for x in grupo if x.get("parte_promocion") == "cobrada"),
                    grupo[0],
                )
                gratuita = next(
                    (x for x in grupo if x.get("parte_promocion") == "gratis"),
                    grupo[-1],
                )
                subtotal_texto = moneda(
                    int(cobrada["cantidad"]) * precio_final_linea(cobrada)
                ).replace("$", r"\$")
                st.markdown(
                    f"**{seguro(cobrada['nombre_producto'])}** · "
                    f"{int(cobrada['cantidad'])}+{int(gratuita['cantidad'])} · "
                    f"{subtotal_texto}"
                )
            else:
                linea = grupo[0]
                precio_texto = moneda(precio_final_linea(linea)).replace("$", r"\$")
                subtotal_texto = moneda(
                    int(linea["cantidad"]) * precio_final_linea(linea)
                ).replace("$", r"\$")
                st.markdown(
                    f"**{seguro(linea['nombre_producto'])}** · "
                    f"{int(linea['cantidad'])} × {precio_texto} · {subtotal_texto}"
                )

    nota = str(st.session_state.get("nota_pedido") or "").strip()
    if nota:
        st.info(f"Nota: {nota}")

    st.caption(
        f"{lineas} líneas · {gratis} unidades gratis · "
        "Odoo confirmará impuestos y total definitivo."
    )

    volver_col, confirmar_col = st.columns([1, 1.5])
    with volver_col:
        if st.button("Seguir editando", use_container_width=True):
            st.session_state.confirmar_envio = False
            st.rerun()
    with confirmar_col:
        if st.button(
            "Confirmar y crear en Odoo",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.confirmar_envio = False
            st.session_state.enviar_pedido = True
            st.rerun()


# =============================================================================
# PANTALLA DE RESULTADO
# =============================================================================

if st.session_state.mostrar_balloons:
    st.balloons()
    st.session_state.mostrar_balloons = False

resultado = st.session_state.resultado_pedido
if resultado:
    with st.container(border=True):
        st.success(f"✅ {resultado['estado']} correctamente en Odoo")
        st.markdown(f"## {seguro(resultado['folio'])}")
        st.markdown(f"**Cliente:** {seguro(resultado['cliente'])}")
        if resultado.get("referencia"):
            st.caption(f"Referencia de seguridad: {resultado['referencia']}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Líneas", resultado["lineas"])
        c2.metric("Unidades", resultado["unidades"])
        c3.metric("Impuestos", moneda(resultado.get("impuestos", 0.0)))
        c4.metric("Total final", moneda(resultado["total"]))

        st.markdown("### Compartir pedido")
        st.link_button(
            "🟢 Abrir WhatsApp",
            resultado["enlace_whatsapp"],
            type="primary",
            use_container_width=True,
        )

        with st.expander("Ver o copiar mensaje"):
            st.text_area(
                "Mensaje",
                value=resultado["texto_whatsapp"],
                height=240,
                key=f"resultado_texto_{resultado['folio']}",
            )

        if st.button(
            "➕ Capturar otro pedido",
            type="primary",
            use_container_width=True,
        ):
            reiniciar_pedido()
            st.rerun()

    st.stop()


# =============================================================================
# ENCABEZADO, CLIENTE Y VISTAS ADAPTATIVAS
# =============================================================================



def render_desktop_clasico() -> None:
    """Renderiza la interfaz de escritorio basada en el diseño clásico.

    Comparte carrito, cliente, conexión y envío con la interfaz móvil. Solo
    cambia la presentación y el flujo de captura.
    """

    lineas, unidades, gratis, total = totales_carrito()
    cliente_id_actual = st.session_state.get("cliente_id")
    cliente_nombre = "Sin seleccionar"
    if cliente_id_actual:
        cliente_nombre = str(
            clientes_por_id[int(cliente_id_actual)].get("name") or "Cliente"
        )

    st.markdown(
        """
        <div class="rv-classic-hero">
            <div class="rv-classic-hero-grid">
                <div>
                    <p class="rv-classic-kicker">Captura de pedidos</p>
                    <h1 class="rv-classic-title">🐾 RapyVet Pedidos</h1>
                    <p class="rv-classic-subtitle">
                        Interfaz de escritorio: selecciona el cliente, agrega
                        ventas o promociones y revisa el pedido antes de enviarlo.
                    </p>
                </div>
            </div>
            <div class="rv-classic-pills">
                <span class="rv-classic-pill">Precios editables</span>
                <span class="rv-classic-pill">Promociones en dos líneas</span>
                <span class="rv-classic-pill">Productos repetidos</span>
                <span class="rv-classic-pill">WhatsApp al finalizar</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="rv-classic-status-grid">
            <div class="rv-classic-status-card">
                <p class="rv-classic-status-label">Conexión</p>
                <p class="rv-classic-status-value">● Odoo conectado</p>
            </div>
            <div class="rv-classic-status-card">
                <p class="rv-classic-status-label">Cliente</p>
                <p class="rv-classic-status-value">{seguro(cliente_nombre)}</p>
            </div>
            <div class="rv-classic-status-card">
                <p class="rv-classic-status-label">Carrito</p>
                <p class="rv-classic-status-value">
                    {lineas} líneas · {unidades} unidades · {moneda(total)}
                </p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    clase_1 = "done" if cliente_id_actual else "active"
    clase_2 = (
        "done"
        if st.session_state.carrito
        else ("active" if cliente_id_actual else "")
    )
    clase_3 = "active" if cliente_id_actual and st.session_state.carrito else ""

    st.markdown(
        f"""
        <div class="rv-classic-steps">
            <div class="rv-classic-step {clase_1}">
                <span class="rv-classic-step-number">1</span>
                Seleccionar cliente
            </div>
            <div class="rv-classic-step {clase_2}">
                <span class="rv-classic-step-number">2</span>
                Agregar productos
            </div>
            <div class="rv-classic-step {clase_3}">
                <span class="rv-classic-step-number">3</span>
                Revisar y enviar
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cliente_col, producto_col = st.columns([.82, 1.18], gap="large")

    with cliente_col:
        with st.container(border=True):
            st.markdown(
                '<p class="rv-classic-section-title">👤 Cliente</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p class="rv-classic-section-copy">Busca por nombre o ciudad.</p>',
                unsafe_allow_html=True,
            )

            cliente_id = st.selectbox(
                "Selecciona el cliente",
                options=opciones_clientes(),
                index=None,
                placeholder="Escribe para buscar…",
                format_func=etiqueta_cliente,
                key="cliente_id",
            )

            if cliente_id:
                cliente = clientes_por_id[int(cliente_id)]
                detalles: list[str] = []
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
                key="desktop_classic_actualizar",
            ):
                cargar_datos_odoo.clear()
                st.rerun()

    with producto_col:
        with st.container(border=True):
            st.markdown(
                '<p class="rv-classic-section-title">➕ Agregar producto</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<p class="rv-classic-section-copy">Busca un producto y elige venta normal o promoción.</p>',
                unsafe_allow_html=True,
            )

            producto_id = st.selectbox(
                "Buscar producto",
                options=list(productos_por_id.keys()),
                index=None,
                placeholder="Código o nombre del producto…",
                format_func=etiqueta_producto_desktop,
                key="desktop_producto_id",
                on_change=sincronizar_producto_desktop,
            )

            producto: dict[str, Any] | None = None
            if producto_id is not None:
                producto = productos_por_id[int(producto_id)]
                if st.session_state.desktop_ultimo_producto_id != int(producto_id):
                    sincronizar_producto_desktop()

                precio_lista = float(producto.get("list_price") or 0.0)
                detalle_lista = detalle_precio_producto(producto, precio_lista)
                st.markdown(
                    f"""
                    <div class="rv-classic-product-preview">
                        <p class="rv-classic-product-name">
                            {seguro(producto.get('name') or 'Producto')}
                        </p>
                        <p class="rv-classic-product-meta">
                            Código {seguro(producto.get('default_code') or 'S/C')}
                            · Precio final {moneda(float(detalle_lista['precio_final']))}
                            · {seguro(detalle_lista['texto_impuestos'])}
                        </p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            producto_valido = producto is not None
            tab_venta, tab_promocion = st.tabs(
                ["🧾 Venta normal", "🎁 Promoción"]
            )

            with tab_venta:
                cantidad_col, precio_col = st.columns(2)
                with cantidad_col:
                    cantidad_normal = st.number_input(
                        "Cantidad",
                        min_value=1,
                        step=1,
                        key="desktop_cantidad_normal",
                    )
                with precio_col:
                    precio_normal = st.number_input(
                        "Precio configurado en Odoo",
                        min_value=0.0,
                        step=0.01,
                        format="%.2f",
                        key="desktop_precio_normal",
                    )

                detalle_normal = (
                    detalle_precio_producto(producto, float(precio_normal))
                    if producto
                    else {"precio_final": float(precio_normal), "texto_impuestos": ""}
                )
                subtotal = int(cantidad_normal) * float(detalle_normal["precio_final"])
                st.caption(
                    f"Precio final unitario: {moneda(float(detalle_normal['precio_final']))} · "
                    f"Subtotal final: {moneda(subtotal)}"
                )

                if st.button(
                    "Agregar venta al carrito",
                    type="primary",
                    use_container_width=True,
                    disabled=not producto_valido,
                    key="desktop_classic_agregar_venta",
                ):
                    agregar_venta_desktop(
                        int(producto_id),
                        int(cantidad_normal),
                        float(precio_normal),
                    )
                    st.rerun()

            with tab_promocion:
                st.selectbox(
                    "Promoción rápida",
                    options=PROMOCIONES_RAPIDAS,
                    key="desktop_preset_promocion",
                    on_change=aplicar_preset_desktop,
                )

                cobradas_col, gratis_col = st.columns(2)
                with cobradas_col:
                    cantidad_cobrada = st.number_input(
                        "Unidades cobradas",
                        min_value=1,
                        step=1,
                        key="desktop_cantidad_cobrada",
                    )
                with gratis_col:
                    cantidad_gratis = st.number_input(
                        "Unidades gratis",
                        min_value=1,
                        step=1,
                        key="desktop_cantidad_gratis",
                    )

                precio_promocion = st.number_input(
                    "Precio configurado en Odoo",
                    min_value=0.0,
                    step=0.01,
                    format="%.2f",
                    key="desktop_precio_promocion",
                )

                combinacion = f"{int(cantidad_cobrada)}+{int(cantidad_gratis)}"
                detalle_promocion_desktop = (
                    detalle_precio_producto(producto, float(precio_promocion))
                    if producto
                    else {"precio_final": float(precio_promocion)}
                )
                precio_final_promocion = float(
                    detalle_promocion_desktop["precio_final"]
                )
                subtotal_promocion = int(cantidad_cobrada) * precio_final_promocion
                st.markdown(
                    f"""
                    <div class="rv-classic-promo-preview">
                        <strong>Promoción {combinacion}</strong><br>
                        {int(cantidad_cobrada)} cobradas × {moneda(precio_final_promocion)} final<br>
                        {int(cantidad_gratis)} gratis × $0.00<br>
                        Total de la promoción: <strong>{moneda(subtotal_promocion)}</strong>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                if st.button(
                    f"Agregar promoción {combinacion}",
                    type="primary",
                    use_container_width=True,
                    disabled=not producto_valido,
                    key="desktop_classic_agregar_promocion",
                ):
                    agregar_promocion_desktop(
                        int(producto_id),
                        int(cantidad_cobrada),
                        int(cantidad_gratis),
                        float(precio_promocion),
                    )
                    st.rerun()

    elementos = elementos_carrito()
    st.markdown(
        f"""
        <div class="rv-classic-cart-head">
            <h2 class="rv-classic-cart-title">🛒 Productos agregados</h2>
            <span class="rv-classic-cart-chip">
                {len(elementos)} productos · {lineas} líneas · {moneda(total)}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_carrito(
        "desktop_classic",
        mostrar_vaciar=True,
        mostrar_envio=True,
    )


def render_encabezado() -> None:
    _, unidades, _, total_actual = totales_carrito()

    if ES_MOVIL:
        st.markdown(
            f"""
            <div class="rv-mobile-appbar">
                <div class="rv-brand">
                    <div class="rv-brand-icon">🐾</div>
                    <div>
                        <p class="rv-brand-title">RapyVet Pedidos</p>
                        <p class="rv-brand-copy">Pedidos rápidos</p>
                    </div>
                </div>
                <div class="rv-mobile-status">
                    <span class="rv-pill"><span class="rv-online-dot"></span>Odoo</span>
                    <span class="rv-pill">{unidades} uds.</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div class="rv-topbar">
            <div class="rv-brand">
                <div class="rv-brand-icon">🐾</div>
                <div>
                    <p class="rv-brand-title">RapyVet Pedidos</p>
                    <p class="rv-brand-copy">Captura rápida conectada con Odoo</p>
                </div>
            </div>
            <div class="rv-top-stats">
                <span class="rv-pill">● Odoo</span>
                <span class="rv-pill">🛒 {len(elementos_carrito())}</span>
                <span class="rv-pill">{moneda(total_actual)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_cliente() -> None:
    if ES_MOVIL:
        with st.container(border=True, key="rv_mobile_client_card"):
            st.markdown(
                '<p class="rv-mobile-client-label">Cliente del pedido</p>',
                unsafe_allow_html=True,
            )
            selector_col, acciones_col = st.columns([6, 1], gap="small")
            with selector_col:
                st.selectbox(
                    "Cliente del pedido",
                    options=opciones_clientes(),
                    index=None,
                    placeholder="Buscar cliente por nombre o ciudad…",
                    format_func=etiqueta_cliente,
                    key="cliente_id",
                    label_visibility="collapsed",
                )
            with acciones_col:
                if st.button(
                    "↻",
                    help="Actualizar clientes y productos",
                    use_container_width=True,
                    key="actualizar_odoo_mobile",
                ):
                    cargar_datos_odoo.clear()
                    st.rerun()
            cliente_actual = st.session_state.get("cliente_id")
            if cliente_actual:
                cliente = clientes_por_id[int(cliente_actual)]
                datos = [
                    str(cliente.get(campo) or "").strip()
                    for campo in ("city", "phone")
                    if str(cliente.get(campo) or "").strip()
                ]
                if datos:
                    st.caption("Cliente seleccionado · " + " · ".join(datos))
        return

    with st.container(border=True):
        cliente_col, actualizar_col = st.columns([5, 1])
        with cliente_col:
            st.selectbox(
                "Cliente del pedido",
                options=opciones_clientes(),
                index=None,
                placeholder="Buscar cliente por nombre o ciudad…",
                format_func=etiqueta_cliente,
                key="cliente_id",
            )
        with actualizar_col:
            st.markdown("<div style='height:.08rem'></div>", unsafe_allow_html=True)
            if st.button(
                "↻",
                help="Actualizar datos de Odoo",
                use_container_width=True,
                key="actualizar_odoo_desktop",
            ):
                cargar_datos_odoo.clear()
                st.rerun()


def render_catalogo(*, movil: bool) -> None:
    if movil:
        st.markdown('<p class="rv-mobile-page-title">Productos</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="rv-mobile-page-copy">Busca y toca <b>Agregar</b>. Usa 🎁 solo cuando el producto lleve promoción.</p>',
            unsafe_allow_html=True,
        )
        catalog_context = st.container()
    else:
        catalog_context = st.container(border=True)

    with catalog_context:
        if not movil:
            st.markdown('<p class="rv-section-title">Productos</p>', unsafe_allow_html=True)
            st.markdown(
                '<p class="rv-section-copy">“+ Agregar” suma una unidad. Usa 🎁 para promociones.</p>',
                unsafe_allow_html=True,
            )

        search_context = (
            st.container(key="rv_mobile_search_area")
            if movil
            else st.container()
        )
        with search_context:
            busqueda_actual = st_keyup(
                "Buscar producto",
                value=str(st.session_state.busqueda_pos or ""),
                placeholder="Buscar por nombre o código…",
                key=(
                    "busqueda_pos_input_"
                    f"{st.session_state.busqueda_widget_version}"
                ),
                debounce=320,
            )

            busqueda_actual = str(busqueda_actual or "")
            if busqueda_actual != str(st.session_state.busqueda_pos or ""):
                st.session_state.busqueda_pos = busqueda_actual
                resetear_catalogo()

            categorias = sorted(
                {categoria_producto(p) for p in productos_por_id.values()}
            )

            if movil:
                st.segmented_control(
                    "Vista",
                    options=["Todos", "Recientes"],
                    key="vista_pos",
                    on_change=resetear_catalogo,
                    label_visibility="collapsed",
                    width="stretch",
                    required=True,
                )
                st.selectbox(
                    "Categoría",
                    options=["Todas", *categorias],
                    key="categoria_pos",
                    on_change=resetear_catalogo,
                    label_visibility="collapsed",
                )
            else:
                filtro_col, vista_col = st.columns([1.2, 1])
                with filtro_col:
                    st.selectbox(
                        "Categoría",
                        options=["Todas", *categorias],
                        key="categoria_pos",
                        on_change=resetear_catalogo,
                    )
                with vista_col:
                    st.radio(
                        "Vista",
                        options=["Todos", "Recientes"],
                        horizontal=True,
                        key="vista_pos",
                        on_change=resetear_catalogo,
                    )

        ids_filtrados = filtrar_productos()
        productos_por_pagina = 6 if movil else PRODUCTOS_POR_PAGINA
        columnas_catalogo = 1 if movil else COLUMNAS_CATALOGO
        total_productos = len(ids_filtrados)
        total_paginas = max(
            1,
            (total_productos + productos_por_pagina - 1) // productos_por_pagina,
        )
        pagina_actual = min(
            max(0, int(st.session_state.pagina_catalogo)),
            total_paginas - 1,
        )
        st.session_state.pagina_catalogo = pagina_actual

        inicio = pagina_actual * productos_por_pagina
        fin = min(inicio + productos_por_pagina, total_productos)
        ids_visibles = ids_filtrados[inicio:fin]
        texto_resultados = (
            f"{inicio + 1}–{fin} de {total_productos}"
            if total_productos
            else "0 productos"
        )
        st.markdown(
            f'<p class="rv-results">{texto_resultados}</p>',
            unsafe_allow_html=True,
        )

        if st.session_state.vista_pos == "Recientes" and not ids_visibles:
            st.markdown(
                '<div class="rv-empty"><div class="rv-empty-icon">🕘</div><div class="rv-empty-title">Aún no hay productos recientes</div><div class="rv-empty-copy">Los productos que agregues aparecerán aquí.</div></div>',
                unsafe_allow_html=True,
            )
        elif not ids_visibles:
            st.markdown(
                '<div class="rv-empty"><div class="rv-empty-icon">🔎</div><div class="rv-empty-title">Sin coincidencias</div><div class="rv-empty-copy">Prueba con otra palabra, código o categoría.</div></div>',
                unsafe_allow_html=True,
            )
        elif movil:
            for producto_id in ids_visibles:
                producto = productos_por_id[producto_id]
                codigo = str(producto.get("default_code") or "S/C")
                nombre = str(producto.get("name") or "Producto")
                precio_base = float(producto.get("list_price") or 0.0)
                detalle_precio = detalle_precio_producto(producto, precio_base)
                precio = float(detalle_precio["precio_final"])
                clase_impuesto = "" if detalle_precio["tiene_impuestos"] else "rv-tax-note-none"

                with st.container(
                    border=True,
                    key=f"rv_mobile_product_card_{producto_id}",
                ):
                    st.markdown(
                        f"""
                        <div class="rv-mobile-product-row">
                            <p class="rv-product-code">{seguro(codigo)}</p>
                            <p class="rv-product-name">{seguro(nombre)}</p>
                            <p class="rv-product-price">{moneda(precio)}</p>
                            <p class="rv-tax-note {clase_impuesto}">{seguro(detalle_precio['texto_impuestos'])}</p>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    agregar_col, promo_col = st.columns([4, 1], gap="small")
                    with agregar_col:
                        st.button(
                            "＋ Agregar",
                            key=f"mobile_quick_add_{producto_id}",
                            type="primary",
                            use_container_width=True,
                            on_click=agregar_venta_rapida,
                            args=(producto_id,),
                        )
                    with promo_col:
                        st.button(
                            "🎁",
                            key=f"mobile_promo_{producto_id}",
                            help="Agregar promoción",
                            use_container_width=True,
                            on_click=abrir_promocion,
                            args=(producto_id,),
                        )
        else:
            for indice in range(0, len(ids_visibles), columnas_catalogo):
                columnas = st.columns(columnas_catalogo, gap="small")
                for desplazamiento, columna in enumerate(columnas):
                    posicion = indice + desplazamiento
                    if posicion >= len(ids_visibles):
                        continue

                    producto_id = ids_visibles[posicion]
                    producto = productos_por_id[producto_id]
                    codigo = str(producto.get("default_code") or "S/C")
                    nombre = str(producto.get("name") or "Producto")
                    precio_base = float(producto.get("list_price") or 0.0)
                    detalle_precio = detalle_precio_producto(producto, precio_base)
                    precio = float(detalle_precio["precio_final"])
                    clase_impuesto = "" if detalle_precio["tiene_impuestos"] else "rv-tax-note-none"

                    with columna:
                        with st.container(border=True):
                            st.markdown(
                                f"""
                                <div class="rv-product-card">
                                    <p class="rv-product-code">{seguro(codigo)}</p>
                                    <p class="rv-product-name">{seguro(nombre)}</p>
                                    <p class="rv-product-price">{moneda(precio)}</p>
                                    <p class="rv-tax-note {clase_impuesto}">{seguro(detalle_precio['texto_impuestos'])}</p>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                            agregar_col, promo_col = st.columns([3, 1])
                            with agregar_col:
                                st.button(
                                    "+ Agregar",
                                    key=f"desktop_quick_add_{producto_id}",
                                    type="primary",
                                    use_container_width=True,
                                    on_click=agregar_venta_rapida,
                                    args=(producto_id,),
                                )
                            with promo_col:
                                st.button(
                                    "🎁",
                                    key=f"desktop_promo_{producto_id}",
                                    help="Agregar promoción",
                                    use_container_width=True,
                                    on_click=abrir_promocion,
                                    args=(producto_id,),
                                )

        if total_paginas > 1:
            anterior_col, estado_col, siguiente_col = st.columns([1, 1.2, 1])
            with anterior_col:
                if st.button(
                    "← Anterior" if movil else "←",
                    help="Página anterior",
                    use_container_width=True,
                    disabled=pagina_actual == 0,
                    key=f"{'mobile' if movil else 'desktop'}_catalogo_anterior",
                ):
                    st.session_state.pagina_catalogo = pagina_actual - 1
                    st.rerun()
            with estado_col:
                st.markdown(
                    f'<div class="rv-page-status">{pagina_actual + 1} de {total_paginas}</div>',
                    unsafe_allow_html=True,
                )
            with siguiente_col:
                if st.button(
                    "Siguiente →" if movil else "→",
                    help="Página siguiente",
                    use_container_width=True,
                    disabled=pagina_actual >= total_paginas - 1,
                    key=f"{'mobile' if movil else 'desktop'}_catalogo_siguiente",
                ):
                    st.session_state.pagina_catalogo = pagina_actual + 1
                    st.rerun()


def render_carrito_panel(*, movil: bool) -> None:
    if movil:
        elementos = elementos_carrito()
        st.markdown('<p class="rv-mobile-page-title">Carrito</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="rv-mobile-page-copy">Ajusta cantidades con − y +. El precio solo se abre cuando necesitas modificarlo.</p>',
            unsafe_allow_html=True,
        )

        if elementos:
            resumen_col, opciones_col = st.columns([5, 1], gap="small")
            with resumen_col:
                _, unidades, gratis, total = totales_carrito()
                st.markdown(
                    f"**{len(elementos)} productos · {unidades} unidades**  \n{gratis} gratis · {moneda(total)}",
                )
            with opciones_col:
                with st.popover("⋯", use_container_width=True):
                    if st.button(
                        "Vaciar carrito",
                        key="mobile_vaciar_menu",
                        use_container_width=True,
                    ):
                        vaciar_carrito()
                        st.rerun()

        render_carrito(
            "mobile",
            mostrar_vaciar=False,
            mostrar_envio=False,
        )
        return

    with st.container(border=True):
        st.markdown('<p class="rv-section-title">Carrito</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="rv-section-copy">Ajusta con − y +. Abre editar solo para cambiar el precio.</p>',
            unsafe_allow_html=True,
        )
        render_carrito("desktop", mostrar_vaciar=True, mostrar_envio=True)


def render_navegacion_movil() -> None:
    elementos = elementos_carrito()
    _, unidades, _, total = totales_carrito()
    activo = str(st.session_state.mobile_tab)
    listo = bool(st.session_state.cliente_id and st.session_state.carrito)

    with st.bottom:
        with st.container(key="rv_mobile_bottom_bar"):
            if activo == "Carrito" and st.session_state.carrito:
                total_col, enviar_col = st.columns([1.05, 1.65], gap="small")
                with total_col:
                    st.markdown(
                        f"""
                        <div class="rv-mobile-bottom-summary">
                            <div>
                                <p class="rv-mobile-bottom-copy">{unidades} unidades</p>
                                <p class="rv-mobile-bottom-total">{moneda(total)}</p>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with enviar_col:
                    st.button(
                        "Crear pedido",
                        type="primary",
                        use_container_width=True,
                        disabled=(
                            not listo
                            or st.session_state.get("envio_en_progreso", False)
                        ),
                        key="mobile_bottom_checkout",
                        on_click=solicitar_envio,
                    )
            else:
                st.markdown(
                    f"""
                    <div class="rv-mobile-bottom-summary">
                        <p class="rv-mobile-bottom-copy">{unidades} unidades en el carrito</p>
                        <p class="rv-mobile-bottom-total">{moneda(total)}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            productos_col, carrito_col = st.columns(2, gap="small")
            with productos_col:
                st.button(
                    "🛍️ Productos",
                    type="primary" if activo == "Productos" else "secondary",
                    use_container_width=True,
                    key="mobile_nav_productos",
                    on_click=cambiar_tab_movil,
                    args=("Productos",),
                )
            with carrito_col:
                st.button(
                    f"🛒 Carrito · {len(elementos)}",
                    type="primary" if activo == "Carrito" else "secondary",
                    use_container_width=True,
                    key="mobile_nav_carrito",
                    on_click=cambiar_tab_movil,
                    args=("Carrito",),
                )


if ES_MOVIL:
    # En teléfono se conserva íntegramente la experiencia mobile-first: una
    # pantalla para Productos, otra para Carrito y navegación inferior fija.
    render_encabezado()
    render_cliente()
    if st.session_state.mobile_tab == "Carrito":
        render_carrito_panel(movil=True)
    else:
        render_catalogo(movil=True)
    render_navegacion_movil()
else:
    # En escritorio se usa una interfaz totalmente distinta, basada en el
    # diseño clásico proporcionado por el usuario. No se renderiza el catálogo
    # interfaz móvil ni la barra inferior.
    render_desktop_clasico()


# Abre el diálogo de promoción una sola vez después de tocar el regalo.
# La solicitud se consume antes de renderizar el diálogo para evitar que vuelva
# a abrirse en futuros reruns al tocar cualquier otra parte de la aplicación.
producto_promocion_pendiente = st.session_state.producto_promocion_id
if producto_promocion_pendiente is not None:
    st.session_state.producto_promocion_id = None
    dialogo_promocion(int(producto_promocion_pendiente))


confirmacion_pendiente = st.session_state.get("confirmar_envio", False)
if confirmacion_pendiente:
    # Se consume antes de abrir el diálogo para que cerrarlo no lo reactive en
    # la siguiente interacción.
    st.session_state.confirmar_envio = False
    dialogo_confirmar_pedido()


# =============================================================================
# ENVÍO
# =============================================================================

if st.session_state.enviar_pedido:
    st.session_state.enviar_pedido = False

    if not st.session_state.cliente_id or not st.session_state.carrito:
        st.error("Selecciona un cliente y agrega productos antes de enviar.")
    else:
        st.session_state.envio_en_progreso = True
        pedido_token = str(st.session_state.pedido_token)
        with st.spinner("Creando el pedido en Odoo..."):
            try:
                (
                    _,
                    folio,
                    estado,
                    total_sin_impuestos_odoo,
                    impuestos_odoo,
                    total_odoo,
                ) = crear_pedido_odoo(
                    uid=uid,
                    cliente_id=int(st.session_state.cliente_id),
                    carrito=st.session_state.carrito,
                    nota=st.session_state.nota_pedido,
                    pedido_token=pedido_token,
                )

                cliente = clientes_por_id[int(st.session_state.cliente_id)]
                nombre_cliente = str(cliente.get("name") or "Cliente")
                clientes_recientes = [
                    int(cliente_id)
                    for cliente_id in st.session_state.clientes_recientes
                    if int(cliente_id) != int(st.session_state.cliente_id)
                ]
                st.session_state.clientes_recientes = [
                    int(st.session_state.cliente_id),
                    *clientes_recientes,
                ][:8]
                carrito_enviado = [dict(linea) for linea in st.session_state.carrito]
                lineas, unidades, gratis, total = totales_carrito()
                texto_whatsapp = construir_mensaje_whatsapp(
                    nombre_cliente,
                    carrito_enviado,
                )

                st.session_state.resultado_pedido = {
                    "folio": folio,
                    "referencia": pedido_token,
                    "estado": estado,
                    "cliente": nombre_cliente,
                    "lineas": lineas,
                    "unidades": unidades,
                    "unidades_gratis": gratis,
                    "subtotal_sin_impuestos": (
                        total_sin_impuestos_odoo
                        if total_sin_impuestos_odoo or total_odoo
                        else max(0.0, total - impuestos_odoo)
                    ),
                    "impuestos": impuestos_odoo,
                    "total": total_odoo if total_odoo else total,
                    "texto_whatsapp": texto_whatsapp,
                    "enlace_whatsapp": crear_enlace_whatsapp(texto_whatsapp),
                }
                st.session_state.mostrar_balloons = True
                st.session_state.borrador_local_eliminar = True
                st.rerun()

            except xmlrpc.client.Fault as error:
                logger.exception("Odoo rechazó el pedido %s", pedido_token)
                st.error("Odoo rechazó el pedido. Revisa los datos e inténtalo nuevamente.")
                with st.expander("Ver detalle técnico"):
                    st.code(error.faultString)
            except xmlrpc.client.ProtocolError as error:
                logger.exception("Error HTTP al enviar %s", pedido_token)
                st.error(
                    "No se recibió una respuesta válida de Odoo. Puedes volver a "
                    f"intentarlo sin duplicar el pedido. Referencia: {pedido_token}"
                )
                st.caption(f"Código HTTP: {error.errcode}")
            except TimeoutError:
                logger.exception("Timeout al enviar %s", pedido_token)
                st.error(
                    "Odoo tardó más de 15 segundos. Puedes reintentar: la app "
                    "buscará primero la misma referencia para evitar duplicados. "
                    f"Referencia: {pedido_token}"
                )
            except Exception as error:
                logger.exception("Error inesperado al enviar %s", pedido_token)
                st.error(
                    f"No se pudo completar el pedido. Referencia: {pedido_token}"
                )
                with st.expander("Ver detalle técnico"):
                    st.code(str(error))
            finally:
                st.session_state.envio_en_progreso = False


# Segunda escritura del ciclo. Captura cambios realizados durante el render,
# por ejemplo cantidades, precios o notas editadas en widgets.
guardar_borrador_en_navegador("rv_borrador_local_guardado_post_v1")
