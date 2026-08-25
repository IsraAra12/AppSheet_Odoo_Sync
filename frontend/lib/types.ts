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
