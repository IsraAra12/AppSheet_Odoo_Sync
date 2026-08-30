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
  Download,
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
  getCustomerStatement,
  getOrderDetail,
  getOrderHistory,
  getStoredSession,
  hasSession,
  login,
  updateOrder,
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
  CustomerStatement,
  Draft,
  OrderResult,
  OrderDetail,
  OutboxItem,
  Product,
  Seller,
  SellerOrderSummary,
  SessionInfo,
  TemporarySellerKey,
} from "@/lib/types";

type Screen = "home" | "clients" | "products" | "cart" | "review" | "success" | "history" | "outbox" | "statement" | "orderEdit";

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
};

const DRAFT_KEY = "rapyvet_order_draft_v2";
const CATALOG_KEY = "rapyvet_catalog_v2";
const FIRST_USE_TUTORIAL_KEY = "rapyvet_first_use_tutorial_seen_v2";
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

function tutorialSeenKey(sellerId?: number) {
  return sellerId ? `${FIRST_USE_TUTORIAL_KEY}.${sellerId}` : FIRST_USE_TUTORIAL_KEY;
}

function isAppRunningStandalone() {
  if (typeof window === "undefined") return false;
  const navigatorWithStandalone = navigator as Navigator & { standalone?: boolean };
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: fullscreen)").matches ||
    navigatorWithStandalone.standalone === true
  );
}

function usePwaInstall() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [installed, setInstalled] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    const updateInstalled = () => setInstalled(isAppRunningStandalone());
    updateInstalled();

    const onBeforeInstallPrompt = (event: Event) => {
      event.preventDefault();
      setDeferredPrompt(event as BeforeInstallPromptEvent);
    };
    const onInstalled = () => {
      setInstalled(true);
      setDeferredPrompt(null);
      setHelpOpen(false);
    };

    const standaloneQuery = window.matchMedia("(display-mode: standalone)");
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt);
    window.addEventListener("appinstalled", onInstalled);
    standaloneQuery.addEventListener?.("change", updateInstalled);

    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt);
      window.removeEventListener("appinstalled", onInstalled);
      standaloneQuery.removeEventListener?.("change", updateInstalled);
    };
  }, []);

  async function requestInstall() {
    if (installed) return "installed" as const;
    if (!deferredPrompt) {
      setHelpOpen(true);
      return "manual" as const;
    }

    const promptEvent = deferredPrompt;
    setDeferredPrompt(null);
    await promptEvent.prompt();
    const choice = await promptEvent.userChoice.catch(() => ({ outcome: "dismissed" as const, platform: "" }));
    if (choice.outcome === "accepted") {
      setInstalled(true);
      return "accepted" as const;
    }
    setHelpOpen(true);
    return "dismissed" as const;
  }

  return {
    canInstall: Boolean(deferredPrompt) && !installed,
    helpOpen,
    installed,
    requestInstall,
    setHelpOpen,
  };
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

type TutorialStep = {
  label: string;
  title: string;
  body: string;
  icon: typeof Search;
  bullets: string[];
  installStep?: boolean;
  target?: Screen;
  visualItems: Array<{ icon: typeof Search; label: string }>;
};

function FirstUseTutorial({
  open,
  seller,
  canInstallApp,
  appInstalled,
  onInstall,
  onDone,
}: {
  open: boolean;
  seller?: Seller;
  canInstallApp: boolean;
  appInstalled: boolean;
  onInstall: () => void;
  onDone: (target?: Screen) => void;
}) {
  const [step, setStep] = useState(0);
  const sellerFirstName = firstName(seller?.name);
  const steps: TutorialStep[] = useMemo(
    () => [
      {
        label: "Guía rápida",
        title: `Bienvenido, ${sellerFirstName}.`,
        body: "Esta app está pensada para que captures pedidos en campo sin pelearte con Odoo ni con la señal.",
        icon: Sparkles,
        bullets: [
          "Primero eliges o das de alta el cliente.",
          "Después agregas productos al carrito.",
          "Al final revisas, envías a Odoo y compartes por WhatsApp.",
        ],
        visualItems: [
          { icon: UserRoundPlus, label: "Cliente" },
          { icon: PackageSearch, label: "Productos" },
          { icon: Send, label: "Enviar" },
        ],
      },
      {
        label: "Paso 1",
        title: "Selecciona el cliente correcto.",
        body: "Busca por nombre, correo o ciudad. Si el cliente todavía no existe, puedes crearlo desde el botón Nuevo.",
        icon: UsersRound,
        bullets: [
          "Usa el buscador para encontrar clientes de Odoo.",
          "El botón Nuevo crea el cliente con nombre, correo, dirección, CP y RFC opcional.",
          "Al seleccionarlo, la app te lleva directo al catálogo.",
        ],
        visualItems: [
          { icon: Search, label: "Buscar" },
          { icon: UserRoundPlus, label: "Nuevo" },
          { icon: Check, label: "Seleccionar" },
        ],
        target: "clients",
      },
      {
        label: "Paso 2",
        title: "Agrega productos sin perder el ritmo.",
        body: "Escribe el medicamento, revisa precio y existencia, y toca Agregar. El carrito se conserva mientras sigues buscando.",
        icon: PackageSearch,
        bullets: [
          "La búsqueda filtra productos mientras escribes.",
          "Puedes agregar varias unidades desde el carrito.",
          "Si aplica promoción, usa el botón de brillo para capturar gratis o combos.",
        ],
        visualItems: [
          { icon: Search, label: "Medicamento" },
          { icon: Plus, label: "Agregar" },
          { icon: Sparkles, label: "Promo" },
        ],
        target: "products",
      },
      {
        label: "Paso 3",
        title: "Revisa antes de enviar a Odoo.",
        body: "En el carrito confirma cantidades, precios y notas. Luego entra a Revisión para mandar el pedido.",
        icon: ShoppingBag,
        bullets: [
          "Valida cantidades y productos antes de confirmar.",
          "Agrega notas de entrega o comentarios especiales.",
          "El envío genera folio y mensaje listo para WhatsApp.",
        ],
        visualItems: [
          { icon: ShoppingBag, label: "Carrito" },
          { icon: FileText, label: "Notas" },
          { icon: Send, label: "Odoo" },
        ],
        target: "cart",
      },
      {
        label: "Respaldo",
        title: "Si falla la señal, no pierdes el pedido.",
        body: "La Bandeja guarda pedidos pendientes y el Historial permite revisar lo que ya quedó registrado en Odoo.",
        icon: Inbox,
        bullets: [
          "La Bandeja muestra pedidos pendientes de sincronizar.",
          "Puedes reintentar envío cuando vuelva la conexión.",
          "El Historial consulta los pedidos asignados a tu usuario.",
        ],
        visualItems: [
          { icon: Inbox, label: "Bandeja" },
          { icon: RefreshCw, label: "Reintentar" },
          { icon: History, label: "Historial" },
        ],
        target: "clients",
      },
      {
        label: "Instalación",
        title: "Instala RapyVet como app.",
        body: "Déjala como acceso directo tipo app de Chrome para abrirla más rápido durante la ruta, sin buscar la liga cada vez.",
        icon: Download,
        installStep: true,
        bullets: [
          "En Chrome y Android, el botón puede abrir la instalación automática.",
          "En iPhone o si Chrome no muestra el instalador, te damos pasos rápidos.",
          "La app seguirá conectada a Odoo y conservará la sesión del vendedor.",
        ],
        visualItems: [
          { icon: Download, label: "Instalar" },
          { icon: Home, label: "Inicio" },
          { icon: Sparkles, label: "Listo" },
        ],
        target: "clients",
      },
    ],
    [sellerFirstName],
  );
  const current = steps[step];
  const CurrentIcon = current.icon;
  const isLast = step === steps.length - 1;
  const installLabel = appInstalled ? "App instalada" : canInstallApp ? "Instalar app" : "Ver cómo instalar";

  useEffect(() => {
    if (open) setStep(0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDone();
      if (event.key === "ArrowRight") setStep((value) => Math.min(value + 1, steps.length - 1));
      if (event.key === "ArrowLeft") setStep((value) => Math.max(value - 1, 0));
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onDone, open, steps.length]);

  function goNext() {
    if (isLast) {
      onDone(current.target);
      return;
    }
    setStep((value) => Math.min(value + 1, steps.length - 1));
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="tutorial-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) onDone();
          }}
        >
          <motion.section
            role="dialog"
            aria-modal="true"
            aria-labelledby="first-use-tutorial-title"
            className="tutorial-sheet"
            initial={{ opacity: 0, y: 28, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 18, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 260, damping: 28 }}
          >
            <span className="tutorial-aura" aria-hidden="true" />
            <div className="tutorial-header">
              <Logo compact />
              <span>Primer uso · {step + 1} de {steps.length}</span>
              <button type="button" className="icon-button" onClick={() => onDone()} aria-label="Cerrar tutorial">
                <X />
              </button>
            </div>

            <div className="tutorial-progress" aria-hidden="true">
              <motion.span
                initial={false}
                animate={{ width: `${((step + 1) / steps.length) * 100}%` }}
              />
            </div>

            <AnimatePresence mode="wait" initial={false}>
              <motion.div
                key={current.title}
                className="tutorial-stage"
                initial={{ opacity: 0, x: 24 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -18 }}
                transition={{ type: "spring", stiffness: 280, damping: 28 }}
              >
                <div className="tutorial-visual" aria-hidden="true">
                  <motion.div
                    className="tutorial-icon"
                    animate={{ y: [0, -5, 0], rotate: [0, -2, 2, 0] }}
                    transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut" }}
                  >
                    <CurrentIcon />
                  </motion.div>
                  <div className="tutorial-mini-flow">
                    {current.visualItems.map((item, index) => {
                      const ItemIcon = item.icon;
                      return (
                        <motion.div
                          key={item.label}
                          className="tutorial-mini-card"
                          initial={{ opacity: 0, y: 12 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ delay: index * 0.08 }}
                        >
                          <ItemIcon />
                          <span>{item.label}</span>
                        </motion.div>
                      );
                    })}
                  </div>
                </div>

                <div className="tutorial-copy">
                  <span className="eyebrow">{current.label}</span>
                  <h2 id="first-use-tutorial-title">{current.title}</h2>
                  <p>{current.body}</p>
                  <ul className="tutorial-bullets">
                    {current.bullets.map((bullet) => (
                      <li key={bullet}>
                        <CircleCheck />
                        <span>{bullet}</span>
                      </li>
                    ))}
                  </ul>
                  {current.installStep && (
                    <motion.button
                      type="button"
                      className="button install-cta wide"
                      onClick={onInstall}
                      whileTap={{ scale: 0.98 }}
                    >
                      {appInstalled ? <BadgeCheck /> : <Download />}
                      {installLabel}
                    </motion.button>
                  )}
                </div>
              </motion.div>
            </AnimatePresence>

            <div className="tutorial-footer">
              <div className="tutorial-dots" aria-label="Pasos del tutorial">
                {steps.map((item, index) => (
                  <button
                    type="button"
                    key={item.label}
                    className={index === step ? "active" : ""}
                    onClick={() => setStep(index)}
                    aria-label={`Ir al paso ${index + 1}`}
                  />
                ))}
              </div>
              <div className="tutorial-actions">
                <button type="button" className="button ghost" onClick={() => onDone()}>
                  Saltar
                </button>
                {step > 0 && (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() => setStep((value) => Math.max(value - 1, 0))}
                  >
                    <ArrowLeft />
                    Atrás
                  </button>
                )}
                <button type="button" className="button primary" onClick={goNext}>
                  {isLast ? "Empezar pedido" : "Siguiente"}
                  <ArrowRight />
                </button>
              </div>
            </div>
          </motion.section>
        </motion.div>
      )}
    </AnimatePresence>
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
          className="dialog-backdrop install-help-backdrop"
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
  onStatement,
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
  onStatement?: () => void;
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
        {customer && onStatement && (
          <button type="button" className="summary-card" onClick={onStatement}>
            <span className="summary-icon"><FileText /></span>
            <small>Cuenta del cliente</small>
            <strong>Estado de cuenta</strong>
            <span className="text-link">Ver saldos abiertos <ChevronRight size={15} /></span>
          </button>
        )}
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
  onStatement,
}: {
  clients: Client[];
  selectedId: number | null;
  onSelect: (client: Client) => void;
  onNew: () => void;
  onStatement: (client: Client) => void;
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
            <motion.article
              layout="position"
              className={`client-row ${selectedId === client.id ? "selected" : ""}`}
              key={client.id}
              initial={{ opacity: 0, scale: 0.99 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.99 }}
              transition={{ duration: 0.16 }}
            >
              <button type="button" className="client-select-main" onClick={() => onSelect(client)}>
                <span className="client-avatar">{client.name.slice(0, 2).toUpperCase()}</span>
                <span className="client-copy"><strong>{client.name}</strong><small>{[client.city, client.email].filter(Boolean).join(" · ") || "Sin datos adicionales"}</small></span>
                {selectedId === client.id ? <span className="selected-check"><Check /></span> : <ChevronRight />}
              </button>
              <button type="button" className="client-statement-button" onClick={() => onStatement(client)} title={`Estado de cuenta de ${client.name}`}>
                <FileText size={16} /> <span>Estado</span>
              </button>
            </motion.article>
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
  onDecrease,
  onPromo,
  onCart,
}: {
  products: Product[];
  cart: CartLine[];
  onAdd: (product: Product) => void;
  onDecrease: (product: Product) => void;
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
  const normalQuantities = useMemo(() => {
    const result = new Map<number, number>();
    for (const line of cart) {
      if (!line.free && !line.groupId) result.set(line.productId, (result.get(line.productId) || 0) + line.quantity);
    }
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
            {filtered.slice(0, visible).map((product) => {
              const totalQuantity = quantities.get(product.id) || 0;
              const normalQuantity = normalQuantities.get(product.id) || 0;
              return (
                <motion.article
                  layout="position"
                  className={`product-card ${totalQuantity ? "in-cart" : ""}`}
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
                    {totalQuantity > 0 && (
                      <motion.span
                        className="quantity-badge-card"
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                      >
                        {totalQuantity} en pedido
                      </motion.span>
                    )}
                  </div>
                  <div className="product-actions">
                    <AnimatePresence initial={false} mode="wait">
                      {normalQuantity > 0 ? (
                        <motion.div
                          key="catalog-stepper"
                          className="catalog-stepper"
                          initial={{ opacity: 0, y: 8, scale: 0.98 }}
                          animate={{ opacity: 1, y: 0, scale: 1 }}
                          exit={{ opacity: 0, y: -6, scale: 0.98 }}
                          transition={{ type: "spring", stiffness: 360, damping: 28 }}
                          aria-label={`Cantidad normal de ${product.name}`}
                        >
                          <motion.button
                            type="button"
                            onClick={() => onDecrease(product)}
                            whileTap={{ scale: 0.9 }}
                            aria-label={`Quitar una pieza de ${product.name}`}
                          >
                            <Minus size={17} />
                          </motion.button>
                          <motion.strong
                            key={normalQuantity}
                            initial={{ opacity: 0, y: 6 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ duration: 0.14 }}
                          >
                            {normalQuantity}
                          </motion.strong>
                          <motion.button
                            type="button"
                            onClick={() => onAdd(product)}
                            whileTap={{ scale: 0.9 }}
                            aria-label={`Agregar una pieza de ${product.name}`}
                          >
                            <Plus size={17} />
                          </motion.button>
                        </motion.div>
                      ) : (
                        <motion.button
                          key="add-button"
                          type="button"
                          className="button primary compact-add"
                          onClick={() => onAdd(product)}
                          initial={{ opacity: 0, y: 8, scale: 0.98 }}
                          animate={{ opacity: 1, y: 0, scale: 1 }}
                          exit={{ opacity: 0, y: -6, scale: 0.98 }}
                          whileTap={{ scale: 0.96 }}
                        >
                          <Plus size={18} /> Agregar
                        </motion.button>
                      )}
                    </AnimatePresence>
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
              );
            })}
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

function SuccessScreen({ result, onNew, title = "Pedido registrado" }: { result: OrderResult; onNew: () => void; title?: string }) {
  const statusMessage = result.recovered
    ? "Este pedido ya estaba registrado; recuperamos el folio para evitar duplicados."
    : result.status === "sale" || result.status === "done"
      ? "Odoo confirmó la operación correctamente."
      : "Odoo registró el pedido correctamente.";

  return (
    <div className="screen success-screen">
      <motion.div className="success-symbol" initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 220, damping: 18 }}><Check /></motion.div>
      <span className="eyebrow">{title}</span>
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

function statementDate(value: string) {
  if (!value) return "Sin fecha";
  const parsed = new Date(value.replace(" ", "T") + (value.includes("T") ? "" : "Z"));
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("es-MX", { dateStyle: "medium" });
}

function safePdfText(value: string) {
  return value
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/[–—]/g, "-")
    .replace(/•/g, "-")
    .replace(/[^\x09\x0A\x0D\x20-\xFF]/g, "?");
}

function pdfString(value: string) {
  return `(${safePdfText(value).replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)").replace(/[\r\n]+/g, " ")})`;
}

function pdfByteLength(value: string) {
  return value.length;
}

function pdfBytes(value: string) {
  const bytes = new Uint8Array(value.length);
  for (let index = 0; index < value.length; index += 1) bytes[index] = value.charCodeAt(index) & 0xff;
  return bytes;
}

function buildStatementPdf(statement: CustomerStatement) {
  const width = 612;
  const height = 792;
  const margin = 46;
  const bottom = 54;
  const rows = statement.lines.length ? statement.lines : [];
  const pages: string[] = [];
  let current = "";
  let y = height - margin;
  let pageNumber = 0;

  const text = (value: string, x: number, size = 10, bold = false, color = "0.14 0.10 0.16") => {
    current += `${color} rg BT /${bold ? "F2" : "F1"} ${size} Tf ${x} ${y} Td ${pdfString(value)} Tj ET\n`;
  };
  const line = (yPosition = y, color = "0.72 0.51 0.76") => {
    current += `${color} RG 0.6 w ${margin} ${yPosition} m ${width - margin} ${yPosition} l S\n`;
  };
  const box = (x: number, yPosition: number, boxWidth: number, boxHeight: number, color = "0.97 0.91 0.98") => {
    current += `${color} rg ${x} ${yPosition} ${boxWidth} ${boxHeight} re f\n`;
  };
  const startPage = () => {
    if (current) {
      text(`Pagina ${pageNumber}`, width - 106, 8, false);
      pages.push(current);
    }
    pageNumber += 1;
    current = "0.995 0.980 1.000 rg 0 0 612 792 re f\n";
    current += "0.11 0.06 0.13 rg 0 704 612 88 re f\n";
    y = height - margin + 4;
    text("RapyVet", margin, 22, true, "1 1 1");
    y -= 24;
    text("Distribuidor veterinario", margin, 11, false, "0.94 0.70 0.96");
    y -= 18;
    line();
    y -= 28;
  };
  const tableHeader = () => {
    box(margin - 8, y - 7, width - margin * 2 + 16, 20, "0.91 0.82 0.93");
    text("Documento", margin, 9, true, "0.26 0.12 0.30");
    text("Vencimiento", 316, 9, true, "0.26 0.12 0.30");
    text("Estado", 405, 9, true, "0.26 0.12 0.30");
    text("Saldo abierto", 488, 9, true, "0.26 0.12 0.30");
    y -= 11;
    line(y, "0.72 0.51 0.76");
    y -= 16;
  };

  startPage();
  text("Estado de cuenta", margin, 18, true, "0.26 0.12 0.30");
  y -= 24;
  text(statement.customer.name || "Cliente", margin, 12, true);
  y -= 17;
  text(`Generado: ${new Date(statement.generated_at * 1000).toLocaleString("es-MX")}`, margin, 10, false, "0.38 0.32 0.40");
  y -= 26;
  box(margin - 8, y - 18, width - margin * 2 + 16, 44, "0.95 0.88 0.96");
  text(`Saldo pendiente: ${money(statement.total_due)}`, margin, 13, true, "0.20 0.10 0.24");
  text(`Vencido: ${money(statement.overdue_due)}`, 250, 13, true, "0.42 0.10 0.16");
  text(`Saldo a favor: ${money(statement.credit_balance)}`, 410, 13, true, "0.10 0.34 0.20");
  y -= 34;
  line(y, "0.72 0.51 0.76");
  y -= 24;
  text("Movimientos abiertos", margin, 14, true, "0.26 0.12 0.30");
  y -= 24;
  tableHeader();

  if (!rows.length) {
    text("Sin movimientos abiertos. Cuenta al corriente.", margin, 11);
  } else {
    for (const row of rows) {
      if (y < bottom + 42) {
        startPage();
        text("Movimientos abiertos", margin, 14, true, "0.26 0.12 0.30");
        y -= 24;
        tableHeader();
      }
      text((row.document || row.label || "Movimiento").slice(0, 43), margin, 9, true);
      text(statementDate(row.due_date), 316, 9, false, "0.30 0.26 0.32");
      text(row.status || "Pendiente", 405, 9, false, row.status === "Vencido" ? "0.62 0.10 0.16" : row.status === "A favor" ? "0.10 0.40 0.24" : "0.30 0.26 0.32");
      text(money(row.open_amount), 488, 9, true);
      y -= 14;
      if (row.reference || row.label) {
        text(`${row.label || ""}${row.reference ? ` · Ref. ${row.reference}` : ""}`.slice(0, 70), margin, 8, false, "0.44 0.38 0.46");
        y -= 12;
      }
      line(y + 4, "0.86 0.77 0.88");
      y -= 9;
    }
  }
  y = Math.max(y - 18, bottom + 22);
  text("Solo consulta: los pagos se aplican unicamente en Odoo.", margin, 9, false, "0.42 0.34 0.45");
  text(`Pagina ${pageNumber}`, width - 106, 8, false);
  pages.push(current);

  const pageObjectNumbers = pages.map((_, index) => 3 + index * 2);
  const fontRegularObject = 3 + pages.length * 2;
  const fontBoldObject = fontRegularObject + 1;
  const objects: string[] = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    `<< /Type /Pages /Kids [${pageObjectNumbers.map((objectNumber) => `${objectNumber} 0 R`).join(" ")}] /Count ${pages.length} >>`,
  ];

  pages.forEach((content, index) => {
    const pageObject = pageObjectNumbers[index];
    const contentObject = pageObject + 1;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 ${fontRegularObject} 0 R /F2 ${fontBoldObject} 0 R >> >> /Contents ${contentObject} 0 R >>`);
    objects.push(`<< /Length ${pdfByteLength(content)} >>\nstream\n${content}endstream`);
  });
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");

  let pdf = "%PDF-1.4\n%\xE2\xE3\xCF\xD3\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(pdfByteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = pdfByteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index <= objects.length; index += 1) {
    pdf += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;

  return new Blob([pdfBytes(pdf)], { type: "application/pdf" });
}

function downloadStatementPdf(statement: CustomerStatement) {
  const filenameBase = safePdfText(statement.customer.name || "cliente")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 52) || "cliente";
  const blob = buildStatementPdf(statement);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `estado-cuenta-${filenameBase}.pdf`;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function StatementScreen({
  customerId,
  initialCustomer,
  onBack,
}: {
  customerId: number;
  initialCustomer?: Client;
  onBack: () => void;
}) {
  const [statement, setStatement] = useState<CustomerStatement | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const fetchStatement = async () => {
    setLoading(true);
    setError("");
    try {
      setStatement(await getCustomerStatement(customerId));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible consultar el estado de cuenta.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchStatement();
  }, [customerId]);

  const current = statement?.customer || initialCustomer;
  const summaryText = statement
    ? `Estado de cuenta de ${current?.name || "cliente"}\nSaldo pendiente: ${money(statement.total_due)}\nVencido: ${money(statement.overdue_due)}\nSaldo a favor: ${money(statement.credit_balance)}`
    : "";

  async function copySummary() {
    if (!summaryText) return;
    try {
      await navigator.clipboard.writeText(summaryText);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("No se pudo copiar el resumen en este dispositivo.");
    }
  }

  function saveStatementPdf() {
    if (!statement) return;
    try {
      setError("");
      downloadStatementPdf(statement);
    } catch {
      setError("No se pudo generar el PDF en este dispositivo. Intenta actualizar y descargar de nuevo.");
    }
  }

  return (
    <div className="screen list-screen statement-screen">
      <button type="button" className="back-link" onClick={onBack}><ArrowLeft /> Volver</button>
      <div className="screen-title-row">
        <div><span className="eyebrow">Consulta de cliente · solo lectura</span><h1>Estado de cuenta</h1><p>{current?.name || "Cliente"}</p></div>
        <button type="button" className="button secondary" onClick={() => void fetchStatement()} disabled={loading}><RefreshCw className={loading ? "spin" : ""} size={16} /> Actualizar</button>
      </div>
      {loading && !statement ? <div className="center-state"><LoaderCircle className="spin" size={32} /><p>Consultando saldos abiertos en Odoo…</p></div> : error && !statement ? <div className="center-state"><CircleAlert size={36} /><h1>No se pudo consultar</h1><p>{error}</p><button type="button" className="button primary" onClick={() => void fetchStatement()}><RefreshCw /> Reintentar</button></div> : statement ? (
        <>
          <div className="statement-toolbar"><span><Clock size={14} /> Actualizado {new Date(statement.generated_at * 1000).toLocaleString("es-MX")}</span><div><button type="button" className="button secondary" onClick={() => void copySummary()}><Copy size={15} /> {copied ? "Copiado" : "Copiar resumen"}</button><button type="button" className="button primary" onClick={saveStatementPdf}><Download size={15} /> Descargar PDF</button></div></div>
          {error && <p className="form-error"><CircleAlert size={16} /> {error}</p>}
          <section className="statement-summary-grid">
            <article className="statement-card"><small>Saldo pendiente</small><strong>{money(statement.total_due)}</strong><span>{statement.lines.length} movimientos abiertos</span></article>
            <article className="statement-card overdue"><small>Vencido</small><strong>{money(statement.overdue_due)}</strong><span>Requiere seguimiento</span></article>
            <article className="statement-card"><small>Vigente</small><strong>{money(statement.current_due)}</strong><span>Dentro de plazo</span></article>
            <article className="statement-card credit"><small>Saldo a favor</small><strong>{money(statement.credit_balance)}</strong><span>No se aplican pagos desde aquí</span></article>
          </section>
          <section className="statement-lines-card"><div className="section-heading"><div><span className="eyebrow">Apuntes abiertos</span><h2>Movimientos pendientes</h2></div></div>{statement.lines.length ? <div className="statement-line-list">{statement.lines.map((line) => <article className="statement-line" key={line.id}><div><strong>{line.document || line.label || "Movimiento"}</strong><small>{line.label}{line.reference ? ` · Ref. ${line.reference}` : ""}</small><small>Vence {statementDate(line.due_date)}{line.days_overdue ? ` · ${line.days_overdue} días vencido` : ""}</small></div><div className="statement-line-amount"><span className={`statement-status ${line.status === "Vencido" ? "danger" : line.status === "A favor" ? "success" : ""}`}>{line.status}</span><strong>{money(line.open_amount)}</strong></div></article>)}</div> : <EmptyState icon={CircleCheck} title="Cuenta al corriente" body="No hay movimientos abiertos para este cliente." />}</section>
          <p className="read-only-note"><ShieldCheck size={16} /> Esta pantalla es de consulta. Las aplicaciones de pago se realizan únicamente en Odoo.</p>
        </>
      ) : null}
    </div>
  );
}

function OrderEditScreen({
  orderId,
  clients,
  products,
  onBack,
  onSaved,
}: {
  orderId: number;
  clients: Client[];
  products: Product[];
  onBack: () => void;
  onSaved: (result: OrderResult) => void;
}) {
  const [detail, setDetail] = useState<OrderDetail | null>(null);
  const [selectedCustomerId, setSelectedCustomerId] = useState<number | null>(null);
  const [lines, setLines] = useState<CartLine[]>([]);
  const [note, setNote] = useState("");
  const [query, setQuery] = useState("");
  const [customerQuery, setCustomerQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const deferredQuery = useDeferredValue(query);
  const deferredCustomerQuery = useDeferredValue(customerQuery);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");

    void getOrderDetail(orderId)
      .then((result) => {
        if (!active) return;
        setDetail(result);
        setSelectedCustomerId(result.customer_id);
        setLines(
          result.lines.map((line) => ({
            id: `odoo-${line.id}`,
            productId: line.product_id,
            code: line.code,
            name: line.name,
            quantity: Math.max(1, Math.round(line.quantity)),
            unitPrice: line.unit_price,
            free: false,
          })),
        );
        setNote(result.note || "");
      })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "No fue posible cargar el pedido.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [orderId]);

  const selectedCustomer = useMemo(() => {
    return clients.find((client) => client.id === selectedCustomerId) || null;
  }, [clients, selectedCustomerId]);

  const customerResults = useMemo(() => {
    const needle = normalize(deferredCustomerQuery);
    if (!needle) return [];
    return clients
      .filter((client) => normalize(`${client.name} ${client.email} ${client.phone} ${client.vat}`).includes(needle))
      .slice(0, 6);
  }, [clients, deferredCustomerQuery]);

  const productResults = useMemo(() => {
    const needle = normalize(deferredQuery);
    if (!needle) return [];
    return products
      .filter((product) => normalize(`${product.code} ${product.name} ${product.category}`).includes(needle))
      .slice(0, 8);
  }, [products, deferredQuery]);

  const total = lines.reduce((sum, line) => sum + line.quantity * line.unitPrice, 0);

  function addProduct(product: Product) {
    setLines((current) => {
      const existing = current.find((line) => line.productId === product.id);
      if (existing) {
        return current.map((line) =>
          line.id === existing.id ? { ...line, quantity: line.quantity + 1 } : line,
        );
      }
      return [
        ...current,
        {
          id: uniqueId(),
          productId: product.id,
          code: product.code,
          name: product.name,
          quantity: 1,
          unitPrice: product.price,
          free: false,
        },
      ];
    });
    setQuery("");
  }

  function updateLine(id: string, patch: Partial<CartLine>) {
    setLines((current) =>
      current.map((line) =>
        line.id === id
          ? {
              ...line,
              ...patch,
              quantity: patch.quantity !== undefined ? Math.max(1, patch.quantity) : line.quantity,
              unitPrice: patch.unitPrice !== undefined ? Math.max(0, patch.unitPrice) : line.unitPrice,
            }
          : line,
      ),
    );
  }

  async function save() {
    if (!detail || !detail.editable || busy || !lines.length || !selectedCustomerId) return;
    setBusy(true);
    setError("");
    try {
      const result = await updateOrder(orderId, {
        customer_id: selectedCustomerId,
        lines: lines.map((line) => ({
          product_id: line.productId,
          quantity: line.quantity,
          unit_price: line.unitPrice,
        })),
        note,
      });
      onSaved(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible guardar los cambios.");
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <div className="screen center-state"><LoaderCircle className="spin" size={32} /><p>Cargando pedido desde Odoo…</p></div>;
  if (!detail) return <div className="screen center-state"><CircleAlert size={36} /><h1>No se pudo abrir el pedido</h1><p>{error}</p><button type="button" className="button secondary" onClick={onBack}><ArrowLeft /> Volver</button></div>;

  return (
    <div className="screen list-screen order-editor-screen">
      <button type="button" className="back-link" onClick={onBack}><ArrowLeft /> Volver al historial</button>
      <div className="screen-title-row">
        <div>
          <span className="eyebrow">Editor seguro · {detail.folio}</span>
          <h1>{detail.editable ? "Editar pedido" : "Detalle del pedido"}</h1>
          <p>{selectedCustomer?.name || detail.customer_name} · {detail.state_label}</p>
        </div>
        <span className={`order-state-badge ${detail.editable ? "draft" : "sale"}`}>{detail.state_label}</span>
      </div>

      {!detail.editable && (
        <div className="read-only-banner">
          <ShieldCheck size={18} />
          <span>{detail.editable_reason}</span>
        </div>
      )}

      <section className="order-editor-card">
        <div className="editor-section">
          <span className="eyebrow">Cliente</span>
          <article className="editor-customer-card">
            <span className="client-avatar">{(selectedCustomer?.name || detail.customer_name).slice(0, 2).toUpperCase()}</span>
            <div>
              <strong>{selectedCustomer?.name || detail.customer_name}</strong>
              <small>{selectedCustomer ? [selectedCustomer.city, selectedCustomer.email].filter(Boolean).join(" · ") || "Cliente de Odoo" : "Cliente del pedido"}</small>
            </div>
          </article>
          {detail.editable && (
            <>
              <label className="search-field compact-search">
                <Search size={18} />
                <input
                  value={customerQuery}
                  onChange={(event) => setCustomerQuery(event.target.value)}
                  placeholder="Cambiar cliente..."
                  autoComplete="off"
                />
                {customerQuery && <button type="button" onClick={() => setCustomerQuery("")} aria-label="Limpiar cliente"><X size={17} /></button>}
              </label>
              {customerQuery && (
                <div className="editor-product-results customer-results">
                  {customerResults.map((client) => (
                    <button
                      type="button"
                      key={client.id}
                      onClick={() => {
                        setSelectedCustomerId(client.id);
                        setCustomerQuery("");
                      }}
                    >
                      <span>
                        <strong>{client.name}</strong>
                        <small>{[client.city, client.email].filter(Boolean).join(" · ") || "Cliente de Odoo"}</small>
                      </span>
                      {client.id === selectedCustomerId ? <Check size={17} /> : <ChevronRight size={17} />}
                    </button>
                  ))}
                  {!customerResults.length && <p className="editor-empty-result">Sin clientes con esa busqueda.</p>}
                </div>
              )}
            </>
          )}
        </div>

        <div className="editor-section">
          <span className="eyebrow">Productos</span>
          <label className="search-field compact-search">
            <Search size={18} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={detail.editable ? "Agregar producto al pedido..." : "Pedido en modo lectura"}
              autoComplete="off"
              disabled={!detail.editable}
            />
            {query && <button type="button" onClick={() => setQuery("")} aria-label="Limpiar búsqueda"><X size={17} /></button>}
          </label>
          {detail.editable && query && (
            <div className="editor-product-results">
              {productResults.map((product) => (
                <button type="button" key={product.id} onClick={() => addProduct(product)}>
                  <span>
                    <strong>{product.name}</strong>
                    <small>{product.code} · {money(product.price)}</small>
                  </span>
                  <Plus size={17} />
                </button>
              ))}
              {!productResults.length && <p className="editor-empty-result">Sin productos con esa busqueda.</p>}
            </div>
          )}

          <div className="editor-lines">
            {lines.map((line) => (
              <article className="editor-line" key={line.id}>
                <div className="editor-line-copy">
                  <strong>{line.name}</strong>
                  <small>{line.code || "Sin código"} · {line.unitPrice === 0 ? "Sin cargo" : money(line.unitPrice)}</small>
                </div>
                <div className="editor-line-actions">
                  <div className="stepper mini-stepper" aria-label={`Cantidad de ${line.name}`}>
                    <button
                      type="button"
                      disabled={!detail.editable || line.quantity <= 1}
                      onClick={() => updateLine(line.id, { quantity: line.quantity - 1 })}
                    >
                      <Minus size={15} />
                    </button>
                    <strong>{line.quantity}</strong>
                    <button
                      type="button"
                      disabled={!detail.editable}
                      onClick={() => updateLine(line.id, { quantity: line.quantity + 1 })}
                    >
                      <Plus size={15} />
                    </button>
                  </div>
                  <label className="price-input editor-price-input">
                    <span>Precio</span>
                    <div>
                      <small>$</small>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        value={line.unitPrice}
                        disabled={!detail.editable}
                        onChange={(event) => updateLine(line.id, { unitPrice: Number(event.target.value) })}
                      />
                    </div>
                  </label>
                  {detail.editable && (
                    <button
                      type="button"
                      className="icon-button danger-button"
                      onClick={() => setLines((current) => current.filter((item) => item.id !== line.id))}
                      aria-label={`Eliminar ${line.name}`}
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </div>
              </article>
            ))}
            {!lines.length && <EmptyState icon={ShoppingBag} title="Sin productos" body="Agrega al menos un producto para guardar el pedido." />}
          </div>
        </div>

        <label className="note-field">
          <span>Notas <small>Opcional</small></span>
          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            disabled={!detail.editable}
            placeholder="Observaciones del pedido..."
            maxLength={2000}
          />
        </label>

        <div className="editor-total">
          <span>Total estimado<strong>{money(total)}</strong></span>
          {detail.editable && (
            <button type="button" className="button primary" onClick={() => void save()} disabled={busy || !lines.length || !selectedCustomerId}>
              {busy ? <LoaderCircle className="spin" /> : <BadgeCheck />}
              {busy ? "Guardando..." : "Guardar cambios"}
            </button>
          )}
        </div>
        {error && <p className="form-error"><CircleAlert size={16} /> {error}</p>}
      </section>

      <p className="read-only-note"><ShieldCheck size={16} /> Editar aquí solo modifica cotizaciones abiertas en Odoo. No confirma pedidos ni aplica pagos.</p>
    </div>
  );
}

function HistoryScreen({
  seller,
  onRefresh,
  onEdit,
}: {
  seller?: Seller;
  onRefresh?: () => void;
  onEdit?: (order: SellerOrderSummary) => void;
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
                  <div><span>Total Odoo</span><strong>{money(order.amount_total)}</strong></div>
                  {onEdit && (
                    <button type="button" className="button secondary history-edit-button" onClick={() => onEdit(order)}>
                      {order.state === "draft" || order.state === "sent" ? <FileText size={15} /> : <ChevronRight size={15} />}
                      {order.state === "draft" || order.state === "sent" ? "Editar" : "Ver"}
                    </button>
                  )}
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
  canInstallApp,
  appInstalled,
  onClose,
  onNavigate,
  onInstall,
  onRefreshCatalog,
  onTutorial,
  onLogout,
}: {
  open: boolean;
  seller?: Seller;
  pendingCount?: number;
  canInstallApp: boolean;
  appInstalled: boolean;
  onClose: () => void;
  onNavigate: (screen: Screen) => void;
  onInstall: () => void;
  onRefreshCatalog: () => void;
  onTutorial: () => void;
  onLogout: () => void;
}) {
  const installTitle = appInstalled ? "App instalada" : "Instalar app";
  const installDescription = appInstalled
    ? "RapyVet ya está corriendo como aplicación"
    : canInstallApp
      ? "Agregar a Chrome como app de pedidos"
      : "Ver pasos para agregarla a Chrome o al inicio";

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
                className="more-menu-item install"
                onClick={() => {
                  onClose();
                  onInstall();
                }}
              >
                <span className="more-menu-icon">
                  {appInstalled ? <BadgeCheck size={22} /> : <Download size={22} />}
                </span>
                <div className="more-menu-text">
                  <strong>{installTitle}</strong>
                  <small>{installDescription}</small>
                </div>
                <ChevronRight size={18} className="more-arrow" />
              </button>

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
                className="more-menu-item"
                onClick={() => {
                  onClose();
                  onTutorial();
                }}
              >
                <span className="more-menu-icon">
                  <ClipboardCheck size={22} />
                </span>
                <div className="more-menu-text">
                  <strong>Tutorial de uso</strong>
                  <small>Ver la guía rápida para tomar pedidos</small>
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

function InstallHelpDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const steps = [
    {
      title: "Android / Chrome",
      body: "Toca el menú de tres puntos y elige Instalar app o Agregar a pantalla principal.",
      icon: Menu,
    },
    {
      title: "Computadora / Chrome",
      body: "Busca el ícono de instalar en la barra de direcciones o entra a menú > Guardar y compartir > Instalar página como app.",
      icon: Download,
    },
    {
      title: "iPhone",
      body: "Abre la liga en Safari, toca Compartir y selecciona Agregar a inicio.",
      icon: Home,
    },
  ];

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
            aria-labelledby="install-help-title"
            className="dialog-sheet install-help-sheet"
            initial={{ opacity: 0, y: 35, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 26, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 320, damping: 30 }}
          >
            <div className="dialog-head">
              <div>
                <span className="eyebrow">Instalación rápida</span>
                <h2 id="install-help-title">Instalar RapyVet como app</h2>
              </div>
              <button type="button" className="icon-button" onClick={onClose} aria-label="Cerrar instalación">
                <X />
              </button>
            </div>

            <div className="install-hero" aria-hidden="true">
              <motion.span
                animate={{ y: [0, -6, 0], rotate: [0, -2, 2, 0] }}
                transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut" }}
              >
                <Download />
              </motion.span>
              <div>
                <strong>Un toque y queda en el teléfono.</strong>
                <small>Así los vendedores abren la app como si fuera una aplicación normal.</small>
              </div>
            </div>

            <div className="install-help-list">
              {steps.map((item, index) => {
                const Icon = item.icon;
                return (
                  <motion.article
                    key={item.title}
                    className="install-help-item"
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.06 }}
                  >
                    <span>
                      <Icon />
                    </span>
                    <div>
                      <strong>{item.title}</strong>
                      <small>{item.body}</small>
                    </div>
                  </motion.article>
                );
              })}
            </div>

            <button type="button" className="button primary wide" onClick={onClose}>
              Entendido
              <Check />
            </button>
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
  const isMoreActive = screen === "outbox" || screen === "history" || screen === "statement" || screen === "orderEdit";
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
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [tutorialAutoChecked, setTutorialAutoChecked] = useState(false);
  const [statementCustomerId, setStatementCustomerId] = useState<number | null>(null);
  const [editingOrderId, setEditingOrderId] = useState<number | null>(null);
  const [successTitle, setSuccessTitle] = useState("Pedido registrado");
  const pwaInstall = usePwaInstall();
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

  useEffect(() => {
    if (!hydrated || !authenticated || !catalog || !session || session.must_change_password || tutorialAutoChecked) return;
    setTutorialAutoChecked(true);
    try {
      if (!localStorage.getItem(tutorialSeenKey(session.seller.id))) {
        localStorage.setItem(tutorialSeenKey(session.seller.id), "true");
        setTutorialOpen(true);
      }
    } catch {
      setTutorialOpen(true);
    }
  }, [authenticated, catalog, hydrated, session, tutorialAutoChecked]);

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

  function openStatement(client: Client) {
    setStatementCustomerId(client.id);
    setScreen("statement");
  }

  function openOrderEditor(order: SellerOrderSummary) {
    setEditingOrderId(order.id);
    setScreen("orderEdit");
  }

  function addProduct(product: Product) {
    setCart((current) => {
      const existing = current.find((line) => line.productId === product.id && !line.free && !line.groupId);
      if (existing) return current.map((line) => line.id === existing.id ? { ...line, quantity: line.quantity + 1 } : line);
      return [...current, { id: uniqueId(), productId: product.id, code: product.code, name: product.name, quantity: 1, unitPrice: product.price, free: false }];
    });
    setToast(`${product.name} agregado`);
  }

  function decreaseProduct(product: Product) {
    setCart((current) => {
      const existing = current.find((line) => line.productId === product.id && !line.free && !line.groupId);
      if (!existing) return current;
      if (existing.quantity <= 1) return current.filter((line) => line.id !== existing.id);
      return current.map((line) => line.id === existing.id ? { ...line, quantity: line.quantity - 1 } : line);
    });
    setToast(`${product.name} actualizado`);
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
    setSuccessTitle("Pedido registrado");
    setScreen("clients");
  }

  function acceptSession(nextSession: SessionInfo, password = "") {
    setSession(nextSession);
    setCurrentLoginPassword(password);
    setAuthenticated(!nextSession.must_change_password);
    setTutorialAutoChecked(false);
  }

  function logout() {
    clearSession();
    setSession(null);
    setCurrentLoginPassword("");
    setAuthenticated(false);
    setTutorialAutoChecked(false);
    setStatementCustomerId(null);
    setEditingOrderId(null);
  }

  function finishTutorial(target?: Screen) {
    try {
      localStorage.setItem(tutorialSeenKey(session?.seller.id), "true");
    } catch {
      // El tutorial puede seguir funcionando aunque el navegador bloquee almacenamiento local.
    }
    setTutorialOpen(false);
    setMoreMenuOpen(false);
    if (target) {
      navigate(target);
    }
  }

  function openTutorial() {
    setMoreMenuOpen(false);
    setTutorialOpen(true);
  }

  async function installApp() {
    const result = await pwaInstall.requestInstall();
    if (result === "installed") {
      setToast("La app ya está instalada.");
    } else if (result === "accepted") {
      setToast("Instalando RapyVet como app…");
    } else if (result === "dismissed") {
      setToast("Instalación cancelada. Te dejo los pasos manuales.");
    } else {
      setToast("Te dejo los pasos para instalar la app.");
    }
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
                  onStatement={customer ? () => openStatement(customer) : undefined}
                />
              )}
              {screen === "clients" && <ClientScreen clients={catalog.clients} selectedId={customerId} onSelect={selectClient} onStatement={openStatement} onNew={() => { setClientError(""); setNewClientOpen(true); }} />}
              {screen === "products" && <ProductScreen products={catalog.products} cart={cart} onAdd={addProduct} onDecrease={decreaseProduct} onPromo={setPromoProduct} onCart={() => setScreen("cart")} />}
              {screen === "cart" && <CartScreen cart={cart} onChange={updateLine} onRemove={removeLine} onProducts={() => setScreen(customer ? "products" : "clients")} onReview={() => customer ? setScreen("review") : setScreen("clients")} />}
              {screen === "review" && customer && <ReviewScreen customer={customer} cart={cart} note={note} busy={submitBusy} error={submitError} onNote={setNote} onBack={() => setScreen("cart")} onSubmit={() => void submitOrder()} />}
              {screen === "success" && orderResult && <SuccessScreen result={orderResult} title={successTitle} onNew={startNewOrder} />}
              {screen === "history" && <HistoryScreen seller={session.seller} onRefresh={() => void loadCatalog(false)} onEdit={openOrderEditor} />}
              {screen === "statement" && statementCustomerId && <StatementScreen customerId={statementCustomerId} initialCustomer={catalog.clients.find((item) => item.id === statementCustomerId)} onBack={() => setScreen("clients")} />}
              {screen === "orderEdit" && editingOrderId && <OrderEditScreen orderId={editingOrderId} clients={catalog.clients} products={catalog.products} onBack={() => setScreen("history")} onSaved={(result) => { setOrderResult(result); setSuccessTitle("Pedido actualizado"); setEditingOrderId(null); setScreen("success"); setToast("Pedido actualizado en Odoo"); }} />}
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
        canInstallApp={pwaInstall.canInstall}
        appInstalled={pwaInstall.installed}
        onClose={() => setMoreMenuOpen(false)}
        onNavigate={(targetScreen) => {
          setMoreMenuOpen(false);
          navigate(targetScreen);
        }}
        onInstall={() => void installApp()}
        onRefreshCatalog={() => {
          void loadCatalog(true);
          setToast("Catálogo actualizado desde Odoo");
        }}
        onTutorial={openTutorial}
        onLogout={logout}
      />
      <InstallHelpDialog open={pwaInstall.helpOpen} onClose={() => pwaInstall.setHelpOpen(false)} />
      <NewClientDialog open={newClientOpen} busy={clientBusy} error={clientError} onClose={() => setNewClientOpen(false)} onSubmit={(data) => void submitNewClient(data)} />
      <PromoDialog product={promoProduct} onClose={() => setPromoProduct(null)} onAdd={addPromotion} />
      <FirstUseTutorial
        open={tutorialOpen}
        seller={session.seller}
        canInstallApp={pwaInstall.canInstall}
        appInstalled={pwaInstall.installed}
        onInstall={() => void installApp()}
        onDone={finishTutorial}
      />
      <AnimatePresence>{toast && <motion.div className="toast" role="status" initial={{ opacity: 0, x: "-50%", y: 18, scale: 0.96 }} animate={{ opacity: 1, x: "-50%", y: 0, scale: 1 }} exit={{ opacity: 0, x: "-50%", y: 12 }}><Check size={17} /> {toast}</motion.div>}</AnimatePresence>
    </MotionConfig>
  );
}
