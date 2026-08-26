"use client";

import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Calendar,
  Check,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CirclePlus,
  ClipboardCheck,
  Clock,
  Copy,
  FileText,
  History,
  Home,
  Inbox,
  KeyRound,
  ListOrdered,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Menu,
  Minus,
  PackageSearch,

  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Trash2,
  UserRound,
  UserRoundPlus,
  UsersRound,
  WifiOff,
  X,
} from "lucide-react";
import {
  AnimatePresence,
  MotionConfig,
  motion,
  useMotionTemplate,
  useMotionValue,
  useReducedMotion,
  useSpring,
} from "motion/react";
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
  changePassword,
  clearSession,
  createClient,
  createOrder,
  generateTemporarySellerKeys,
  getCatalog,
  getOrderHistory,
  getStoredSession,
  hasSession,
  login,
} from "@/lib/api";
import {
  clearConfirmedOutbox,
  enqueueOrder,
  getOutbox,
  getPendingOutboxCount,
  removeOutboxItem,
  subscribeOutbox,
  syncAllPendingOutbox,
  syncOutboxItem,
  updateOutboxStatus,
} from "@/lib/outbox";
import type {
  CartLine,
  Catalog,
  Client,
  Draft,
  OrderResult,
  OutboxItem,
  Product,
  Seller,
  SellerOrderSummary,
  SessionInfo,
  TemporarySellerKey,
} from "@/lib/types";

type Screen = "home" | "clients" | "products" | "cart" | "review" | "success" | "history" | "outbox";

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

function productInitials(product: Product) {
  return product.name
    .split(/[\s/-]+/)
    .filter((part) => Boolean(part) && /[a-záéíóúñ]/i.test(part))
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function firstName(name = "") {
  return name.trim().split(/\s+/)[0] || "equipo";
}

function DesktopPointerField() {
  const rawX = useMotionValue(-600);
  const rawY = useMotionValue(-600);
  const x = useSpring(rawX, { stiffness: 95, damping: 24, mass: 0.35 });
  const y = useSpring(rawY, { stiffness: 95, damping: 24, mass: 0.35 });
  const glow = useMotionTemplate`radial-gradient(520px circle at ${x}px ${y}px, rgba(253, 170, 249, 0.17), rgba(139, 69, 139, 0.08) 32%, transparent 72%)`;

  useEffect(() => {
    const handlePointerMove = (event: PointerEvent) => {
      rawX.set(event.clientX);
      rawY.set(event.clientY);
    };
    const handlePointerLeave = () => {
      rawX.set(-600);
      rawY.set(-600);
    };

    window.addEventListener("pointermove", handlePointerMove, { passive: true });
    window.addEventListener("pointerleave", handlePointerLeave);
    return () => {
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerleave", handlePointerLeave);
    };
  }, [rawX, rawY]);

  return (
    <motion.div className="desktop-pointer-field" style={{ background: glow }} aria-hidden="true">
      {Array.from({ length: 12 }).map((_, index) => (
        <span key={index} />
      ))}
    </motion.div>
  );
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

function LoginScreen({ onReady }: { onReady: (session: SessionInfo, password: string) => void }) {
  const [loginName, setLoginName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [adminOpen, setAdminOpen] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const session = await login(loginName, password);
      onReady(session, password);
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
          <h1>Acceso con ID de Odoo</h1>
          <p>Ingresa tu ID, correo o usuario de Odoo y tu NIP temporal o personal.</p>
        </div>

        <form onSubmit={submit} className="stack-form">
          <label htmlFor="seller-login">Vendedor de Odoo</label>
          <input
            id="seller-login"
            type="text"
            autoComplete="username"
            value={loginName}
            onChange={(event) => setLoginName(event.target.value)}
            placeholder="ID, correo o usuario"
            minLength={1}
            required
          />
          <label htmlFor="seller-password">NIP de 4 dígitos</label>
          <input
            id="seller-password"
            type="password"
            inputMode="numeric"
            pattern="[0-9]{4}"
            maxLength={4}
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value.replace(/\D/g, "").slice(0, 4))}
            placeholder="4 dígitos"
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
          <button className="button primary wide" disabled={busy || password.length !== 4}>
            {busy ? <LoaderCircle className="spin" /> : <ArrowRight />}
            {busy ? "Ingresando…" : "Entrar a pedidos"}
          </button>
        </form>
        <button type="button" className="admin-link" onClick={() => setAdminOpen(true)}>
          <ShieldCheck size={16} /> Consultar claves temporales
        </button>
        <p className="secure-note"><BadgeCheck size={16} /> Conexión protegida · La clave maestra de Odoo no se expone</p>
      </motion.section>
      <AdminKeysDialog open={adminOpen} onClose={() => setAdminOpen(false)} />
    </main>
  );
}

function ChangePasswordScreen({
  session,
  currentPassword,
  onReady,
  onLogout,
}: {
  session: SessionInfo;
  currentPassword: string;
  onReady: (session: SessionInfo) => void;
  onLogout: () => void;
}) {
  const [current, setCurrent] = useState(currentPassword);
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (next.length !== 4 || !/^\d{4}$/.test(next)) {
      setError("El nuevo NIP debe tener exactamente 4 dígitos numéricos.");
      return;
    }
    if (next === current) {
      setError("El nuevo NIP debe ser diferente al NIP temporal.");
      return;
    }
    if (next !== confirm) {
      setError("La confirmación no coincide con el nuevo NIP.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const updated = await changePassword(current, next);
      onReady(updated);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible cambiar el NIP.");
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
        <div className="seller-welcome">
          <span className="seller-avatar"><KeyRound /></span>
          <div>
            <small>Primer ingreso · ID {session.seller.id}</small>
            <strong>{session.seller.name}</strong>
          </div>
        </div>
        <div className="login-intro compact">
          <span className="eyebrow">Primer acceso</span>
          <h1>Define tu nuevo NIP de 4 dígitos.</h1>
          <p>Para mayor seguridad, crea un NIP personal de 4 números que recordarás fácilmente.</p>
        </div>
        <form onSubmit={submit} className="stack-form">
          <label htmlFor="current-password">NIP temporal actual</label>
          <input
            id="current-password"
            type="password"
            inputMode="numeric"
            maxLength={4}
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value.replace(/\D/g, "").slice(0, 4))}
            minLength={4}
            required
          />
          <label htmlFor="new-password">Nuevo NIP personal (4 dígitos)</label>
          <input
            id="new-password"
            type="password"
            inputMode="numeric"
            maxLength={4}
            pattern="[0-9]{4}"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value.replace(/\D/g, "").slice(0, 4))}
            placeholder="Ej. 1234"
            minLength={4}
            required
          />
          <label htmlFor="confirm-password">Confirmar nuevo NIP</label>
          <input
            id="confirm-password"
            type="password"
            inputMode="numeric"
            maxLength={4}
            pattern="[0-9]{4}"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value.replace(/\D/g, "").slice(0, 4))}
            placeholder="Repite tu nuevo NIP"
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
          <button className="button primary wide" disabled={busy || next.length !== 4}>
            {busy ? <LoaderCircle className="spin" /> : <LockKeyhole />}
            {busy ? "Guardando NIP…" : "Guardar nuevo NIP"}
          </button>
          <button type="button" className="button secondary wide" onClick={onLogout} disabled={busy}>
            <LogOut /> Salir
          </button>
        </form>
      </motion.section>
    </main>
  );
}


function AdminKeysDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [adminPin, setAdminPin] = useState("");
  const [resetExisting, setResetExisting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [keys, setKeys] = useState<TemporarySellerKey[]>([]);
  const [copied, setCopied] = useState("");

  useEffect(() => {
    if (!open) {
      setAdminPin("");
      setResetExisting(false);
      setError("");
      setKeys([]);
      setCopied("");
    }
  }, [open]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    setCopied("");
    try {
      const result = await generateTemporarySellerKeys(adminPin, resetExisting);
      setKeys(result.sellers);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible generar las claves.");
    } finally {
      setBusy(false);
    }
  }

  async function copyKey(key: TemporarySellerKey) {
    if (!key.temporary_password) return;
    const text = `${key.seller.name}\nID de Odoo: ${key.seller.id}\nNIP temporal: ${key.temporary_password}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(String(key.seller.id));
    } catch {
      setCopied("");
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="dialog-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !busy) onClose();
          }}
        >
          <motion.section
            role="dialog"
            aria-modal="true"
            aria-labelledby="seller-keys-title"
            className="dialog-sheet admin-dialog"
            initial={{ opacity: 0, y: 32 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 32 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
          >
            <div className="dialog-head">
              <div>
                <span className="eyebrow">Administración</span>
                <h2 id="seller-keys-title">Claves y NIPs de vendedores</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={onClose}
                disabled={busy}
                aria-label="Cerrar"
              >
                <X />
              </button>
            </div>
            <form className="dialog-form" onSubmit={submit}>
              <label>
                <span>Clave de administrador</span>
                <input
                  type="password"
                  minLength={6}
                  value={adminPin}
                  onChange={(event) => setAdminPin(event.target.value)}
                  required
                />
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={resetExisting}
                  onChange={(event) => setResetExisting(event.target.checked)}
                />
                <span>Restablecer también vendedores que ya tienen NIP personal</span>
              </label>
              {error && (
                <p className="form-error">
                  <CircleAlert size={16} /> {error}
                </p>
              )}
              <button className="button primary wide" disabled={busy}>
                {busy ? <LoaderCircle className="spin" /> : <UsersRound />}
                {busy ? "Consultando Odoo…" : "Ver claves temporales"}
              </button>
            </form>
            {keys.length > 0 && (
              <div className="seller-key-list">
                {keys.map((key) => (
                  <article className="seller-key-row" key={key.seller.id}>
                    <span className="seller-avatar">
                      <UserRound />
                    </span>
                    <div>
                      <strong>
                        ID {key.seller.id} · {key.seller.name}
                      </strong>
                      <small>{key.seller.login}</small>
                      <em>{key.status}</em>
                    </div>
                    {key.temporary_password ? (
                      <button
                        type="button"
                        className="copy-key-button"
                        onClick={() => void copyKey(key)}
                      >
                        <Copy size={16} />
                        <span>
                          {copied === String(key.seller.id)
                            ? "Copiado"
                            : `NIP: ${key.temporary_password}`}
                        </span>
                      </button>
                    ) : (
                      <span className="key-ready">NIP Activo</span>
                    )}
                  </article>
                ))}
              </div>
            )}
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>
  );
}


function TopBar({
  customer,
  seller,
  pendingCount = 0,
  onCustomer,
  onHistory,
  onOutbox,
  onLogout,
}: {
  customer?: Client;
  seller?: Seller;
  pendingCount?: number;
  onCustomer: () => void;
  onHistory: () => void;
  onOutbox: () => void;
  onLogout: () => void;
}) {
  return (
    <header className="topbar">
      <Logo />
      <div className="topbar-actions">
        {seller && (
          <span className="seller-chip" title={seller.login}>
            <UserRound size={16} />
            <span>{seller.name}</span>
          </span>
        )}
        <button
          type="button"
          className="icon-button outbox-top-button"
          onClick={onOutbox}
          aria-label="Bandeja de pedidos"
          title="Bandeja de pedidos offline"
        >
          <Inbox size={19} />
          {pendingCount > 0 && <span className="topbar-badge">{pendingCount}</span>}
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={onHistory}
          aria-label="Historial de pedidos"
          title="Historial de pedidos en Odoo"
        >
          <History size={19} />
        </button>
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
  seller,
  cart,
  pendingCount = 0,
  onStart,
  onProducts,
  onCart,
  onHistory,
  onOutbox,
}: {
  customer?: Client;
  seller?: Seller;
  cart: CartLine[];
  pendingCount?: number;
  onStart: () => void;
  onProducts: () => void;
  onCart: () => void;
  onHistory: () => void;
  onOutbox: () => void;
}) {
  const units = cart.reduce((sum, line) => sum + line.quantity, 0);
  const total = cart.reduce((sum, line) => sum + line.quantity * line.unitPrice, 0);
  return (
    <div className="screen home-screen">
      <section className="hero-panel dashboard-hero">
        <div>
          <div className="hero-status-row">
            <span className="eyebrow">Resumen de hoy</span>
            <span className="sync-pill">Sincronizado</span>
          </div>
          <h1>Hola, {firstName(seller?.name)}.</h1>
          <p>Captura pedidos, revisa pendientes y consulta tu historial sin perder ritmo en campo.</p>
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
        <button type="button" className="summary-card" onClick={onOutbox}>
          <span className="summary-icon"><Inbox /></span>
          <small>Bandeja de salida</small>
          <strong>{pendingCount > 0 ? `${pendingCount} pendientes` : "Al día"}</strong>
          <span className="text-link">{pendingCount > 0 ? "Sincronizar ahora" : "Ver cola"} <ChevronRight size={15} /></span>
        </button>
        <button type="button" className="summary-card" onClick={onHistory}>
          <span className="summary-icon"><History /></span>
          <small>Historial Odoo</small>
          <strong>Mis pedidos</strong>
          <span className="text-link">Consultar folios <ChevronRight size={15} /></span>
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
  onCart,
}: {
  products: Product[];
  cart: CartLine[];
  onAdd: (product: Product) => void;
  onPromo: (product: Product) => void;
  onCart: () => void;
}) {
  const [query, setQuery] = useState("");
  const [visible, setVisible] = useState(VISIBLE_STEP);
  const deferredQuery = useDeferredValue(query);
  const inputRef = useRef<HTMLInputElement>(null);
  const quantities = useMemo(() => {
    const result = new Map<number, number>();
    for (const line of cart) result.set(line.productId, (result.get(line.productId) || 0) + line.quantity);
    return result;
  }, [cart]);
  const filtered = useMemo(() => {
    const needle = normalize(deferredQuery);
    if (!needle) return products;
    return products.filter((product) =>
      normalize(`${product.code} ${product.name} ${product.category}`).includes(needle),
    );
  }, [products, deferredQuery]);
  const cartCount = cart.reduce((sum, line) => sum + line.quantity, 0);
  const cartTotal = cart.reduce((sum, line) => sum + line.quantity * line.unitPrice, 0);

  useEffect(() => setVisible(VISIBLE_STEP), [deferredQuery]);

  return (
    <div className="screen product-screen">
      <div className="screen-title-row">
        <div><span className="eyebrow">Catálogo Odoo</span><h1>Inventario disponible</h1><p>Busca por nombre o código y agrega sin perder tu posición.</p></div>
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
      </div>

      <div className="catalog-results">
        <div className="result-meta"><span>{filtered.length} productos</span>{deferredQuery && <span>Resultados para “{deferredQuery}”</span>}</div>
        <motion.div className="product-grid" layout>
          <AnimatePresence initial={false} mode="popLayout">
            {filtered.slice(0, visible).map((product) => (
              <motion.article
                layout="position"
                className={`product-card ${quantities.has(product.id) ? "in-cart" : ""}`}
                key={product.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, scale: 0.98 }}
                transition={{ duration: 0.16 }}
              >
                <div className="product-card-top">
                  <span className="product-category">{product.category}</span>
                  <span className="product-code">SKU: {product.code}</span>
                </div>
                <h2>{product.name}</h2>
                <div className="product-price-row">
                  <div className="product-price">
                    <strong>{money(product.price)}</strong>
                    <small>Precio de lista</small>
                  </div>
                  {quantities.has(product.id) && (
                    <motion.span
                      className="quantity-badge-card"
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                    >
                      {quantities.get(product.id)} en pedido
                    </motion.span>
                  )}
                </div>
                <div className="product-actions">
                  <motion.button
                    type="button"
                    className="button primary compact-add"
                    onClick={() => onAdd(product)}
                    whileTap={{ scale: 0.96 }}
                  >
                    <Plus size={18} /> Agregar
                  </motion.button>
                  <motion.button
                    type="button"
                    className="icon-button promo"
                    onClick={() => onPromo(product)}
                    whileTap={{ scale: 0.94 }}
                    aria-label={`Agregar promoción de ${product.name}`}
                    title="Agregar promoción"
                  >
                    <Sparkles size={18} />
                  </motion.button>
                </div>
              </motion.article>
            ))}
          </AnimatePresence>
        </motion.div>

        {!filtered.length && <EmptyState icon={PackageSearch} title="No encontramos productos" body="Revisa el nombre, el código o cambia la categoría." />}
        {visible < filtered.length && <button type="button" className="button secondary load-more" onClick={() => setVisible((count) => count + VISIBLE_STEP)}>Mostrar más productos</button>}
      </div>
      <AnimatePresence>
        {cartCount > 0 && (
          <motion.button
            type="button"
            className="floating-order-card"
            onClick={onCart}
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 18, scale: 0.96 }}
            transition={{ type: "spring", stiffness: 260, damping: 24 }}
          >
            <span className="floating-bag">
              <ShoppingBag />
              <b>{cartCount}</b>
            </span>
            <span><small>Pedido actual</small><strong>{money(cartTotal)}</strong></span>
            <em>Revisar <ArrowRight /></em>
          </motion.button>
        )}
      </AnimatePresence>
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
  const statusMessage = result.recovered
    ? "Este pedido ya estaba registrado; recuperamos el folio para evitar duplicados."
    : result.status === "sale" || result.status === "done"
      ? "Odoo confirmó la operación correctamente."
      : "Odoo registró el pedido correctamente.";

  return (
    <div className="screen success-screen">
      <motion.div className="success-symbol" initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 220, damping: 18 }}><Check /></motion.div>
      <span className="eyebrow">Pedido registrado</span>
      <h1>{result.folio}</h1>
      <p>{statusMessage}</p>
      <section className="success-total"><span>Total en Odoo</span><strong>{money(result.total)}</strong><small>Subtotal {money(result.subtotal)} · Impuestos {money(result.tax)}</small></section>
      <div className="success-actions">
        <a className="button whatsapp wide" href={result.whatsapp_url} target="_blank" rel="noreferrer">Compartir por WhatsApp <ArrowRight /></a>
        <button type="button" className="button secondary wide" onClick={onNew}><CirclePlus /> Capturar otro pedido</button>
      </div>
    </div>
  );
}

function HistoryScreen({
  seller,
  onRefresh,
}: {
  seller?: Seller;
  onRefresh?: () => void;
}) {
  const [orders, setOrders] = useState<SellerOrderSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);

  const fetchOrders = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getOrderHistory(50);
      setOrders(data.orders);
      if (onRefresh) onRefresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible consultar el historial.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchOrders();
  }, []);

  const filtered = useMemo(() => {
    const needle = normalize(deferredQuery);
    if (!needle) return orders;
    return orders.filter(
      (o) =>
        normalize(o.customer_name).includes(needle) ||
        normalize(o.folio).includes(needle) ||
        normalize(o.client_order_ref).includes(needle),
    );
  }, [orders, deferredQuery]);

  const totalSales = useMemo(() => {
    return filtered.reduce((sum, o) => sum + (o.state !== "cancel" ? o.amount_total : 0), 0);
  }, [filtered]);

  return (
    <div className="screen list-screen history-screen">
      <div className="screen-title-row">
        <div>
          <span className="eyebrow">Odoo · Ventas</span>
          <h1>Historial de pedidos</h1>
          <p>{seller ? `Pedidos asignados a ${seller.name}` : "Tus pedidos registrados en Odoo"}</p>
        </div>
        <button
          type="button"
          className="button secondary"
          onClick={() => void fetchOrders()}
          disabled={loading}
        >
          <RefreshCw className={loading ? "spin" : ""} size={16} />
          <span>{loading ? "Actualizando…" : "Actualizar"}</span>
        </button>
      </div>

      <div className="history-summary-card">
        <div>
          <small>Pedidos en Odoo</small>
          <strong>
            {filtered.length} {filtered.length === 1 ? "pedido" : "pedidos"}
          </strong>
        </div>
        <div className="history-summary-right">
          <small>Monto acumulado</small>
          <strong>{money(totalSales)}</strong>
        </div>
      </div>

      <div className="sticky-tools">
        <label className="search-field">
          <Search size={20} />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por cliente o folio (S00...)"
            autoComplete="off"
          />
          {query && (
            <button type="button" onClick={() => setQuery("")} aria-label="Limpiar búsqueda">
              <X size={18} />
            </button>
          )}
        </label>
      </div>

      {loading && !orders.length ? (
        <div className="center-state">
          <LoaderCircle className="spin" size={32} />
          <p>Consultando pedidos en Odoo…</p>
        </div>
      ) : error && !orders.length ? (
        <div className="center-state">
          <CircleAlert size={36} />
          <h1>Error al cargar historial</h1>
          <p>{error}</p>
          <button type="button" className="button primary" onClick={() => void fetchOrders()}>
            <RefreshCw /> Reintentar
          </button>
        </div>
      ) : !filtered.length ? (
        <EmptyState
          icon={ListOrdered}
          title="Sin pedidos encontrados"
          body={
            query
              ? "No hay pedidos que coincidan con la búsqueda."
              : "Aún no tienes pedidos registrados con este usuario."
          }
        />
      ) : (
        <div className="order-history-list">
          {filtered.map((order) => {
            const isSale = order.state === "sale" || order.state === "done";
            const isCancel = order.state === "cancel";
            return (
              <article className="history-order-card" key={order.id}>
                <div className="history-card-header">
                  <span className="order-folio">
                    <FileText size={15} />
                    <strong>{order.folio}</strong>
                  </span>
                  <span
                    className={`order-state-badge ${isSale ? "sale" : isCancel ? "cancel" : "draft"}`}
                  >
                    {order.state_label || order.state}
                  </span>
                </div>
                <div className="history-card-body">
                  <div className="history-customer-row">
                    <UserRound size={16} />
                    <span>{order.customer_name}</span>
                  </div>
                  <div className="history-date-row">
                    <Clock size={14} />
                    <small>
                      {order.date_order
                        ? new Date(order.date_order.replace(" ", "T") + "Z").toLocaleString(
                            "es-MX",
                            { dateStyle: "medium", timeStyle: "short" },
                          )
                        : "Fecha no registrada"}
                    </small>
                  </div>
                  {order.client_order_ref && (
                    <div className="history-ref-row">
                      <small>Ref: {order.client_order_ref}</small>
                    </div>
                  )}
                </div>
                <div className="history-card-footer">
                  <span>Total Odoo</span>
                  <strong>{money(order.amount_total)}</strong>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function OutboxScreen({
  onNewOrder,
  onNavigateHome,
}: {
  onNewOrder: () => void;
  onNavigateHome: () => void;
}) {
  const [items, setItems] = useState<OutboxItem[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");

  const refresh = () => {
    setItems(getOutbox());
  };

  useEffect(() => {
    refresh();
    const unsubscribe = subscribeOutbox(refresh);
    return () => unsubscribe();
  }, []);

  const handleSyncAll = async () => {
    setSyncing(true);
    setSyncMessage("");
    try {
      const res = await syncAllPendingOutbox();
      if (res.processed === 0) {
        setSyncMessage("No hay pedidos pendientes por sincronizar.");
      } else {
        setSyncMessage(
          `Procesados: ${res.processed} | Exitosos: ${res.succeeded} | Con error: ${res.failed}`,
        );
      }
    } catch {
      setSyncMessage("Error de conexión durante la sincronización.");
    } finally {
      setSyncing(false);
      refresh();
    }
  };

  const handleSyncItem = async (id: string) => {
    setSyncing(true);
    try {
      await syncOutboxItem(id);
    } finally {
      setSyncing(false);
      refresh();
    }
  };

  const handleRemove = (id: string) => {
    removeOutboxItem(id);
    refresh();
  };

  const handleClearConfirmed = () => {
    clearConfirmedOutbox();
    refresh();
  };

  const pendingCount = items.filter(
    (i) => i.status === "pending" || i.status === "sending" || i.status === "attention",
  ).length;
  const confirmedCount = items.filter((i) => i.status === "confirmed").length;

  return (
    <div className="screen list-screen outbox-screen">
      <div className="screen-title-row">
        <div>
          <span className="eyebrow">Modo Offline & Cola</span>
          <h1>Bandeja de pedidos</h1>
          <p>Tus pedidos guardados en este dispositivo con protección contra duplicados</p>
        </div>
        <div className="outbox-top-actions">
          {pendingCount > 0 && (
            <button
              type="button"
              className="button primary"
              onClick={() => void handleSyncAll()}
              disabled={syncing}
            >
              {syncing ? <LoaderCircle className="spin" size={16} /> : <Send size={16} />}
              <span>{syncing ? "Sincronizando…" : "Sincronizar pendientes"}</span>
            </button>
          )}
          {confirmedCount > 0 && (
            <button
              type="button"
              className="button secondary"
              onClick={handleClearConfirmed}
              disabled={syncing}
            >
              <Trash2 size={16} />
              <span>Limpiar confirmados</span>
            </button>
          )}
        </div>
      </div>

      {syncMessage && (
        <div className="outbox-sync-alert">
          <CircleCheck size={16} />
          <span>{syncMessage}</span>
        </div>
      )}

      {!items.length ? (
        <EmptyState
          icon={Inbox}
          title="Bandeja vacía"
          body="Todos tus pedidos se han sincronizado con Odoo o aún no has capturado pedidos en este dispositivo."
        />
      ) : (
        <div className="outbox-list">
          {items.map((item) => {
            const isPending = item.status === "pending";
            const isSending = item.status === "sending";
            const isConfirmed = item.status === "confirmed";
            const isAttention = item.status === "attention";

            return (
              <article className={`outbox-card ${item.status}`} key={item.id}>
                <div className="outbox-card-header">
                  <div className="outbox-status-tag">
                    {isPending && (
                      <span className="tag-pending">
                        <Clock size={14} /> Pendiente de enviar
                      </span>
                    )}
                    {isSending && (
                      <span className="tag-sending">
                        <LoaderCircle className="spin" size={14} /> Enviando a Odoo…
                      </span>
                    )}
                    {isConfirmed && (
                      <span className="tag-confirmed">
                        <Check size={14} /> Confirmado en Odoo{" "}
                        {item.result?.folio ? `(${item.result.folio})` : ""}
                      </span>
                    )}
                    {isAttention && (
                      <span className="tag-attention">
                        <AlertTriangle size={14} /> Requiere atención
                      </span>
                    )}
                  </div>
                  <small className="outbox-timestamp">
                    {new Date(item.created_at).toLocaleTimeString("es-MX", {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </small>
                </div>

                <div className="outbox-card-body">
                  <strong className="outbox-client-name">{item.customer_name}</strong>
                  <div className="outbox-details">
                    <span>{item.items_count} unidades</span>
                    <span>·</span>
                    <strong>{money(item.total_amount)}</strong>
                  </div>
                  {item.note && <p className="outbox-note">Nota: {item.note}</p>}
                  {item.error_message && (
                    <div className="outbox-error-box">
                      <CircleAlert size={14} />
                      <small>{item.error_message}</small>
                    </div>
                  )}
                  <small className="outbox-ref">Ref: {item.idempotency_key}</small>
                </div>

                <div className="outbox-card-footer">
                  {isConfirmed && item.result?.whatsapp_url ? (
                    <a
                      className="button whatsapp"
                      href={item.result.whatsapp_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <Send size={15} /> Compartir WhatsApp
                    </a>
                  ) : (
                    <button
                      type="button"
                      className="button primary"
                      onClick={() => void handleSyncItem(item.id)}
                      disabled={syncing || isSending}
                    >
                      <RotateCcw size={15} /> Reintentar envío
                    </button>
                  )}
                  <button
                    type="button"
                    className="icon-button delete-outbox-button"
                    onClick={() => handleRemove(item.id)}
                    aria-label="Eliminar"
                    title="Eliminar de bandeja"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

function MoreOptionsDialog({
  open,
  seller,
  pendingCount = 0,
  onClose,
  onNavigate,
  onRefreshCatalog,
  onLogout,
}: {
  open: boolean;
  seller?: Seller;
  pendingCount?: number;
  onClose: () => void;
  onNavigate: (screen: Screen) => void;
  onRefreshCatalog: () => void;
  onLogout: () => void;
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="dialog-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) onClose();
          }}
        >
          <motion.section
            role="dialog"
            aria-modal="true"
            aria-labelledby="more-options-title"
            className="dialog-sheet more-options-sheet"
            initial={{ opacity: 0, y: 35 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 35 }}
            transition={{ type: "spring", stiffness: 320, damping: 30 }}
          >
            <div className="dialog-head">
              <div>
                <span className="eyebrow">Menú de opciones</span>
                <h2 id="more-options-title">Más funciones</h2>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={onClose}
                aria-label="Cerrar menú"
              >
                <X />
              </button>
            </div>

            {seller && (
              <div className="seller-profile-banner">
                <span className="seller-avatar">
                  <UserRound />
                </span>
                <div className="seller-info">
                  <strong>{seller.name}</strong>
                  <small>ID de Odoo: {seller.id} · {seller.login}</small>
                </div>
              </div>
            )}

            <div className="more-menu-grid">
              <button
                type="button"
                className="more-menu-item"
                onClick={() => {
                  onClose();
                  onNavigate("outbox");
                }}
              >
                <span className="more-menu-icon">
                  <Inbox size={22} />
                  {pendingCount > 0 && <span className="more-badge">{pendingCount}</span>}
                </span>
                <div className="more-menu-text">
                  <strong>Bandeja de pedidos offline</strong>
                  <small>
                    {pendingCount > 0
                      ? `${pendingCount} pedido(s) pendientes de envío`
                      : "Cola de salida local y reintentos"}
                  </small>
                </div>
                <ChevronRight size={18} className="more-arrow" />
              </button>

              <button
                type="button"
                className="more-menu-item"
                onClick={() => {
                  onClose();
                  onNavigate("history");
                }}
              >
                <span className="more-menu-icon">
                  <History size={22} />
                </span>
                <div className="more-menu-text">
                  <strong>Historial de pedidos</strong>
                  <small>Consultar pedidos y cotizaciones en Odoo</small>
                </div>
                <ChevronRight size={18} className="more-arrow" />
              </button>

              <button
                type="button"
                className="more-menu-item"
                onClick={() => {
                  onClose();
                  onRefreshCatalog();
                }}
              >
                <span className="more-menu-icon">
                  <RefreshCw size={22} />
                </span>
                <div className="more-menu-text">
                  <strong>Actualizar catálogo</strong>
                  <small>Recargar productos y clientes desde Odoo</small>
                </div>
                <ChevronRight size={18} className="more-arrow" />
              </button>

              <button
                type="button"
                className="more-menu-item danger"
                onClick={() => {
                  onClose();
                  onLogout();
                }}
              >
                <span className="more-menu-icon">
                  <LogOut size={22} />
                </span>
                <div className="more-menu-text">
                  <strong>Cerrar sesión</strong>
                  <small>Salir de la cuenta del vendedor</small>
                </div>
                <ChevronRight size={18} className="more-arrow" />
              </button>
            </div>
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function BottomNav({
  screen,
  cartCount,
  pendingCount = 0,
  hasCustomer,
  navigate,
  onOpenMore,
}: {
  screen: Screen;
  cartCount: number;
  pendingCount?: number;
  hasCustomer: boolean;
  navigate: (screen: Screen) => void;
  onOpenMore: () => void;
}) {
  const isMoreActive = screen === "outbox" || screen === "history";
  const catalogLabel = hasCustomer || screen === "products" ? "Productos" : "Cliente";
  const CatalogIcon = hasCustomer || screen === "products" ? PackageSearch : UserRoundPlus;

  return (
    <nav className="bottom-nav" aria-label="Navegación principal">
      <button
        type="button"
        className={screen === "home" ? "active" : ""}
        onClick={() => navigate("home")}
      >
        <span>
          <Home />
        </span>
        <small>Inicio</small>
      </button>

      <button
        type="button"
        className={screen === "products" || screen === "clients" ? "active" : ""}
        onClick={() => navigate(hasCustomer ? "products" : "clients")}
      >
        <span>
          <CatalogIcon />
        </span>
        <small>{catalogLabel}</small>
      </button>

      <button
        type="button"
        className={screen === "cart" || screen === "review" ? "active" : ""}
        onClick={() => navigate("cart")}
      >
        <span>
          <ShoppingBag />
          {cartCount > 0 && <b>{cartCount}</b>}
        </span>
        <small>Carrito</small>
      </button>

      <button
        type="button"
        className={isMoreActive ? "active" : ""}
        onClick={onOpenMore}
        aria-label="Más opciones"
      >
        <span>
          <Menu />
          {pendingCount > 0 && <b>{pendingCount}</b>}
        </span>
        <small>Menú</small>
      </button>
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
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [currentLoginPassword, setCurrentLoginPassword] = useState("");
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
  const [pendingCount, setPendingCount] = useState(0);
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  const mainRef = useRef<HTMLElement>(null);


  useEffect(() => {
    let unsubscribe = () => {};
    try {
      const savedSession = getStoredSession();
      setSession(savedSession);
      setAuthenticated(Boolean(hasSession() && savedSession && !savedSession.must_change_password));
      setPendingCount(getPendingOutboxCount());

      unsubscribe = subscribeOutbox(() => {
        setPendingCount(getPendingOutboxCount());
      });

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
      clearSession();
      localStorage.removeItem(DRAFT_KEY);
    } finally {
      setHydrated(true);
    }

    return () => unsubscribe();
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
    const timer = window.setTimeout(() => setToast(""), 2800);
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
        setSession(null);
        setCurrentLoginPassword("");
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
    if (!customerId || !customer || !cart.length || submitBusy) return;
    setSubmitBusy(true);
    setSubmitError("");

    // Guardar en la bandeja local con estado inicial 'sending'
    const outboxItem = enqueueOrder({
      customerId,
      customerName: customer.name,
      lines: cart,
      note,
      idempotencyKey,
      status: "sending",
    });

    try {
      const result = await createOrder({
        customer_id: customerId,
        lines: cart.map((line) => ({
          product_id: line.productId,
          quantity: line.quantity,
          unit_price: line.free ? 0 : line.unitPrice,
        })),
        note,
        idempotency_key: idempotencyKey,
      });

      updateOutboxStatus(outboxItem.id, "confirmed", { result });
      setOrderResult(result);
      setScreen("success");
      localStorage.removeItem(DRAFT_KEY);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 422) {
        updateOutboxStatus(outboxItem.id, "attention", { errorMessage: caught.message });
        setSubmitError(caught.message);
      } else {
        const errorMsg = caught instanceof Error ? caught.message : "Error de red";
        updateOutboxStatus(outboxItem.id, "pending", { errorMessage: errorMsg });
        setToast("Sin señal directa. Pedido guardado en tu Bandeja; se enviará al recuperar conexión.");
        localStorage.removeItem(DRAFT_KEY);
        setScreen("outbox");
      }

      if (caught instanceof ApiError && caught.status === 401) {
        setSession(null);
        setCurrentLoginPassword("");
        setAuthenticated(false);
      }
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

  function acceptSession(nextSession: SessionInfo, password = "") {
    setSession(nextSession);
    setCurrentLoginPassword(password);
    setAuthenticated(!nextSession.must_change_password);
  }

  function logout() {
    clearSession();
    setSession(null);
    setCurrentLoginPassword("");
    setAuthenticated(false);
  }

  if (!hydrated) return <LoadingScreen />;
  if (!session || !hasSession()) {
    return <MotionConfig reducedMotion="user"><LoginScreen onReady={acceptSession} /></MotionConfig>;
  }
  if (session.must_change_password) {
    return (
      <MotionConfig reducedMotion="user">
        <ChangePasswordScreen
          session={session}
          currentPassword={currentLoginPassword}
          onReady={(nextSession) => acceptSession(nextSession)}
          onLogout={logout}
        />
      </MotionConfig>
    );
  }
  if (!authenticated) {
    return <MotionConfig reducedMotion="user"><LoginScreen onReady={acceptSession} /></MotionConfig>;
  }
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
        <DesktopPointerField />
        <TopBar
          customer={customer}
          seller={session.seller}
          pendingCount={pendingCount}
          onCustomer={() => setScreen("clients")}
          onHistory={() => setScreen("history")}
          onOutbox={() => setScreen("outbox")}
          onLogout={logout}
        />
        {offline && <div className="offline-banner"><WifiOff size={15} /> Usando el catálogo guardado. El pedido se enviará cuando haya conexión.<button type="button" onClick={() => void loadCatalog(true)}><RefreshCw size={15} /> Reintentar</button></div>}
        <main className="app-main" ref={mainRef}>
          <AnimatePresence initial={false} mode="wait">
            <motion.div key={screen} {...pageMotion} className="screen-motion">
              {screen === "home" && (
                <HomeScreen
                  customer={customer}
                  seller={session.seller}
                  cart={cart}
                  pendingCount={pendingCount}
                  onStart={() => setScreen("clients")}
                  onProducts={() => setScreen(customer ? "products" : "clients")}
                  onCart={() => setScreen("cart")}
                  onHistory={() => setScreen("history")}
                  onOutbox={() => setScreen("outbox")}
                />
              )}
              {screen === "clients" && <ClientScreen clients={catalog.clients} selectedId={customerId} onSelect={selectClient} onNew={() => { setClientError(""); setNewClientOpen(true); }} />}
              {screen === "products" && <ProductScreen products={catalog.products} cart={cart} onAdd={addProduct} onPromo={setPromoProduct} onCart={() => setScreen("cart")} />}
              {screen === "cart" && <CartScreen cart={cart} onChange={updateLine} onRemove={removeLine} onProducts={() => setScreen(customer ? "products" : "clients")} onReview={() => customer ? setScreen("review") : setScreen("clients")} />}
              {screen === "review" && customer && <ReviewScreen customer={customer} cart={cart} note={note} busy={submitBusy} error={submitError} onNote={setNote} onBack={() => setScreen("cart")} onSubmit={() => void submitOrder()} />}
              {screen === "success" && orderResult && <SuccessScreen result={orderResult} onNew={startNewOrder} />}
              {screen === "history" && <HistoryScreen seller={session.seller} onRefresh={() => void loadCatalog(false)} />}
              {screen === "outbox" && <OutboxScreen onNewOrder={startNewOrder} onNavigateHome={() => setScreen("home")} />}
            </motion.div>
          </AnimatePresence>
        </main>
        {screen !== "success" && (
          <BottomNav
            screen={screen}
            cartCount={cartCount}
            pendingCount={pendingCount}
            hasCustomer={Boolean(customer)}
            navigate={navigate}
            onOpenMore={() => setMoreMenuOpen(true)}
          />
        )}
      </div>
      <MoreOptionsDialog
        open={moreMenuOpen}
        seller={session.seller}
        pendingCount={pendingCount}
        onClose={() => setMoreMenuOpen(false)}
        onNavigate={(targetScreen) => {
          setMoreMenuOpen(false);
          navigate(targetScreen);
        }}
        onRefreshCatalog={() => {
          void loadCatalog(true);
          setToast("Catálogo actualizado desde Odoo");
        }}
        onLogout={logout}
      />
      <NewClientDialog open={newClientOpen} busy={clientBusy} error={clientError} onClose={() => setNewClientOpen(false)} onSubmit={(data) => void submitNewClient(data)} />
      <PromoDialog product={promoProduct} onClose={() => setPromoProduct(null)} onAdd={addPromotion} />
      <AnimatePresence>{toast && <motion.div className="toast" role="status" initial={{ opacity: 0, x: "-50%", y: 18, scale: 0.96 }} animate={{ opacity: 1, x: "-50%", y: 0, scale: 1 }} exit={{ opacity: 0, x: "-50%", y: 12 }}><Check size={17} /> {toast}</motion.div>}</AnimatePresence>
    </MotionConfig>
  );
}
