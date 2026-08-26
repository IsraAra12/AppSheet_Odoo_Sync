export type Client = {
  id: number;
  name: string;
  email: string;
  phone: string;
  street: string;
  city: string;
  postal_code: string;
  vat: string;
};

export type Product = {
  id: number;
  code: string;
  name: string;
  price: number;
  category: string;
  tax_ids: number[];
};

export type Seller = {
  id: number;
  name: string;
  login: string;
  email: string;
};

export type SessionInfo = {
  token: string;
  expires_in: number;
  seller: Seller;
  must_change_password: boolean;
};

export type TemporarySellerKey = {
  seller: Seller;
  temporary_password: string;
  status: string;
  must_change_password: boolean;
};

export type Catalog = {
  clients: Client[];
  products: Product[];
  refreshed_at: number;
};

export type CartLine = {
  id: string;
  productId: number;
  code: string;
  name: string;
  quantity: number;
  unitPrice: number;
  free: boolean;
  groupId?: string;
};

export type OrderResult = {
  id: number;
  folio: string;
  status: string;
  subtotal: number;
  tax: number;
  total: number;
  recovered: boolean;
  whatsapp_message: string;
  whatsapp_url: string;
};

export type Draft = {
  customerId: number | null;
  cart: CartLine[];
  note: string;
  idempotencyKey: string;
  savedAt: number;
};

export type SellerOrderSummary = {
  id: number;
  folio: string;
  customer_id: number;
  customer_name: string;
  amount_total: number;
  state: string;
  state_label: string;
  date_order: string;
  client_order_ref: string;
};

export type OutboxStatus = "pending" | "sending" | "confirmed" | "attention";

export type OutboxItem = {
  id: string;
  idempotency_key: string;
  customer_id: number;
  customer_name: string;
  lines: CartLine[];
  note: string;
  total_amount: number;
  items_count: number;
  status: OutboxStatus;
  created_at: number;
  updated_at: number;
  error_message?: string;
  result?: OrderResult;
};

