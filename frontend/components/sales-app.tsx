"use client";

import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Check,
  ChevronRight,
  CircleAlert,
  CirclePlus,
  ClipboardCheck,
  Home,
  LoaderCircle,
  LogOut,
  Minus,
  PackageSearch,
  Plus,
  RefreshCw,
  Search,
  ShoppingBag,
  Sparkles,
  Trash2,
  UserRound,
  UserRoundPlus,
  WifiOff,
  X,
} from "lucide-react";
import { AnimatePresence, MotionConfig, motion, useReducedMotion } from "motion/react";
import {
  FormEvent,
  useDeferredValue,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { ServiceWorker } from "@/components/service-worker";
import {
  ApiError,
  clearSession,
  createClient,
  createOrder,
  getCatalog,
  hasSession,
  login,
} from "@/lib/api";
import type { CartLine, Catalog, Client, Draft, OrderResult, Product } from "@/lib/types";

type Screen = "home" | "clients" | "products" | "cart" | "review" | "success";

const DRAFT_KEY = "rapyvet_order_draft_v2";
const CATALOG_KEY = "rapyvet_catalog_v2";
const VISIBLE_STEP = 30;

const pageMotion = {
  initial: { opacity: 0, x: 12 },
  animate: { opacity: 1, x: 0 },
  exit: { opacity: 0, x: -8 },
};

function money(value: number) {
  return new Intl.NumberFormat("es-MX", {
    style: "currency",
    currency: "MXN",
    minimumFractionDigits: 2,
  }).format(value);
}

function normalize(value: string) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("es-MX")
    .trim();
}

function uniqueId() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function freshOrderKey() {
  return `RV-${uniqueId()}`.slice(0, 39);
}

function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand" aria-label="RapyVet Distribuidor Veterinario">
      <span className="brand-mark">RV</span>
      {!compact && (
        <span className="brand-copy">
          <strong>RapyVet</strong>
          <small>Distribuidor veterinario</small>
        </span>
      )}
    </div>
  );
}

function LoadingScreen({ label = "Preparando tu espacio de ventas" }: { label?: string }) {
  return (
    <div className="center-state" role="status">
      <motion.div
        className="loading-orbit"
        animate={{ rotate: 360 }}
        transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
      >
        <span />
      </motion.div>
      <p>{label}</p>
      <small>Conectando de forma segura con Odoo</small>
    </div>
  );
}

function EmptyState({ icon: Icon, title, body }: { icon: typeof Search; title: string; body: string }) {
  return (
    <motion.div className="empty-state" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
      <Icon size={28} />
      <strong>{title}</strong>
      <span>{body}</span>
    </motion.div>
  );
}

function LoginScreen({ onReady }: { onReady: () => void }) {
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await login(pin);
      onReady();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible ingresar.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <motion.section
        className="login-card"
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 260, damping: 26 }}
      >
        <Logo />
        <div className="login-intro">
          <span className="eyebrow">Ventas en campo</span>
          <h1>Tu ruta de pedidos, más rápida.</h1>
          <p>Consulta clientes, arma el carrito y registra el pedido directamente en Odoo.</p>
        </div>
        <form onSubmit={submit} className="stack-form">
          <label htmlFor="access-pin">Código de acceso</label>
          <input
            id="access-pin"
            type="password"
            inputMode="numeric"
            autoComplete="current-password"
            value={pin}
            onChange={(event) => setPin(event.target.value)}
            placeholder="••••••"
            minLength={4}
            required
          />
          <AnimatePresence initial={false}>
            {error && (
              <motion.p
                className="form-error"
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
              >
                <CircleAlert size={16} /> {error}
              </motion.p>
            )}
          </AnimatePresence>
          <button className="button primary wide" disabled={busy}>
            {busy ? <LoaderCircle className="spin" /> : <ArrowRight />}
            {busy ? "Ingresando…" : "Entrar a pedidos"}
          </button>
        </form>
        <p className="secure-note"><BadgeCheck size={16} /> Conexión protegida · Tus claves de Odoo no se guardan aquí</p>
      </motion.section>
    </main>
  );
}

function TopBar({
  customer,
  onCustomer,
  onLogout,
}: {
  customer?: Client;
  onCustomer: () => void;
  onLogout: () => void;
}) {
  return (
    <header className="topbar">
      <Logo />
      <div className="topbar-actions">
        <button type="button" className="customer-chip" onClick={onCustomer}>
          <UserRound size={17} />
          <span>{customer?.name || "Elegir cliente"}</span>
          <ChevronRight size={16} />
        </button>
        <button type="button" className="icon-button" onClick={onLogout} aria-label="Cerrar sesión">
          <LogOut size={19} />
        </button>
      </div>
    </header>
  );
}

function HomeScreen({
  customer,
  cart,
  onStart,
  onProducts,
  onCart,
}: {
  customer?: Client;
  cart: CartLine[];
  onStart: () => void;
  onProducts: () => void;
  onCart: () => void;
}) {
  const units = cart.reduce((sum, line) => sum + line.quantity, 0);
  const total = cart.reduce((sum, line) => sum + line.quantity * line.unitPrice, 0);
  return (
    <div className="screen home-screen">
      <section className="hero-panel">
        <div>
          <span className="eyebrow">RapyVet · Ventas</span>
          <h1>Pedidos sin pausas, estés donde estés.</h1>
          <p>Un flujo claro para dedicar menos tiempo a capturar y más tiempo a vender.</p>
        </div>
        <motion.button
          type="button"
          className="button primary hero-action"
          onClick={customer ? onProducts : onStart}
          whileTap={{ scale: 0.98 }}
        >
          {customer ? <PackageSearch /> : <UserRoundPlus />}
          {customer ? "Continuar pedido" : "Comenzar pedido"}
        </motion.button>
      </section>

      <section className="home-grid">
        <button type="button" className="summary-card" onClick={onStart}>
          <span className="summary-icon"><UserRound /></span>
          <small>Cliente</small>
          <strong>{customer?.name || "Sin seleccionar"}</strong>
          <span className="text-link">{customer ? "Cambiar" : "Seleccionar"} <ChevronRight size={15} /></span>
        </button>
        <button type="button" className="summary-card" onClick={cart.length ? onCart : onProducts}>
          <span className="summary-icon"><ShoppingBag /></span>
          <small>Pedido actual</small>
          <strong>{units ? `${units} unidades` : "Carrito vacío"}</strong>
          <span className="text-link">{cart.length ? money(total) : "Agregar productos"} <ChevronRight size={15} /></span>
        </button>
      </section>

      <section className="flow-card">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Flujo guiado</span>
            <h2>Todo en tres pasos</h2>
          </div>
        </div>
        <ol className="flow-steps">
          <li className={customer ? "done" : "active"}><span>{customer ? <Check /> : "1"}</span><div><strong>Cliente</strong><small>Selecciona o crea uno nuevo</small></div></li>
          <li className={cart.length ? "done" : customer ? "active" : ""}><span>{cart.length ? <Check /> : "2"}</span><div><strong>Productos</strong><small>Agrega venta normal o promoción</small></div></li>
          <li className={cart.length ? "active" : ""}><span>3</span><div><strong>Confirmación</strong><small>Revisa y envía a Odoo</small></div></li>
        </ol>
      </section>
    </div>
  );
}

function ClientScreen({
  clients,
  selectedId,
  onSelect,
  onNew,
}: {
  clients: Client[];
  selectedId: number | null;
  onSelect: (client: Client) => void;
  onNew: () => void;
}) {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const filtered = useMemo(() => {
    const needle = normalize(deferredQuery);
    if (!needle) return clients;
    return clients.filter((client) =>
      normalize(`${client.name} ${client.email} ${client.phone} ${client.vat}`).includes(needle),
    );
  }, [clients, deferredQuery]);

  return (
    <div className="screen list-screen">
      <div className="screen-title-row">
        <div><span className="eyebrow">Paso 1 de 3</span><h1>Selecciona al cliente</h1><p>{clients.length} contactos disponibles en Odoo</p></div>
        <button type="button" className="button secondary" onClick={onNew}><UserRoundPlus /> Nuevo cliente</button>
      </div>
      <div className="sticky-tools">
        <label className="search-field">
          <Search size={20} />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Nombre, correo, teléfono o RFC"
            autoComplete="off"
          />
          {query && <button type="button" onClick={() => setQuery("")} aria-label="Limpiar búsqueda"><X size={18} /></button>}
        </label>
      </div>
      <motion.div className="client-list" layout>
        <AnimatePresence initial={false} mode="popLayout">
          {filtered.slice(0, 100).map((client) => (
            <motion.button
              layout="position"
              type="button"
              className={`client-row ${selectedId === client.id ? "selected" : ""}`}
              key={client.id}
              onClick={() => onSelect(client)}
              initial={{ opacity: 0, scale: 0.99 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.99 }}
              transition={{ duration: 0.16 }}
            >
              <span className="client-avatar">{client.name.slice(0, 2).toUpperCase()}</span>
              <span className="client-copy"><strong>{client.name}</strong><small>{[client.city, client.email].filter(Boolean).join(" · ") || "Sin datos adicionales"}</small></span>
              {selectedId === client.id ? <span className="selected-check"><Check /></span> : <ChevronRight />}
            </motion.button>
          ))}
        </AnimatePresence>
        {!filtered.length && <EmptyState icon={UserRound} title="No encontramos clientes" body="Prueba otra búsqueda o crea un cliente nuevo." />}
      </motion.div>
    </div>
  );
}

function ProductScreen({
  products,
  cart,
  onAdd,
  onPromo,
}: {
  products: Product[];
  cart: CartLine[];
  onAdd: (product: Product) => void;
  onPromo: (product: Product) => void;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("Todos");
  const [visible, setVisible] = useState(VISIBLE_STEP);
  const deferredQuery = useDeferredValue(query);
  const inputRef = useRef<HTMLInputElement>(null);
  const categories = useMemo(
    () => ["Todos", ...Array.from(new Set(products.map((item) => item.category))).sort()],
    [products],
  );
  const quantities = useMemo(() => {
    const result = new Map<number, number>();
    for (const line of cart) result.set(line.productId, (result.get(line.productId) || 0) + line.quantity);
    return result;
  }, [cart]);
  const filtered = useMemo(() => {
    const needle = normalize(deferredQuery);
    return products.filter((product) => {
      const inCategory = category === "Todos" || product.category === category;
      return inCategory && (!needle || normalize(`${product.code} ${product.name}`).includes(needle));
    });
  }, [products, deferredQuery, category]);

  useEffect(() => setVisible(VISIBLE_STEP), [deferredQuery, category]);

  return (
    <div className="screen product-screen">
      <div className="screen-title-row">
        <div><span className="eyebrow">Paso 2 de 3</span><h1>Arma el pedido</h1><p>Busca por nombre o código y agrega sin perder tu posición.</p></div>
      </div>
      <div className="sticky-tools catalog-tools">
        <label className={`search-field ${deferredQuery !== query ? "searching" : ""}`}>
          {deferredQuery !== query ? <LoaderCircle className="spin" size={20} /> : <Search size={20} />}
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            placeholder="Buscar medicamento o código"
            autoComplete="off"
            enterKeyHint="search"
          />
          {query && <button type="button" onClick={() => { setQuery(""); inputRef.current?.focus(); }} aria-label="Limpiar búsqueda"><X size={18} /></button>}
        </label>
        <div className="category-strip" aria-label="Categorías">
          {categories.map((item) => (
            <button type="button" key={item} className={category === item ? "active" : ""} onClick={() => setCategory(item)}>{item}</button>
          ))}
        </div>
      </div>
      <div className="catalog-results">
        <div className="result-meta"><span>{filtered.length} productos</span>{deferredQuery && <span>Resultados para “{deferredQuery}”</span>}</div>
        <motion.div className="product-grid" layout>
          <AnimatePresence initial={false} mode="popLayout">
            {filtered.slice(0, visible).map((product) => (
              <motion.article
                layout="position"
                className="product-card"
                key={product.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.16 }}
              >
                <div className="product-card-top">
                  <span className="product-code">{product.code}</span>
                  {quantities.has(product.id) && <motion.span className="quantity-badge" initial={{ scale: 0.7 }} animate={{ scale: 1 }}>{quantities.get(product.id)} en carrito</motion.span>}
                </div>
                <h2>{product.name}</h2>
                <p>{product.category}</p>
                <div className="product-price"><strong>{money(product.price)}</strong><small>Precio de lista</small></div>
                <div className="product-actions">
                  <motion.button type="button" className="button primary" onClick={() => onAdd(product)} whileTap={{ scale: 0.96 }}><Plus /> Agregar</motion.button>
                  <motion.button type="button" className="icon-button promo" onClick={() => onPromo(product)} whileTap={{ scale: 0.94 }} aria-label={`Agregar promoción de ${product.name}`}><Sparkles /></motion.button>
                </div>
              </motion.article>
            ))}
          </AnimatePresence>
        </motion.div>
        {!filtered.length && <EmptyState icon={PackageSearch} title="No encontramos productos" body="Revisa el nombre, el código o cambia la categoría." />}
        {visible < filtered.length && <button type="button" className="button secondary load-more" onClick={() => setVisible((count) => count + VISIBLE_STEP)}>Mostrar más productos</button>}
      </div>
    </div>
  );
}

function CartScreen({
  cart,
  onChange,
  onRemove,
  onProducts,
  onReview,
}: {
  cart: CartLine[];
  onChange: (id: string, patch: Partial<CartLine>) => void;
  onRemove: (id: string) => void;
  onProducts: () => void;
  onReview: () => void;
}) {
  const total = cart.reduce((sum, line) => sum + line.quantity * line.unitPrice, 0);
  return (
    <div className="screen cart-screen">
      <div className="screen-title-row"><div><span className="eyebrow">Tu selección</span><h1>Carrito</h1><p>Confirma cantidades y precios antes de continuar.</p></div><button type="button" className="button secondary" onClick={onProducts}><Plus /> Agregar más</button></div>
      {!cart.length ? (
        <EmptyState icon={ShoppingBag} title="Tu carrito está vacío" body="Agrega productos del catálogo para comenzar." />
      ) : (
        <>
          <motion.div className="cart-list" layout>
            <AnimatePresence initial={false} mode="popLayout">
              {cart.map((line) => (
                <motion.article
                  layout
                  className={`cart-line ${line.free ? "free" : ""}`}
                  key={line.id}
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: "auto" }}
                  exit={{ opacity: 0, height: 0 }}
                >
                  <div className="cart-line-head"><span className="product-code">{line.code}</span>{line.free && <span className="free-badge"><Sparkles size={13} /> Gratis</span>}<button type="button" onClick={() => onRemove(line.id)} aria-label={`Eliminar ${line.name}`}><Trash2 size={18} /></button></div>
                  <h2>{line.name}</h2>
                  <div className="cart-controls">
                    <div className="stepper" aria-label={`Cantidad de ${line.name}`}>
                      <button type="button" onClick={() => line.quantity === 1 ? onRemove(line.id) : onChange(line.id, { quantity: line.quantity - 1 })}><Minus /></button>
                      <strong>{line.quantity}</strong>
                      <button type="button" onClick={() => onChange(line.id, { quantity: line.quantity + 1 })}><Plus /></button>
                    </div>
                    <label className="price-input"><span>Precio unitario</span><div><small>$</small><input type="number" min="0" step="0.01" value={line.unitPrice} disabled={line.free} onChange={(event) => onChange(line.id, { unitPrice: Math.max(0, Number(event.target.value)) })} /></div></label>
                    <div className="line-total"><span>Importe</span><strong>{money(line.quantity * line.unitPrice)}</strong></div>
                  </div>
                </motion.article>
              ))}
            </AnimatePresence>
          </motion.div>
          <section className="total-card"><div><span>Subtotal estimado</span><small>Odoo calculará impuestos y total final.</small></div><strong>{money(total)}</strong></section>
          <button type="button" className="button primary wide checkout-button" onClick={onReview}><ClipboardCheck /> Revisar pedido <ArrowRight /></button>
        </>
      )}
    </div>
  );
}

function ReviewScreen({
  customer,
  cart,
  note,
  busy,
  error,
  onNote,
  onBack,
  onSubmit,
}: {
  customer: Client;
  cart: CartLine[];
  note: string;
  busy: boolean;
  error: string;
  onNote: (value: string) => void;
  onBack: () => void;
  onSubmit: () => void;
}) {
  const estimated = cart.reduce((sum, line) => sum + line.quantity * line.unitPrice, 0);
  return (
    <div className="screen review-screen">
      <button type="button" className="back-link" onClick={onBack}><ArrowLeft /> Volver al carrito</button>
      <div className="screen-title-row"><div><span className="eyebrow">Paso 3 de 3</span><h1>Revisa el pedido</h1><p>El pedido se conservará si la conexión tarda o se interrumpe.</p></div></div>
      <div className="review-grid">
        <section className="review-card"><span className="review-icon"><UserRound /></span><div><small>Cliente</small><h2>{customer.name}</h2><p>{[customer.street, customer.city, customer.email].filter(Boolean).join(" · ")}</p></div></section>
        <section className="review-card products-review"><span className="review-icon"><ShoppingBag /></span><div className="review-body"><small>Productos</small><h2>{cart.reduce((sum, line) => sum + line.quantity, 0)} unidades</h2><ul>{cart.map((line) => <li key={line.id}><span>{line.quantity} × {line.name}{line.free ? " · Gratis" : ""}</span><strong>{money(line.quantity * line.unitPrice)}</strong></li>)}</ul></div></section>
      </div>
      <label className="note-field"><span>Notas para el pedido <small>Opcional</small></span><textarea value={note} onChange={(event) => onNote(event.target.value)} maxLength={2000} placeholder="Horario de entrega, referencias u observaciones…" /></label>
      <section className="order-total"><div><span>Total estimado</span><small>El total definitivo se confirma en Odoo.</small></div><strong>{money(estimated)}</strong></section>
      <AnimatePresence initial={false}>{error && <motion.p className="submit-error" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}><CircleAlert /> {error}</motion.p>}</AnimatePresence>
      <button type="button" className="button primary wide submit-order" disabled={busy} onClick={onSubmit}>{busy ? <LoaderCircle className="spin" /> : <BadgeCheck />}{busy ? "Enviando a Odoo…" : "Crear pedido en Odoo"}</button>
      <p className="idempotency-note">Puedes reintentar con seguridad: esta captura tiene una referencia única que evita pedidos duplicados.</p>
    </div>
  );
}

function SuccessScreen({ result, onNew }: { result: OrderResult; onNew: () => void }) {
  return (
    <div className="screen success-screen">
      <motion.div className="success-symbol" initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 220, damping: 18 }}><Check /></motion.div>
      <span className="eyebrow">Pedido registrado</span>
      <h1>{result.folio}</h1>
      <p>{result.status}. Odoo confirmó la operación correctamente.</p>
      <section className="success-total"><span>Total en Odoo</span><strong>{money(result.total)}</strong><small>Subtotal {money(result.subtotal)} · Impuestos {money(result.tax)}</small></section>
      <div className="success-actions">
        <a className="button whatsapp wide" href={result.whatsapp_url} target="_blank" rel="noreferrer">Compartir por WhatsApp <ArrowRight /></a>
        <button type="button" className="button secondary wide" onClick={onNew}><CirclePlus /> Capturar otro pedido</button>
      </div>
    </div>
  );
}

function BottomNav({ screen, cartCount, hasCustomer, navigate }: { screen: Screen; cartCount: number; hasCustomer: boolean; navigate: (screen: Screen) => void }) {
  const items = [
    { screen: "home" as const, label: "Inicio", icon: Home },
    { screen: hasCustomer ? "products" as const : "clients" as const, label: "Productos", icon: PackageSearch },
    { screen: "cart" as const, label: "Carrito", icon: ShoppingBag },
  ];
  return (
    <nav className="bottom-nav" aria-label="Navegación principal">
      {items.map((item) => {
        const active = screen === item.screen || (item.label === "Productos" && screen === "clients");
        return <button type="button" key={item.label} className={active ? "active" : ""} onClick={() => navigate(item.screen)}><span><item.icon />{item.label === "Carrito" && cartCount > 0 && <b>{cartCount}</b>}</span><small>{item.label}</small></button>;
      })}
    </nav>
  );
}

function NewClientDialog({ open, busy, error, onClose, onSubmit }: { open: boolean; busy: boolean; error: string; onClose: () => void; onSubmit: (data: { name: string; email: string; street: string; postal_code: string; vat: string }) => void }) {
  const [form, setForm] = useState({ name: "", email: "", street: "", postal_code: "", vat: "" });
  useEffect(() => { if (!open) setForm({ name: "", email: "", street: "", postal_code: "", vat: "" }); }, [open]);
  return (
    <AnimatePresence>
      {open && <motion.div className="dialog-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
        <motion.section role="dialog" aria-modal="true" aria-labelledby="new-client-title" className="dialog-sheet" initial={{ opacity: 0, y: 32 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 32 }} transition={{ type: "spring", stiffness: 300, damping: 30 }}>
          <div className="dialog-head"><div><span className="eyebrow">Alta en Odoo</span><h2 id="new-client-title">Nuevo cliente</h2></div><button type="button" className="icon-button" onClick={onClose} disabled={busy} aria-label="Cerrar"><X /></button></div>
          <form className="dialog-form" onSubmit={(event) => { event.preventDefault(); onSubmit(form); }}>
            <label><span>Nombre completo</span><input required minLength={3} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} autoComplete="name" /></label>
            <label><span>Correo</span><input required type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} autoComplete="email" /></label>
            <label><span>Dirección</span><input required minLength={5} value={form.street} onChange={(event) => setForm({ ...form, street: event.target.value })} autoComplete="street-address" /></label>
            <div className="form-columns"><label><span>Código postal</span><input required inputMode="numeric" pattern="[0-9]{5}" maxLength={5} value={form.postal_code} onChange={(event) => setForm({ ...form, postal_code: event.target.value.replace(/\D/g, "").slice(0, 5) })} autoComplete="postal-code" /></label><label><span>RFC <small>Opcional</small></span><input maxLength={13} value={form.vat} onChange={(event) => setForm({ ...form, vat: event.target.value.toUpperCase().replace(/[\s-]/g, "") })} /></label></div>
            {error && <p className="form-error"><CircleAlert size={16} /> {error}</p>}
            <button className="button primary wide" disabled={busy}>{busy ? <LoaderCircle className="spin" /> : <UserRoundPlus />}{busy ? "Guardando en Odoo…" : "Crear y seleccionar cliente"}</button>
          </form>
        </motion.section>
      </motion.div>}
    </AnimatePresence>
  );
}

function PromoDialog({ product, onClose, onAdd }: { product: Product | null; onClose: () => void; onAdd: (paid: number, free: number) => void }) {
  const [paid, setPaid] = useState(1);
  const [free, setFree] = useState(1);
  useEffect(() => { setPaid(1); setFree(1); }, [product]);
  const presets = [[1, 1], [2, 1], [2, 2], [4, 1], [10, 2], [11, 1]];
  return (
    <AnimatePresence>
      {product && <motion.div className="dialog-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
        <motion.section role="dialog" aria-modal="true" aria-labelledby="promo-title" className="dialog-sheet compact-dialog" initial={{ opacity: 0, y: 32 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 32 }} transition={{ type: "spring", stiffness: 300, damping: 30 }}>
          <div className="dialog-head"><div><span className="eyebrow">Promoción</span><h2 id="promo-title">{product.name}</h2></div><button type="button" className="icon-button" onClick={onClose} aria-label="Cerrar"><X /></button></div>
          <div className="preset-grid">{presets.map(([sale, gift]) => <button type="button" key={`${sale}-${gift}`} className={paid === sale && free === gift ? "active" : ""} onClick={() => { setPaid(sale); setFree(gift); }}>{sale}+{gift}</button>)}</div>
          <div className="promo-quantities"><label><span>Unidades con precio</span><input type="number" min="1" max="999" value={paid} onChange={(event) => setPaid(Math.max(1, Number(event.target.value)))} /></label><label><span>Unidades gratis</span><input type="number" min="1" max="999" value={free} onChange={(event) => setFree(Math.max(1, Number(event.target.value)))} /></label></div>
          <div className="promo-summary"><span>{paid} × {money(product.price)}</span><strong>+ {free} gratis</strong></div>
          <button type="button" className="button primary wide" onClick={() => onAdd(paid, free)}><Sparkles /> Agregar promoción</button>
        </motion.section>
      </motion.div>}
    </AnimatePresence>
  );
}

export function SalesApp() {
  const reduceMotion = useReducedMotion();
  const [hydrated, setHydrated] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [offline, setOffline] = useState(false);
  const [screen, setScreen] = useState<Screen>("home");
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [cart, setCart] = useState<CartLine[]>([]);
  const [note, setNote] = useState("");
  const [idempotencyKey, setIdempotencyKey] = useState(freshOrderKey);
  const [toast, setToast] = useState("");
  const [newClientOpen, setNewClientOpen] = useState(false);
  const [clientBusy, setClientBusy] = useState(false);
  const [clientError, setClientError] = useState("");
  const [promoProduct, setPromoProduct] = useState<Product | null>(null);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [orderResult, setOrderResult] = useState<OrderResult | null>(null);
  const mainRef = useRef<HTMLElement>(null);

  useEffect(() => {
    setAuthenticated(hasSession());
    try {
      const cached = localStorage.getItem(CATALOG_KEY);
      if (cached) setCatalog(JSON.parse(cached) as Catalog);
      const saved = localStorage.getItem(DRAFT_KEY);
      if (saved) {
        const draft = JSON.parse(saved) as Draft;
        if (Date.now() - draft.savedAt < 24 * 60 * 60 * 1000) {
          setCustomerId(draft.customerId);
          setCart(draft.cart || []);
          setNote(draft.note || "");
          setIdempotencyKey(draft.idempotencyKey || freshOrderKey());
        }
      }
    } catch {
      localStorage.removeItem(DRAFT_KEY);
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated || !authenticated) return;
    void loadCatalog(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, authenticated]);

  useEffect(() => {
    if (!hydrated) return;
    const draft: Draft = { customerId, cart, note, idempotencyKey, savedAt: Date.now() };
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
  }, [hydrated, customerId, cart, note, idempotencyKey]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(""), 2200);
    return () => window.clearTimeout(timer);
  }, [toast]);

  useLayoutEffect(() => {
    if (mainRef.current) mainRef.current.scrollTop = 0;
  }, [screen]);

  async function loadCatalog(refresh: boolean) {
    setLoadingCatalog(true);
    try {
      const result = await getCatalog(refresh);
      setCatalog(result);
      localStorage.setItem(CATALOG_KEY, JSON.stringify(result));
      setOffline(false);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setAuthenticated(false);
      } else if (catalog) {
        setOffline(true);
      }
    } finally {
      setLoadingCatalog(false);
    }
  }

  function navigate(next: Screen) {
    if (next === "cart" && !cart.length) setToast("Agrega al menos un producto al carrito.");
    setScreen(next);
  }

  function selectClient(client: Client) {
    setCustomerId(client.id);
    setScreen("products");
    setToast(`${client.name} seleccionado`);
  }

  function addProduct(product: Product) {
    setCart((current) => {
      const existing = current.find((line) => line.productId === product.id && !line.free && !line.groupId);
      if (existing) return current.map((line) => line.id === existing.id ? { ...line, quantity: line.quantity + 1 } : line);
      return [...current, { id: uniqueId(), productId: product.id, code: product.code, name: product.name, quantity: 1, unitPrice: product.price, free: false }];
    });
    setToast(`${product.name} agregado`);
  }

  function addPromotion(paid: number, free: number) {
    if (!promoProduct) return;
    const groupId = uniqueId();
    setCart((current) => [...current,
      { id: uniqueId(), groupId, productId: promoProduct.id, code: promoProduct.code, name: promoProduct.name, quantity: paid, unitPrice: promoProduct.price, free: false },
      { id: uniqueId(), groupId, productId: promoProduct.id, code: promoProduct.code, name: promoProduct.name, quantity: free, unitPrice: 0, free: true },
    ]);
    setToast(`Promoción ${paid}+${free} agregada`);
    setPromoProduct(null);
  }

  function updateLine(id: string, patch: Partial<CartLine>) {
    setCart((current) => current.map((line) => line.id === id ? { ...line, ...patch } : line));
  }

  function removeLine(id: string) {
    setCart((current) => current.filter((line) => line.id !== id));
  }

  async function submitNewClient(data: { name: string; email: string; street: string; postal_code: string; vat: string }) {
    setClientBusy(true);
    setClientError("");
    try {
      const client = await createClient(data);
      setCatalog((current) => current ? { ...current, clients: [client, ...current.clients.filter((item) => item.id !== client.id)] } : current);
      setCustomerId(client.id);
      setNewClientOpen(false);
      setScreen("products");
      setToast(client.created ? "Cliente creado y seleccionado" : "El cliente ya existía y fue seleccionado");
    } catch (caught) {
      setClientError(caught instanceof Error ? caught.message : "No fue posible crear el cliente.");
    } finally {
      setClientBusy(false);
    }
  }

  async function submitOrder() {
    if (!customerId || !cart.length || submitBusy) return;
    setSubmitBusy(true);
    setSubmitError("");
    try {
      const result = await createOrder({
        customer_id: customerId,
        lines: cart.map((line) => ({ product_id: line.productId, quantity: line.quantity, unit_price: line.unitPrice })),
        note,
        idempotency_key: idempotencyKey,
      });
      setOrderResult(result);
      setScreen("success");
      localStorage.removeItem(DRAFT_KEY);
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "No fue posible enviar el pedido.";
      setSubmitError(message);
      if (caught instanceof ApiError && caught.status === 401) setAuthenticated(false);
    } finally {
      setSubmitBusy(false);
    }
  }

  function startNewOrder() {
    setCart([]);
    setNote("");
    setCustomerId(null);
    setIdempotencyKey(freshOrderKey());
    setOrderResult(null);
    setSubmitError("");
    setScreen("clients");
  }

  if (!hydrated) return <LoadingScreen />;
  if (!authenticated) return <MotionConfig reducedMotion="user"><LoginScreen onReady={() => setAuthenticated(true)} /></MotionConfig>;
  if (!catalog && loadingCatalog) return <LoadingScreen />;
  if (!catalog) return (
    <div className="center-state"><WifiOff size={36} /><h1>No pudimos cargar Odoo</h1><p>Revisa tu conexión y vuelve a intentarlo.</p><button type="button" className="button primary" onClick={() => void loadCatalog(true)}><RefreshCw /> Reintentar</button></div>
  );

  const customer = catalog.clients.find((item) => item.id === customerId);
  const cartCount = cart.reduce((sum, line) => sum + line.quantity, 0);

  return (
    <MotionConfig reducedMotion={reduceMotion ? "always" : "user"} transition={{ duration: 0.2, ease: [0.22, 1, 0.36, 1] }}>
      <ServiceWorker />
      <div className="app-frame">
        <TopBar customer={customer} onCustomer={() => setScreen("clients")} onLogout={() => { clearSession(); setAuthenticated(false); }} />
        {offline && <div className="offline-banner"><WifiOff size={15} /> Usando el catálogo guardado. El pedido se enviará cuando haya conexión.<button type="button" onClick={() => void loadCatalog(true)}><RefreshCw size={15} /> Reintentar</button></div>}
        <main className="app-main" ref={mainRef}>
          <AnimatePresence initial={false} mode="wait">
            <motion.div key={screen} {...pageMotion} className="screen-motion">
              {screen === "home" && <HomeScreen customer={customer} cart={cart} onStart={() => setScreen("clients")} onProducts={() => setScreen(customer ? "products" : "clients")} onCart={() => setScreen("cart")} />}
              {screen === "clients" && <ClientScreen clients={catalog.clients} selectedId={customerId} onSelect={selectClient} onNew={() => { setClientError(""); setNewClientOpen(true); }} />}
              {screen === "products" && <ProductScreen products={catalog.products} cart={cart} onAdd={addProduct} onPromo={setPromoProduct} />}
              {screen === "cart" && <CartScreen cart={cart} onChange={updateLine} onRemove={removeLine} onProducts={() => setScreen(customer ? "products" : "clients")} onReview={() => customer ? setScreen("review") : setScreen("clients")} />}
              {screen === "review" && customer && <ReviewScreen customer={customer} cart={cart} note={note} busy={submitBusy} error={submitError} onNote={setNote} onBack={() => setScreen("cart")} onSubmit={() => void submitOrder()} />}
              {screen === "success" && orderResult && <SuccessScreen result={orderResult} onNew={startNewOrder} />}
            </motion.div>
          </AnimatePresence>
        </main>
        {screen !== "success" && <BottomNav screen={screen} cartCount={cartCount} hasCustomer={Boolean(customer)} navigate={navigate} />}
      </div>
      <NewClientDialog open={newClientOpen} busy={clientBusy} error={clientError} onClose={() => setNewClientOpen(false)} onSubmit={(data) => void submitNewClient(data)} />
      <PromoDialog product={promoProduct} onClose={() => setPromoProduct(null)} onAdd={addPromotion} />
      <AnimatePresence>{toast && <motion.div className="toast" role="status" initial={{ opacity: 0, y: 18, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 12 }}><Check size={17} /> {toast}</motion.div>}</AnimatePresence>
    </MotionConfig>
  );
}
