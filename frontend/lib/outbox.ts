import { createOrder, ApiError } from "@/lib/api";
import type { CartLine, OrderResult, OutboxItem, OutboxStatus } from "@/lib/types";

const OUTBOX_KEY = "rapyvet_outbox_v2";
const listeners = new Set<() => void>();
let syncInProgress = false;

function notify() {
  for (const listener of listeners) {
    try {
      listener();
    } catch {
      // Ignorar errores de suscriptores desmontados
    }
  }
}

export function subscribeOutbox(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getOutbox(): OutboxItem[] {
  if (typeof window === "undefined") return [];
  const raw = localStorage.getItem(OUTBOX_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed as OutboxItem[];
  } catch {
    localStorage.removeItem(OUTBOX_KEY);
    return [];
  }
}

export function getPendingOutboxCount(): number {
  return getOutbox().filter((item) => item.status === "pending" || item.status === "sending" || item.status === "attention").length;
}

export function saveOutbox(items: OutboxItem[]): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(OUTBOX_KEY, JSON.stringify(items.slice(0, 50)));
  notify();
}

export function enqueueOrder(params: {
  customerId: number;
  customerName: string;
  lines: CartLine[];
  note: string;
  idempotencyKey: string;
  status?: OutboxStatus;
  result?: OrderResult;
  errorMessage?: string;
}): OutboxItem {
  const totalAmount = params.lines.reduce(
    (acc, line) => acc + (line.free ? 0 : line.quantity * line.unitPrice),
    0,
  );
  const itemsCount = params.lines.reduce((acc, line) => acc + line.quantity, 0);

  const existing = getOutbox().find((i) => i.idempotency_key === params.idempotencyKey);
  if (existing) {
    return existing;
  }

  const newItem: OutboxItem = {
    id: `outbox-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    idempotency_key: params.idempotencyKey,
    customer_id: params.customerId,
    customer_name: params.customerName,
    lines: params.lines,
    note: params.note,
    total_amount: totalAmount,
    items_count: itemsCount,
    status: params.status || "pending",
    created_at: Date.now(),
    updated_at: Date.now(),
    error_message: params.errorMessage,
    result: params.result,
  };

  const current = getOutbox();
  saveOutbox([newItem, ...current]);

  if (newItem.status === "pending" && typeof navigator !== "undefined" && navigator.onLine) {
    void syncOutboxItem(newItem.id);
  }

  return newItem;
}

export function updateOutboxStatus(
  id: string,
  status: OutboxStatus,
  extra?: { errorMessage?: string; result?: OrderResult },
): void {
  const items = getOutbox().map((item) => {
    if (item.id !== id) return item;
    return {
      ...item,
      status,
      updated_at: Date.now(),
      error_message: extra?.errorMessage ?? (status === "confirmed" ? undefined : item.error_message),
      result: extra?.result ?? item.result,
    };
  });
  saveOutbox(items);
}

export function removeOutboxItem(id: string): void {
  const items = getOutbox().filter((item) => item.id !== id);
  saveOutbox(items);
}

export function clearConfirmedOutbox(): void {
  const items = getOutbox().filter((item) => item.status !== "confirmed");
  saveOutbox(items);
}

export async function syncOutboxItem(id: string): Promise<OutboxItem | null> {
  const item = getOutbox().find((i) => i.id === id);
  if (!item || item.status === "confirmed") return item || null;

  updateOutboxStatus(id, "sending");

  try {
    const result = await createOrder({
      customer_id: item.customer_id,
      lines: item.lines.map((line) => ({
        product_id: line.productId,
        quantity: line.quantity,
        unit_price: line.free ? 0 : line.unitPrice,
      })),
      note: item.note,
      idempotency_key: item.idempotency_key,
    });

    updateOutboxStatus(id, "confirmed", { result });
    return getOutbox().find((i) => i.id === id) || null;
  } catch (error) {
    if (error instanceof ApiError) {
      if (error.status === 422) {
        updateOutboxStatus(id, "attention", { errorMessage: error.message });
      } else {
        updateOutboxStatus(id, "pending", { errorMessage: error.message });
      }
    } else {
      updateOutboxStatus(id, "pending", { errorMessage: "Error de red al conectar con Odoo." });
    }
    return getOutbox().find((i) => i.id === id) || null;
  }
}

export async function syncAllPendingOutbox(): Promise<{ processed: number; succeeded: number; failed: number }> {
  if (syncInProgress) return { processed: 0, succeeded: 0, failed: 0 };
  syncInProgress = true;

  try {
    const pending = getOutbox().filter((item) => item.status === "pending" || item.status === "sending" || item.status === "attention");
    let succeeded = 0;
    let failed = 0;

    for (const item of pending) {
      try {
        const synced = await syncOutboxItem(item.id);
        if (synced?.status === "confirmed") {
          succeeded += 1;
        } else {
          failed += 1;
        }
      } catch {
        failed += 1;
      }
    }

    return { processed: pending.length, succeeded, failed };
  } finally {
    syncInProgress = false;
  }
}

if (typeof window !== "undefined") {
  window.addEventListener("online", () => {
    void syncAllPendingOutbox();
  });
}
