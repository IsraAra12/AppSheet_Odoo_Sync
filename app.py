from __future__ import annotations

import hashlib
import html
import json
import logging
import math
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

from rapyvet.customers import (
    ConflictoClienteError,
    ValidacionClienteError,
    alta_cliente_odoo,
    dominio_clientes_odoo,
)
from rapyvet.mobile import calcular_paginacion, cantidad_producto_en_carrito
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
ODOO_TIMEOUT_SEGUNDOS = 30.0

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
        "mobile_cliente_expandido": True,
        "mobile_cliente_selector": None,
        "mobile_panel_transition": "",
        "mobile_producto_confirmado_id": None,
        "enviar_pedido": False,
        "confirmar_envio": False,
        "envio_en_progreso": False,
        "error_envio_pedido": None,
        "pedido_token": f"RV-{uuid.uuid4().hex}",
        "nuevo_cliente_pendiente": False,
        "nuevo_cliente_version": 0,
        "alta_cliente_en_progreso": False,
        "cliente_seleccion_pendiente": None,
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

# Un cliente recién creado se selecciona al inicio del siguiente ciclo, antes
# de que el selector exista. Streamlit no permite cambiar la clave de un widget
# después de haberlo renderizado en el mismo ciclo.
if st.session_state.get("cliente_seleccion_pendiente") is not None:
    st.session_state.cliente_id = int(st.session_state.cliente_seleccion_pendiente)
    st.session_state.mobile_cliente_selector = int(
        st.session_state.cliente_seleccion_pendiente
    )
    st.session_state.cliente_seleccion_pendiente = None
    st.session_state.mobile_cliente_expandido = False

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
            --rv-bg: #09070c;
            --rv-surface: #151019;
            --rv-surface-soft: #201724;
            --rv-surface-elevated: #2a1d30;
            --rv-text: #f8f4fa;
            --rv-muted: #b9aec0;
            --rv-border: rgba(183, 120, 199, .24);
            --rv-primary: #773b86;
            --rv-primary-hover: #9654a6;
            --rv-primary-bright: #c58bd2;
            --rv-primary-soft: rgba(119, 59, 134, .24);
            --rv-promo-soft: rgba(237, 174, 82, .15);
            --rv-promo-text: #f2c879;
            --rv-danger: #ff8b9b;
            --rv-shadow: 0 18px 54px rgba(0, 0, 0, .38);
            --rv-glow: 0 0 0 1px rgba(197, 139, 210, .08),
                0 16px 46px rgba(52, 19, 62, .3);
            --rv-motion-snap: cubic-bezier(.2, .9, .2, 1);
            --rv-motion-ui: cubic-bezier(.2, .8, .2, 1);
            --rv-motion-gentle: cubic-bezier(.22, .7, .22, 1);
            --rv-motion-stagger: 40ms;
            --rv-motion-travel: 12px;
            color-scheme: dark;
        }

        html {
            scroll-behavior: auto;
            -webkit-text-size-adjust: 100%;
        }

        @keyframes rv-enter {
            from { opacity: 0; transform: scale(.992); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }

        @keyframes rv-dialog-enter {
            from { opacity: 0; transform: translateY(14px) scale(.975); }
            to { opacity: 1; transform: translateY(0) scale(1); }
        }

        @keyframes rv-status-pulse {
            0%, 100% { box-shadow: 0 0 0 3px rgba(34, 197, 94, .15); }
            50% { box-shadow: 0 0 0 6px rgba(34, 197, 94, .04); }
        }

        @keyframes rv-shimmer {
            from { transform: translateX(-120%); }
            to { transform: translateX(240%); }
        }

        @keyframes rv-card-confirmed {
            0% { box-shadow: 0 0 0 0 rgba(119, 59, 134, .42); }
            45% { box-shadow: 0 0 0 6px rgba(119, 59, 134, .16); }
            100% { box-shadow: 0 0 0 0 rgba(119, 59, 134, 0); }
        }

        @keyframes rv-add-confirmed {
            0% { background-color: transparent; }
            35% { background-color: color-mix(in srgb, var(--rv-primary-soft) 72%, transparent); }
            100% { background-color: transparent; }
        }

        @keyframes rv-catalog-card-in {
            from {
                opacity: .5;
                transform: translate3d(0, 0, 0) scale(.992);
            }
            to {
                opacity: 1;
                transform: translate3d(0, 0, 0) scale(1);
            }
        }

        @keyframes rv-catalog-scan {
            0% { opacity: 0; transform: translate3d(-115%, 0, 0); }
            22% { opacity: .7; }
            100% { opacity: 0; transform: translate3d(235%, 0, 0); }
        }

        @keyframes rv-result-ready {
            0% { opacity: 0; transform: translate3d(0, -3px, 0); }
            100% { opacity: 1; transform: translate3d(0, 0, 0); }
        }

        @keyframes rv-result-dot {
            0%, 100% { transform: scale(.78); opacity: .55; }
            50% { transform: scale(1); opacity: 1; }
        }

        @keyframes rv-panel-from-right {
            from {
                opacity: .64;
                filter: blur(1px);
                transform: translate3d(10px, 0, 0);
            }
            to { opacity: 1; filter: blur(0); transform: translate3d(0, 0, 0); }
        }

        @keyframes rv-panel-from-left {
            from {
                opacity: .64;
                filter: blur(1px);
                transform: translate3d(-10px, 0, 0);
            }
            to { opacity: 1; filter: blur(0); transform: translate3d(0, 0, 0); }
        }

        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(circle at 8% -8%, rgba(119, 59, 134, .26), transparent 31rem),
                radial-gradient(circle at 94% 22%, rgba(119, 59, 134, .13), transparent 27rem),
                linear-gradient(180deg, #0d0911 0%, var(--rv-bg) 34%, #08060a 100%);
            color: var(--rv-text);
        }

        [data-testid="stMain"] {
            overflow-anchor: none;
            overscroll-behavior-y: contain;
            -webkit-overflow-scrolling: touch;
            touch-action: pan-y;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        /*
         * streamlit-js-eval se renderiza dentro de un iframe invisible.
         * Algunas versiones de Streamlit reservan cerca de 150 px para ese
         * componente aunque no muestre contenido. Colapsamos exclusivamente
         * ese iframe sin afectar los controles nativos ni otros componentes.
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

        [data-testid="stAppViewBlockContainer"],
        [data-testid="stMainBlockContainer"] {
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
            animation: rv-enter .38s cubic-bezier(.2, .8, .2, 1) both;
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
            animation: rv-status-pulse 2.2s ease-in-out infinite;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--rv-border);
            border-radius: 1rem;
            background: var(--rv-surface);
            box-shadow: 0 4px 16px rgba(20, 35, 50, .04);
            transition: border-color .2s ease, box-shadow .2s ease,
                transform .2s ease;
        }

        div[data-testid="stVerticalBlockBorderWrapper"]:hover {
            border-color: color-mix(in srgb, var(--rv-primary) 36%, var(--rv-border));
            box-shadow: 0 10px 28px rgba(20, 35, 50, .07);
        }

        [data-testid="stDialog"] > div {
            animation: rv-dialog-enter .26s cubic-bezier(.2, .8, .2, 1) both;
        }

        [data-testid="stToast"] {
            animation: rv-dialog-enter .24s cubic-bezier(.2, .8, .2, 1) both;
        }

        .rv-new-client-intro {
            display: flex;
            align-items: center;
            gap: .75rem;
            margin: -.15rem 0 .9rem;
            padding: .78rem .85rem;
            border: 1px solid color-mix(in srgb, var(--rv-primary) 28%, var(--rv-border));
            border-radius: .95rem;
            background: linear-gradient(135deg, var(--rv-primary-soft), var(--rv-surface));
            animation: rv-enter .32s cubic-bezier(.2, .8, .2, 1) both;
        }

        .rv-new-client-icon {
            display: grid;
            flex: 0 0 2.45rem;
            width: 2.45rem;
            height: 2.45rem;
            place-items: center;
            border-radius: .8rem;
            background: var(--rv-primary);
            color: #fff;
            font-size: 1.25rem;
            font-weight: 950;
        }

        .rv-new-client-intro strong {
            font-size: .9rem;
        }

        .rv-new-client-intro p {
            margin: .1rem 0 0;
            color: var(--rv-muted) !important;
            font-size: .72rem;
            line-height: 1.4;
        }

        .rv-client-selected {
            display: flex;
            align-items: flex-start;
            gap: .52rem;
            margin-top: .5rem;
            padding: .58rem .65rem;
            border-radius: .78rem;
            background: var(--rv-primary-soft);
            animation: rv-enter .26s ease both;
        }

        .rv-client-selected-icon {
            line-height: 1.2;
        }

        .rv-client-selected strong,
        .rv-client-selected p {
            margin: 0;
        }

        .rv-client-selected strong { font-size: .75rem; }
        .rv-client-selected p {
            margin-top: .08rem;
            color: var(--rv-muted) !important;
            font-size: .66rem;
            line-height: 1.35;
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
            animation: rv-enter .28s cubic-bezier(.2, .8, .2, 1) both;
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

        .rv-mobile-progress {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .38rem;
            margin: 0 0 .72rem;
            padding: .28rem;
            border: 1px solid var(--rv-border);
            border-radius: 1rem;
            background: var(--rv-surface);
            box-shadow: 0 8px 24px rgba(20, 35, 50, .06);
            animation: rv-enter .32s cubic-bezier(.2, .8, .2, 1) both;
        }

        .rv-mobile-progress-step {
            display: flex;
            min-width: 0;
            align-items: center;
            gap: .38rem;
            padding: .42rem .38rem;
            border-radius: .72rem;
            color: var(--rv-muted) !important;
            font-size: .65rem;
            font-weight: 850;
            transition: color .22s cubic-bezier(.2, .8, .2, 1),
                background-color .22s cubic-bezier(.2, .8, .2, 1),
                transform .22s cubic-bezier(.2, .8, .2, 1);
        }

        .rv-mobile-progress-step span {
            display: grid;
            flex: 0 0 1.35rem;
            width: 1.35rem;
            height: 1.35rem;
            place-items: center;
            border: 1px solid var(--rv-border);
            border-radius: .45rem;
            background: var(--rv-surface-soft);
            font-size: .61rem;
            font-weight: 950;
        }

        .rv-mobile-progress-step.is-active {
            background: var(--rv-primary-soft);
            color: var(--rv-primary) !important;
        }

        .rv-mobile-progress-step.is-active span,
        .rv-mobile-progress-step.is-done span {
            border-color: var(--rv-primary);
            background: var(--rv-primary);
            color: #fff !important;
        }

        .rv-mobile-section-heading {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: .65rem;
            align-items: start;
            margin: .08rem 0 .7rem;
        }

        .rv-mobile-step-number {
            display: grid;
            width: 2.25rem;
            height: 2.25rem;
            place-items: center;
            border-radius: .75rem;
            background: linear-gradient(145deg, var(--rv-primary), #0891b2);
            color: #fff !important;
            box-shadow: 0 7px 18px rgba(15, 118, 110, .22);
            font-size: .78rem;
            font-weight: 950;
        }

        .rv-mobile-section-eyebrow {
            margin: .02rem 0 .05rem;
            color: var(--rv-primary) !important;
            font-size: .61rem;
            font-weight: 950;
            letter-spacing: .08em;
            text-transform: uppercase;
        }

        .rv-mobile-section-heading .rv-mobile-page-title {
            margin: 0;
        }

        .rv-mobile-section-heading .rv-mobile-page-copy {
            margin: .12rem 0 0;
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

        .rv-mobile-client-compact {
            display: grid;
            grid-template-columns: auto minmax(0, 1fr);
            gap: .55rem;
            align-items: start;
            padding: .1rem .05rem .55rem;
        }

        .rv-mobile-client-check {
            display: grid;
            width: 1.65rem;
            height: 1.65rem;
            place-items: center;
            border-radius: .55rem;
            background: var(--rv-primary-soft);
            color: var(--rv-primary) !important;
            font-size: .78rem;
            font-weight: 950;
        }

        .rv-mobile-client-compact strong {
            display: block;
            overflow: hidden;
            font-size: .82rem;
            line-height: 1.25;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .rv-mobile-client-compact p {
            overflow: hidden;
            margin: .1rem 0 0;
            color: var(--rv-muted) !important;
            font-size: .67rem;
            line-height: 1.3;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .rv-mobile-product-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: .16rem .8rem;
            align-items: center;
            padding: .05rem .02rem .45rem;
        }

        .rv-mobile-cart-status {
            display: flex;
            align-items: flex-end;
            min-height: 1.75rem;
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

        .rv-in-cart-chip {
            display: inline-flex;
            width: max-content;
            margin-top: .34rem;
            padding: .14rem .42rem;
            border-radius: 999px;
            background: var(--rv-primary-soft);
            color: var(--rv-primary) !important;
            font-size: .61rem;
            font-weight: 900;
        }

        .rv-mobile-cart-status .rv-in-cart-chip { margin-top: 0; }
        .rv-in-cart-chip-placeholder { visibility: hidden; }

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
            animation: rv-enter .25s ease both;
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
            position: relative;
            overflow: hidden;
            max-width: 22rem;
            margin: 25vh auto 0;
            padding: 1rem;
            color: var(--rv-muted);
            text-align: center;
        }

        .rv-review-metrics,
        .rv-result-metrics {
            display: grid;
            gap: .5rem;
            margin: .65rem 0 .8rem;
        }

        .rv-review-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        .rv-result-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }

        .rv-mini-metric {
            min-width: 0;
            padding: .62rem .66rem;
            border: 1px solid var(--rv-border);
            border-radius: .78rem;
            background: var(--rv-surface-soft);
        }

        .rv-mini-metric-label {
            overflow: hidden;
            margin: 0;
            color: var(--rv-muted) !important;
            font-size: .6rem;
            font-weight: 850;
            line-height: 1.2;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .rv-mini-metric-value {
            overflow: hidden;
            margin: .14rem 0 0;
            font-size: 1rem;
            font-weight: 950;
            line-height: 1.15;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .rv-loading::after {
            position: absolute;
            inset: 0;
            width: 45%;
            background: linear-gradient(90deg, transparent, var(--rv-primary-soft), transparent);
            content: "";
            animation: rv-shimmer 1.25s ease-in-out infinite;
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
            transition: transform .16s ease, box-shadow .16s ease,
                background-color .16s ease, border-color .16s ease;
        }

        div[data-testid="stButton"] > button:hover:not(:disabled) {
            transform: translateY(-1px);
            box-shadow: 0 7px 18px rgba(15, 118, 110, .14);
        }

        div[data-testid="stButton"] > button:active:not(:disabled) {
            transform: translateY(0) scale(.985);
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
            top: .35rem;
            z-index: 80;
            margin: 0 0 .65rem;
            padding: .62rem;
            border: 1px solid color-mix(in srgb, var(--rv-primary) 20%, var(--rv-border));
            border-radius: 1rem;
            background: color-mix(in srgb, var(--rv-surface) 96%, transparent);
            box-shadow: 0 10px 28px rgba(20, 35, 50, .09);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            contain: layout paint;
            transition: border-color .22s cubic-bezier(.2, .8, .2, 1),
                box-shadow .22s cubic-bezier(.2, .8, .2, 1);
        }

        .st-key-rv_mobile_search_area:focus-within {
            border-color: color-mix(in srgb, var(--rv-primary) 62%, var(--rv-border));
            box-shadow: 0 12px 30px rgba(15, 118, 110, .13);
        }

        .st-key-rv_mobile_search_area iframe:not([title*="streamlit_js_eval"]) {
            border-radius: .72rem;
            transition: opacity .18s ease, transform .18s ease;
        }

        .st-key-rv_mobile_catalog_results {
            position: relative;
            min-height: 7rem;
            overflow: clip;
            isolation: isolate;
        }

        .st-key-rv_mobile_catalog_surface {
            min-height: 22rem;
            padding-bottom: 3.5rem;
            overflow-anchor: none;
        }

        .st-key-rv_mobile_catalog_results::after {
            position: absolute;
            z-index: 6;
            top: 0;
            bottom: 0;
            left: 0;
            width: 34%;
            background: linear-gradient(
                90deg,
                transparent,
                color-mix(in srgb, var(--rv-primary-soft) 58%, transparent),
                transparent
            );
            content: "";
            pointer-events: none;
            animation: rv-catalog-scan .48s cubic-bezier(.2, .8, .2, 1) both;
        }

        .rv-motion-result-meta {
            position: relative;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: .5rem;
            margin: .12rem 0 .42rem;
            color: var(--rv-muted) !important;
            font-size: .69rem;
            font-weight: 820;
            overflow: hidden;
            animation: rv-result-ready .2s ease-out both;
        }

        .rv-motion-result-meta::after {
            position: absolute;
            inset: 0 auto 0 0;
            width: 32%;
            background: linear-gradient(
                90deg,
                transparent,
                color-mix(in srgb, var(--rv-primary-soft) 76%, transparent),
                transparent
            );
            content: "";
            pointer-events: none;
            animation: rv-catalog-scan .44s var(--rv-motion-ui) both;
        }

        .st-key-rv_mobile_panel_motion_to_cart {
            animation: rv-panel-from-right .28s var(--rv-motion-ui) both;
        }

        .st-key-rv_mobile_panel_motion_to_products {
            animation: rv-panel-from-left .28s var(--rv-motion-ui) both;
        }

        [class*="st-key-rv_mobile_panel_motion_"] {
            min-height: max(48rem, calc(100dvh + 18rem));
        }

        .rv-mobile-product-feedback.is-confirmed {
            border-radius: .72rem;
            animation: rv-add-confirmed .72s var(--rv-motion-ui) both;
        }

        .rv-motion-result-state {
            display: inline-flex;
            align-items: center;
            gap: .3rem;
            color: var(--rv-primary) !important;
            white-space: nowrap;
        }

        .rv-motion-result-state::before {
            width: .38rem;
            height: .38rem;
            border-radius: 999px;
            background: var(--rv-primary);
            content: "";
            animation: rv-result-dot .8s ease-in-out 1;
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

        .st-key-rv_mobile_client_card [data-testid="stVerticalBlock"],
        .st-key-rv_mobile_search_area [data-testid="stVerticalBlock"] {
            gap: .48rem;
        }

        .st-key-rv_mobile_client_card div[data-testid="stButton"] > button {
            min-height: 2.55rem;
        }

        [class*="st-key-rv_mobile_product_card_"] > div,
        [class*="st-key-rv_mobile_cart_card_"] > div {
            padding: .68rem !important;
        }

        @media (max-width: 820px) {
            [data-testid="stAppViewBlockContainer"],
            [data-testid="stMainBlockContainer"] {
                max-width: 100%;
                padding: .12rem .62rem 9.4rem;
            }

            [data-testid="stToolbar"] { display: none !important; }
            [data-testid="stHeader"] { height: 0 !important; }

            /* Streamlit apila columnas en pantallas angostas. En estos
               controles la disposición horizontal ahorra varios gestos y
               mantiene juntas las acciones relacionadas. */
            .st-key-rv_mobile_client_card [data-testid="stHorizontalBlock"],
            [class*="st-key-rv_mobile_product_card_"] [data-testid="stHorizontalBlock"],
            [class*="st-key-rv_mobile_cart_card_"] [data-testid="stHorizontalBlock"],
            .st-key-rv_mobile_cart_header [data-testid="stHorizontalBlock"],
            .st-key-rv_mobile_pagination [data-testid="stHorizontalBlock"],
            .st-key-rv_mobile_search_controls [data-testid="stHorizontalBlock"],
            .st-key-rv_mobile_filter_controls [data-testid="stHorizontalBlock"],
            .st-key-rv_mobile_bottom_bar [data-testid="stHorizontalBlock"] {
                flex-wrap: nowrap !important;
                align-items: stretch !important;
            }

            .st-key-rv_mobile_client_card [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            [class*="st-key-rv_mobile_product_card_"] [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            [class*="st-key-rv_mobile_cart_card_"] [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            .st-key-rv_mobile_cart_header [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            .st-key-rv_mobile_pagination [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            .st-key-rv_mobile_search_controls [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            .st-key-rv_mobile_filter_controls [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"],
            .st-key-rv_mobile_bottom_bar [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"] {
                width: auto !important;
                min-width: 0 !important;
                flex: 1 1 0 !important;
            }

            [class*="st-key-rv_mobile_product_card_"] [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:last-child,
            .st-key-rv_mobile_cart_header [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:last-child {
                flex: 0 0 5rem !important;
            }

            .st-key-rv_mobile_search_controls [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:last-child {
                flex: 0 0 3.25rem !important;
            }

            [class*="st-key-rv_mobile_product_card_"] {
                border-left: 3px solid color-mix(in srgb, var(--rv-primary) 78%, transparent);
                transform: translateZ(0);
                animation: rv-catalog-card-in .26s cubic-bezier(.2, .8, .2, 1) both;
                transition: border-color .2s cubic-bezier(.2, .8, .2, 1),
                    box-shadow .2s cubic-bezier(.2, .8, .2, 1),
                    transform .2s cubic-bezier(.2, .8, .2, 1);
                will-change: transform, opacity;
            }

            .st-key-rv_mobile_catalog_results
                [class*="st-key-rv_mobile_product_card_"]:nth-child(2) { animation-delay: 25ms; }
            .st-key-rv_mobile_catalog_results
                [class*="st-key-rv_mobile_product_card_"]:nth-child(3) { animation-delay: 50ms; }
            .st-key-rv_mobile_catalog_results
                [class*="st-key-rv_mobile_product_card_"]:nth-child(4) { animation-delay: 75ms; }
            .st-key-rv_mobile_catalog_results
                [class*="st-key-rv_mobile_product_card_"]:nth-child(5) { animation-delay: 100ms; }
            .st-key-rv_mobile_catalog_results
                [class*="st-key-rv_mobile_product_card_"]:nth-child(6) { animation-delay: 125ms; }

            [class*="st-key-rv_mobile_product_card_"].rv-mobile-card-confirmed {
                border-color: var(--rv-primary) !important;
                animation: rv-card-confirmed .85s ease both;
            }

            [class*="st-key-rv_mobile_product_card_"] > div {
                background: linear-gradient(145deg, var(--rv-surface), var(--rv-surface-soft));
            }

            [class*="st-key-rv_mobile_product_card_"] .rv-product-code {
                width: max-content;
                padding: .14rem .4rem;
                border-radius: 999px;
                background: var(--rv-primary-soft);
            }

            .st-key-rv_mobile_pagination [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:nth-child(2) {
                flex: 0 0 4.5rem !important;
            }

            .rv-mobile-appbar {
                margin-bottom: .55rem;
                padding: .62rem .68rem;
                border-color: transparent;
                border-radius: .92rem;
                background: linear-gradient(128deg, #0f766e 0%, #075985 100%);
                box-shadow: 0 10px 28px rgba(4, 85, 104, .22);
            }

            .rv-mobile-appbar .rv-brand-title,
            .rv-mobile-appbar .rv-brand-copy,
            .rv-mobile-appbar .rv-pill {
                color: #fff !important;
            }

            .rv-mobile-appbar .rv-brand-icon {
                background: rgba(255,255,255,.17);
            }

            .rv-mobile-appbar .rv-pill {
                border-color: rgba(255,255,255,.24);
                background: rgba(255,255,255,.13);
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
                box-sizing: border-box !important;
                border-radius: 1rem !important;
            }

            [data-testid="stDialog"] {
                overflow-x: hidden !important;
            }

            .rv-result-metrics {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }

            .rv-mini-metric {
                padding: .55rem .5rem;
            }

            .rv-mini-metric-value {
                font-size: .9rem;
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

        /* ================================================================
           RAPYVET 2026 — SISTEMA VISUAL DE MARCA
           Violeta extraído del logotipo (#773B86), carbón y ciruela.
           Las transiciones siguen los tokens snap/ui/gentle de Motion UI.
           ================================================================ */
        [data-testid="stAppViewContainer"] {
            font-family: Inter, "Avenir Next", Aptos, "Segoe UI", sans-serif;
        }

        [data-testid="stAppViewBlockContainer"],
        [data-testid="stMainBlockContainer"] {
            position: relative;
        }

        .rv-topbar,
        .rv-mobile-appbar {
            position: relative;
            overflow: hidden;
            border-color: rgba(197, 139, 210, .25);
            background:
                radial-gradient(circle at 14% -70%, rgba(197, 139, 210, .23), transparent 48%),
                linear-gradient(128deg, #1b1121 0%, #26152e 54%, #171019 100%);
            box-shadow: var(--rv-glow);
        }

        .rv-topbar::after,
        .rv-mobile-appbar::after {
            position: absolute;
            inset: 0 auto 0 -40%;
            width: 28%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,.11), transparent);
            content: "";
            pointer-events: none;
            animation: rv-catalog-scan .72s var(--rv-motion-gentle) .08s both;
        }

        .rv-brand-monogram {
            display: grid;
            flex: 0 0 2.55rem;
            width: 2.55rem;
            height: 2.55rem;
            place-items: center;
            border: 1px solid rgba(231, 194, 239, .22);
            border-radius: .88rem;
            background: linear-gradient(145deg, #9a56aa 0%, #773b86 58%, #55245f 100%);
            box-shadow: inset 0 1px rgba(255,255,255,.16), 0 8px 22px rgba(53, 17, 61, .4);
            color: #fff;
            font-size: .72rem;
            font-weight: 1000;
            letter-spacing: -.08em;
        }

        .rv-brand-title {
            color: var(--rv-text) !important;
            font-size: 1.08rem;
            line-height: 1;
            letter-spacing: -.055em;
        }

        .rv-brand-title span { font-weight: 950; }
        .rv-brand-title strong {
            color: var(--rv-primary-bright) !important;
            font-weight: 1000;
        }

        .rv-brand-copy {
            margin-top: .18rem;
            color: #cbbfd0 !important;
            font-size: .55rem;
            font-weight: 800;
            letter-spacing: .12em;
            text-transform: uppercase;
        }

        .rv-pill {
            border-color: rgba(197, 139, 210, .22);
            background: rgba(12, 8, 15, .48);
            color: #eee6f0 !important;
            box-shadow: inset 0 1px rgba(255,255,255,.04);
        }

        .rv-cart-pill {
            border-color: rgba(197, 139, 210, .38);
            color: var(--rv-primary-bright) !important;
        }

        .rv-online-dot {
            background: #68d69f;
            box-shadow: 0 0 0 3px rgba(104, 214, 159, .12);
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            border-color: var(--rv-border);
            background:
                linear-gradient(145deg, rgba(34, 23, 39, .96), rgba(20, 15, 24, .98));
            box-shadow: var(--rv-glow);
        }

        div[data-testid="stVerticalBlockBorderWrapper"]:hover {
            border-color: rgba(197, 139, 210, .48);
            box-shadow: 0 0 0 1px rgba(197, 139, 210, .08),
                0 18px 50px rgba(46, 17, 54, .34);
        }

        .rv-mobile-progress {
            gap: .3rem;
            padding: .3rem;
            border-color: rgba(197, 139, 210, .18);
            background: rgba(16, 11, 19, .74);
            box-shadow: inset 0 1px rgba(255,255,255,.035),
                0 12px 30px rgba(0,0,0,.22);
        }

        .rv-mobile-progress-step {
            color: #a99caf !important;
        }

        .rv-mobile-progress-step span {
            border-color: rgba(197, 139, 210, .18);
            background: #211726;
            color: #c8bbcd !important;
        }

        .rv-mobile-progress-step.is-active {
            background: linear-gradient(135deg, rgba(119,59,134,.38), rgba(119,59,134,.16));
            color: #f7eef9 !important;
            box-shadow: inset 0 0 0 1px rgba(197,139,210,.16);
        }

        .rv-mobile-progress-step.is-active span,
        .rv-mobile-progress-step.is-done span {
            border-color: #9b59aa;
            background: linear-gradient(145deg, #9b59aa, var(--rv-primary));
            box-shadow: 0 5px 14px rgba(65, 25, 74, .42);
        }

        .rv-mobile-step-number {
            border: 1px solid rgba(231,194,239,.2);
            background: linear-gradient(145deg, #a35bb3, #773b86 62%, #54235e);
            box-shadow: 0 9px 22px rgba(58, 20, 68, .42);
        }

        .rv-mobile-section-eyebrow,
        .rv-product-code,
        .rv-tax-note,
        .rv-motion-result-state {
            color: var(--rv-primary-bright) !important;
        }

        .rv-mobile-page-title {
            color: #fff9ff !important;
            font-size: 1.34rem;
        }

        .rv-mobile-page-copy {
            color: #ad9fb4 !important;
        }

        .st-key-rv_mobile_client_card > div {
            border-top: 1px solid rgba(222, 170, 233, .28);
            background:
                radial-gradient(circle at 100% 0, rgba(119,59,134,.18), transparent 48%),
                linear-gradient(145deg, #211725, #151019) !important;
        }

        .rv-mobile-client-label,
        .rv-mobile-filter-label {
            color: #c8b8cd !important;
            letter-spacing: .09em;
        }

        .rv-mobile-client-check {
            background: rgba(119,59,134,.28);
            color: var(--rv-primary-bright) !important;
            box-shadow: inset 0 0 0 1px rgba(197,139,210,.2);
        }

        input,
        textarea,
        [data-baseweb="select"] > div,
        [data-baseweb="input"] > div {
            border-color: rgba(197,139,210,.2) !important;
            background-color: #120d16 !important;
            color: var(--rv-text) !important;
            caret-color: var(--rv-primary-bright) !important;
        }

        input:focus,
        textarea:focus,
        [data-baseweb="select"]:focus-within,
        [data-baseweb="input"]:focus-within {
            border-color: rgba(197,139,210,.68) !important;
            box-shadow: 0 0 0 3px rgba(119,59,134,.2) !important;
        }

        [data-baseweb="popover"],
        [data-baseweb="menu"],
        [role="listbox"] {
            border-color: rgba(197,139,210,.24) !important;
            background: #18101c !important;
            color: var(--rv-text) !important;
        }

        [role="option"]:hover,
        [role="option"][aria-selected="true"] {
            background: var(--rv-primary-soft) !important;
        }

        div[data-testid="stButton"] > button {
            border-color: rgba(197,139,210,.24);
            background: linear-gradient(145deg, #25192a, #1a121e);
            color: #f6eff8;
            box-shadow: inset 0 1px rgba(255,255,255,.045);
            transition: transform .18s var(--rv-motion-snap),
                box-shadow .18s var(--rv-motion-ui),
                background-color .18s var(--rv-motion-ui),
                border-color .18s var(--rv-motion-ui);
        }

        div[data-testid="stButton"] > button:hover:not(:disabled) {
            border-color: rgba(197,139,210,.55);
            background: linear-gradient(145deg, #302037, #211625);
            box-shadow: 0 8px 24px rgba(43, 15, 51, .34);
        }

        button[kind="primary"] {
            border-color: #9e5bae !important;
            background: linear-gradient(135deg, #9350a3 0%, #773b86 58%, #652e72 100%) !important;
            color: #fff !important;
            box-shadow: inset 0 1px rgba(255,255,255,.14),
                0 9px 24px rgba(65, 24, 75, .38) !important;
        }

        button[kind="primary"]:hover {
            border-color: #b675c4 !important;
            background: linear-gradient(135deg, #a65db6, #874596 60%, #71347e) !important;
        }

        .st-key-rv_mobile_search_area {
            position: relative;
            top: auto;
            z-index: 4;
            contain: none;
            margin-bottom: .75rem;
            padding: .72rem;
            border-color: rgba(197,139,210,.34);
            background:
                linear-gradient(150deg, rgba(43,29,48,.98), rgba(21,16,25,.99));
            box-shadow: 0 0 0 1px rgba(197,139,210,.05),
                0 16px 38px rgba(0,0,0,.26);
            backdrop-filter: none;
            -webkit-backdrop-filter: none;
        }

        .st-key-rv_mobile_search_area:focus-within {
            border-color: rgba(197,139,210,.72);
            box-shadow: 0 0 0 3px rgba(119,59,134,.19),
                0 18px 40px rgba(0,0,0,.3);
        }

        .st-key-rv_mobile_search_area iframe:not([title*="streamlit_js_eval"]) {
            background: #120d16;
            transform: translateZ(0);
        }

        .st-key-rv_mobile_catalog_surface {
            padding-bottom: 4.4rem;
        }

        .rv-motion-result-meta {
            color: #aa9caf !important;
        }

        .rv-motion-result-meta::after,
        .st-key-rv_mobile_catalog_results::after {
            background: linear-gradient(90deg, transparent, rgba(197,139,210,.18), transparent);
        }

        .rv-motion-result-state::before {
            background: var(--rv-primary-bright);
            box-shadow: 0 0 0 4px rgba(197,139,210,.09);
        }

        [class*="st-key-rv_mobile_product_card_"] {
            border-left-color: #8f4e9e !important;
        }

        [class*="st-key-rv_mobile_product_card_"] > div {
            border-color: rgba(197,139,210,.2) !important;
            background:
                radial-gradient(circle at 100% 0, rgba(119,59,134,.14), transparent 46%),
                linear-gradient(145deg, #211725, #151019) !important;
            box-shadow: 0 10px 28px rgba(0,0,0,.2);
        }

        [class*="st-key-rv_mobile_product_card_"] .rv-product-code {
            border: 1px solid rgba(197,139,210,.18);
            background: rgba(119,59,134,.22);
        }

        .rv-mobile-product-row .rv-product-price {
            color: #e2b8ea !important;
        }

        .rv-in-cart-chip {
            border: 1px solid rgba(197,139,210,.2);
            background: rgba(119,59,134,.24);
            color: #dbaee5 !important;
        }

        [class*="st-key-rv_mobile_cart_card_"] > div,
        .rv-total-card {
            border-color: rgba(197,139,210,.22) !important;
            background: linear-gradient(145deg, #211725, #151019) !important;
        }

        .st-key-rv_mobile_bottom_bar {
            border-color: rgba(197,139,210,.3);
            background: linear-gradient(180deg, rgba(28,18,32,.985), rgba(14,9,17,.995));
            box-shadow: 0 -16px 42px rgba(0,0,0,.42),
                inset 0 1px rgba(255,255,255,.045);
            backdrop-filter: none;
            -webkit-backdrop-filter: none;
        }

        [data-testid="stBottom"],
        [data-testid="stBottomBlockContainer"] {
            background: linear-gradient(180deg, transparent, rgba(9,7,12,.93) 28%) !important;
        }

        .rv-mobile-bottom-total {
            color: #e3bce9 !important;
        }

        [data-testid="stDialog"] > div,
        [data-testid="stPopoverBody"] {
            border: 1px solid rgba(197,139,210,.25) !important;
            background: linear-gradient(145deg, #211725, #120d16) !important;
            box-shadow: 0 24px 80px rgba(0,0,0,.56) !important;
        }

        .rv-new-client-intro {
            border-color: rgba(197,139,210,.28);
            background: linear-gradient(135deg, rgba(119,59,134,.26), #18101c);
        }

        .rv-new-client-icon {
            background: linear-gradient(145deg, #a45db4, #773b86);
            box-shadow: 0 8px 22px rgba(54,18,63,.4);
        }

        .rv-empty,
        .rv-loading {
            border-color: rgba(197,139,210,.22) !important;
            background: linear-gradient(145deg, #211725, #151019) !important;
        }

        @media (max-width: 820px) {
            [data-testid="stAppViewBlockContainer"],
            [data-testid="stMainBlockContainer"] {
                padding-top: .3rem;
                padding-right: .62rem;
                padding-left: .62rem;
            }

            .rv-mobile-appbar {
                min-height: 4.15rem;
                margin-bottom: .62rem;
                padding: .68rem .72rem;
                border: 1px solid rgba(197,139,210,.3);
                border-radius: 1.15rem;
                background:
                    radial-gradient(circle at 12% -55%, rgba(197,139,210,.26), transparent 50%),
                    linear-gradient(128deg, #211328 0%, #321a3b 55%, #171019 100%);
                box-shadow: 0 16px 38px rgba(0,0,0,.32);
            }

            .rv-mobile-appbar .rv-brand-copy { display: block; }
            .rv-mobile-appbar .rv-brand-title,
            .rv-mobile-appbar .rv-brand-copy,
            .rv-mobile-appbar .rv-pill { color: inherit !important; }

            .rv-mobile-appbar .rv-pill {
                border-color: rgba(197,139,210,.24);
                background: rgba(9,6,11,.44);
            }

            .rv-brand-monogram {
                flex-basis: 2.35rem;
                width: 2.35rem;
                height: 2.35rem;
                border-radius: .8rem;
            }

            .rv-brand-title { font-size: 1.02rem; }
            .rv-brand-copy { font-size: .48rem; }
            .rv-mobile-status .rv-pill { font-size: .59rem; }

            .rv-mobile-section-heading {
                margin-top: .2rem;
                margin-bottom: .82rem;
            }

            .rv-mobile-page-copy {
                max-width: 31rem;
            }

            [class*="st-key-rv_mobile_product_card_"] {
                animation-duration: .24s;
            }
        }

        @media (max-width: 360px) {
            .rv-brand-copy { display: none !important; }
            .rv-mobile-status .rv-pill:first-child { display: none; }
            .rv-mobile-progress-step { justify-content: center; }
            .rv-mobile-progress-step { font-size: 0; }
            .rv-mobile-progress-step span { font-size: .61rem; }
        }

        /* ================================================================
           PULIDO PROFESIONAL MOBILE-FIRST
           Corrige la densidad que Streamlit agrega a cada bloque, refuerza
           la jerarquía tipográfica y deja más producto visible por pantalla.
           ================================================================ */
        @keyframes rv-professional-card-in {
            from { opacity: .76; transform: translate3d(0, 4px, 0); }
            to { opacity: 1; transform: translate3d(0, 0, 0); }
        }

        @media (max-width: 820px) {
            .rv-mobile-appbar {
                box-sizing: border-box;
                min-height: 3.8rem;
                margin-bottom: .48rem;
                padding: .54rem .62rem;
                border-radius: 1rem;
            }

            .rv-brand-monogram {
                flex-basis: 2.15rem;
                width: 2.15rem;
                height: 2.15rem;
                border-radius: .72rem;
                font-size: .64rem;
            }

            .rv-brand-title {
                margin: 0 !important;
                font-size: .96rem !important;
                line-height: 1 !important;
            }

            .rv-brand-copy {
                margin-top: .16rem !important;
                font-size: .45rem !important;
                line-height: 1.15 !important;
            }

            .rv-mobile-status { gap: .25rem; }
            .rv-mobile-status .rv-pill {
                padding: .27rem .42rem;
                font-size: .58rem !important;
                line-height: 1.1;
            }

            .rv-mobile-progress {
                gap: .22rem;
                margin-bottom: .58rem;
                padding: .22rem;
                border-radius: .86rem;
            }

            .rv-mobile-progress-step {
                gap: .3rem;
                min-height: 1.95rem;
                padding: .3rem .34rem;
                border-radius: .62rem;
                font-size: .6rem !important;
                line-height: 1.1;
            }

            .rv-mobile-progress-step span {
                flex-basis: 1.18rem;
                width: 1.18rem;
                height: 1.18rem;
                border-radius: .38rem;
                font-size: .55rem !important;
            }

            .st-key-rv_mobile_client_card {
                gap: .48rem !important;
                margin-bottom: .54rem;
                padding: .7rem !important;
                border-color: rgba(197,139,210,.25) !important;
                border-radius: 1rem !important;
            }

            /* El key de un contenedor vive en el bloque exterior. La regla
               anterior aplicaba relleno también a cada hijo y duplicaba el
               alto de clientes y productos. */
            .st-key-rv_mobile_client_card
                > [data-testid="stElementContainer"],
            .st-key-rv_mobile_client_card
                > [data-testid="stLayoutWrapper"],
            [class*="st-key-rv_mobile_product_card_"]
                > [data-testid="stElementContainer"],
            [class*="st-key-rv_mobile_product_card_"]
                > [data-testid="stLayoutWrapper"] {
                padding: 0 !important;
            }

            /* Streamlit aplica un margen negativo al contenedor Markdown.
               Reservamos sólo la separación necesaria para que títulos,
               etiquetas y acciones nunca se monten entre sí. */
            .st-key-rv_mobile_client_card
                > [data-testid="stElementContainer"]:has(.rv-mobile-client-head),
            .st-key-rv_mobile_search_area
                > [data-testid="stElementContainer"]:has(.rv-mobile-filter-label),
            [class*="st-key-rv_mobile_product_card_"]
                > [data-testid="stElementContainer"]:has(.rv-mobile-product-feedback) {
                padding-bottom: .55rem !important;
            }

            /* La tarjeta compacta contiene dos líneas (nombre y detalle),
               pero el Markdown de Streamlit descuenta 1rem de su altura. Sin
               este aislamiento los botones comienzan antes de que termine el
               correo y el bloque se ve comprimido. */
            .st-key-rv_mobile_client_card
                [data-testid="stMarkdownContainer"]:has(.rv-mobile-client-compact) {
                margin-bottom: 0 !important;
            }

            .st-key-rv_mobile_client_card
                > [data-testid="stElementContainer"]:has(.rv-mobile-client-compact),
            .st-key-rv_mobile_client_card
                [data-testid="stMarkdown"]:has(.rv-mobile-client-compact) {
                min-height: 2.25rem !important;
            }

            .rv-mobile-client-head {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: .65rem;
            }

            .rv-mobile-client-title {
                margin: 0 !important;
                color: #f8f1fa !important;
                font-size: .76rem !important;
                font-weight: 900;
                line-height: 1.2 !important;
            }

            .rv-mobile-client-step {
                flex: 0 0 auto;
                padding: .2rem .4rem;
                border: 1px solid rgba(197,139,210,.2);
                border-radius: 999px;
                background: rgba(119,59,134,.18);
                color: var(--rv-primary-bright) !important;
                font-size: .53rem !important;
                font-weight: 950;
                letter-spacing: .07em;
                line-height: 1.1 !important;
                text-transform: uppercase;
            }

            .st-key-rv_mobile_client_card div[data-testid="stButton"] > button {
                min-height: 2.42rem;
                border-radius: .68rem;
                font-size: .72rem;
            }

            .rv-mobile-client-compact {
                min-height: 2.25rem;
                align-items: center;
                padding-bottom: .28rem;
            }
            .rv-mobile-client-compact strong {
                font-size: .78rem !important;
                line-height: 1.2 !important;
            }
            .rv-mobile-client-compact p {
                font-size: .63rem !important;
                line-height: 1.25 !important;
            }

            .rv-mobile-section-heading {
                gap: .56rem;
                margin: .08rem 0 .58rem;
            }

            .rv-mobile-step-number {
                width: 2rem;
                height: 2rem;
                border-radius: .66rem;
                font-size: .68rem !important;
            }

            .rv-mobile-section-eyebrow {
                margin: .01rem 0 .04rem !important;
                font-size: .55rem !important;
                line-height: 1.15 !important;
            }

            .rv-mobile-page-title {
                margin: 0 !important;
                font-size: 1.08rem !important;
                line-height: 1.12 !important;
                letter-spacing: -.035em;
            }

            .rv-mobile-page-copy {
                margin: .14rem 0 0 !important;
                font-size: .69rem !important;
                line-height: 1.38 !important;
            }

            .st-key-rv_mobile_search_area {
                gap: .48rem !important;
                margin-bottom: .62rem;
                padding: .64rem;
                border-radius: 1rem;
            }

            .rv-mobile-filter-label {
                margin: 0 !important;
                font-size: .57rem !important;
                line-height: 1.15 !important;
            }

            .st-key-rv_mobile_search_area
                iframe:not([title*="streamlit_js_eval"]) {
                height: 3.3rem !important;
                min-height: 3.3rem !important;
                border: 1px solid rgba(197,139,210,.12);
                border-radius: .72rem;
            }

            .st-key-rv_mobile_search_controls [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:last-child {
                flex-basis: 3rem !important;
            }

            .st-key-rv_mobile_search_controls div[data-testid="stButton"] > button,
            .st-key-rv_mobile_filter_controls button,
            .st-key-rv_mobile_filter_controls [data-baseweb="select"] > div {
                min-height: 2.48rem !important;
                border-radius: .65rem !important;
                font-size: .7rem !important;
            }

            .st-key-rv_mobile_filter_controls [role="radiogroup"] {
                display: flex !important;
                width: 100% !important;
                flex-flow: row nowrap !important;
            }

            .st-key-rv_mobile_filter_controls [role="radiogroup"] > button {
                min-width: 0 !important;
                flex: 1 1 0 !important;
                padding-right: .3rem !important;
                padding-left: .3rem !important;
            }

            .rv-motion-result-meta {
                margin: .04rem 0 .4rem;
                font-size: .62rem !important;
                line-height: 1.15;
            }

            .rv-motion-result-state::before {
                width: .32rem;
                height: .32rem;
            }

            [class*="st-key-rv_mobile_product_card_"] {
                gap: .5rem !important;
                padding: .68rem !important;
                border: 1px solid rgba(197,139,210,.2) !important;
                border-left: 3px solid #8f4e9e !important;
                border-radius: .96rem !important;
                animation: rv-professional-card-in .22s var(--rv-motion-ui) both;
                will-change: auto;
            }

            [class*="st-key-rv_mobile_product_card_"] > div {
                background: transparent !important;
                box-shadow: none !important;
            }

            .rv-mobile-product-feedback {
                position: relative;
                min-height: 4.65rem;
                padding-bottom: 1.18rem;
            }

            .rv-mobile-product-row {
                grid-template-columns: minmax(0, 1fr) auto;
                gap: .12rem .65rem;
                padding: 0;
            }

            [class*="st-key-rv_mobile_product_card_"] .rv-product-code {
                padding: .13rem .36rem;
                font-size: .54rem !important;
                line-height: 1.12 !important;
            }

            .rv-mobile-product-row .rv-product-name {
                font-size: .78rem !important;
                line-height: 1.24 !important;
            }

            .rv-mobile-product-row .rv-product-price {
                font-size: .84rem !important;
                line-height: 1.15 !important;
            }

            .rv-tax-note {
                grid-column: 1 / -1;
                margin: .1rem 0 0 !important;
                font-size: .57rem !important;
                line-height: 1.2 !important;
            }

            .rv-mobile-cart-status {
                position: absolute;
                bottom: 0;
                left: 0;
                min-height: 1rem;
            }

            .rv-in-cart-chip {
                padding: .12rem .36rem;
                font-size: .55rem !important;
                line-height: 1.15 !important;
            }

            [class*="st-key-rv_mobile_product_card_"]
                [data-testid="stHorizontalBlock"]
                > [data-testid="stColumn"]:last-child {
                flex-basis: 4.35rem !important;
            }

            [class*="st-key-rv_mobile_product_card_"]
                div[data-testid="stButton"] > button {
                min-height: 2.55rem;
                border-radius: .68rem;
                font-size: .72rem;
                line-height: 1.1;
            }

            .st-key-rv_mobile_pagination { margin-top: .18rem; }
            .st-key-rv_mobile_pagination div[data-testid="stButton"] > button {
                min-height: 2.48rem;
                font-size: .68rem;
            }

            .rv-page-status {
                min-height: 2.48rem;
                font-size: .62rem !important;
            }

            .st-key-rv_mobile_bottom_bar {
                position: fixed !important;
                z-index: 1000;
                bottom: calc(.42rem + env(safe-area-inset-bottom));
                left: 50%;
                width: min(calc(100vw - 1.25rem), 48rem);
                box-sizing: border-box;
                gap: .42rem !important;
                padding: .5rem .5rem calc(.46rem + env(safe-area-inset-bottom));
                border-radius: 1.05rem;
                transform: translateX(-50%);
            }

            /* El markdown con HTML hereda un margen inferior negativo de
               Streamlit. En una barra fija ese margen colapsaba la fila del
               resumen y la dejaba visualmente detrás de los botones. */
            .st-key-rv_mobile_bottom_bar [data-testid="stMarkdownContainer"] {
                margin-bottom: 0 !important;
            }

            .st-key-rv_mobile_bottom_bar [data-testid="stElementContainer"]:has(
                .rv-mobile-bottom-summary
            ),
            .st-key-rv_mobile_bottom_bar [data-testid="stMarkdown"]:has(
                .rv-mobile-bottom-summary
            ) {
                min-height: 1.65rem !important;
            }

            .rv-mobile-bottom-summary {
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto;
                min-height: 1.65rem;
                align-items: center;
                gap: .75rem;
                padding: 0 .16rem .14rem;
            }
            .rv-mobile-bottom-copy {
                overflow: hidden;
                font-size: .64rem !important;
                line-height: 1.2 !important;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .rv-mobile-bottom-total {
                font-size: .9rem !important;
                line-height: 1.1 !important;
            }

            .st-key-rv_mobile_bottom_bar div[data-testid="stButton"] > button {
                min-height: 2.8rem;
                border-radius: .76rem;
                font-size: .72rem;
            }

            [class*="st-key-rv_mobile_panel_motion_"] {
                min-height: max(26rem, calc(100dvh - 17rem));
            }

            button:focus-visible,
            input:focus-visible,
            [role="combobox"]:focus-visible {
                outline: 2px solid var(--rv-primary-bright) !important;
                outline-offset: 2px !important;
            }
        }

        @media (max-width: 360px) {
            .rv-mobile-status .rv-pill:first-child {
                display: inline-flex;
                align-items: center;
            }
            .rv-mobile-status .rv-pill:last-child { display: none; }
        }

        @media (min-width: 821px) {
            .rv-classic-hero {
                border-color: rgba(197,139,210,.28);
                background:
                    radial-gradient(circle at 88% -40%, rgba(197,139,210,.3), transparent 35%),
                    linear-gradient(128deg, #201126 0%, #773b86 58%, #2a1531 100%);
                box-shadow: 0 20px 60px rgba(38,12,45,.38);
            }

            .rv-classic-title span { color: #fff !important; }
            .rv-classic-title strong {
                color: #e7b9ef !important;
                font-weight: 1000;
            }
            .rv-classic-title em {
                margin-left: .34rem;
                color: rgba(255,255,255,.72) !important;
                font-size: .72em;
                font-style: normal;
                font-weight: 760;
            }

            .rv-classic-status-card,
            .rv-classic-step,
            .rv-classic-product-preview,
            .rv-classic-promo-preview {
                border-color: rgba(197,139,210,.2);
                background: linear-gradient(145deg, #211725, #151019);
            }

            .rv-classic-step.active {
                border-color: #9955a8;
                box-shadow: 0 0 0 .18rem rgba(119,59,134,.22);
            }
        }

        @media (prefers-reduced-motion: reduce) {
            html { scroll-behavior: auto; }

            *, *::before, *::after {
                animation-duration: .001ms !important;
                animation-iteration-count: 1 !important;
                scroll-behavior: auto !important;
                transition-duration: .001ms !important;
            }

            div[data-testid="stButton"] > button:hover:not(:disabled),
            div[data-testid="stButton"] > button:active:not(:disabled) {
                transform: none;
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
        [dominio_clientes_odoo()],
        {
            "fields": [
                "id",
                "name",
                "street",
                "city",
                "zip",
                "vat",
                "email",
                "phone",
            ],
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
                for campo in (
                    "name",
                    "street",
                    "city",
                    "zip",
                    "vat",
                    "email",
                    "phone",
                )
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

    def resultado_desde_registro(
        registro: dict[str, Any],
    ) -> tuple[int, str, str, float, float, float]:
        sale_order_id = int(registro["id"])
        return (
            sale_order_id,
            str(registro.get("name") or sale_order_id),
            (
                "Pedido recuperado"
                if str(registro.get("state") or "") in {"sale", "done"}
                else "Cotización recuperada"
            ),
            float(registro.get("amount_untaxed") or 0.0),
            float(registro.get("amount_tax") or 0.0),
            float(registro.get("amount_total") or 0.0),
        )

    def buscar_existente(proxy: Any) -> dict[str, Any] | None:
        registros = proxy.execute_kw(
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
        return registros[0] if registros else None

    # La misma referencia se conserva después de un timeout. Antes de crear se
    # busca una orden previa para que reintentar recupere el resultado en lugar
    # de duplicar el pedido.
    registro_existente = buscar_existente(models)
    if registro_existente:
        logger.warning(
            "Pedido recuperado por referencia idempotente %s (Odoo id=%s)",
            token,
            registro_existente["id"],
        )
        return resultado_desde_registro(registro_existente)

    if not carrito:
        raise ValueError("El pedido no contiene productos.")

    lineas_validadas: list[tuple[int, int, float]] = []
    for posicion, linea in enumerate(carrito, start=1):
        try:
            producto_id = int(linea["product_id"])
            cantidad = int(linea["cantidad"])
            precio = float(linea["precio_unitario"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(
                f"La línea {posicion} tiene datos incompletos o inválidos."
            ) from error

        if producto_id <= 0:
            raise ValueError(f"La línea {posicion} no tiene un producto válido.")
        if cantidad <= 0:
            raise ValueError(f"La línea {posicion} debe tener al menos una unidad.")
        if not math.isfinite(precio) or precio < 0:
            raise ValueError(f"La línea {posicion} tiene un precio inválido.")

        lineas_validadas.append((producto_id, cantidad, precio))

    cliente_disponible = models.execute_kw(
        DB,
        uid,
        PASSWORD,
        "res.partner",
        "search_count",
        [[("id", "=", int(cliente_id)), ("active", "=", True)]],
    )
    if not cliente_disponible:
        raise ValueError(
            "El cliente ya no está disponible en Odoo. Actualiza la lista y "
            "selecciónalo nuevamente."
        )

    productos_ids = sorted({producto_id for producto_id, _, _ in lineas_validadas})
    productos_disponibles = models.execute_kw(
        DB,
        uid,
        PASSWORD,
        "product.product",
        "search_read",
        [[
            ("id", "in", productos_ids),
            ("active", "=", True),
            ("sale_ok", "=", True),
        ]],
        {"fields": ["id"]},
    )
    productos_disponibles_ids = {
        int(producto["id"]) for producto in productos_disponibles
    }
    faltantes = [
        producto_id
        for producto_id in productos_ids
        if producto_id not in productos_disponibles_ids
    ]
    if faltantes:
        raise ValueError(
            "Uno o más productos fueron desactivados o ya no pueden venderse. "
            "Actualiza el catálogo y vuelve a agregarlos."
        )

    # Odoo calcula la descripción, unidad e impuestos mediante el cambio de
    # producto. No enviamos `name`: sobrescribirlo duplica la descripción al
    # facturar en Odoo SaaS 19.3.
    lineas_odoo = [
        (
            0,
            0,
            {
                "product_id": producto_id,
                "product_uom_qty": cantidad,
                "price_unit": precio,
            },
        )
        for producto_id, cantidad, precio in lineas_validadas
    ]

    valores: dict[str, Any] = {
        "partner_id": int(cliente_id),
        "order_line": lineas_odoo,
        "origin": f"RapyVet Pedidos | {token}",
        "client_order_ref": token,
    }

    if nota.strip():
        valores["note"] = nota.strip()

    try:
        sale_order_id = models.execute_kw(
            DB,
            uid,
            PASSWORD,
            "sale.order",
            "create",
            [valores],
        )
    except (TimeoutError, OSError, xmlrpc.client.ProtocolError):
        # Odoo puede confirmar la transacción aunque la respuesta se pierda.
        # Recuperamos automáticamente por la referencia antes de mostrar error.
        for intento in range(3):
            if intento:
                time.sleep(0.4 * intento)
            try:
                proxy_recuperacion = crear_proxy_odoo(
                    URL,
                    "/xmlrpc/2/object",
                    timeout=ODOO_TIMEOUT_SEGUNDOS,
                )
                recuperado = buscar_existente(proxy_recuperacion)
                if recuperado:
                    logger.warning(
                        "Pedido %s recuperado automáticamente tras pérdida de respuesta",
                        token,
                    )
                    return resultado_desde_registro(recuperado)
            except Exception:
                logger.warning(
                    "Intento %s sin respuesta al recuperar %s",
                    intento + 1,
                    token,
                )
        raise
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


def detalle_fallo_odoo(error: Exception) -> str:
    """Extrae una causa breve sin mostrar todo el traceback del servidor."""

    texto = (
        str(error.faultString)
        if isinstance(error, xmlrpc.client.Fault)
        else str(error)
    )
    lineas = [linea.strip() for linea in texto.splitlines() if linea.strip()]
    return (lineas[-1] if lineas else texto).strip()[:500]


def guardar_error_envio(
    mensaje: str,
    referencia: str,
    detalle: str = "",
) -> None:
    st.session_state.error_envio_pedido = {
        "mensaje": str(mensaje).strip(),
        "referencia": str(referencia).strip(),
        "detalle": str(detalle).strip()[:500],
    }


def render_error_envio_pendiente() -> None:
    error = st.session_state.get("error_envio_pedido")
    if not isinstance(error, dict):
        return

    with st.container(border=True, key="rv_order_error_card"):
        st.error(str(error.get("mensaje") or "No se pudo enviar el pedido."))
        if error.get("referencia"):
            st.caption(f"Referencia segura: {error['referencia']}")
        if error.get("detalle"):
            with st.expander("Ver detalle para soporte"):
                st.code(str(error["detalle"]))


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
    if ES_MOVIL:
        st.session_state.mobile_producto_confirmado_id = int(producto_id)
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
    eliminada = next(
        (
            linea
            for linea in st.session_state.carrito
            if str(linea["linea_id"]) == str(linea_id)
        ),
        None,
    )
    st.session_state.carrito = [
        linea
        for linea in st.session_state.carrito
        if str(linea["linea_id"]) != str(linea_id)
    ]
    if eliminada:
        st.session_state.notificacion_pendiente = {
            "texto": f"{eliminada.get('nombre_producto') or 'Producto'} eliminado",
            "icono": "🗑️",
        }


def eliminar_promocion(grupo_id: str) -> None:
    eliminada = next(
        (
            linea
            for linea in st.session_state.carrito
            if str(linea.get("grupo_promocion")) == str(grupo_id)
        ),
        None,
    )
    st.session_state.carrito = [
        linea
        for linea in st.session_state.carrito
        if str(linea.get("grupo_promocion")) != str(grupo_id)
    ]
    if eliminada:
        st.session_state.notificacion_pendiente = {
            "texto": f"Promoción de {eliminada.get('nombre_producto') or 'producto'} eliminada",
            "icono": "🗑️",
        }


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
    st.session_state.mobile_tab = "Productos"
    st.session_state.mobile_cliente_expandido = True
    st.session_state.mobile_cliente_selector = None
    st.session_state.confirmar_envio = False
    st.session_state.envio_en_progreso = False
    st.session_state.error_envio_pedido = None
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
    """Limpia el buscador móvil y vuelve a la primera página."""
    st.session_state.busqueda_pos = ""
    st.session_state.busqueda_widget_version = (
        int(st.session_state.get("busqueda_widget_version", 0)) + 1
    )
    st.session_state.pagina_catalogo = 0

    # El cambio de versión monta un campo vacío sin intentar imponer un valor
    # sobre el componente que el usuario está editando.
    for clave in list(st.session_state.keys()):
        if str(clave).startswith("busqueda_pos_input_"):
            del st.session_state[clave]


def solicitar_envio() -> None:
    """Marca la confirmación sin forzar un rerun desde un callback.

    Streamlit vuelve a ejecutar automáticamente después de un callback. Llamar
    ``st.rerun`` dentro de él es un no-op y, en la interfaz móvil fragmentada,
    impide que el flujo llegue al diálogo y al envío a Odoo.
    """

    if st.session_state.get("envio_en_progreso", False):
        return
    st.session_state.error_envio_pedido = None
    st.session_state.confirmar_envio = True


def solicitar_nuevo_cliente() -> None:
    """Marca el alta pendiente; el llamador móvil solicita el rerun completo."""

    if st.session_state.get("alta_cliente_en_progreso", False):
        return
    st.session_state.nuevo_cliente_pendiente = True


def seleccionar_cliente_movil() -> None:
    """Compacta el selector después de elegir un cliente válido."""

    cliente_id = st.session_state.get("mobile_cliente_selector")
    st.session_state.cliente_id = int(cliente_id) if cliente_id is not None else None
    st.session_state.mobile_cliente_expandido = not bool(cliente_id)


def editar_cliente_movil() -> None:
    st.session_state.mobile_cliente_selector = st.session_state.get("cliente_id")
    st.session_state.mobile_cliente_expandido = True


def habilitar_estabilidad_viewport_movil() -> None:
    """Conserva la tarjeta tocada en el mismo sitio durante cada rerun."""

    script_source = r"""
((host) => {
  const window = host;
  const document = host.document;
  const performance = host.performance;
  const CSS = host.CSS;

  if (document.documentElement.dataset.rvViewportStabilityBound === '1') return;
  document.documentElement.dataset.rvViewportStabilityBound = '1';
  let viewportLock = null;
  let viewportLockFrame = null;

  const cancelLock = () => {
    if (viewportLock) viewportLock.until = 0;
    window.localStorage.removeItem('rv-mobile-viewport-lock');
  };

  const persistLock = (durationMs) => {
    if (!viewportLock) return;
    viewportLock.token = `${Date.now()}-${Math.random()}`;
    viewportLock.expiresAt = Date.now() + durationMs;
    window.localStorage.setItem(
      'rv-mobile-viewport-lock',
      JSON.stringify(viewportLock)
    );
  };

  const keepStable = (now) => {
    const lock = viewportLock;
    if (!lock || now > lock.until) {
      viewportLockFrame = null;
      return;
    }

    const scroller = document.querySelector('[data-testid="stMain"]');
    if (scroller) {
      let desired = lock.scrollTop;
      if (lock.resetToTop) {
        const progress = Math.min(
          1,
          Math.max(0, (now - lock.startedAt) / 260)
        );
        const eased = 1 - Math.pow(1 - progress, 3);
        desired = lock.fromScrollTop * (1 - eased);
      } else if (lock.anchorClass) {
        const anchor = document.querySelector(
          '.' + CSS.escape(lock.anchorClass)
        );
        if (anchor) {
          desired = scroller.scrollTop
            + anchor.getBoundingClientRect().top
            - lock.anchorTop;
        }
      }

      const maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      desired = Math.max(0, Math.min(maxTop, desired));
      if (Math.abs(scroller.scrollTop - desired) > 0.5) {
        scroller.scrollTop = desired;
      }
    }

    viewportLockFrame = window.requestAnimationFrame(keepStable);
  };

  document.addEventListener('pointerdown', (event) => {
    const button = event.target.closest?.('button, [role="button"]');
    if (!button) {
      cancelLock();
      return;
    }

    const scroller = document.querySelector('[data-testid="stMain"]');
    if (!scroller) return;

    const candidate = button.closest('[class*="st-key-rv_mobile_"]');
    const isFixedNavigation = candidate?.classList.contains(
      'st-key-rv_mobile_bottom_bar'
    );

    if (isFixedNavigation) {
      const isCurrentTab = button.getAttribute('kind') === 'primary';
      if (isCurrentTab) {
        cancelLock();
        return;
      }

      const startedAt = performance.now();
      viewportLock = {
        scrollTop: 0,
        anchorClass: null,
        anchorTop: 0,
        resetToTop: true,
        fromScrollTop: scroller.scrollTop,
        startedAt,
        until: startedAt + 1400,
      };
      persistLock(1400);

      if (!viewportLockFrame) {
        viewportLockFrame = window.requestAnimationFrame(keepStable);
      }
      return;
    }

    const anchor = candidate && scroller.contains(candidate) && !isFixedNavigation
      ? candidate
      : null;
    const anchorClass = anchor
      ? [...anchor.classList].find((name) => name.startsWith('st-key-rv_mobile_'))
      : null;

    viewportLock = {
      scrollTop: scroller.scrollTop,
      anchorClass: anchorClass || null,
      anchorTop: anchor ? anchor.getBoundingClientRect().top : 0,
      until: performance.now() + 2400,
    };
    persistLock(2400);

    if (!viewportLockFrame) {
      viewportLockFrame = window.requestAnimationFrame(keepStable);
    }
  }, true);

  document.addEventListener('wheel', cancelLock, {
    passive: true,
    capture: true,
  });
  document.addEventListener('touchmove', cancelLock, {
    passive: true,
    capture: true,
  });
})(window.parent);
"""

    streamlit_js_eval(
        js_expressions=script_source,
        want_output=False,
        key="rv_mobile_viewport_stability",
    )


def restaurar_estabilidad_viewport_movil() -> None:
    """Reaplica el ancla después de que un fragmento termina de renderizar."""

    script_source = r"""
(() => {
  const host = window.parent;
  const storageKey = 'rv-mobile-viewport-lock';
  let lock;
  try {
    lock = JSON.parse(host.localStorage.getItem(storageKey) || 'null');
  } catch (_) {
    host.localStorage.removeItem(storageKey);
    return false;
  }
  if (!lock || Date.now() > Number(lock.expiresAt || 0)) {
    host.localStorage.removeItem(storageKey);
    return false;
  }
  const settle = () => {
    let current;
    try {
      current = JSON.parse(host.localStorage.getItem(storageKey) || 'null');
    } catch (_) {
      current = null;
    }
    if (!current || current.token !== lock.token) return;

    const scroller = host.document.querySelector('[data-testid="stMain"]');
    if (scroller) {
      let desired = Number(lock.scrollTop || 0);
      if (lock.resetToTop) {
        desired = 0;
      } else if (lock.anchorClass) {
        const anchor = host.document.querySelector(
          '.' + host.CSS.escape(lock.anchorClass)
        );
        if (anchor) {
          desired = scroller.scrollTop
            + anchor.getBoundingClientRect().top
            - Number(lock.anchorTop || 0);
        }
      }
      const maxTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
      scroller.scrollTop = Math.max(0, Math.min(maxTop, desired));
    }

    if (Date.now() <= Number(lock.expiresAt || 0)) {
      host.requestAnimationFrame(settle);
    } else {
      host.localStorage.removeItem(storageKey);
    }
  };

  host.requestAnimationFrame(() => host.requestAnimationFrame(settle));
  return true;
})()
"""
    streamlit_js_eval(
        js_expressions=f"{script_source}\n/* {time.time_ns()} */",
        want_output=False,
        key="rv_mobile_viewport_restore",
    )


def cambiar_pagina_catalogo(diferencia: int) -> None:
    st.session_state.pagina_catalogo = max(
        0,
        int(st.session_state.get("pagina_catalogo", 0)) + int(diferencia),
    )


def cambiar_tab_movil(destino: str) -> None:
    destino = str(destino)
    if str(st.session_state.get("mobile_tab")) != destino:
        st.session_state.mobile_panel_transition = (
            "to_cart" if destino == "Carrito" else "to_products"
        )
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
    st.info(
        "Todavía no hay clientes disponibles. Usa **＋ Nuevo cliente** para "
        "registrar el primero directamente en Odoo."
    )

# Una selección guardada puede dejar de existir después de actualizar Odoo.
# Se limpia antes de crear el selector para evitar claves inválidas y permitir
# que el alta rápida siga funcionando incluso con un catálogo inicialmente vacío.
cliente_guardado = st.session_state.get("cliente_id")
if cliente_guardado is not None:
    try:
        cliente_guardado = int(cliente_guardado)
    except (TypeError, ValueError):
        cliente_guardado = None
    if cliente_guardado not in clientes_por_id:
        st.session_state.cliente_id = None
        st.session_state.mobile_cliente_selector = None
        st.session_state.mobile_cliente_expandido = True

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
    st.session_state.mobile_cliente_selector = cliente_id
    st.session_state.mobile_cliente_expandido = not bool(cliente_id)
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


def render_resumen_cliente(cliente: dict[str, Any]) -> None:
    domicilio = ", ".join(
        str(cliente.get(campo) or "").strip()
        for campo in ("street", "city", "zip")
        if str(cliente.get(campo) or "").strip()
    )
    detalles = [
        valor
        for valor in (
            domicilio,
            str(cliente.get("email") or "").strip(),
            (
                f"RFC {cliente['vat']}"
                if str(cliente.get("vat") or "").strip()
                else ""
            ),
        )
        if valor
    ]
    texto = " · ".join(detalles) or "Cliente listo para continuar"
    st.markdown(
        f"""
        <div class="rv-client-selected">
            <span class="rv-client-selected-icon">✓</span>
            <div>
                <strong>{seguro(cliente.get('name') or 'Cliente seleccionado')}</strong>
                <p>{seguro(texto)}</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )



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

                with st.container(
                    border=True,
                    key=(
                        f"rv_mobile_cart_card_{linea_id}"
                        if prefijo == "mobile"
                        else None
                    ),
                ):
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
                        if prefijo == "mobile" and cantidad == 1:
                            st.button(
                                "🗑️",
                                help="Eliminar producto",
                                key=f"{prefijo}_remove_quick_{linea_id}",
                                use_container_width=True,
                                on_click=eliminar_linea,
                                args=(linea_id,),
                            )
                        else:
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

                with st.container(
                    border=True,
                    key=(
                        f"rv_mobile_cart_card_{grupo_id}"
                        if prefijo == "mobile"
                        else None
                    ),
                ):
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
    texto_lineas = f"{lineas} {'línea' if lineas == 1 else 'líneas'}"
    texto_unidades = f"{unidades} {'unidad' if unidades == 1 else 'unidades'}"
    st.caption(f"{texto_lineas} · {texto_unidades} · {gratis} gratis")

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


def render_metricas_compactas(
    metricas: list[tuple[str, str]],
    *,
    clase: str,
) -> None:
    tarjetas = "".join(
        (
            '<div class="rv-mini-metric">'
            f'<p class="rv-mini-metric-label">{seguro(etiqueta)}</p>'
            f'<p class="rv-mini-metric-value">{seguro(valor)}</p>'
            "</div>"
        )
        for etiqueta, valor in metricas
    )
    st.markdown(
        f'<div class="{clase}">{tarjetas}</div>',
        unsafe_allow_html=True,
    )


# =============================================================================
# DIÁLOGOS
# =============================================================================


@st.dialog("Nuevo cliente", width="large", on_dismiss="rerun")
def dialogo_nuevo_cliente() -> None:
    """Alta rápida de un contacto de venta directamente en Odoo."""

    version = int(st.session_state.nuevo_cliente_version)
    st.markdown(
        """
        <div class="rv-new-client-intro">
            <span class="rv-new-client-icon">＋</span>
            <div>
                <strong>Alta rápida en Odoo</strong>
                <p>Completa los datos esenciales. El cliente quedará seleccionado para continuar el pedido.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form(f"nuevo_cliente_form_{version}", clear_on_submit=False):
        nombre = st.text_input(
            "Nombre *",
            placeholder="Ej. Clínica Veterinaria San José",
            max_chars=160,
            key=f"nuevo_cliente_nombre_{version}",
        )
        correo = st.text_input(
            "Correo *",
            placeholder="cliente@dominio.com",
            max_chars=160,
            key=f"nuevo_cliente_correo_{version}",
        )
        direccion = st.text_area(
            "Dirección *",
            placeholder="Calle, número, colonia y municipio",
            max_chars=240,
            height=88,
            key=f"nuevo_cliente_direccion_{version}",
        )
        cp_col, rfc_col = st.columns(2, gap="small")
        with cp_col:
            codigo_postal = st.text_input(
                "Código postal *",
                placeholder="64000",
                max_chars=5,
                key=f"nuevo_cliente_cp_{version}",
            )
        with rfc_col:
            rfc = st.text_input(
                "RFC (opcional)",
                placeholder="XAXX010101000",
                max_chars=15,
                help="Se guardará en el campo RFC/ID fiscal de Odoo.",
                key=f"nuevo_cliente_rfc_{version}",
            )

        st.caption("* Campos obligatorios · Se verificará correo y RFC para evitar duplicados.")
        guardar = st.form_submit_button(
            "Guardar cliente en Odoo",
            type="primary",
            use_container_width=True,
            disabled=st.session_state.get("alta_cliente_en_progreso", False),
        )

    if not guardar:
        return

    st.session_state.alta_cliente_en_progreso = True
    try:
        with st.spinner("Validando y guardando cliente..."):
            resultado_cliente = alta_cliente_odoo(
                url=URL,
                db=DB,
                uid=uid,
                password=PASSWORD,
                nombre=nombre,
                correo=correo,
                direccion=direccion,
                codigo_postal=codigo_postal,
                rfc=rfc,
                timeout=ODOO_TIMEOUT_SEGUNDOS,
            )

        cliente_id = int(resultado_cliente["id"])
        recientes = [
            int(item)
            for item in st.session_state.clientes_recientes
            if int(item) != cliente_id
        ]
        st.session_state.clientes_recientes = [cliente_id, *recientes][:8]
        st.session_state.cliente_seleccion_pendiente = cliente_id
        st.session_state.nuevo_cliente_version = version + 1
        st.session_state.nuevo_cliente_pendiente = False
        cargar_datos_odoo.clear()

        accion = "creado" if resultado_cliente["creado"] else "encontrado"
        st.session_state.notificacion_pendiente = {
            "texto": (
                f"Cliente {accion} y seleccionado: "
                f"{resultado_cliente['name']}"
            ),
            "icono": "👤",
        }
        logger.info(
            "Cliente %s en Odoo (id=%s)",
            accion,
            cliente_id,
        )
        st.rerun()
    except ValidacionClienteError as error:
        st.error("Revisa los datos marcados antes de guardar.")
        st.markdown(
            "\n".join(f"- {seguro(mensaje)}" for mensaje in error.errores.values())
        )
    except ConflictoClienteError as error:
        st.error(str(error))
        st.caption(
            "Revisa el contacto en Odoo o usa los datos que ya están registrados."
        )
    except xmlrpc.client.Fault as error:
        logger.exception("Odoo rechazó el alta del cliente")
        st.error(
            "Odoo rechazó el cliente. Verifica que el correo o RFC no estén "
            "registrados con información diferente."
        )
        with st.expander("Ver detalle técnico"):
            st.code(error.faultString)
    except xmlrpc.client.ProtocolError as error:
        logger.exception("Error HTTP durante el alta del cliente")
        st.error(
            "No se recibió una respuesta válida de Odoo. Puedes reintentar: "
            "la app buscará el mismo correo/RFC antes de crear otro contacto."
        )
        st.caption(f"Código HTTP: {error.errcode}")
    except TimeoutError:
        logger.exception("Timeout durante el alta del cliente")
        st.error(
            "Odoo tardó más de 15 segundos. Puedes reintentar sin riesgo de "
            "duplicarlo: primero se buscará el correo y RFC ingresados."
        )
    except Exception as error:
        logger.exception("Error inesperado durante el alta del cliente")
        st.error("No fue posible guardar el cliente en este momento.")
        with st.expander("Ver detalle técnico"):
            st.code(str(error))
    finally:
        st.session_state.alta_cliente_en_progreso = False


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

    preset = st.pills(
        "Promoción",
        PROMOCIONES_RAPIDAS,
        default="1+1",
        required=True,
        width="stretch",
        key=f"promo_preset_{producto_id}",
    )
    preset = str(preset or "1+1")

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

    render_metricas_compactas(
        [
            ("Productos", str(len(elementos))),
            ("Unidades", str(unidades)),
            ("Total", moneda(total)),
        ],
        clase="rv-review-metrics",
    )

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
        f"{lineas} {'línea' if lineas == 1 else 'líneas'} · "
        f"{gratis} {'unidad' if gratis == 1 else 'unidades'} gratis · "
        "Odoo confirmará impuestos y total definitivo."
    )

    if ES_MOVIL:
        if st.button(
            "Confirmar y crear en Odoo",
            type="primary",
            use_container_width=True,
            key="mobile_confirmar_pedido_odoo",
        ):
            st.session_state.confirmar_envio = False
            st.session_state.enviar_pedido = True
            st.rerun()
        if st.button(
            "Seguir editando",
            use_container_width=True,
            key="mobile_seguir_editando",
        ):
            st.session_state.confirmar_envio = False
            st.rerun()
    else:
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

        render_metricas_compactas(
            [
                ("Líneas", str(resultado["lineas"])),
                ("Unidades", str(resultado["unidades"])),
                ("Impuestos", moneda(resultado.get("impuestos", 0.0))),
                ("Total final", moneda(resultado["total"])),
            ],
            clase="rv-result-metrics",
        )

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

    render_error_envio_pendiente()

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
                    <p class="rv-classic-kicker">Distribuidor veterinario</p>
                    <h1 class="rv-classic-title"><span>Rapy</span><strong>Vet</strong><em>Pedidos</em></h1>
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
                <span class="rv-classic-pill">Alta de clientes en campo</span>
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
                '<p class="rv-classic-section-copy">Busca por nombre o ciudad. Si no existe, créalo sin salir del pedido.</p>',
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
                render_resumen_cliente(cliente)

            st.divider()
            nuevo_col, actualizar_col = st.columns([1.45, 1], gap="small")
            with nuevo_col:
                st.button(
                    "＋ Nuevo cliente",
                    type="primary",
                    use_container_width=True,
                    key="desktop_classic_nuevo_cliente",
                    on_click=solicitar_nuevo_cliente,
                )
            with actualizar_col:
                if st.button(
                    "↻ Actualizar",
                    help="Actualizar clientes y productos desde Odoo",
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
                <div class="rv-brand" aria-label="RapyVet Distribuidor Veterinario">
                    <div class="rv-brand-monogram" aria-hidden="true">RV</div>
                    <div>
                        <p class="rv-brand-title"><span>Rapy</span><strong>Vet</strong></p>
                        <p class="rv-brand-copy">Distribuidor veterinario</p>
                    </div>
                </div>
                <div class="rv-mobile-status">
                    <span class="rv-pill"><span class="rv-online-dot"></span>Odoo</span>
                    <span class="rv-pill rv-cart-pill">{unidades} uds.</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        f"""
        <div class="rv-topbar">
            <div class="rv-brand" aria-label="RapyVet Distribuidor Veterinario">
                <div class="rv-brand-monogram" aria-hidden="true">RV</div>
                <div>
                    <p class="rv-brand-title"><span>Rapy</span><strong>Vet</strong></p>
                    <p class="rv-brand-copy">Distribuidor veterinario · Pedidos conectados con Odoo</p>
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


def render_progreso_movil() -> None:
    """Muestra la arquitectura del pedido como un flujo corto de tres pasos."""

    cliente_listo = st.session_state.get("cliente_id") is not None
    tab_actual = str(st.session_state.get("mobile_tab") or "Productos")
    clase_cliente = "is-done" if cliente_listo else "is-active"
    clase_productos = "is-active" if cliente_listo and tab_actual == "Productos" else ""
    clase_carrito = "is-active" if cliente_listo and tab_actual == "Carrito" else ""
    numero_cliente = "✓" if cliente_listo else "1"

    st.markdown(
        f"""
        <div class="rv-mobile-progress" aria-label="Progreso del pedido">
            <div class="rv-mobile-progress-step {clase_cliente}">
                <span>{numero_cliente}</span>Cliente
            </div>
            <div class="rv-mobile-progress-step {clase_productos}">
                <span>2</span>Productos
            </div>
            <div class="rv-mobile-progress-step {clase_carrito}">
                <span>3</span>Carrito
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_cliente() -> None:
    if ES_MOVIL:
        cliente_actual = st.session_state.get("cliente_id")
        cliente = (
            clientes_por_id.get(int(cliente_actual))
            if cliente_actual is not None
            else None
        )
        expandido = bool(st.session_state.get("mobile_cliente_expandido", True))

        with st.container(border=True, key="rv_mobile_client_card"):
            if cliente and not expandido:
                detalle_cliente = " · ".join(
                    valor
                    for valor in (
                        str(cliente.get("city") or "").strip(),
                        str(cliente.get("email") or "").strip(),
                    )
                    if valor
                ) or "Listo para continuar el pedido"
                st.markdown(
                    f"""
                    <div class="rv-mobile-client-compact">
                        <span class="rv-mobile-client-check">✓</span>
                        <div>
                            <strong>{seguro(cliente.get('name') or 'Cliente seleccionado')}</strong>
                            <p>{seguro(detalle_cliente)}</p>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                cambiar_col, nuevo_col = st.columns(2, gap="small")
                with cambiar_col:
                    st.button(
                        "Cambiar",
                        use_container_width=True,
                        key="mobile_cambiar_cliente",
                        on_click=editar_cliente_movil,
                    )
                with nuevo_col:
                    if st.button(
                        "＋ Nuevo",
                        type="primary",
                        use_container_width=True,
                        key="nuevo_cliente_mobile_compacto",
                    ):
                        solicitar_nuevo_cliente()
                        st.rerun(scope="app")
                return

            st.markdown(
                """
                <div class="rv-mobile-client-head">
                    <p class="rv-mobile-client-title">Cliente del pedido</p>
                    <span class="rv-mobile-client-step">Paso 01</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            selector_guardado = st.session_state.get("mobile_cliente_selector")
            if selector_guardado not in clientes_por_id:
                st.session_state.mobile_cliente_selector = (
                    int(cliente_actual) if cliente else None
                )

            st.selectbox(
                "Cliente del pedido",
                options=opciones_clientes(),
                index=None,
                placeholder="Buscar por nombre, ciudad, correo o RFC…",
                format_func=etiqueta_cliente,
                key="mobile_cliente_selector",
                label_visibility="collapsed",
                on_change=seleccionar_cliente_movil,
            )

            nuevo_col, actualizar_col = st.columns(2, gap="small")
            with nuevo_col:
                if st.button(
                    "＋ Nuevo cliente",
                    type="primary",
                    use_container_width=True,
                    key="nuevo_cliente_mobile",
                ):
                    solicitar_nuevo_cliente()
                    st.rerun(scope="app")
            with actualizar_col:
                if st.button(
                    "↻ Actualizar",
                    help="Actualizar clientes y productos",
                    use_container_width=True,
                    key="actualizar_odoo_mobile",
                ):
                    cargar_datos_odoo.clear()
                    st.rerun()
        return

    with st.container(border=True):
        cliente_col, nuevo_col, actualizar_col = st.columns([5, 1.6, 1])
        with cliente_col:
            st.selectbox(
                "Cliente del pedido",
                options=opciones_clientes(),
                index=None,
                placeholder="Buscar cliente por nombre o ciudad…",
                format_func=etiqueta_cliente,
                key="cliente_id",
            )
        with nuevo_col:
            st.markdown("<div style='height:.08rem'></div>", unsafe_allow_html=True)
            st.button(
                "＋ Nuevo cliente",
                type="primary",
                use_container_width=True,
                key="nuevo_cliente_desktop",
                on_click=solicitar_nuevo_cliente,
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


def render_encabezado_catalogo_movil() -> None:
    st.markdown(
        """
        <div class="rv-mobile-section-heading" id="rv-mobile-catalog-heading">
            <span class="rv-mobile-step-number">02</span>
            <div>
                <p class="rv-mobile-section-eyebrow">Catálogo RapyVet</p>
                <p class="rv-mobile-page-title">Encuentra el producto</p>
                <p class="rv-mobile-page-copy">Busca el medicamento por nombre o código y agrégalo sin perder tu lugar.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_catalogo(*, movil: bool, mostrar_encabezado: bool = True) -> None:
    if movil:
        if mostrar_encabezado:
            render_encabezado_catalogo_movil()
        catalog_context = st.container(key="rv_mobile_catalog_surface")
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
            if movil:
                st.markdown(
                    '<p class="rv-mobile-filter-label">Medicamento o producto</p>',
                    unsafe_allow_html=True,
                )
                with st.container(key="rv_mobile_search_controls"):
                    buscar_col, limpiar_col = st.columns([6, 1], gap="small")
                    with buscar_col:
                        busqueda_actual = st_keyup(
                            "Buscar producto",
                            placeholder="Nombre, producto o código…",
                            key=(
                                "busqueda_pos_input_"
                                f"{st.session_state.busqueda_widget_version}"
                            ),
                            debounce=320,
                            label_visibility="collapsed",
                        )
                        busqueda_actual = str(busqueda_actual or "")
                        if busqueda_actual != str(st.session_state.busqueda_pos or ""):
                            st.session_state.busqueda_pos = busqueda_actual
                            resetear_catalogo()
                    with limpiar_col:
                        st.button(
                            "✕",
                            help="Limpiar búsqueda",
                            use_container_width=True,
                            disabled=not bool(busqueda_actual.strip()),
                            key="mobile_limpiar_busqueda",
                            on_click=limpiar_busqueda_catalogo,
                        )
            else:
                st.text_input(
                    "Buscar producto",
                    placeholder="Buscar por nombre o código…",
                    key="busqueda_pos",
                    on_change=resetear_catalogo,
                )

            categorias = sorted(
                {categoria_producto(p) for p in productos_por_id.values()}
            )

            if movil:
                with st.container(key="rv_mobile_filter_controls"):
                    vista_col, categoria_col = st.columns(2, gap="small")
                    with vista_col:
                        st.segmented_control(
                            "Vista",
                            options=["Todos", "Recientes"],
                            format_func=(
                                lambda opcion: (
                                    "Últimos" if opcion == "Recientes" else opcion
                                )
                            ),
                            key="vista_pos",
                            on_change=resetear_catalogo,
                            label_visibility="collapsed",
                            width="stretch",
                            required=True,
                        )
                    with categoria_col:
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
        paginacion = calcular_paginacion(
            total_productos,
            int(st.session_state.pagina_catalogo),
            productos_por_pagina,
        )
        total_paginas = paginacion["total_paginas"]
        pagina_actual = paginacion["pagina"]
        st.session_state.pagina_catalogo = pagina_actual

        inicio = paginacion["inicio"]
        fin = paginacion["fin"]
        ids_visibles = ids_filtrados[inicio:fin]
        texto_resultados = (
            f"{inicio + 1}–{fin} de {total_productos}"
            if total_productos
            else "0 productos"
        )
        if movil:
            st.markdown(
                f"""
                <div class="rv-motion-result-meta" aria-live="polite">
                    <span>{texto_resultados}</span>
                    <span class="rv-motion-result-state">Listo para agregar</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
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
            producto_confirmado_id = st.session_state.get(
                "mobile_producto_confirmado_id"
            )
            for producto_id in ids_visibles:
                producto = productos_por_id[producto_id]
                codigo = str(producto.get("default_code") or "S/C")
                nombre = str(producto.get("name") or "Producto")
                precio_base = float(producto.get("list_price") or 0.0)
                detalle_precio = detalle_precio_producto(producto, precio_base)
                precio = float(detalle_precio["precio_final"])
                clase_impuesto = "" if detalle_precio["tiene_impuestos"] else "rv-tax-note-none"
                cantidad_en_carrito = cantidad_producto_en_carrito(
                    st.session_state.carrito,
                    producto_id,
                )
                indicador_carrito = (
                    f'<span class="rv-in-cart-chip">En carrito · {cantidad_en_carrito}</span>'
                    if cantidad_en_carrito
                    else (
                        '<span class="rv-in-cart-chip rv-in-cart-chip-placeholder" '
                        'aria-hidden="true">En carrito · 0</span>'
                    )
                )
                clase_confirmacion = (
                    "is-confirmed"
                    if producto_confirmado_id is not None
                    and int(producto_confirmado_id) == int(producto_id)
                    else ""
                )

                with st.container(
                    border=True,
                    key=f"rv_mobile_product_card_{producto_id}",
                ):
                    st.markdown(
                        f"""
                        <div class="rv-mobile-product-feedback {clase_confirmacion}">
                            <div class="rv-mobile-product-row">
                                <p class="rv-product-code">{seguro(codigo)}</p>
                                <p class="rv-product-name">{seguro(nombre)}</p>
                                <p class="rv-product-price">{moneda(precio)}</p>
                                <p class="rv-tax-note {clase_impuesto}">{seguro(detalle_precio['texto_impuestos'])}</p>
                            </div>
                            <div class="rv-mobile-cart-status">{indicador_carrito}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    agregar_col, promo_col = st.columns([3, 1.25], gap="small")
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
                        if st.button(
                            "Promo",
                            key=f"mobile_promo_{producto_id}",
                            help="Agregar promoción",
                            use_container_width=True,
                        ):
                            abrir_promocion(producto_id)
                            st.rerun(scope="app")
            st.session_state.mobile_producto_confirmado_id = None
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
            pagination_context = (
                st.container(key="rv_mobile_pagination")
                if movil
                else st.container()
            )
            with pagination_context:
                anterior_col, estado_col, siguiente_col = st.columns([1, 1.2, 1])
                with anterior_col:
                    if movil:
                        st.button(
                            "← Anterior",
                            help="Página anterior",
                            use_container_width=True,
                            disabled=pagina_actual == 0,
                            key="mobile_catalogo_anterior",
                            on_click=cambiar_pagina_catalogo,
                            args=(-1,),
                        )
                    elif st.button(
                        "←",
                        help="Página anterior",
                        use_container_width=True,
                        disabled=pagina_actual == 0,
                        key="desktop_catalogo_anterior",
                    ):
                        st.session_state.pagina_catalogo = pagina_actual - 1
                        st.rerun()
                with estado_col:
                    st.markdown(
                        f'<div class="rv-page-status">{pagina_actual + 1} de {total_paginas}</div>',
                        unsafe_allow_html=True,
                    )
                with siguiente_col:
                    if movil:
                        st.button(
                            "Siguiente →",
                            help="Página siguiente",
                            use_container_width=True,
                            disabled=pagina_actual >= total_paginas - 1,
                            key="mobile_catalogo_siguiente",
                            on_click=cambiar_pagina_catalogo,
                            args=(1,),
                        )
                    elif st.button(
                        "→",
                        help="Página siguiente",
                        use_container_width=True,
                        disabled=pagina_actual >= total_paginas - 1,
                        key="desktop_catalogo_siguiente",
                    ):
                        st.session_state.pagina_catalogo = pagina_actual + 1
                        st.rerun()


def render_catalogo_movil_fragmento() -> None:
    """Renderiza el catálogo dentro de la experiencia móvil fragmentada."""

    render_catalogo(movil=True, mostrar_encabezado=False)


def render_carrito_panel(*, movil: bool) -> None:
    if movil:
        elementos = elementos_carrito()
        st.markdown(
            """
            <div class="rv-mobile-section-heading">
                <span class="rv-mobile-step-number">03</span>
                <div>
                    <p class="rv-mobile-section-eyebrow">Pedido en revisión</p>
                    <p class="rv-mobile-page-title">Confirma tu pedido</p>
                    <p class="rv-mobile-page-copy">Revisa cantidades y total antes de enviarlo a Odoo.</p>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if elementos:
            with st.container(key="rv_mobile_cart_header"):
                resumen_col, opciones_col = st.columns([5, 1], gap="small")
                with resumen_col:
                    _, unidades, gratis, total = totales_carrito()
                    texto_productos = (
                        "1 producto"
                        if len(elementos) == 1
                        else f"{len(elementos)} productos"
                    )
                    texto_unidades = (
                        "1 unidad" if unidades == 1 else f"{unidades} unidades"
                    )
                    st.markdown(
                        f"**{texto_productos} · {texto_unidades}**  \n{gratis} gratis · {moneda(total)}",
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
    texto_unidades = f"{unidades} {'unidad' if unidades == 1 else 'unidades'}"

    with st.container(key="rv_mobile_bottom_bar"):
        if activo == "Carrito" and st.session_state.carrito:
            total_col, enviar_col = st.columns([1.05, 1.65], gap="small")
            with total_col:
                st.markdown(
                    f"""
                    <div class="rv-mobile-bottom-summary">
                        <div>
                            <p class="rv-mobile-bottom-copy">{texto_unidades}</p>
                            <p class="rv-mobile-bottom-total">{moneda(total)}</p>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with enviar_col:
                if st.button(
                    "Crear pedido" if st.session_state.cliente_id else "Elige un cliente",
                    help=(
                        "Revisar y crear el pedido en Odoo"
                        if st.session_state.cliente_id
                        else "Selecciona un cliente en la parte superior"
                    ),
                    type="primary",
                    use_container_width=True,
                    disabled=(
                        not listo
                        or st.session_state.get("envio_en_progreso", False)
                    ),
                    key="mobile_bottom_checkout",
                ):
                    # Este código se ejecuta en el cuerpo del fragmento, no en
                    # un callback. Así el rerun completo sí abre la confirmación
                    # y continúa hasta crear el pedido y preparar WhatsApp.
                    solicitar_envio()
                    st.rerun(scope="app")
        else:
            st.markdown(
                f"""
                    <div class="rv-mobile-bottom-summary">
                    <p class="rv-mobile-bottom-copy">{texto_unidades} en el carrito</p>
                    <p class="rv-mobile-bottom-total">{moneda(total)}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

        productos_col, carrito_col = st.columns(2, gap="small")
        with productos_col:
            st.button(
                "Productos",
                type="primary" if activo == "Productos" else "secondary",
                use_container_width=True,
                key="mobile_nav_productos",
                on_click=cambiar_tab_movil,
                args=("Productos",),
            )
        with carrito_col:
            st.button(
                f"Carrito · {len(elementos)}",
                type="primary" if activo == "Carrito" else "secondary",
                use_container_width=True,
                key="mobile_nav_carrito",
                on_click=cambiar_tab_movil,
                args=("Carrito",),
            )


@st.fragment
def render_experiencia_movil_fragmento() -> None:
    """Actualiza la interfaz móvil sin reconstruir toda la aplicación."""

    if st.session_state.notificacion_pendiente:
        aviso = st.session_state.notificacion_pendiente
        st.toast(aviso["texto"], icon=aviso.get("icono", "✅"))
        st.session_state.notificacion_pendiente = None

    render_encabezado()
    render_error_envio_pendiente()
    render_progreso_movil()
    render_cliente()
    panel_transition = str(
        st.session_state.get("mobile_panel_transition") or "steady"
    )
    with st.container(key=f"rv_mobile_panel_motion_{panel_transition}"):
        if st.session_state.mobile_tab == "Carrito":
            render_carrito_panel(movil=True)
        else:
            render_encabezado_catalogo_movil()
            render_catalogo_movil_fragmento()
    st.session_state.mobile_panel_transition = ""
    render_navegacion_movil()
    restaurar_estabilidad_viewport_movil()
    guardar_borrador_en_navegador("rv_borrador_local_mobile_fragment_v1")


if ES_MOVIL:
    # Catálogo, carrito y navegación forman una sola superficie reactiva.
    # Agregar un producto ya no reconstruye la página ni altera el scroll.
    habilitar_estabilidad_viewport_movil()
    render_experiencia_movil_fragmento()
else:
    # En escritorio se usa una interfaz totalmente distinta, basada en el
    # diseño clásico proporcionado por el usuario. No se renderiza el catálogo
    # interfaz móvil ni la barra inferior.
    render_desktop_clasico()


# Abre el alta de cliente una sola vez. Consumir la solicitud antes de mostrar
# el diálogo evita que vuelva a aparecer tras cerrarlo.
nuevo_cliente_pendiente = st.session_state.get("nuevo_cliente_pendiente", False)
if nuevo_cliente_pendiente:
    st.session_state.nuevo_cliente_pendiente = False
    dialogo_nuevo_cliente()


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
    error_requiere_rerun = False

    if not st.session_state.cliente_id or not st.session_state.carrito:
        guardar_error_envio(
            "Selecciona un cliente y agrega productos antes de enviar.",
            str(st.session_state.get("pedido_token") or ""),
        )
        error_requiere_rerun = True
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
                st.session_state.error_envio_pedido = None
                st.session_state.mostrar_balloons = True
                st.session_state.borrador_local_eliminar = True
                st.rerun()

            except ValueError as error:
                logger.warning("Pedido %s inválido: %s", pedido_token, error)
                guardar_error_envio(str(error), pedido_token)
                error_requiere_rerun = True
            except xmlrpc.client.Fault as error:
                logger.exception("Odoo rechazó el pedido %s", pedido_token)
                guardar_error_envio(
                    "Odoo rechazó uno de los datos del pedido. Revisa el "
                    "cliente y los productos antes de reintentar.",
                    pedido_token,
                    detalle_fallo_odoo(error),
                )
                error_requiere_rerun = True
            except xmlrpc.client.ProtocolError as error:
                logger.exception("Error HTTP al enviar %s", pedido_token)
                guardar_error_envio(
                    "Odoo no devolvió una respuesta válida. Puedes reintentar "
                    "el mismo pedido sin riesgo de duplicarlo.",
                    pedido_token,
                    f"HTTP {error.errcode}",
                )
                error_requiere_rerun = True
            except TimeoutError:
                logger.exception("Timeout al enviar %s", pedido_token)
                guardar_error_envio(
                    "Odoo tardó demasiado y no fue posible confirmar la "
                    "respuesta. Reintenta el mismo pedido; la app verificará "
                    "primero que no exista.",
                    pedido_token,
                )
                error_requiere_rerun = True
            except OSError as error:
                logger.exception("Conexión interrumpida al enviar %s", pedido_token)
                guardar_error_envio(
                    "La conexión con Odoo se interrumpió. Reintenta el mismo "
                    "pedido; la referencia evita que se duplique.",
                    pedido_token,
                    detalle_fallo_odoo(error),
                )
                error_requiere_rerun = True
            except Exception as error:
                logger.exception("Error inesperado al enviar %s", pedido_token)
                guardar_error_envio(
                    "No se pudo completar el pedido. Conservamos la referencia "
                    "para que soporte pueda revisarlo sin duplicar la orden.",
                    pedido_token,
                    detalle_fallo_odoo(error),
                )
                error_requiere_rerun = True
            finally:
                st.session_state.envio_en_progreso = False

    if error_requiere_rerun:
        st.rerun()


# Segunda escritura del ciclo. Captura cambios realizados durante el render,
# por ejemplo cantidades, precios o notas editadas en widgets.
guardar_borrador_en_navegador("rv_borrador_local_guardado_post_v1")
