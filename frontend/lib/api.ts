import type {
  Catalog,
  Client,
  CustomerStatement,
  OrderResult,
  OrderDetail,
  SellerOrderSummary,
  SessionInfo,
  TemporarySellerKey,
} from "@/lib/types";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080").replace(/\/$/, "");
const TOKEN_KEY = "rapyvet_session_v2";
const SESSION_INFO_KEY = "rapyvet_session_info_v2";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}

export function hasSession() {
  return typeof window !== "undefined" && Boolean(localStorage.getItem(TOKEN_KEY));
}

export function getStoredSession() {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(SESSION_INFO_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SessionInfo;
  } catch {
    localStorage.removeItem(SESSION_INFO_KEY);
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(SESSION_INFO_KEY);
}

function storeSession(session: SessionInfo) {
  localStorage.setItem(TOKEN_KEY, session.token);
  localStorage.setItem(SESSION_INFO_KEY, JSON.stringify(session));
}

let pendingRequests = 0;
const pendingListeners = new Set<(count: number) => void>();

function changePendingRequests(delta: number) {
  pendingRequests += delta;
  pendingListeners.forEach((listener) => listener(pendingRequests));
}

/** Avisa cuántas solicitudes al servidor siguen en curso (lo usa la pantalla de carga). */
export function subscribePendingRequests(listener: (count: number) => void) {
  pendingListeners.add(listener);
  listener(pendingRequests);
  return () => {
    pendingListeners.delete(listener);
  };
}

async function request<T>(path: string, init: RequestInit = {}, authenticated = true): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (authenticated) {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  changePendingRequests(1);
  try {
    let response: Response;
    try {
      response = await fetch(`${API_URL}${path}`, { ...init, headers });
    } catch {
      throw new ApiError("No hay conexión con el servidor. Revisa tu señal e intenta otra vez.", 0);
    }

    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && authenticated) clearSession();
      const detail = typeof body.detail === "string" ? body.detail : "No fue posible completar la operación.";
      throw new ApiError(detail, response.status);
    }
    return body as T;
  } finally {
    changePendingRequests(-1);
  }
}

export async function login(loginName: string, password: string) {
  const result = await request<SessionInfo>(
    "/api/session",
    { method: "POST", body: JSON.stringify({ login: loginName, password }) },
    false,
  );
  storeSession(result);
  return result;
}

export async function changePassword(currentPassword: string, newPassword: string) {
  const result = await request<SessionInfo>("/api/session/change-password", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  storeSession(result);
  return result;
}

export function generateTemporarySellerKeys(adminPin: string, resetExisting: boolean) {
  return request<{ sellers: TemporarySellerKey[]; generated_at: number }>(
    "/api/admin/sellers/temporary-keys",
    {
      method: "POST",
      body: JSON.stringify({ admin_pin: adminPin, reset_existing: resetExisting }),
    },
    false,
  );
}

export function getCatalog(refresh = false) {
  return request<Catalog>(`/api/catalog${refresh ? "?refresh=true" : ""}`);
}

export function createClient(data: {
  name: string;
  email: string;
  street: string;
  postal_code: string;
  vat: string;
}) {
  return request<Client & { created: boolean }>("/api/clients", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function createOrder(data: {
  customer_id: number;
  lines: { product_id: number; quantity: number; unit_price: number }[];
  note: string;
  idempotency_key: string;
}) {
  return request<OrderResult>("/api/orders", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function getOrderHistory(limit = 30) {
  return request<{ orders: SellerOrderSummary[]; total: number }>(
    `/api/orders/history?limit=${limit}`,
  );
}

export function getCustomerStatement(customerId: number) {
  return request<CustomerStatement>(`/api/clients/${customerId}/statement`);
}

export function getOrderDetail(orderId: number) {
  return request<OrderDetail>(`/api/orders/${orderId}`);
}

export function updateOrder(orderId: number, data: {
  customer_id: number;
  lines: { product_id: number; quantity: number; unit_price: number }[];
  note: string;
}) {
  return request<OrderResult>(`/api/orders/${orderId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}
